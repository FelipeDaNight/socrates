"""Ouvido: voz -> texto. Implementação real chega na fase 1 (Whisper via Groq)."""

from abc import ABC, abstractmethod


class Ouvido(ABC):
    @abstractmethod
    async def transcrever(self, audio_wav: bytes) -> str:
        """Recebe áudio WAV e devolve o texto falado."""
