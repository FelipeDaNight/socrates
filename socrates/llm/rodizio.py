"""Rodízio de cérebros grátis: Groq -> Mistral -> Gemini -> ...

Cada serviço grátis tem o seu limite. Quando um bate no limite (ou cai), o
pedido vai para o próximo da lista, sem você perceber. Quem bateu no limite
"descansa" até liberar e não é tentado de novo à toa.
"""

from __future__ import annotations

import logging
import time
from typing import AsyncIterator

from .base import Cerebro, ErroCerebro, ErroLimite, ErroPesquisa, Mensagem

log = logging.getLogger("socrates.rodizio")

DESCANSO_PADRAO = 60          # limite por minuto sem tempo informado
DESCANSO_DIA = 3 * 3600       # limite do dia: tenta de novo daqui a algumas horas
DESCANSO_FALHA = 120          # caiu, chave errada, modelo sumiu...


class CerebroRodizio(Cerebro):
    def __init__(self, membros: list):
        if not membros:
            raise ValueError("o rodízio precisa de pelo menos um cérebro")
        self.membros = membros
        self.nome = " > ".join(f"{m.nome}:{m.modelo}" for m in membros)
        self.ultimo_usado = None

    # ---------- quem tentar ----------
    def ordem(self, filtro=None) -> list:
        candidatos = [m for m in self.membros if filtro is None or filtro(m)]
        agora = time.monotonic()
        prontos = [m for m in candidatos if agora >= m.descansar_ate]
        if prontos:
            return prontos
        # todos descansando: tenta o que libera primeiro, vai que já liberou
        return sorted(candidatos, key=lambda m: m.descansar_ate)[:1]

    def _descansar(self, m, erro: Exception) -> None:
        if isinstance(erro, ErroLimite):
            seg = DESCANSO_DIA if erro.do_dia else max(erro.espera or DESCANSO_PADRAO, 20)
        else:
            seg = DESCANSO_FALHA
        m.descansar_ate = time.monotonic() + seg
        log.warning("%s:%s descansa %.0f s (%s); passando para o próximo", m.nome, m.modelo, seg, erro)

    @staticmethod
    def _falha_de_provedor(erro: Exception) -> bool:
        """Erros em que vale tentar outro serviço (limite, queda, chave). Erros do
        próprio pedido seriam iguais em qualquer um."""
        return isinstance(erro, (ErroLimite, ErroCerebro))

    # ---------- conversa (com streaming) ----------
    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        ultimo: Exception | None = None
        for m in self.ordem():
            fluxo = m.responder(mensagens).__aiter__()
            try:
                primeiro = await fluxo.__anext__()   # se for falhar, falha aqui, antes de falar
            except StopAsyncIteration:
                return
            except ErroCerebro as e:
                self._descansar(m, e)
                ultimo = e
                continue
            self.ultimo_usado = m
            yield primeiro
            async for pedaco in fluxo:
                yield pedaco
            return
        raise ultimo or ErroCerebro("Nenhum cérebro disponível agora.")

    # ---------- ações ----------
    async def com_ferramentas(self, mensagens, esquemas, executar, max_rodadas: int = 4,
                              parar=None) -> str:
        ultimo: Exception | None = None
        for m in self.ordem():
            try:
                if parar is None:
                    texto = await m.com_ferramentas(mensagens, esquemas, executar, max_rodadas)
                else:
                    texto = await m.com_ferramentas(mensagens, esquemas, executar, max_rodadas,
                                                    parar=parar)
            except ErroCerebro as e:
                self._descansar(m, e)
                ultimo = e
                continue
            self.ultimo_usado = m
            return texto
        raise ultimo or ErroCerebro("Nenhum cérebro disponível agora.")

    # ---------- pesquisa (só quem tem busca embutida) ----------
    @property
    def pesquisa_ok(self) -> bool:
        return any(getattr(m, "pesquisa_ok", False) for m in self.membros)

    async def pesquisar(self, mensagens: list[Mensagem]) -> str:
        ultimo: Exception | None = None
        for m in self.ordem(lambda m: getattr(m, "pesquisa_ok", False)):
            try:
                texto = await m.pesquisar(mensagens)
            except ErroPesquisa as e:
                if isinstance(e.__cause__, ErroCerebro):   # limite/queda: tenta o próximo
                    self._descansar(m, e.__cause__)
                    ultimo = e
                    continue
                raise
            self.ultimo_usado = m
            return texto
        raise ultimo or ErroPesquisa("Nenhum serviço de pesquisa disponível agora.")
