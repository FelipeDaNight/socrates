"""Voz do Gemini (Google): bem mais natural, com 30 vozes e controle de estilo.

Precisa de uma chave grátis do Google AI Studio (GEMINI_API_KEY no .env).
Usa só a biblioteca padrão do Python (urllib): nada a instalar.

API: POST /v1beta/interactions, resposta em WAV 24 kHz mono 16 bits.
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import urllib.error
import urllib.request
import wave

import numpy as np

from ..audio.alto_falante import AltoFalante
from . import ErroVoz, Voz

log = logging.getLogger("socrates.voz")

URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
ESTILO = ("calmo, pausado e acolhedor, como um professor sábio e experiente, "
          "em português do Brasil")


def montar_pedido(texto: str, voz: str, modelo: str, estilo: str) -> dict:
    conteudo = {"type": "text", "text": texto}
    if estilo:
        conteudo["annotations"] = [{"type": "speech_metadata", "style": estilo}]
    return {
        "model": modelo,
        "input": [{"type": "user_input", "content": [conteudo]}],
        "response_format": {"type": "audio"},
        "generation_config": {"speech_config": [{"voice": voz}]},
    }


def extrair_audio(resposta: dict) -> bytes:
    """O áudio vem em base64 no último pedaço 'audio' da saída do modelo."""
    audios = [c for passo in resposta.get("steps", []) if passo.get("type") == "model_output"
              for c in passo.get("content", []) if c.get("type") == "audio"]
    if not audios or not audios[-1].get("data"):
        raise ErroVoz("O Gemini não devolveu áudio.")
    return base64.b64decode(audios[-1]["data"])


def wav_para_amostras(dados: bytes) -> tuple[np.ndarray, int]:
    if dados[:4] == b"RIFF":
        with wave.open(io.BytesIO(dados)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16), w.getframerate()
    return np.frombuffer(dados, dtype=np.int16), 24_000   # PCM puro


class VozGemini(Voz):
    def __init__(self, chave: str, voz: str = "Sadaltager", modelo: str = "gemini-3.8-flash-tts",
                 estilo: str = ESTILO, alto_falante: AltoFalante | None = None,
                 tempo_limite: float = 20.0):
        self.chave = chave
        self.voz = voz
        self.modelo = modelo
        self.estilo = estilo
        self.tempo_limite = tempo_limite
        self.alto_falante = alto_falante or AltoFalante()

    def _pedir(self, texto: str) -> bytes:
        corpo = json.dumps(montar_pedido(texto, self.voz, self.modelo, self.estilo)).encode()
        req = urllib.request.Request(URL, data=corpo, method="POST", headers={
            "x-goog-api-key": self.chave, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.tempo_limite) as r:
                return extrair_audio(json.loads(r.read()))
        except urllib.error.HTTPError as e:
            detalhe = e.read().decode(errors="ignore")[:300]
            log.warning("Gemini TTS %s: %s", e.code, detalhe)
            if e.code == 429:
                raise ErroVoz("Limite grátis da voz do Gemini atingido.") from e
            if e.code in (401, 403):
                raise ErroVoz("Chave do Gemini inválida ou sem acesso à voz.") from e
            raise ErroVoz(f"O Gemini recusou a voz ({e.code}): {detalhe}") from e
        except (urllib.error.URLError, TimeoutError) as e:
            raise ErroVoz("Sem conexão com a voz do Gemini.") from e

    async def sintetizar(self, texto: str) -> bytes:
        return await asyncio.to_thread(self._pedir, texto)

    async def tocar(self, audio: bytes) -> None:
        amostras, taxa = wav_para_amostras(audio)
        await self.alto_falante.tocar_wav(amostras, taxa)

    def parar(self) -> None:
        self.alto_falante.parar()
