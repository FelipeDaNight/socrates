""""Ele não está entendendo quando chamo ele" (22/11/2026).

No registro: depois de atualizar, 4 minutos de chamados sem nenhuma transcrição, e depois
"Alô, Sócrates, Sócrates, Sócrates". Fora da janela de conversa, a falha da transcrição era
engolida calada (internet lenta naquela hora: a busca do autoestudo deu "operation timed
out"), e a transcrição não tinha limite de tempo (até 10 min presa). Também: o Whisper erra
o nome ("Socates", "Sucrates") e o autoestudo disputava o limite grátis com a conversa.
"""

import asyncio
import logging

import numpy as np
import pytest

from socrates.audio.escuta import Escuta
from socrates.core.despertar import chamou, e_o_nome
from socrates.stt import ErroOuvido
from socrates.visor.quadro import interpretar

from test_maos_livres import _montar, _rodar


@pytest.mark.parametrize("fala,pedido", [
    ("Alô, Sócrates, Sócrates, Sócrates.", ""),
    ("Sócrates, Sócrates, abre o bloco de notas", "abre o bloco de notas"),
    ("Socates, que horas são?", "que horas são?"),
    ("Sucrates me ajuda", "me ajuda"),
    ("Ei Socrades, abre o Spotify", "abre o Spotify"),
    ("Sokrates.", ""),
])
def test_nome_mal_ouvido_ainda_chama(fala, pedido):
    assert chamou(fala) == (True, pedido)


@pytest.mark.parametrize("fala", ["o método socrático é bom", "Democrates venceu a eleição",
                                  "Sorteios de hoje", "o que Sócrates dizia sobre ética"])
def test_palavras_parecidas_nao_chamam(fala):
    assert chamou(fala)[0] is False


def test_e_o_nome():
    assert e_o_nome("socrates") and e_o_nome("socates") and not e_o_nome("sorte")


def test_transcricao_tem_limite_de_tempo():
    from socrates.stt.groq_whisper import TEMPO_MAXIMO, OuvidoWhisper
    o = OuvidoWhisper("http://x", "k")
    assert o._cliente.timeout == TEMPO_MAXIMO <= 30 and o._cliente.max_retries == 1


class OuvidoQueFalha:
    def __init__(self, vezes):
        self.vezes = vezes
        self.chamadas = 0

    async def transcrever(self, wav, dica=None):
        self.chamadas += 1
        if self.chamadas <= self.vezes:
            raise ErroOuvido("Sem conexão para transcrever. Verifique a internet.")
        return "Sócrates, oi"


@pytest.mark.asyncio
async def test_falha_ao_chamar_nao_fica_calada(caplog):
    conversa, s, *_ = _montar()
    s.ouvido = OuvidoQueFalha(2)
    audio = np.full(1600, 1, dtype=np.int16)
    with caplog.at_level(logging.WARNING, logger="socrates.conversa"):
        await _rodar(conversa, [audio, audio, audio])
    assert sum("não consegui transcrever" in r.message for r in caplog.records) == 2
    assert any("Não estou conseguindo te ouvir" in f for f in s.voz.faladas)
    assert "não consegui ouvir" in conversa.painel.aprendendo
    assert conversa._falhas_ouvido == 0                 # a 3ª deu certo: zera


@pytest.mark.asyncio
async def test_aviso_falado_no_maximo_a_cada_5_minutos():
    conversa, s, *_ = _montar()
    s.ouvido = OuvidoQueFalha(6)
    audio = np.full(1600, 1, dtype=np.int16)
    await _rodar(conversa, [audio] * 6)
    assert sum("Não estou conseguindo te ouvir" in f for f in s.voz.faladas) == 1


def test_microfone_registra_chamado_baixo_demais(caplog):
    e = Escuta()
    e.seg.piso = 400.0                                   # limiar = 1200
    with caplog.at_level(logging.INFO, logger="socrates.escuta"):
        e._diagnosticar(900.0, None, agora=e._pico_desde + 1)
        e._diagnosticar(100.0, None, agora=e._pico_desde + 61)
    assert any("perto do limiar" in r.message and "pico 900" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="socrates.escuta"):
        e._diagnosticar(100.0, None, agora=e._pico_desde + 61)   # sala quieta: nada
    assert not caplog.records


def test_quadro_sem_asteriscos_do_markdown():
    itens = interpretar("# Art. 5º\n- **Caput**: todos são iguais\n1. Inciso I\n**Atenção** ao $x^2$")
    assert [i.conteudo for i in itens] == ["Art. 5º", "Caput: todos são iguais", "1. Inciso I",
                                           "Atenção ao $x^2$"]
    assert itens[2].tipo == "item"


@pytest.mark.asyncio
async def test_autoestudo_espera_a_conversa():
    from socrates.estudo.autoestudo import Autoestudo
    from socrates.estudo.plano import carregar_planos
    estado = {"ocupado": True}
    a = Autoestudo(carregar_planos(ids=["prf"]), escritor=None, buscar=None, ler=None,
                   ocupado=lambda: estado["ocupado"])

    async def soltar():
        await asyncio.sleep(1.2)
        estado["ocupado"] = False

    inicio = asyncio.get_running_loop().time()
    await asyncio.gather(a._esperar_conversa(maximo=5), soltar())
    assert 1.0 <= asyncio.get_running_loop().time() - inicio < 4


