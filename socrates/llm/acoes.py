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

MARCADOR = "executar"   # o modelo responde isso quando percebe um pedido de ação

INSTRUCAO_MARCADOR = """Você consegue mexer no computador do aluno (abrir programas, sites e
pastas, tocar no YouTube, volume, timer, anotar, bloquear a tela).
Se o aluno pedir uma dessas ações, responda APENAS com a palavra EXECUTAR e mais nada.
Nunca diga que não consegue abrir programas ou mexer no computador."""

# Jeitos educados de pedir, antes do verbo: "você pode abrir...", "quero que você toque..."
_CORTESIA = (r"(?:(?:voce|vc|tu)\s+)?(?:pode|poderia|podia|consegue|conseguiria|da pra|da para"
             r"|quero que (?:voce |vc )?|preciso que (?:voce |vc )?|tem como|me ajuda a|faz o favor de)?\s*")
# Verbos de ação no começo da frase (imperativo ou infinitivo)
_VERBO = re.compile(
    r"^" + _CORTESIA +
    r"(abre|abra|abrir|abri|toca|toque|tocar|coloca|coloque|colocar|bota|bote|botar|poe|ponha"
    r"|aumenta|aumente|aumentar|abaixa|abaixe|abaixar|diminui|diminua|diminuir|baixa|baixe"
    r"|muta|silencia|silenciar|tira o som|anota|anote|anotar|salva|salve|bloqueia|bloqueie|bloquear"
    r"|cancela|cancele|cancelar|para o timer|pare o timer|inicia|inicie|iniciar|comeca|comece"
    r"|liga|ligue|ligar|executa|execute|executar|roda|rode|rodar)\b"
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
    """Tira a regra "responda EXECUTAR" (senão o modelo responde isso em vez de
    usar a ferramenta) e põe a de usar as ferramentas."""
    copia = [dict(m) for m in mensagens
             if not (m["role"] == "assistant" and _norm(m["content"]) == MARCADOR)]
    if copia and copia[0]["role"] == "system":
        copia[0]["content"] = copia[0]["content"].replace(INSTRUCAO_MARCADOR, "").rstrip()
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
        if pede_acao(pergunta):
            log.info("ação: %r", pergunta[:60])
            yield await self._agir(mensagens)
            return

        # Espia o começo: se o modelo respondeu EXECUTAR, era uma ação que o filtro não pegou
        inicio = ""
        fluxo = self.interno.responder(mensagens).__aiter__()
        async for pedaco in fluxo:
            inicio += pedaco
            if len(inicio.strip()) >= 12:
                break
        if _norm(inicio).startswith(MARCADOR):
            log.info("o modelo pediu ação: %r", pergunta[:60])
            async for _ in fluxo:
                pass
            yield await self._agir(mensagens)
            return
        if inicio:
            yield inicio
        async for pedaco in fluxo:
            yield pedaco

    async def _agir(self, mensagens: list[Mensagem]) -> str:
        texto = await self.base.com_ferramentas(_com_instrucao(mensagens), self.esquemas(),
                                                _executar)
        texto = texto.strip()
        if not texto or _norm(texto) == MARCADOR:
            return "Não consegui fazer isso agora. Tente pedir de outro jeito."
        return texto
