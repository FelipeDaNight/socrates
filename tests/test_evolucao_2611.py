"""Evolução de 26/11/2026: mais cérebros grátis no rodízio e filtro de voz antes do Whisper.

- Em 25/11 a conversa esperou até 90 s: o Groq bateu 8 mil tokens/min, o Gemini deu 503 e o
  autoestudo gastava o mesmo limite no meio da aula. Agora há mais modelos grátis com as
  mesmas chaves (cada modelo tem o seu limite) e o autoestudo só estuda com 5 min de quieto.
- O Whisper inventava frases para sopro, clique e TV ("Legenda Adriana Zanotto", "FFFF!").
  O detector de voz (Silero VAD, MIT) descarta o que não tem voz antes da transcrição.
  tests/dados/fala_silero.wav: 1,5 s do áudio de teste do próprio Silero VAD (MIT).
"""

import os
import types
import wave
from pathlib import Path

import numpy as np
import pytest

from socrates import config
from socrates.llm.compativel_openai import CerebroCompativelOpenAI

from test_maos_livres import _montar, _rodar

DADOS = Path(__file__).parent / "dados"


# ---------------------------------------------------------------- rodízio maior

def test_rodizio_tem_mais_modelos_gratis_com_as_mesmas_chaves(monkeypatch):
    for k in ("MISTRAL_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("GEMINI_API_KEY", "m")
    cfg = config.carregar(config.RAIZ / "config.yaml")
    nomes = [c.provedor for c in cfg.rodizio]
    assert nomes[:2] == ["groq", "gemini"]
    assert {"groq_qwen", "groq_leve", "gemini_leve"} <= set(nomes)
    assert "openrouter" not in nomes and "mistral" not in nomes        # sem chave: pulados


def test_openrouter_entra_quando_tem_chave(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("OPENROUTER_API_KEY", "o")
    try:
        cfg = config.carregar(config.RAIZ / "config.yaml")
        orc = next(c for c in cfg.rodizio if c.provedor == "openrouter")
        assert orc.modelo.endswith(":free") and "openrouter.ai" in orc.base_url
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


def test_autoestudo_nao_disputa_o_limite_no_meio_da_aula():
    import yaml
    dados = yaml.safe_load((config.RAIZ / "config.yaml").read_text(encoding="utf-8"))
    assert dados["autoestudo"]["ocioso_seg"] >= 300
    assert dados["autoestudo"]["cerebros"][0] == "groq_qwen"   # poupa o modelo principal da conversa


# ---------------------------------------------------------------- raciocínio por modelo

def _cerebro(base, modelo):
    return CerebroCompativelOpenAI(base_url=base, chave="k", modelo=modelo)


def test_qwen_do_groq_responde_sem_pensar_alto():
    groq = "https://api.groq.com/openai/v1"
    assert _cerebro(groq, "qwen/qwen3.8-27b")._extras("qwen/qwen3.8-27b") == {"reasoning_effort": "none"}
    assert _cerebro(groq, "openai/gpt-oss-120b")._extras("openai/gpt-oss-120b") == {"reasoning_effort": "low"}
    assert _cerebro(groq, "openai/gpt-oss-120b")._extras("openai/gpt-oss-120b", False) == {}
    fora = "https://openrouter.ai/api/v1"
    assert _cerebro(fora, "openai/gpt-oss-120b:free")._extras("openai/gpt-oss-120b:free") == {}


class _Pedaco:
    def __init__(self, texto):
        self.choices = [types.SimpleNamespace(delta=types.SimpleNamespace(content=texto))]


class _ClienteFalso:
    def __init__(self, partes):
        self.pedidos = []
        cliente = self

        class _Completions:
            async def create(self, **pedido):
                cliente.pedidos.append(pedido)

                async def fluxo():
                    for p in partes:
                        yield _Pedaco(p)
                return fluxo()

        self.chat = types.SimpleNamespace(completions=_Completions())


@pytest.mark.asyncio
async def test_pensamento_entre_think_nunca_vai_para_a_voz():
    c = _cerebro("https://api.groq.com/openai/v1", "qwen/qwen3.8-27b")
    c._cliente = _ClienteFalso(["<thi", "nk>vou explicar a crase</th", "ink>", "Crase é ", "a fusão."])
    texto = "".join([p async for p in c.responder([{"role": "user", "content": "crase"}])])
    assert texto == "Crase é a fusão."
    assert c._cliente.pedidos[0]["reasoning_effort"] == "none"


# ---------------------------------------------------------------- detector de voz

def _fala():
    with wave.open(str(DADOS / "fala_silero.wav")) as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def test_detector_reconhece_voz_e_ignora_chiado():
    pytest.importorskip("onnxruntime")
    from socrates.audio.vad import DetectorDeVoz
    d = DetectorDeVoz()
    assert d.tem_voz(_fala()) and d.segundos_de_voz(_fala()) > 1.0
    ruido = np.random.default_rng(0).normal(0, 3000, 32000).astype(np.int16)
    assert not d.tem_voz(ruido) and not d.tem_voz(np.zeros(32000, dtype=np.int16))


def test_sem_onnxruntime_nada_e_filtrado(monkeypatch):
    import builtins
    from socrates.audio import vad
    original = builtins.__import__

    def sem_ort(nome, *a, **k):
        if nome == "onnxruntime":
            raise ImportError("sem onnxruntime")
        return original(nome, *a, **k)

    monkeypatch.setattr(builtins, "__import__", sem_ort)
    assert vad.carregar() is None


class VadFalso:
    def __init__(self, segundos):
        self.segundos = segundos

    def segundos_de_voz(self, audio):
        return self.segundos


@pytest.mark.asyncio
async def test_som_sem_voz_nao_gasta_o_whisper():
    conversa, s, painel, cerebro, _ = _montar()
    conversa.vad = VadFalso(0.05)
    await _rodar(conversa, [s.ouvido.fala("Sócrates, Legenda Adriana Zanotto")])
    assert s.ouvido.chamadas == 0 and cerebro.recebido == []


@pytest.mark.asyncio
async def test_resposta_curta_na_janela_passa_e_fora_da_janela_precisa_de_mais_voz():
    conversa, s, painel, cerebro, _ = _montar()
    conversa.vad = VadFalso(0.15)                 # um "Sim." curto
    painel.abrir_janela(30)
    await _rodar(conversa, [s.ouvido.fala("Sim.")])
    assert s.ouvido.chamadas == 1                 # na janela: vai para o Whisper

    conversa, s, painel, cerebro, _ = _montar()
    conversa.vad = VadFalso(0.15)
    await _rodar(conversa, [s.ouvido.fala("Sócrates")])
    assert s.ouvido.chamadas == 0                 # fora da janela: o nome tem mais voz que isso


@pytest.mark.asyncio
async def test_detector_que_quebra_e_desligado_e_a_fala_segue():
    class VadQuebrado:
        def segundos_de_voz(self, audio):
            raise RuntimeError("onnx quebrou")

    conversa, s, painel, cerebro, _ = _montar()
    conversa.vad = VadQuebrado()
    await _rodar(conversa, [s.ouvido.fala("Sócrates, oi")])
    assert s.ouvido.chamadas == 1 and conversa.vad is None


# ---------------------------------------------------------------- só as ferramentas do assunto

def _agente_pc(tmp_path, cerebro=None):
    from socrates import ferramentas
    from socrates.core.agente import Agente
    from socrates.core.memoria import Memorias

    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    return Agente(cerebro or C(), memorias=Memorias(tmp_path / "S"),
                  acoes_pc=ferramentas.nomes_das_acoes(), executar_pc=lambda n, a: "ok")


def test_pedido_ao_pc_leva_so_as_ferramentas_do_assunto(tmp_path):
    import json
    ag = _agente_pc(tmp_path)

    def nomes(pedido, historico=None):
        return {e["function"]["name"] for e in ag.esquemas(True, pedido, historico or [])} \
            & set(ag.acoes_pc)

    assert nomes("toca lo-fi no youtube") == {"musica", "volume", "abrir_site"}
    assert nomes("inicia um pomodoro de português") == {"iniciar_timer", "consultar_timer",
                                                        "cancelar_timer", "iniciar_pomodoro"}
    assert nomes("manda pro Claude deixar a voz grave") == {"pedir_ao_claude", "atualizar_socrates"}
    assert nomes("faz aquilo de novo") == set(ag.acoes_pc)            # sem assunto: todas
    assert "fechar_programa" in nomes("e agora fecha", [{"role": "user", "content": "abre a calculadora"}])
    tudo = len(json.dumps(ag.esquemas(True), ensure_ascii=False))
    pouco = len(json.dumps(ag.esquemas(True, "toca lo-fi no youtube"), ensure_ascii=False))
    assert pouco < 0.65 * tudo


@pytest.mark.asyncio
async def test_se_recusar_a_segunda_tentativa_tem_todas_as_ferramentas(tmp_path):
    class Roteiro:
        def __init__(self):
            self.vistas = []

        async def com_ferramentas(self, msgs, esquemas, executar, **k):
            self.vistas.append({e["function"]["name"] for e in esquemas})
            if len(self.vistas) == 1:
                return "Não consigo abrir isso daqui, desculpe."
            await executar("abrir_site", {"url": "https://youtube.com"})
            return "Pronto, abri."

    c = Roteiro()
    ag = _agente_pc(tmp_path, c)
    r = await ag.atender("toca o som do youtube")
    assert c.vistas[0] & set(ag.acoes_pc) == {"musica", "volume", "abrir_site"}
    assert set(ag.acoes_pc) <= c.vistas[1]                   # na insistência, todas as do PC
    assert r.texto == "Pronto, abri."


# ---------------------------------------------------------------- cache de prompt do Groq

def test_comeco_do_pedido_fica_igual_e_o_que_muda_vai_no_fim(tmp_path):
    """O Groq guarda o começo do pedido (persona, ferramentas) e o que vem do cache não conta
    no limite por minuto. A hora mudava a cada minuto logo depois da persona e estragava isso."""
    from socrates.core.agente import Agente
    from socrates.core.memoria import Memorias

    class C:
        async def com_ferramentas(self, *a, **k):
            return ""

    hora = {"agora": "Agora é quarta, 25/11/2026, 23:31."}
    ag = Agente(C(), memorias=Memorias(tmp_path / "S"), contexto=lambda: hora["agora"])
    antes = ag.mensagens("explica de novo", [])
    hora["agora"] = "Agora é quarta, 25/11/2026, 23:32."
    depois = ag.mensagens("explica de novo", [])
    assert antes[0] == depois[0]                                  # o começo é o mesmo
    assert "23:32" in depois[-2]["content"] and depois[-1]["role"] == "user"
    assert "23:3" not in depois[0]["content"]
