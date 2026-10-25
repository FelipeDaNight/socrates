"""O maestro: guarda o estado, o histórico e o modo, e liga os módulos."""

from __future__ import annotations

import logging
from typing import AsyncIterator, Callable

from ..llm import Cerebro, Mensagem
from . import persona
from .estados import TRANSICOES, Estado, TransicaoInvalida

log = logging.getLogger("socrates.orquestrador")


class Orquestrador:
    def __init__(self, cerebro: Cerebro, nome: str = "Sócrates",
                 modo: str = "explicar", historico_max: int = 20):
        self.cerebro = cerebro
        self.nome = nome
        self.historico_max = historico_max
        self.historico: list[Mensagem] = []
        self.estado = Estado.DORMINDO
        self._ao_mudar: list[Callable[[Estado, Estado], None]] = []
        self.mudar_modo(modo)

    # ---------- estado ----------
    def ao_mudar_estado(self, funcao: Callable[[Estado, Estado], None]) -> None:
        """Avisa quem quiser (ex.: a interface visual da fase 3) quando o estado muda."""
        self._ao_mudar.append(funcao)

    def _ir_para(self, novo: Estado) -> None:
        if novo == self.estado:
            return
        if novo not in TRANSICOES[self.estado]:
            raise TransicaoInvalida(f"{self.estado.value} -> {novo.value}")
        antigo, self.estado = self.estado, novo
        log.debug("estado: %s -> %s", antigo.value, novo.value)
        for f in self._ao_mudar:
            f(antigo, novo)

    # ---------- modo ----------
    def mudar_modo(self, modo: str) -> None:
        self._sistema = persona.montar(self.nome, modo)
        self.modo = modo
        log.info("modo: %s", modo)

    def limpar(self) -> None:
        self.historico.clear()

    # ---------- conversa ----------
    def _mensagens(self) -> list[Mensagem]:
        recentes = self.historico[-self.historico_max:]
        return [{"role": "system", "content": self._sistema}, *recentes]

    async def conversar(self, texto: str) -> AsyncIterator[str]:
        """Recebe o que o aluno disse e devolve a resposta em pedaços."""
        texto = texto.strip()
        if not texto:
            return
        self._ir_para(Estado.OUVINDO)
        self.historico.append({"role": "user", "content": texto})
        self._ir_para(Estado.PENSANDO)

        resposta = ""
        try:
            async for pedaco in self.cerebro.responder(self._mensagens()):
                if not resposta:
                    self._ir_para(Estado.FALANDO)
                resposta += pedaco
                yield pedaco
        except Exception:
            self.historico.pop()   # não guarda pergunta sem resposta
            raise
        finally:
            self._ir_para(Estado.DORMINDO)

        if resposta:
            self.historico.append({"role": "assistant", "content": resposta.strip()})
        log.info("aluno: %r | %s: %d caracteres", texto[:60], self.nome, len(resposta))
