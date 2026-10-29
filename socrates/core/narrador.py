"""Fala a resposta frase a frase, sem esperar o texto todo.

Enquanto a frase 1 toca, a frase 2 já está sendo transformada em áudio.
É isso que corta o silêncio entre a pergunta e o começo da resposta.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator, Callable

from ..tts import ErroVoz, Voz
from ..tts.limpeza import limpar_para_fala
from .frases import em_frases

log = logging.getLogger("socrates.narrador")

ADIANTADAS = 2   # quantas frases ficam prontas na frente da que está tocando


async def ecoar(pedacos: AsyncIterator[str], escrever: Callable[[str], None]) -> AsyncIterator[str]:
    """Mostra o texto na tela conforme chega e repassa adiante."""
    async for p in pedacos:
        escrever(p)
        yield p


async def narrar(pedacos: AsyncIterator[str], voz: Voz,
                 ao_falhar: Callable[[ErroVoz], None] | None = None) -> None:
    fila: asyncio.Queue[asyncio.Task | None] = asyncio.Queue(maxsize=ADIANTADAS)

    async def produzir() -> None:
        try:
            async for frase in em_frases(pedacos):
                frase = limpar_para_fala(frase)
                if frase:
                    await fila.put(asyncio.create_task(voz.sintetizar(frase)))
        finally:
            await fila.put(None)

    produtor = asyncio.create_task(produzir())
    avisou = False
    try:
        while (tarefa := await fila.get()) is not None:
            try:
                audio = await tarefa
            except ErroVoz as e:
                if not avisou and ao_falhar:
                    ao_falhar(e)
                avisou = True
                continue
            await voz.tocar(audio)
    except BaseException:
        produtor.cancel()
        voz.parar()
        while not fila.empty():
            t = fila.get_nowait()
            if t:
                t.cancel()
        raise
    await produtor   # se o cérebro falhou, o erro aparece aqui
