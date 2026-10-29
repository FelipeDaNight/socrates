"""Testes da fase 1 sem microfone, alto-falante ou internet."""

import asyncio
import io
import json
import shutil
import subprocess
import wave

import httpx2 as httpx
import numpy as np
import pytest

from socrates.audio.microfone import AjustesMic, DetectorDeFala, Status, para_wav
from socrates.core.comandos import Comando, interpretar
from socrates.core.narrador import narrar
from socrates.llm import ErroCerebro
from socrates.stt.groq_whisper import OuvidoWhisper, filtrar_alucinacao
from socrates.tts import ErroVoz, Voz
from socrates.tts.limpeza import limpar_para_fala

TAXA = 16_000
BLOCO = 480  # 30 ms


def _ruido(seg, nivel=60, semente=0):
    rng = np.random.default_rng(semente)
    return (rng.normal(0, nivel, int(TAXA * seg))).astype(np.int16)


def _voz(seg, amplitude=3000):
    t = np.arange(int(TAXA * seg)) / TAXA
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def _rodar_detector(sinal, ajustes=None):
    d = DetectorDeFala(ajustes or AjustesMic())
    status = Status.CONTINUAR
    for i in range(0, len(sinal) - BLOCO + 1, BLOCO):
        status = d.alimentar(sinal[i:i + BLOCO])
        if status is not Status.CONTINUAR:
            break
    return d, status


# ---------- microfone ----------

def test_detector_grava_fala_e_para_no_silencio():
    sinal = np.concatenate([_ruido(1), _voz(2), _ruido(3, semente=1)])
    d, status = _rodar_detector(sinal)
    assert status is Status.TERMINOU
    dur = len(d.audio()) / TAXA
    # 2 s de fala + ~1,2 s de silêncio + pré-gravação: não corta nem estica demais
    assert 3.0 < dur < 3.8


def test_detector_desiste_se_ninguem_fala():
    d, status = _rodar_detector(_ruido(10), AjustesMic(espera_seg=3))
    assert status is Status.NADA
    assert d.limiar is not None and len(d.audio()) == 0


def test_detector_respeita_tempo_maximo():
    sinal = np.concatenate([_ruido(0.5), _voz(10)])
    d, status = _rodar_detector(sinal, AjustesMic(max_seg=4))
    assert status is Status.TERMINOU
    assert len(d.audio()) / TAXA <= 4.1


def test_detector_se_ajusta_a_sala_barulhenta():
    barulho = _ruido(1, nivel=900)            # ventilador, rua
    d, _ = _rodar_detector(np.concatenate([barulho, _ruido(3, nivel=900, semente=2)]),
                           AjustesMic(espera_seg=3))
    assert d.limiar > 2000 and not d.falando  # barulho sozinho não conta como fala


def test_wav_valido_para_o_whisper():
    dados = para_wav(_voz(0.5))
    with wave.open(io.BytesIO(dados)) as w:
        assert (w.getnchannels(), w.getframerate(), w.getsampwidth()) == (1, TAXA, 2)
        assert w.getnframes() == TAXA // 2


# ---------- ouvido ----------

def test_filtra_alucinacoes_do_whisper():
    assert filtrar_alucinacao("Legendas pela comunidade Amara.org") == ""
    assert filtrar_alucinacao(" Obrigado por assistir! ") == ""
    assert filtrar_alucinacao(" O que é crase? ") == "O que é crase?"


@pytest.mark.asyncio
async def test_ouvido_manda_o_pedido_certo_ao_groq():
    pedidos = []

    def responder(req: httpx.Request):
        pedidos.append(req)
        return httpx.Response(200, json={"text": " Me testa em crase. "})

    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    ouvido = OuvidoWhisper("https://api.groq.com/openai/v1", "chave-falsa", http_client=cliente)
    texto = await ouvido.transcrever(para_wav(_voz(1)))

    assert texto == "Me testa em crase."
    req = pedidos[0]
    assert str(req.url) == "https://api.groq.com/openai/v1/audio/transcriptions"
    corpo = req.content.decode("latin-1")
    for campo in ("whisper-large-v3-turbo", 'name="language"', "pt", "fala.wav"):
        assert campo in corpo


# ---------- voz ----------

def test_limpeza_tira_markdown_emoji_e_links():
    sujo = "**Não** é a *b*. Veja https://exemplo.com 😀\n- primeiro item\n## Título"
    assert limpar_para_fala(sujo) == "Não é a b. Veja link primeiro item Título"


