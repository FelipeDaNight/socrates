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


class ErroPesquisa(Exception):
    """A pesquisa na internet falhou (o resto do Sócrates continua funcionando)."""


class ErroQuerFerramenta(ErroCerebro):
    """O modelo quis chamar uma ferramenta num pedido só de texto (o Groq recusa: "Tool choice
    is none, but model called a tool"). Não é o serviço que caiu: é o pedido que ainda precisa
    de uma ação. O rodízio não põe o modelo para descansar por isso."""


class ErroLimite(ErroCerebro):
    """O provedor bateu no limite grátis (429). O rodízio passa para o próximo."""

    def __init__(self, mensagem: str, espera: float | None = None, do_dia: bool = False):
        super().__init__(mensagem)
        self.espera = espera
        self.do_dia = do_dia
