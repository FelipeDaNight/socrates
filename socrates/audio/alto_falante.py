"""Toca o áudio MP3 que a voz gera."""

from __future__ import annotations

import asyncio

import numpy as np

from . import TAXA_VOZ, ErroAudio, importar_sounddevice


def decodificar_mp3(mp3: bytes, taxa: int = TAXA_VOZ) -> np.ndarray:
    import miniaudio

    try:
        som = miniaudio.decode(mp3, output_format=miniaudio.SampleFormat.SIGNED16,
                               nchannels=1, sample_rate=taxa)
    except miniaudio.DecodeError as e:
        raise ErroAudio("Áudio da voz veio corrompido.") from e
    return np.frombuffer(som.samples, dtype=np.int16)


class AltoFalante:
    def __init__(self, dispositivo: int | str | None = None):
        self.dispositivo = dispositivo

    def _tocar_bloqueando(self, amostras: np.ndarray, taxa: int) -> None:
        sd = importar_sounddevice()
        try:
            sd.play(amostras, taxa, device=self.dispositivo)
            sd.wait()
        except sd.PortAudioError as e:
            raise ErroAudio(f"Problema com o alto-falante: {e}") from e

    async def tocar_mp3(self, mp3: bytes) -> None:
        amostras = decodificar_mp3(mp3)
        await asyncio.to_thread(self._tocar_bloqueando, amostras, TAXA_VOZ)

    async def tocar_wav(self, amostras: np.ndarray, taxa: int) -> None:
        await asyncio.to_thread(self._tocar_bloqueando, amostras, taxa)

    def parar(self) -> None:
        try:
            importar_sounddevice().stop()
        except ErroAudio:
            pass
