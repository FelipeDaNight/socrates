"""Voz: texto -> fala. Implementação real chega na fase 1 (edge-tts, voz Antonio)."""

from abc import ABC, abstractmethod


class Voz(ABC):
    @abstractmethod
    async def falar(self, texto: str) -> None:
        """Fala o texto em voz alta. Deve poder ser cancelada (interrupção)."""
