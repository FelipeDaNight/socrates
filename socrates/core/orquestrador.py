"""O maestro: guarda o estado, o histórico e o modo, e liga os módulos."""

from __future__ import annotations

import logging
import re
from typing import AsyncIterator, Callable

from ..llm import Cerebro, Mensagem
from . import persona
from .estados import TRANSICOES, Estado, TransicaoInvalida

log = logging.getLogger("socrates.orquestrador")


_QUADRO = re.compile(r"\[QUADRO\](.*?)(?:\[/QUADRO\]|$)", re.S | re.I)
CORTE_ANTIGAS = 600


def _resumo_quadro(m: re.Match) -> str:
    titulo = next((l.lstrip("# ").strip() for l in m.group(1).splitlines() if l.strip()), "")
    return f"[quadro mostrado: {titulo}]"


def compactar(historico: list[Mensagem]) -> list[Mensagem]:
    """Mensagens antigas ficam curtas (o plano grátis conta cada token): o quadro
    vira uma linha e o texto longo é cortado. As 2 últimas ficam inteiras."""
    saida = []
    for i, m in enumerate(historico):
        if i >= len(historico) - 2 or m["role"] != "assistant":
            saida.append(m)
            continue
        texto = _QUADRO.sub(_resumo_quadro, m["content"])
        if len(texto) > CORTE_ANTIGAS:
            texto = texto[:CORTE_ANTIGAS] + "..."
        saida.append({"role": m["role"], "content": texto})
    return saida


class Orquestrador:
    def __init__(self, cerebro: Cerebro, nome: str = "Sócrates",
                 modo: str = "explicar", historico_max: int = 20,
                 contexto: Callable[[], str] | None = None, contexto_no_fim: bool = False,
                 extra_sistema: str = ""):
        self.cerebro = cerebro
        self.contexto = contexto   # data, hora, cidade: recalculado a cada pergunta
        # No modelo local, o começo do pedido precisa ser SEMPRE igual para o Ollama
        # reaproveitar o que já leu; por isso a data (que muda) vai para o fim.
        self.contexto_no_fim = contexto_no_fim
        self.extra_sistema = extra_sistema
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
    def _mensagens(self, extra: str | None = None) -> list[Mensagem]:
        """`extra`: informação só para ESTE pedido (a questão do treino, trechos da lei).
        Vai logo antes da pergunta e não fica no histórico."""
        recentes = compactar(self.historico[-self.historico_max:])
        sistema = self._sistema + (f"\n\n{self.extra_sistema}" if self.extra_sistema else "")
        antes_da_pergunta = []
        if self.contexto and self.contexto_no_fim:
            antes_da_pergunta.append({"role": "system", "content": self.contexto()})
        elif self.contexto:
            sistema += "\n\n" + self.contexto()
        if extra:
            antes_da_pergunta.append({"role": "system", "content": extra})
        if not antes_da_pergunta:
            return [{"role": "system", "content": sistema}, *recentes]
        return [{"role": "system", "content": sistema}, *recentes[:-1], *antes_da_pergunta,
                *recentes[-1:]]

    async def conversar(self, texto: str, extra: str | None = None) -> AsyncIterator[str]:
        """Recebe o que o aluno disse e devolve a resposta em pedaços."""
        texto = texto.strip()
        if not texto:
            return
        self._ir_para(Estado.OUVINDO)
        self.historico.append({"role": "user", "content": texto})
        self._ir_para(Estado.PENSANDO)

        resposta = ""
        try:
            async for pedaco in self.cerebro.responder(self._mensagens(extra)):
                if not resposta:
                    self._ir_para(Estado.FALANDO)
                resposta += pedaco
                yield pedaco
        except BaseException:      # erro ou interrompido no meio
            self.historico.pop()   # não guarda pergunta sem resposta
            raise
        finally:
            self._ir_para(Estado.DORMINDO)

        if resposta:
            self.historico.append({"role": "assistant", "content": resposta.strip()})
        log.info("aluno: %r | %s respondeu (%d caracteres): %r", texto[:80], self.nome,
                 len(resposta), resposta[:600])

    async def complemento(self, pedido: str) -> str:
        """Pede algo extra sobre a última resposta, sem virar uma pergunta nova
        no histórico (usado para pedir o quadro quando o modelo esqueceu)."""
        mensagens = self._mensagens() + [{"role": "user", "content": pedido}]
        texto = "".join([p async for p in self.cerebro.responder(mensagens)])
        log.info("complemento %r -> %r", pedido[:50], texto[:600])
        return texto

    def registrar(self, usuario: str | None, resposta: str | None) -> None:
        """Guarda no histórico uma troca que não passou por conversar(): o tutor falou,
        chegou um aviso, o agente respondeu. Assim a fala seguinte ("vai", "sim",
        "e o próximo?") tem o contexto do que acabou de acontecer."""
        if usuario and usuario.strip():
            self.historico.append({"role": "user", "content": usuario.strip()})
        if resposta and resposta.strip():
            if self.historico and self.historico[-1]["role"] == "assistant" and not usuario:
                self.historico[-1]["content"] += "\n" + resposta.strip()   # dois avisos seguidos
            else:
                self.historico.append({"role": "assistant", "content": resposta.strip()})
        excesso = len(self.historico) - 4 * self.historico_max
        if excesso > 0:
            del self.historico[:excesso]

    def anexar_a_ultima_resposta(self, texto: str) -> None:
        if self.historico and self.historico[-1]["role"] == "assistant":
            self.historico[-1]["content"] += "\n" + texto
