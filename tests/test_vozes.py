"""Vozes: Edge com tom, Gemini, reserva automática e o provador."""

import base64
import io
import json
import urllib.error
import wave

import numpy as np
import pytest
import yaml

from socrates.config import ConfigVoz
from socrates.tts import ErroVoz, Voz
from socrates.tts import gemini as g
from socrates.tts.edge import VozEdge
from socrates.tts.fabrica import CANDIDATAS, criar_voz
from socrates.tts.reserva import FALHAS_PARA_DESCANSAR, VozComReserva


def _wav(n=2400, taxa=24_000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(taxa)
        w.writeframes((np.ones(n) * 1000).astype(np.int16).tobytes())
    return buf.getvalue()


# ---------- Gemini ----------

def test_pedido_no_formato_do_gemini():
    p = g.montar_pedido("Olá!", "Sadaltager", "gemini-3.8-flash-tts", "calmo")
    assert p["model"] == "gemini-3.8-flash-tts"
    assert p["generation_config"]["speech_config"] == [{"voice": "Sadaltager"}]
    conteudo = p["input"][0]["content"][0]
    assert conteudo["text"] == "Olá!"     # o texto vai literal; o estilo vai separado
    assert conteudo["annotations"] == [{"type": "speech_metadata", "style": "calmo"}]
    assert p["response_format"] == {"type": "audio"}


def test_extrai_o_ultimo_audio():
    resp = {"steps": [
        {"type": "thought", "content": [{"type": "text", "text": "..."}]},
        {"type": "model_output", "content": [
            {"type": "audio", "data": base64.b64encode(b"velho").decode()},
            {"type": "audio", "data": base64.b64encode(b"novo").decode()}]}]}
    assert g.extrair_audio(resp) == b"novo"
    with pytest.raises(ErroVoz):
        g.extrair_audio({"steps": []})


def test_le_wav_e_pcm():
    amostras, taxa = g.wav_para_amostras(_wav(2400, 24_000))
    assert taxa == 24_000 and len(amostras) == 2400
    amostras, taxa = g.wav_para_amostras(np.zeros(10, dtype=np.int16).tobytes())
    assert taxa == 24_000 and len(amostras) == 10


class _Resposta(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): self.close()


def test_gemini_manda_chave_no_cabecalho(monkeypatch):
    vistos = []

    def falso_urlopen(req, timeout):
        vistos.append(req)
        dados = base64.b64encode(_wav()).decode()
        return _Resposta(json.dumps({"steps": [{"type": "model_output",
                                                "content": [{"type": "audio", "data": dados}]}]}).encode())

    monkeypatch.setattr(g.urllib.request, "urlopen", falso_urlopen)
    audio = g.VozGemini("minha-chave")._pedir("Olá")
    req = vistos[0]
    assert req.full_url == g.URL and req.get_header("X-goog-api-key") == "minha-chave"
    assert json.loads(req.data)["generation_config"]["speech_config"][0]["voice"] == "Sadaltager"
    assert audio[:4] == b"RIFF"


@pytest.mark.parametrize("codigo,trecho", [(429, "Limite"), (403, "Chave"), (500, "recusou")])
def test_gemini_erros_viram_frases(monkeypatch, codigo, trecho):
    def falso_urlopen(req, timeout):
        raise urllib.error.HTTPError(req.full_url, codigo, "x", {}, io.BytesIO(b'{"error":"x"}'))

    monkeypatch.setattr(g.urllib.request, "urlopen", falso_urlopen)
    with pytest.raises(ErroVoz, match=trecho):
        g.VozGemini("k")._pedir("Olá")


# ---------- Edge com tom ----------

@pytest.mark.asyncio
async def test_edge_manda_tom_e_velocidade(monkeypatch):
    import edge_tts
    vistos = {}

    class Falso:
        def __init__(self, texto, voz, rate, pitch):
            vistos.update(texto=texto, voz=voz, rate=rate, pitch=pitch)

        async def stream(self):
            yield {"type": "audio", "data": b"mp3"}

    monkeypatch.setattr(edge_tts, "Communicate", Falso)
    audio = await VozEdge("pt-BR-AntonioNeural", "-4%", tom="-6Hz").sintetizar("Olá")
    assert audio == b"mp3" and vistos["pitch"] == "-6Hz" and vistos["rate"] == "-4%"


# ---------- reserva ----------

class VozTeste(Voz):
    def __init__(self, nome, falhar=False):
        self.nome, self.falhar, self.tocadas, self.pedidos = nome, falhar, [], 0

    async def sintetizar(self, texto):
        self.pedidos += 1
        if self.falhar:
            raise ErroVoz("Limite grátis da voz do Gemini atingido.")
        return f"{self.nome}:{texto}"

    async def tocar(self, audio):
        self.tocadas.append(audio)


@pytest.mark.asyncio
async def test_reserva_assume_quando_a_principal_falha():
    principal, reserva = VozTeste("gemini", falhar=True), VozTeste("edge")
    voz = VozComReserva(principal, reserva)
    await voz.tocar(await voz.sintetizar("Olá"))
    assert reserva.tocadas == ["edge:Olá"]


@pytest.mark.asyncio
async def test_reserva_descansa_a_principal_depois_de_varias_falhas():
    avisos = []
    principal, reserva = VozTeste("gemini", falhar=True), VozTeste("edge")
    voz = VozComReserva(principal, reserva, avisos.append)
    for i in range(FALHAS_PARA_DESCANSAR + 3):
        await voz.sintetizar(f"frase {i}")
    assert principal.pedidos == FALHAS_PARA_DESCANSAR   # parou de insistir
    assert len(avisos) == 1 and "10 minutos" in avisos[0]


@pytest.mark.asyncio
async def test_principal_funcionando_e_usada():
    principal, reserva = VozTeste("gemini"), VozTeste("edge")
    voz = VozComReserva(principal, reserva)
    await voz.tocar(await voz.sintetizar("Oi"))
    assert principal.tocadas == ["gemini:Oi"] and reserva.pedidos == 0


# ---------- fábrica e provador ----------

def test_fabrica_edge_por_padrao():
    voz = criar_voz(ConfigVoz(tom="-6Hz"), alto_falante=None)
    assert isinstance(voz, VozEdge) and voz.tom == "-6Hz"


def test_fabrica_gemini_sem_chave_avisa_e_usa_edge(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    avisos = []
    voz = criar_voz(ConfigVoz(provedor="gemini"), None, avisos.append)
    assert isinstance(voz, VozEdge) and "GEMINI_API_KEY" in avisos[0]


def test_fabrica_gemini_com_chave_tem_reserva(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    voz = criar_voz(ConfigVoz(provedor="gemini", gemini_voz="Charon"), None)
    assert isinstance(voz, VozComReserva)
    assert voz.principal.voz == "Charon" and isinstance(voz.reserva, VozEdge)


@pytest.mark.parametrize("candidata", CANDIDATAS, ids=lambda c: c.rotulo)
def test_provador_gera_config_valido(candidata):
    trecho = yaml.safe_load(candidata.config_yaml())["voz"]
    cfg = ConfigVoz(**trecho)
    assert cfg.provedor == candidata.provedor
