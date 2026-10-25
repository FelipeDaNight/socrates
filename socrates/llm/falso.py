"""Cérebro de mentira para testes: responde sem internet nem chave."""

from __future__ import annotations

from typing import AsyncIterator

from .base import Cerebro, Mensagem


class CerebroFalso(Cerebro):
    nome = "falso"

    def __init__(self, resposta: str = "Olá! Sou o Sócrates."):
        self.resposta = resposta
        self.recebido: list[list[Mensagem]] = []

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        self.recebido.append(list(mensagens))
        for palavra in self.resposta.split(" "):
            yield palavra + " "
