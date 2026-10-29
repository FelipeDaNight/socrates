"""Ouvido: voz -> texto."""

from abc import ABC, abstractmethod


class Ouvido(ABC):
    @abstractmethod
    async def transcrever(self, audio_wav: bytes) -> str:
        """Recebe áudio WAV e devolve o texto falado ("" se não entendeu nada)."""


class ErroOuvido(Exception):
    """Falha ao transcrever (rede, chave, limite)."""
