"""Separa o quadro branco da fala, enquanto a resposta ainda está chegando.

    "A fórmula é essa, veja no quadro. [QUADRO]# Bhaskara ...[/QUADRO] Entendeu?"
      -> fala:   "A fórmula é essa, veja no quadro.  Entendeu?"
      -> quadro: "# Bhaskara ..."

As marcas podem chegar quebradas entre pedaços ("[QUA" + "DRO]"); por isso
o fim do texto que pode ser o começo de uma marca fica guardado até completar.
"""

from __future__ import annotations

import inspect
from typing import AsyncIterator, Awaitable, Callable

ABRE = "[QUADRO]"
FECHA = "[/QUADRO]"


def _sufixo_parcial(texto: str, marca: str) -> int:
    """Quantos caracteres do fim de `texto` podem ser o começo de `marca`."""
    alto = texto.upper()
    for n in range(min(len(marca) - 1, len(alto)), 0, -1):
        if marca.startswith(alto[-n:]):
            return n
    return 0


async def separar_quadro(pedacos: AsyncIterator[str],
                         ao_quadro: Callable[[str], Awaitable[None] | None]) -> AsyncIterator[str]:
    async def entregar(conteudo: str) -> None:
        conteudo = conteudo.strip()
        if conteudo:
            r = ao_quadro(conteudo)
            if inspect.isawaitable(r):
                await r

    buf, quadro, dentro = "", "", False
    async for p in pedacos:
        buf += p
        while True:
            marca = FECHA if dentro else ABRE
            i = buf.upper().find(marca)
            if i >= 0:
                if dentro:
                    quadro += buf[:i]
                    await entregar(quadro)
                    quadro = ""
                elif buf[:i]:
                    yield buf[:i]
                buf = buf[i + len(marca):]
                dentro = not dentro
                continue
            k = _sufixo_parcial(buf, marca)
            pronto, buf = buf[:len(buf) - k], buf[len(buf) - k:]
            if dentro:
                quadro += pronto
            elif pronto:
                yield pronto
            break
    if dentro:                  # o modelo esqueceu de fechar o quadro
        await entregar(quadro + buf)
    elif buf:
        yield buf
