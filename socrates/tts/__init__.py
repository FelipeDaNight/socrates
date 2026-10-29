"""Voz: texto -> fala."""

from abc import ABC, abstractmethod


class Voz(ABC):
    @abstractmethod
    async def sintetizar(self, texto: str) -> bytes:
        """Transforma texto em áudio (sem tocar). Separado de tocar() para
        a próxima frase ser gerada enquanto a atual está tocando."""

    @abstractmethod
    async def tocar(self, audio: bytes) -> None:
        """Toca o áudio e só retorna quando terminar."""

    def parar(self) -> None:
        """Interrompe o que estiver tocando."""


class ErroVoz(Exception):
    """Falha ao gerar a fala."""
