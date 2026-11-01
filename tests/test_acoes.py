"""Ações no computador, sem abrir nada de verdade."""

import json
import time

import httpx2 as httpx
import pytest

from socrates import ferramentas
from socrates.ferramentas import computador as pc
from socrates.llm import CerebroCompativelOpenAI
from socrates.llm.acoes import CerebroComAcoes, pede_acao
from socrates.llm.falso import CerebroFalso


@pytest.fixture
def abertos(monkeypatch):
    lista = []
    monkeypatch.setattr(pc, "_iniciar", lista.append)
    return lista


# ---------- quando é ação ----------

@pytest.mark.parametrize("frase,esperado", [
    ("Abre a calculadora", True),
    ("Por favor, abre o YouTube", True),
    ("Toca lo-fi pra estudar no YouTube", True),
    ("Aumenta o volume", True),
    ("Inicia um pomodoro de 25 minutos", True),
    ("Quanto tempo falta?", True),
    ("Anota que tenho prova sexta", True),
    ("Cancela o timer", True),
    ("O que é crase?", False),
    ("Me explica a fórmula de Bhaskara", False),
    ("Qual a cotação do dólar?", False),
    ("Me testa em concordância", False),
])
def test_pede_acao(frase, esperado):
    assert pede_acao(frase) is esperado


# ---------- ferramentas ----------

def test_abre_programa_conhecido(abertos):
    assert pc.abrir_programa("a Calculadora") == "Abri a Calculadora."
    assert pc.abrir_programa("Word") == "Abri Word."
    assert abertos == ["calc", "winword"]


def test_programa_desconhecido_explica(abertos):
    r = pc.abrir_programa("Photoshop")
    assert "Não conheço" in r and "config.yaml" in r and abertos == []


def test_programas_do_config(abertos):
    pc.adicionar_programas({"Anki": r"C:\Anki\anki.exe"})
    pc.abrir_programa("anki")
    assert abertos == [r"C:\Anki\anki.exe"]


def test_site_ganha_https(abertos):
    pc.abrir_site("g1.globo.com")
    assert abertos == ["https://g1.globo.com"]


def test_busca_no_youtube_codifica_o_termo(abertos):
    pc.buscar_no_navegador("lo-fi & chuva", "youtube")
    assert abertos == ["https://www.youtube.com/results?search_query=lo-fi+%26+chuva"]


def test_pasta_desconhecida(abertos):
    assert "Não conheço a pasta" in pc.abrir_pasta("sistema32")


def test_timer_avisa_quando_acaba(monkeypatch):
    avisos = []
    monkeypatch.setattr(pc, "avisar", avisos.append)
    assert pc.iniciar_timer(0.002, "estudo").endswith("iniciado.")
    assert "Faltam" in pc.consultar_timer()
    time.sleep(0.4)
    assert avisos == ["Seu tempo de estudo acabou! Hora de fazer uma pausa."]
    assert pc.consultar_timer() == "Não há nenhum timer ativo."


def test_timer_cancelado_nao_avisa(monkeypatch):
    avisos = []
    monkeypatch.setattr(pc, "avisar", avisos.append)
    pc.iniciar_timer(0.003)
    assert pc.cancelar_timer() == "Timer cancelado."
    time.sleep(0.4)
    assert avisos == []


def test_timer_fala_minutos_bem():
    assert pc.iniciar_timer(25, "estudo") == "Timer de 25 minutos iniciado."
    pc.cancelar_timer()
    assert "entre" in pc.iniciar_timer(0)


def test_anotar_cria_caderno(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "PASTA_SOCRATES", tmp_path / "Socrates")
    assert pc.anotar("Prova da PRF dia 10") == "Anotado no seu caderno."
    conteudo = (tmp_path / "Socrates" / "anotacoes.md").read_text(encoding="utf-8")
    assert "Prova da PRF dia 10" in conteudo


def test_executar_transforma_erro_em_texto():
    assert "não existe" in ferramentas.executar("formatar_disco", {})
    assert "Erro" in ferramentas.executar("iniciar_timer", {"motivo": "sem minutos"})
    r = ferramentas.executar("abrir_site", {"endereco": "g1.globo.com", "lixo": 1})
    assert "Abri" in r or "Erro" in r   # argumento estranho é ignorado


def test_esquema_tem_opcoes_e_descricoes():
    esq = ferramentas.REGISTRO["volume"].esquema()["function"]
    assert esq["parameters"]["properties"]["acao"]["enum"] == ["aumentar", "diminuir", "mudo"]
    assert esq["parameters"]["properties"]["quanto"]["type"] == "integer"
    assert esq["parameters"]["required"] == ["acao"]


# ---------- vaivém com o Groq ----------

def _resposta(msg):
    return httpx.Response(200, json={"id": "1", "object": "chat.completion", "created": 0,
                                     "model": "openai/gpt-oss-120b",
                                     "choices": [{"index": 0, "finish_reason": "stop", "message": msg}]})


