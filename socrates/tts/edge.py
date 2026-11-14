"""Voz neural da Microsoft (a mesma do navegador Edge). Grátis, precisa de internet."""

from __future__ import annotations

import asyncio
import logging

from ..audio.alto_falante import AltoFalante
from . import ErroVoz, Voz

log = logging.getLogger("socrates.voz")

TENTATIVAS = 3
ESPERAS = (0.3, 0.8)          # segundos antes da 2ª e da 3ª tentativa


class VozEdge(Voz):
    def __init__(self, voz: str = "pt-BR-AntonioNeural", velocidade: str = "+0%",
                 alto_falante: AltoFalante | None = None, tom: str = "+0Hz"):
        self.voz = voz
        self.velocidade = velocidade
        self.tom = tom                      # "-8Hz" deixa a voz mais grave
        self.alto_falante = alto_falante or AltoFalante()

    async def sintetizar(self, texto: str) -> bytes:
        """O serviço do Edge às vezes falha à toa ("No audio was received"): tenta de
        novo duas vezes, rapidinho, antes de desistir (aí entra a voz reserva)."""
        ultimo: ErroVoz | None = None
        for tentativa in range(TENTATIVAS):
            try:
                return await self._uma_vez(texto)
            except ErroVoz as e:
                ultimo = e
                if tentativa + 1 < TENTATIVAS:
                    await asyncio.sleep(ESPERAS[min(tentativa, len(ESPERAS) - 1)])
        raise ultimo

    async def _uma_vez(self, texto: str) -> bytes:
        import edge_tts

        partes: list[bytes] = []
        try:
            fala = edge_tts.Communicate(texto, self.voz, rate=self.velocidade, pitch=self.tom)
            async for pedaco in fala.stream():
                if pedaco["type"] == "audio":
                    partes.append(pedaco["data"])
        except Exception as e:   # edge-tts levanta erros de rede variados
            log.warning("falha na voz: %s", e)
            raise ErroVoz("Não consegui gerar a voz. Verifique a internet.") from e
        if not partes:
            raise ErroVoz("O serviço de voz não devolveu áudio.")
        return b"".join(partes)

    async def tocar(self, audio: bytes) -> None:
        await self.alto_falante.tocar_mp3(audio)

    def parar(self) -> None:
        self.alto_falante.parar()