def test_limpeza_mantem_alternativas():
    assert limpar_para_fala("a) Vou a casa.") == "a) Vou a casa."


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="precisa do ffmpeg para criar um MP3")
def test_decodifica_mp3_igual_ao_edge(tmp_path):
    from socrates.audio.alto_falante import decodificar_mp3

    mp3 = tmp_path / "t.mp3"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "sine=frequency=440:duration=1", "-ar", "24000", "-ac", "1",
                    "-b:a", "48k", str(mp3)], check=True)
    amostras = decodificar_mp3(mp3.read_bytes())
    assert amostras.dtype == np.int16
    assert 0.9 < len(amostras) / 24000 < 1.2
    assert np.abs(amostras).max() > 1000


# ---------- comandos ----------

@pytest.mark.parametrize("fala,esperado", [
    ("Sócrates, modo prova.", Comando.TESTAR),
    ("Modo de explicação!", Comando.EXPLICAR),
    ("modo teste", Comando.TESTAR),
    ("Limpar conversa.", Comando.LIMPAR),
    ("Tchau, Sócrates!", Comando.SAIR),
    ("/testar", Comando.TESTAR),
    ("/SAIR", Comando.SAIR),
    ("Me testa em crase", None),           # pedido normal, não comando
    ("Quero sair do modo prova", None),
    ("O que é encerrar um processo?", None),
])
def test_comandos(fala, esperado):
    assert interpretar(fala) is esperado


# ---------- fala em fluxo ----------

class VozFalsa(Voz):
    def __init__(self, atrasos=None, falhar_em=None):
        self.atrasos = atrasos or {}
        self.falhar_em = falhar_em
        self.tocadas: list[str] = []
        self.sintetizando = 0
        self.max_paralelo = 0
        self.parou = False

    async def sintetizar(self, texto):
        self.sintetizando += 1
        self.max_paralelo = max(self.max_paralelo, self.sintetizando)
        await asyncio.sleep(self.atrasos.get(texto, 0.01))
        self.sintetizando -= 1
        if texto == self.falhar_em:
            raise ErroVoz("sem internet")
        return texto.encode()

    async def tocar(self, audio):
        await asyncio.sleep(0.02)
        self.tocadas.append(audio.decode())

    def parar(self):
        self.parou = True


async def _fluxo(*pedacos, erro=None):
    for p in pedacos:
        await asyncio.sleep(0)
        yield p
    if erro:
        raise erro


@pytest.mark.asyncio
async def test_narrador_fala_na_ordem_mesmo_com_sintese_fora_de_ordem():
    # a 1ª frase demora mais para virar áudio que a 2ª
    voz = VozFalsa(atrasos={"Primeira frase longa aqui.": 0.08})
    await narrar(_fluxo("Primeira frase longa aqui. ", "Segunda frase curta.", " Terceira!"), voz)
    assert voz.tocadas == ["Primeira frase longa aqui.", "Segunda frase curta.", "Terceira!"]
    assert voz.max_paralelo >= 2   # gerou a próxima enquanto a anterior ainda estava em curso


@pytest.mark.asyncio
async def test_narrador_limpa_markdown_antes_de_falar():
    voz = VozFalsa()
    await narrar(_fluxo("A resposta é **b**, com certeza."), voz)
    assert voz.tocadas == ["A resposta é b, com certeza."]


@pytest.mark.asyncio
async def test_narrador_segue_se_uma_frase_falhar():
    avisos = []
    voz = VozFalsa(falhar_em="Essa frase vai falhar.")
    await narrar(_fluxo("Essa frase vai falhar. ", "Essa outra funciona."), voz, avisos.append)
    assert voz.tocadas == ["Essa outra funciona."] and len(avisos) == 1


@pytest.mark.asyncio
async def test_narrador_repassa_erro_do_cerebro():
    voz = VozFalsa()
    with pytest.raises(ErroCerebro):
        await narrar(_fluxo("Começou a responder bem. ", erro=ErroCerebro("caiu a internet")), voz)
    assert voz.tocadas == ["Começou a responder bem."]


@pytest.mark.asyncio
async def test_narrador_para_a_voz_se_cancelado():
    voz = VozFalsa(atrasos={"Uma frase bem demorada.": 5})
    tarefa = asyncio.create_task(narrar(_fluxo("Uma frase bem demorada. "), voz))
    await asyncio.sleep(0.05)
    tarefa.cancel()
    with pytest.raises(asyncio.CancelledError):
        await tarefa
    assert voz.parou