@pytest.mark.asyncio
async def test_cerebro_chama_a_ferramenta_e_confirma(abertos):
    pedidos = []

    def groq(req):
        corpo = json.loads(req.content)
        pedidos.append(corpo)
        if len(pedidos) == 1:
            return _resposta({"role": "assistant", "content": None, "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "abrir_programa", "arguments": '{"nome": "calculadora"}'}}]})
        return _resposta({"role": "assistant", "content": "Pronto, abri a calculadora."})

    base = CerebroCompativelOpenAI("https://api.groq.com/openai/v1", "k", "openai/gpt-oss-120b",
                                   http_client=httpx.AsyncClient(transport=httpx.MockTransport(groq)))
    nomes = ["abrir_programa", "volume"]
    cerebro = CerebroComAcoes(CerebroFalso("não deveria"), base, nomes)
    msgs = [{"role": "system", "content": "persona"}, {"role": "user", "content": "abre a calculadora"}]
    texto = "".join([p async for p in cerebro.responder(msgs)])

    assert texto == "Pronto, abri a calculadora."
    assert abertos == ["calc"]
    assert [t["function"]["name"] for t in pedidos[0]["tools"]] == nomes
    assert "controlar o computador" in pedidos[0]["messages"][0]["content"]
    volta = pedidos[1]["messages"]
    assert volta[-1] == {"role": "tool", "tool_call_id": "c1", "content": "Abri calculadora."}


@pytest.mark.asyncio
async def test_pergunta_normal_nao_usa_ferramentas():
    class SemFerramentas(CerebroFalso):
        async def com_ferramentas(self, *a):
            raise AssertionError("não deveria chamar")

    interno = CerebroFalso("Crase é a fusão.")
    cerebro = CerebroComAcoes(interno, SemFerramentas())
    msgs = [{"role": "user", "content": "O que é crase?"}]
    assert "".join([p async for p in cerebro.responder(msgs)]).strip() == "Crase é a fusão."


# ---------- bug real: "você pode abrir o Chrome?" não virava ação ----------

@pytest.mark.parametrize("frase", [
    "Você pode abrir o Chrome?",
    "Consegue abrir o Google Chrome pra mim?",
    "Quero que você toque uma música no YouTube",
    "Abrir o Word",
    "Pode aumentar o volume?",
    "Dá pra iniciar um timer de 10 minutos?",
])
def test_pedidos_educados_sao_acao(frase):
    assert pede_acao(frase)


@pytest.mark.parametrize("frase", [
    "Por que a crase é usada antes de palavra feminina?",
    "Você pode me explicar crase?",
    "Pode me testar em regência?",
])
def test_perguntas_nao_viram_acao(frase):
    assert not pede_acao(frase)


@pytest.mark.asyncio
async def test_modelo_avisa_executar_e_vira_acao():
    class Base(CerebroFalso):
        async def com_ferramentas(self, mensagens, esquemas, executar):
            self.msgs_acao = mensagens
            return "Pronto, abri o Chrome."

    base = Base("")
    cerebro = CerebroComAcoes(CerebroFalso("EXECUTAR"), base, ["abrir_programa"])
    msgs = [{"role": "system", "content": "persona\n\n" + __import__(
        "socrates.llm.acoes", fromlist=["x"]).INSTRUCAO_MARCADOR},
            {"role": "user", "content": "Será que dá pro senhor abrir o navegador?"}]
    texto = "".join([p async for p in cerebro.responder(msgs)])
    assert texto == "Pronto, abri o Chrome."
    assert "responda APENAS com a palavra EXECUTAR" not in base.msgs_acao[0]["content"]


def test_chrome_nao_achado_abre_navegador_padrao(monkeypatch):
    abertos = []
    monkeypatch.setattr(pc, "_iniciar", lambda alvo: (_ for _ in ()).throw(FileNotFoundError(alvo)))
    monkeypatch.setattr(pc.webbrowser, "open", abertos.append)
    assert "navegador padrão" in pc.abrir_programa("Chrome")
    assert abertos == ["https://www.google.com"]


def test_programa_nao_instalado_explica(monkeypatch):
    monkeypatch.setattr(pc, "_iniciar", lambda alvo: (_ for _ in ()).throw(FileNotFoundError(alvo)))
    assert "não foi encontrado" in pc.abrir_programa("Spotify")


def test_windows_tenta_varios_jeitos(monkeypatch, tmp_path):
    exe = tmp_path / "chrome.exe"
    exe.write_text("")
    monkeypatch.setitem(pc.CAMINHOS, "chrome", [str(exe)])
    monkeypatch.setattr(pc.shutil, "which", lambda a: None)
    assert pc._candidatos("chrome") == ["chrome", "chrome.exe", str(exe)]
    assert pc._candidatos("https://g1.globo.com") == ["https://g1.globo.com"]
