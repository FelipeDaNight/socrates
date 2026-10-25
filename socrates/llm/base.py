"""Contrato que todo cérebro precisa seguir.

O orquestrador só conhece esta interface. Trocar Groq por Gemini, Ollama
ou Claude é só escrever outra classe com o mesmo método.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, TypedDict


class Mensagem(TypedDict):
    role: str      # "system" | "user" | "assistant"
    content: str


class Cerebro(ABC):
    nome: str = "base"

    @abstractmethod
    def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        """Devolve a resposta em pedaços (streaming), conforme é gerada."""


class ErroCerebro(Exception):
    """Falha ao falar com o provedor (rede, chave, limite, modelo)."""
