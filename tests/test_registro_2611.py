"""O que o registro de 26/11 mostrou (a primeira sessão com o visor novo).

  18h57 "Coloque o seu visor grande na tela, no centro." -> "não consigo mudar o tamanho"
  18h58 o vigia avisou a notícia dos 22 mil policiais; "e você viu isso?" -> "não vi essa notícia"
  19h00 "pode buscar na internet, mas abre o Spotify" -> abriu, bateu no limite, e o fechamento
        disse "dei uma olhada nas notícias" sem ter pesquisado (e o melhor modelo ficou 2 min de
        castigo por "Tool choice is none, but model called a tool")
  21h24 "SÓCRATES, ALÔ? SÓCRATES? SÓCRATES." -> abriu o Spotify de novo e repetiu a pesquisa
  21h25 "Posso baixar a nova versão e reiniciar?" -> "Por favor." não valeu como sim
  o dia todo: Qwen do Groq recusado na hora ("Request too large ... (OTPM): Limit 1000")
  autoestudo: 11 buscas compridas voltaram sem nada ("No results found")
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx2 as httpx
import pytest

from socrates import config, ferramentas
from socrates.core.agente import Agente, familias_do_pc
from socrates.core.despertar import chamou
from socrates.core.memoria import Memorias
from socrates.estudo import noticias as nt
from socrates.ferramentas import Ferramenta, aparencia
from socrates.llm import CerebroCompativelOpenAI, ErroCerebro
from socrates.llm.base import ErroLimite, ErroQuerFerramenta
from socrates.llm.compativel_openai import SAIDA_CURTA
from socrates.llm.rodizio import PARAR_SE_QUISER_FERRAMENTA, CerebroRodizio
from socrates.visor import tamanho as tam

from test_agente import BibliotecaFalsa

GROQ = "https://api.groq.com/openai/v1"


# ---------------------------------------------------------------- só chamou: "Sim?"

@pytest.mark.parametrize("fala", [
    "SÓCRATES, ALÔ? SÓCRATES? SÓCRATES.",          # 21h24: foi ao cérebro e abriu o Spotify
    "Sócrates, tá aí?", "Você tá aí, Sócrates?", "Tá me ouvindo, Sócrates?",
    "Sócrates, você está me ouvindo?", "Alô, Sócrates?", "Ei, Sócrates, acorda!",
])
def test_so_chamar_nao_vira_pedido(fala):
    assert chamou(fala) == (True, "")


@pytest.mark.parametrize("fala,pedido", [
    ("Sócrates, tá aí o resumo?", "tá aí o resumo?"),
    ("Alô, Sócrates, abre o Spotify", "abre o Spotify"),
    ("Sócrates, bom dia", "bom dia"),                 # saudação ele responde
    ("Tá, Sócrates, acho que eu tô cansado", "acho que eu tô cansado"),
])
def test_chamado_com_pedido_continua_igual(fala, pedido):
    assert chamou(fala) == (True, pedido)


# ---------------------------------------------------------------- "Por favor." é sim

def test_por_favor_confirma_a_atualizacao(monkeypatch):
    feito = []
    f = Ferramenta("teste_confirma", "Teste.", lambda: feito.append(1) or "Atualizei.", True, {}, {},
                   lambda a: "baixar a versão nova e reiniciar")
    monkeypatch.setitem(ferramentas.REGISTRO, "teste_confirma", f)
    assert "AGUARDANDO CONFIRMAÇÃO" in ferramentas.executar("teste_confirma", {})
    assert ferramentas.resolver_confirmacao("Por favor.") == "Atualizei." and feito == [1]


# ---------------------------------------------------------------- a notícia que ele avisou

AGORA = datetime(2026, 11, 26, 21, 55, tzinfo=timezone.utc)
GRAN = {"title": "Concurso PRF: estudo prevê até 22 mil policiais", "source": "Blog Gran Cursos Online",
        "url": "https://blog.grancursosonline.com.br/concurso-prf-caderno-tecnico-diagnostico/",
        "date": (AGORA - timedelta(days=3)).isoformat(),
        "body": "Caderno técnico da PRF projeta efetivo de até 22 mil policiais; o novo concurso "
                "depende de autorização do Ministério da Gestão."}


def test_vigia_guarda_o_trecho_e_a_ferramenta_conta(tmp_path):
    v = nt.Vigia(tmp_path / "noticias.json", ["prf"], buscar=lambda q: [GRAN], relogio=lambda: AGORA)
    novas = v.verificar()
    assert novas[0].resumo.startswith("Caderno técnico da PRF")
    texto = nt.resumo_para_o_cerebro(novas, v.recentes())
    assert "Trecho: Caderno técnico da PRF projeta efetivo de até 22 mil" in texto
    assert "a que você avisou está aqui" in texto


def test_noticias_json_antigo_sem_trecho_ainda_abre_e_ganha_o_trecho(tmp_path):
    arq = tmp_path / "noticias.json"
    antigo = {"concurso": "prf", "titulo": GRAN["title"], "fonte": GRAN["source"], "url": GRAN["url"],
              "data": GRAN["date"]}              # o que o PC tem hoje (sem "resumo")
    arq.write_text(json.dumps({"vistas": {nt._chave(GRAN["title"]): AGORA.isoformat()},
                               "recentes": [antigo, {"lixo": 1}],
                               "ultima_busca": AGORA.isoformat()}), encoding="utf-8")
    v = nt.Vigia(arq, ["prf"], buscar=lambda q: [GRAN], relogio=lambda: AGORA + timedelta(hours=7))
    assert v.recentes()[0].resumo == ""
    assert v.verificar() == []                    # já avisada: não avisa de novo
    assert v.recentes()[0].resumo.startswith("Caderno técnico")


# ---------------------------------------------------------------- não fingir a pesquisa

class CerebroSessao:
    """Cérebro de roteiro para a fala das 19h: cada chamada a com_ferramentas segue um passo."""
    nome = "sessao"
    pesquisa_ok = True

    def __init__(self, passos, responder_erro=None):
        self.passos = list(passos)
        self.responder_erro = responder_erro
        self.pedidos = []
        self.pesquisas = 0

    async def com_ferramentas(self, mensagens, esquemas, executar, max_rodadas=4, parar=None):
        self.pedidos.append(mensagens)
        chamadas, final = self.passos.pop(0)
        resultados = [await executar(n, a) for n, a in chamadas]
        return resultados[-1] if final is None else final

    async def responder(self, mensagens):
        if self.responder_erro is not None:
            raise self.responder_erro
        yield "Pronto."

    async def pesquisar(self, mensagens):
        self.pesquisas += 1
        return "Segundo o blog Gran Cursos, um estudo da PRF prevê até 22 mil policiais."


def _agente(cerebro, tmp_path):
    feitos = []

    def executar_pc(nome, args):
        feitos.append((nome, args))
        return "Abri spotify."

    ag = Agente(cerebro, memorias=Memorias(tmp_path / "S"), biblioteca=BibliotecaFalsa(),
                acoes_pc=["abrir_programa", "fechar_programa"], executar_pc=executar_pc)
    return ag, feitos


PEDIDO = "Tá, pode buscar na internet, mas abre o Spotify, por favor."
SPOTIFY = ("abrir_programa", {"nome": "spotify"})
BUSCA = ("pesquisar_internet", {"pergunta": "concurso PRF 22 mil policiais"})


def test_disse_que_olhou_as_noticias_sem_pesquisar_e_corrigido(tmp_path):
    c = CerebroSessao([
        ([SPOTIFY], "Já abri o Spotify para você. Dei uma olhada nas notícias e há estudos "
                    "prevendo até 22 mil policiais."),
        ([BUSCA], "O Spotify está aberto. Segundo o Gran Cursos, um estudo prevê até 22 mil policiais."),
    ])
    ag, feitos = _agente(c, tmp_path)
    r = asyncio.run(ag.atender(PEDIDO))
    assert r.ferramentas == ["abrir_programa", "pesquisar_internet"] and c.pesquisas == 1
    assert feitos == [SPOTIFY]                             # o Spotify abriu uma vez só
    assert "Gran Cursos" in r.texto
    assert "não usou pesquisar_internet" in c.pedidos[1][-1]["content"]


def test_se_nao_der_para_pesquisar_diz_a_verdade(tmp_path):
    c = CerebroSessao([([SPOTIFY], "Abri o Spotify e pesquisei na internet: saiu o edital!"),
                       ([], "Pesquisei na internet de novo e saiu o edital.")])
    ag, _ = _agente(c, tmp_path)
    r = asyncio.run(ag.atender(PEDIDO))
    assert r.texto == "Abri spotify. Não consegui fazer a pesquisa agora. Se quiser, peça de novo daqui a pouco."


def test_pesquisa_feita_de_verdade_nao_e_corrigida(tmp_path):
    c = CerebroSessao([([SPOTIFY, BUSCA], "Abri o Spotify e pesquisei na internet: estudo prevê 22 mil.")])
    ag, _ = _agente(c, tmp_path)
    r = asyncio.run(ag.atender(PEDIDO))
    assert len(c.pedidos) == 1 and r.texto.startswith("Abri o Spotify e pesquisei")


def test_limite_depois_de_abrir_e_o_modelo_ainda_queria_pesquisar(tmp_path):
    """O caminho exato das 19h: a rodada 2 bateu no limite (volta o resultado cru), e no
    fechamento só de texto o modelo quis pesquisar. Agora ele pesquisa."""
    c = CerebroSessao([([SPOTIFY], None),                       # cru: "Abri spotify."
                       ([BUSCA], "Abri o Spotify. Segundo o Gran Cursos, até 22 mil policiais.")],
                      responder_erro=ErroQuerFerramenta("O modelo quis usar uma ferramenta."))
    ag, feitos = _agente(c, tmp_path)
    r = asyncio.run(ag.atender(PEDIDO))
    assert feitos == [SPOTIFY] and c.pesquisas == 1
    assert r.texto.startswith("Abri o Spotify. Segundo o Gran Cursos")
    assert "faça agora com a ferramenta" in c.pedidos[1][-1]["content"]


class Membro:
    def __init__(self, nome, erro=None, texto="Oi."):
        self.nome, self.modelo, self.erro, self.texto = nome, nome, erro, texto
        self.descansar_ate = 0.0

    async def responder(self, mensagens):
        if self.erro is not None:
            raise self.erro
        yield self.texto


async def _juntar(fluxo):
    return "".join([p async for p in fluxo])


def test_rodizio_nao_poe_de_castigo_quem_quis_ferramenta():
    gpt, gemini = Membro("gpt", ErroQuerFerramenta("quis")), Membro("gemini", texto="Fiz.")
    r = CerebroRodizio([gpt, gemini])
    assert asyncio.run(_juntar(r.responder([]))) == "Fiz."      # resposta comum: segue o rodízio
    assert gpt.descansar_ate == 0.0                               # sem os 120 s de castigo

    async def fechando():
        marca = PARAR_SE_QUISER_FERRAMENTA.set(True)
        try:
            return await _juntar(r.responder([]))
        finally:
            PARAR_SE_QUISER_FERRAMENTA.reset(marca)
    with pytest.raises(ErroQuerFerramenta):                       # fechamento: o agente decide
        asyncio.run(fechando())


def _sse(*eventos):
    corpo = "".join(f"data: {json.dumps(e)}\n\n" for e in eventos) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, text=corpo)


def test_erro_do_groq_tool_choice_none_vira_quer_ferramenta():
    def groq(req):
        return _sse({"error": {"message": "Tool choice is none, but model called a tool",
                               "type": "invalid_request_error", "code": "tool_use_failed"}})

    c = CerebroCompativelOpenAI(GROQ, "k", "openai/gpt-oss-120b",
                                http_client=httpx.AsyncClient(transport=httpx.MockTransport(groq)))
    with pytest.raises(ErroQuerFerramenta):
        asyncio.run(_juntar(c.responder([{"role": "user", "content": "oi"}])))


def _chamada(nome, args, id_="call_1"):
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1, "model": "m",
                                     "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                                         "role": "assistant", "content": None, "tool_calls": [{
                                             "id": id_, "type": "function",
                                             "function": {"name": nome, "arguments": json.dumps(args)}}]}}]})


def test_a_fala_das_19h_de_ponta_a_ponta(tmp_path):
    """Groq de mentira com a sequência real: abre o Spotify, bate no limite, no fechamento o
    gpt-oss quer pesquisar. Agora: pesquisa (uma vez), sem castigo e sem abrir de novo."""
    vistos = []

    def groq(req):
        corpo = json.loads(req.content)
        textos = " ".join(str(m.get("content") or "") for m in corpo["messages"])
        vistos.append(corpo)
        if corpo.get("stream"):
            return _sse({"error": {"message": "Tool choice is none, but model called a tool"}})
        if corpo.get("tools") == [{"type": "browser_search"}]:
            return _ok("Segundo o blog Gran Cursos, um estudo da PRF prevê até 22 mil policiais.")
        if "faça agora com a ferramenta" in textos:
            if any(m.get("role") == "tool" and "Gran Cursos" in str(m.get("content")) for m in corpo["messages"]):
                return _ok("O Spotify está aberto. Segundo o Gran Cursos, um estudo prevê até 22 mil policiais.")
            return _chamada("pesquisar_internet", {"pergunta": "concurso PRF 22 mil policiais"}, "call_2")
        if any(m.get("role") == "tool" for m in corpo["messages"]):
            return httpx.Response(429, headers={"retry-after": "12"}, json={"error": {
                "message": "Rate limit reached for model `openai/gpt-oss-120b`: tokens per minute (TPM)",
                "type": "tokens", "code": "rate_limit_exceeded"}})
        return _chamada("abrir_programa", {"nome": "spotify"})

    cli = httpx.AsyncClient(transport=httpx.MockTransport(groq))
    gpt = CerebroCompativelOpenAI(GROQ, "k", "openai/gpt-oss-120b", http_client=cli)
    ag, feitos = _agente(CerebroRodizio([gpt]), tmp_path)
    r = asyncio.run(ag.atender(PEDIDO))
    assert feitos == [SPOTIFY]                                  # abriu uma vez só
    assert r.ferramentas == ["abrir_programa", "pesquisar_internet"]
    assert r.texto.startswith("O Spotify está aberto. Segundo o Gran Cursos")
    assert gpt.descansar_ate == 0.0                             # o melhor modelo não ficou de castigo


# ---------------------------------------------------------------- Qwen dentro do limite dele

def _otpm(pedido_tokens=1107):
    return httpx.Response(429, json={"error": {
        "message": ("Request too large for model `qwen/qwen3.8-27b` in organization `org_x` service "
                    f"tier `on_demand` on output tokens per minute (OTPM): Limit 1000, Requested "
                    f"{pedido_tokens}. The request's expected output tokens exceed the enforced "
                    "limit; reduce max_tokens (or the request's expected output) and try again."),
        "type": "tokens", "code": "rate_limit_exceeded"}})


def _ok(texto="Oi!"):
    return httpx.Response(200, json={"id": "x", "object": "chat.completion", "created": 1,
                                     "model": "m", "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": texto}}]})


def _cerebro(modelo, resposta):
    pedidos = []

    def servidor(req):
        corpo = json.loads(req.content)
        pedidos.append(corpo)
        return resposta(corpo)

    cli = httpx.AsyncClient(transport=httpx.MockTransport(servidor))
    base = GROQ if "qwen" in modelo else "https://api.mistral.ai/v1"
    return CerebroCompativelOpenAI(base, "k", modelo, http_client=cli), pedidos


async def _na_conversa(coro):
    marca = SAIDA_CURTA.set(True)
    try:
        return await coro
    finally:
        SAIDA_CURTA.reset(marca)


def test_qwen_do_groq_ja_vai_com_teto_na_conversa():
    c, pedidos = _cerebro("qwen/qwen3.8-27b", lambda corpo: _ok() if corpo.get("max_tokens") else _otpm())
    texto = asyncio.run(_na_conversa(c.com_ferramentas([{"role": "user", "content": "oi"}], [],
                                                       lambda n, a: "")))
    assert texto == "Oi!" and len(pedidos) == 1 and pedidos[0]["max_tokens"] == 800


def test_teto_aprendido_no_erro_e_tentado_na_hora():
    c, pedidos = _cerebro("mistral-small-latest",
                          lambda corpo: _ok() if corpo.get("max_tokens") else _otpm(1435))
    texto = asyncio.run(_na_conversa(c.com_ferramentas([{"role": "user", "content": "oi"}], [],
                                                       lambda n, a: "")))
    assert texto == "Oi!" and [p.get("max_tokens") for p in pedidos] == [None, 800]
    assert c.teto_saida == {"mistral-small-latest": 800}


def test_fora_da_conversa_sem_teto_e_o_rodizio_segue():
    c, pedidos = _cerebro("qwen/qwen3.8-27b", lambda corpo: _ok() if corpo.get("max_tokens") else _otpm())
    with pytest.raises(ErroLimite):                # autoestudo: aula longa não pode ser cortada
        asyncio.run(c.com_ferramentas([{"role": "user", "content": "oi"}], [], lambda n, a: ""))
    assert "max_tokens" not in pedidos[0]


def test_teto_que_nao_resolve_nao_fica_em_laco():
    c, pedidos = _cerebro("qwen/qwen3.8-27b", lambda corpo: _otpm())
    with pytest.raises(ErroCerebro):
        asyncio.run(_na_conversa(c.com_ferramentas([{"role": "user", "content": "oi"}], [],
                                                   lambda n, a: "")))
    assert len(pedidos) == 1


# ---------------------------------------------------------------- o visor grande

class WindowsFalso:
    def __init__(self, janelas, area=(0, 0, 1920, 1040)):
        self._janelas, self._area, self.feito = janelas, area, []

    def janelas(self):
        return self._janelas

    def area(self, hwnd):
        return self._area

    def maximizar(self, hwnd):
        self.feito.append(("maximizar", hwnd))

    def restaurar(self, hwnd):
        self.feito.append(("restaurar", hwnd))

    def mover(self, hwnd, x, y, w, h):
        self.feito.append(("mover", hwnd, x, y, w, h))

    def frente(self, hwnd):
        self.feito.append(("frente", hwnd))


JANELAS = [(11, "Sócrates – Wikipédia, a enciclopédia livre - Pessoal - Microsoft Edge", "Chrome_WidgetWin_1"),
           (12, "Sócrates", "Notepad"), (13, "Sócrates", "Chrome_WidgetWin_1")]


@pytest.mark.parametrize("fala,nome", [
    ("grande", "grande"), ("maximizado", "grande"), ("tela cheia", "grande"), ("grande no centro", "grande"),
    ("no centro", "normal"), ("normal", "normal"), ("menor", "pequeno"), ("pequeno", "pequeno"),
    ("azul", None),
])
def test_nome_do_tamanho(fala, nome):
    assert tam.nome_do_tamanho(fala) == nome


def test_acha_a_janela_do_visor_e_nao_a_aba_nem_o_bloco_de_notas():
    assert tam.achar(JANELAS) == 13
    assert tam.achar(JANELAS[:2]) is None
    assert tam.achar([(21, "Sócrates - Microsoft Edge", "Chrome_WidgetWin_1")]) == 21


def test_retangulo_no_centro_da_area_de_trabalho():
    assert tam.retangulo("normal", (0, 0, 1920, 1040), 1280, 760) == (320, 140, 1280, 760)
    assert tam.retangulo("pequeno", (0, 0, 1920, 1040), 1280, 760) == (384, 208, 1152, 624)
    assert tam.retangulo("normal", (0, 0, 1280, 690), 1280, 760) == (0, 0, 1280, 690)   # tela menor
    assert tam.retangulo("normal", (1920, 0, 3840, 1040), 1280, 760) == (2240, 140, 1280, 760)


def test_ajustar_grande_maximiza_e_normal_centraliza():
    w = WindowsFalso(JANELAS)
    assert tam.ajustar("grande", api=w) == "Pronto, deixei o visor grande, ocupando a tela."
    assert w.feito == [("maximizar", 13), ("frente", 13)]
    w.feito.clear()
    assert "normal" in tam.ajustar("normal", 1280, 760, api=w)
    assert w.feito == [("restaurar", 13), ("mover", 13, 320, 140, 1280, 760), ("frente", 13)]
    assert tam.ajustar("grande", api=WindowsFalso([])) == "Não achei a janela do visor aberta."


def test_a_ligacao_com_o_user32_do_windows(monkeypatch):
    """A classe Windows de verdade, com um user32 falso: pega erro de digitação no ctypes."""
    import ctypes

    titulos = {101: "Sócrates – Wikipédia - Microsoft Edge", 102: "Sócrates", 103: ""}
    classes = {101: "Chrome_WidgetWin_1", 102: "Chrome_WidgetWin_1", 103: "Shell_TrayWnd"}
    chamadas = []

    class Funcao:
        def __init__(self, impl):
            self.impl, self.argtypes, self.restype = impl, None, None

        def __call__(self, *a):
            return self.impl(*a)

    def texto(h, buf, n):
        buf.value = titulos[h][:n - 1]
        return len(buf.value)

    def classe(h, buf, n):
        buf.value = classes[h]
        return len(buf.value)

    def info(monitor, ref):
        r = ref._obj.rcWork
        r.left, r.top, r.right, r.bottom = 0, 0, 1920, 1040
        return 1

    class User32:
        EnumWindows = Funcao(lambda proc, lp: all(proc(h, 0) for h in titulos))
        IsWindowVisible = Funcao(lambda h: 1)
        GetWindowTextLengthW = Funcao(lambda h: len(titulos[h]))
        GetWindowTextW = Funcao(texto)
        GetClassNameW = Funcao(classe)
        ShowWindow = Funcao(lambda h, modo: chamadas.append(("show", h, modo)) or 1)
        SetWindowPos = Funcao(lambda *a: chamadas.append(("pos", *a)) or 1)
        SetForegroundWindow = Funcao(lambda h: chamadas.append(("frente", h)) or 1)
        MonitorFromWindow = Funcao(lambda h, modo: 77)
        GetMonitorInfoW = Funcao(info)

    monkeypatch.setattr(ctypes, "WinDLL", lambda nome, use_last_error=True: User32(), raising=False)
    monkeypatch.setattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE, raising=False)
    w = tam.Windows()
    assert w.janelas() == [(101, titulos[101], "Chrome_WidgetWin_1"), (102, "Sócrates", "Chrome_WidgetWin_1")]
    assert w.area(102) == (0, 0, 1920, 1040)
    assert "pequeno" in tam.ajustar("pequeno", 1280, 760, api=w)
    assert chamadas == [("show", 102, 9), ("pos", 102, None, 384, 208, 1152, 624, 0x44), ("frente", 102)]


def test_fora_do_windows_diz_que_nao_da(monkeypatch):
    monkeypatch.setattr(tam.sys, "platform", "linux")
    assert "só funciona no Windows" in tam.ajustar("grande")
    assert tam.argumentos_de_abertura("normal", 1280, 760) == ["--window-size=1280,760"]


def test_o_edge_ja_abre_do_tamanho_guardado():
    assert "--start-maximized" in tam.argumentos_de_abertura("grande", 1280, 760, api=WindowsFalso([]))
    assert tam.argumentos_de_abertura("normal", 1280, 760, api=WindowsFalso([])) == [
        "--window-size=1280,760", "--window-position=320,140"]


def test_hud_passa_o_tamanho_para_o_edge(monkeypatch):
    from socrates.visor import hud
    abertos = []

    class Processo:
        def __init__(self, args, **kw):
            abertos.append(args)

    monkeypatch.setattr(hud, "achar_navegador", lambda: "msedge.exe")
    monkeypatch.setattr(hud.subprocess, "Popen", Processo)
    monkeypatch.setattr(hud, "argumentos_de_abertura", lambda t, w, h: ["--start-maximized"] if t == "grande" else [])
    h = hud.Hud.__new__(hud.Hud)
    h.url = "http://127.0.0.1:1/"
    assert h.abrir_janela(1280, 760, "grande")
    assert "--start-maximized" in abertos[0]


def test_ferramenta_do_tamanho_muda_e_guarda(monkeypatch):
    feito, guardado = [], []
    monkeypatch.setattr(aparencia.janela_do_visor, "ajustar",
                        lambda nome, w, h: feito.append((nome, w, h)) or f"ok {nome}")
    monkeypatch.setattr(config, "gravar_local", lambda extra: guardado.append(extra))
    assert aparencia.tamanho_do_visor("Grande") == "ok grande"
    assert feito == [("grande", 1280, 760)] and guardado == [{"visor": {"tamanho": "grande"}}]
    assert "Não tenho o tamanho" in aparencia.tamanho_do_visor("xadrez") and len(guardado) == 1


def test_o_cerebro_recebe_a_ferramenta_quando_fala_do_visor():
    assert "tamanho_do_visor" in ferramentas.nomes_das_acoes()
    assert "tamanho_do_visor" in familias_do_pc("Coloque o seu visor grande na tela, no centro.")
    assert "tamanho_do_visor" in familias_do_pc("maximiza você na tela cheia")
    assert config.ConfigVisor().tamanho == "normal"


# ---------------------------------------------------------------- autoestudo: busca mais curta

def test_encurtar_busca():
    from socrates.estudo.autoestudo import encurtar_busca
    assert encurtar_busca("história política de Goiás coronelismo oligarquias Caiado Pedro Ludovico "
                          "Revolução de 1930") == "história política Goiás coronelismo"
    assert encurtar_busca("Constituição Federal art. 37 texto") == "Constituição Federal art. 37"
    assert encurtar_busca("crase") == "" and encurtar_busca("Lei Seca") == ""


def test_busca_comprida_sem_resultado_tenta_a_curta(tmp_path):
    from test_autoestudo import motor
    feitas = []

    def buscar(q):
        feitas.append(q)
        if len(q.split()) > 4:
            raise RuntimeError("No results found.")
        return [{"title": "Página", "href": "https://www.gov.br/goias"}]

    m = motor(tmp_path, buscar=buscar)
    paginas = m._paginas("ondas sonoras efeito Doppler radar velocidade frequência", 2)
    assert feitas == ["ondas sonoras efeito Doppler radar velocidade frequência", "ondas sonoras efeito Doppler"]
    assert len(paginas) == 1 and paginas[0].url == "https://www.gov.br/goias"
