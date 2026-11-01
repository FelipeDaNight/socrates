"""Cérebro que, quando você pede uma AÇÃO ("abre a calculadora", "toca lo-fi no
YouTube", "inicia um pomodoro"), usa as ferramentas do seu computador.

Pedidos que não são ações seguem para o cérebro normal (com pesquisa, se
estiver ligada), sem custo extra.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import AsyncIterator

from .. import ferramentas
from .base import Cerebro, Mensagem

log = logging.getLogger("socrates.acoes")

INSTRUCAO = """Você pode controlar o computador do aluno usando as ferramentas.
Use a ferramenta certa para o pedido. Depois confirme em UMA frase curta e natural
o que você fez (ex.: "Pronto, abri a calculadora."). Nunca diga que fez algo sem
ter chamado a ferramenta. Se a ferramenta der erro, explique em uma frase."""

# Verbos de ação no começo da frase
_VERBO = re.compile(
    r"^(abre|abra|abrir|abri|toca|toque|tocar|coloca|coloque|bota|bote|poe|ponha"
    r"|aumenta|aumente|abaixa|abaixe|diminui|diminua|baixa|baixe|muta|silencia|tira o som"
    r"|anota|anote|salva|salve|bloqueia|bloqueie|cancela|cancele|para o timer|pare o timer)\b"
)
# Assuntos que são sempre ação, em qualquer parte da frase
_ASSUNTO = re.compile(
    r"\b(volume|timer|cronometro|pomodoro|alarme|me avisa daqui|me avise daqui|me lembra daqui"
    r"|quanto tempo falta|no youtube|minhas anotacoes|meu caderno)\b"
)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()
    return re.sub(r"^(por favor|pfv|pf) ", "", t)


def pede_acao(pergunta: str) -> bool:
    t = _norm(pergunta)
    return bool(_VERBO.search(t) or _ASSUNTO.search(t))


def _com_instrucao(mensagens: list[Mensagem]) -> list[Mensagem]:
    copia = [dict(m) for m in mensagens]
    if copia and copia[0]["role"] == "system":
        copia[0]["content"] += "\n\n" + INSTRUCAO
    else:
        copia.insert(0, {"role": "system", "content": INSTRUCAO})
    return copia


async def _executar(nome: str, args: dict) -> str:
    return await asyncio.to_thread(ferramentas.executar, nome, args)


class CerebroComAcoes(Cerebro):
    def __init__(self, interno: Cerebro, base, nomes: list[str] | None = None):
        if not hasattr(base, "com_ferramentas"):
            raise TypeError("o cérebro base precisa ter com_ferramentas()")
        self.interno = interno
        self.base = base
        self.nome = f"{interno.nome}+acoes"
        self.nomes = nomes

    def esquemas(self) -> list[dict]:
        regs = ferramentas.REGISTRO
        nomes = self.nomes or list(regs)
        return [regs[n].esquema() for n in nomes if n in regs]

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        pergunta = next((m["content"] for m in reversed(mensagens) if m["role"] == "user"), "")
        if not pede_acao(pergunta):
            async for p in self.interno.responder(mensagens):
                yield p
            return
        log.info("ação: %r", pergunta[:60])
        texto = await self.base.com_ferramentas(_com_instrucao(mensagens), self.esquemas(),
                                                _executar)
        yield texto.strip() or "Pronto."
