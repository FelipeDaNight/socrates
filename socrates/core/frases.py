"""Junta os pedaços do streaming em frases completas.

Na fase 1 é isso que deixa o Sócrates começar a falar a primeira frase
enquanto o cérebro ainda gera a segunda.
"""

from __future__ import annotations

import re
from typing import AsyncIterator

_FIM = re.compile(r"([.!?…]+)(\s+)")


async def em_frases(pedacos: AsyncIterator[str], minimo: int = 12) -> AsyncIterator[str]:
    buffer = ""
    async for pedaco in pedacos:
        buffer += pedaco
        while True:
            achou = None
            for m in _FIM.finditer(buffer):
                if m.end(1) >= minimo:   # evita cortar em "Sr." ou "1."
                    achou = m
                    break
            if not achou:
                break
            frase, buffer = buffer[: achou.end(1)], buffer[achou.end():]
            if frase.strip():
                yield frase.strip()
    if buffer.strip():
        yield buffer.strip()