def test_chaves_extras_no_env_local(tmp_path, monkeypatch):
    """A chave do Gemini foi gravada em .env.local (sem abrir o .env, que guarda a do Groq)."""
    from socrates import config
    (tmp_path / "config.yaml").write_text((config.RAIZ / "config.yaml").read_text(encoding="utf-8"),
                                          encoding="utf-8")
    (tmp_path / ".env").write_text("GROQ_API_KEY=do-env\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("GEMINI_API_KEY=do-local\nGROQ_API_KEY=nao-vale\n",
                                         encoding="utf-8")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setattr(config, "RAIZ", tmp_path)
    import os
    try:
        config.carregar(tmp_path / "config.yaml")
        assert os.environ["GEMINI_API_KEY"] == "do-local" and os.environ["GROQ_API_KEY"] == "do-env"
    finally:                                   # não deixa as chaves de teste para os outros testes
        os.environ.pop("GEMINI_API_KEY", None)
        os.environ.pop("GROQ_API_KEY", None)


# ---------------------------------------------------------------- microfone que cai e volta

class FluxoFalso:
    """Lê 2 blocos e "perde o driver" (MME error 6), como em 22/11 às 17:35."""

    def __init__(self, falhar):
        self.falhar = falhar
        self.lidos = 0

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n):
        self.lidos += 1
        if self.falhar and self.lidos > 2:
            raise RuntimeError("There is no driver installed on your system. [MME error 6]")
        return np.zeros((n, 1), dtype=np.int16), False


def test_microfone_cai_e_reconecta_sozinho(monkeypatch):
    import socrates.audio.escuta as esc

    abertos, reinicios = [], []

    class SdFalso:
        def InputStream(self, **k):
            f = FluxoFalso(falhar=len(abertos) == 0)       # o 1º cai; o 2º funciona
            abertos.append(f)
            return f

        def _terminate(self):
            reinicios.append("t")

        def _initialize(self):
            reinicios.append("i")

    entregues = []
    e = esc.Escuta()
    monkeypatch.setattr(esc, "importar_sounddevice", lambda: SdFalso())
    monkeypatch.setattr(esc, "ESPERAS_RECONEXAO", (0.01,))

    def entregar(item):
        entregues.append(item)
        if isinstance(item, esc.EventoMicrofone) and item.voltou:
            e.parar()

    e._entregar = entregar
    e._rodar()
    eventos = [i for i in entregues if isinstance(i, esc.EventoMicrofone)]
    assert [ev.voltou for ev in eventos] == [False, True]
    assert "desconectou" in eventos[0].texto and reinicios == ["t", "i"] and len(abertos) == 2


@pytest.mark.asyncio
async def test_conversa_avisa_que_o_microfone_caiu_e_voltou():
    from socrates.audio.escuta import EventoMicrofone
    conversa, s, *_ = _montar()
    await _rodar(conversa, [EventoMicrofone("O microfone desconectou (x). Estou tentando reconectar.",
                                            False),
                            EventoMicrofone("Voltei a te ouvir.", True)])
    assert s.voz.faladas[:2] == ["O microfone desconectou (x). Estou tentando reconectar.",
                                 "Voltei a te ouvir."]


# ---------------------------------------------------------------- "Cloud" é o Claude

@pytest.mark.parametrize("fala,certo", [
    ("Você pode digitar no Cloud o que deve melhorar?", "Você pode digitar no Claude o que deve melhorar?"),
    ("Manda suas ideias para o Clout.", "Manda suas ideias para o Claude."),
    ("Não foi enviado ao Claudio", "Não foi enviado ao Claude"),
    ("o que é computação em nuvem, cloud computing?", "o que é computação em nuvem, cloud computing?"),
])
def test_cloud_e_o_claude(fala, certo):
    from socrates.core.despertar import nome_do_claude
    assert nome_do_claude(fala) == certo


def test_frase_inventada_em_maiusculas_e_descartada():
    from socrates.stt.groq_whisper import parece_legenda
    assert parece_legenda("A CIDADE NO BRASIL", -0.95) and parece_legenda("CELSO SÓRICA", -0.84)
    assert not parece_legenda("SÓCRATES", -0.75) and not parece_legenda("A CIDADE NO BRASIL", -0.3)


def test_anotar_melhoria_deixa_claro_que_nao_enviou(tmp_path):
    from socrates.core.agente import Agente
    from socrates.core.memoria import Memorias

    class C:
        async def com_ferramentas(self, *a, **k):
            return ""

    ag = Agente(C(), memorias=Memorias(tmp_path / "S"))
    r = ag.sugerir_melhoria("Sincronizar algo")
    assert "NÃO foi enviada" in r and "pedir_ao_claude" in r


@pytest.mark.asyncio
async def test_saudacao_le_o_recado_do_claude_uma_vez(tmp_path, monkeypatch):
    import socrates.core.memoria as mem
    monkeypatch.setattr(mem, "PASTA", tmp_path)
    (tmp_path / "recado_do_claude.txt").write_text("Agora eu reconecto o microfone sozinho.",
                                                   encoding="utf-8")
    conversa, s, *_ = _montar()
    conversa.cfg.voz.saudacao = True
    await _rodar(conversa, [])
    assert "Recado do Claude: Agora eu reconecto o microfone sozinho." in s.voz.faladas[0]
    assert not (tmp_path / "recado_do_claude.txt").exists()
    assert (tmp_path / "recado_do_claude.lido.txt").exists()
