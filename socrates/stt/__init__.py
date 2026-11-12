"""Ouvido: voz -> texto."""

from abc import ABC, abstractmethod


class Ouvido(ABC):
    @abstractmethod
    async def transcrever(self, audio_wav: bytes, dica: str | None = None) -> str:
        """Recebe áudio WAV e devolve o texto falado ("" se não entendeu nada).
        `dica` é o vocabulário esperado (muda durante um treino de questões)."""


class ErroOuvido(Exception):
    """Falha ao transcrever (rede, chave, limite)."""
