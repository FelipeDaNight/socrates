"""Separa o quadro branco da fala, enquanto a resposta ainda está chegando.

    "A fórmula é essa, veja no quadro. [QUADRO]# Bhaskara ...[/QUADRO] Entendeu?"
      -> fala:   "A fórmula é essa, veja no quadro.  Entendeu?"
      -> quadro: "# Bhaskara ..."

As marcas podem chegar quebradas entre pedaços ("[QUA" + "DRO]"); por isso o fim do
texto que pode ser o começo de uma marca fica guardado até completar.

O modelo às vezes escreve a marca torta: "[quadro]", "**[QUADRO]**", "[ QUADRO ]" ou
até "[quadro mostrado]" (imitando o histórico). Tudo isso vale como quadro, para a
marca nunca ser lida em voz alta e o quadro nunca sumir. Quadro sem [/QUADRO] (resposta
cortada) fecha sozinho no fim, e uma pergunta solta depois dele ("Certo ou errado?")
volta para a fala.
"""

from __future__ import annotations

import inspect
import re
from typing import AsyncIterator, Awaitable, Callable

ABRE = "[QUADRO]"
FECHA = "[/QUADRO]"

_ABRE = re.compile(r"\*{0,2}\[\s*quadro(?:\s+mostrado)?(?:\s*:\s*([^\]\n]{0,80}))?\s*\]\*{0,2}", re.I)
_FECHA = re.compile(r"\*{0,2}\[\s*/\s*quadro\s*\]\*{0,2}", re.I)
_SEGURA = 100        # um "[" sem "]" a até tantos caracteres do fim pode ser uma marca


def _corte_seguro(buf: str) -> int:
    """Até onde dá para entregar sem cortar uma marca que ainda está chegando."""
    i = buf.rfind("[")
    if i >= 0 and "]" not in buf[i:] and len(buf) - i <= _SEGURA:
        while i > 0 and buf[i - 1] == "*":
            i -= 1
        return i
    j = len(buf)
    while j > 0 and buf[j - 1] == "*" and len(buf) - j < 2:     # "**" antes de "[QUADRO]"
        j -= 1
    return j


def _sobra_falada(conteudo: str) -> tuple[str, str]:
    """Quadro que não fechou: o último parágrafo curto que não é do quadro (uma pergunta,
    "Certo ou errado?") volta para a fala."""
    partes = re.split(r"\n\s*\n", conteudo.strip())
    if len(partes) >= 2:
        ultima = partes[-1].strip()
        if (len(ultima) <= 160 and not ultima.startswith(("-", "#", "$", "|", "•", "–"))
                and (ultima.endswith("?") or len(ultima.split()) <= 10)):
            return "\n\n".join(partes[:-1]), " " + ultima
    return conteudo, ""


async def separar_quadro(pedacos: AsyncIterator[str],
                         ao_quadro: Callable[[str], Awaitable[None] | None]) -> AsyncIterator[str]:
    async def entregar(titulo: str, conteudo: str) -> None:
        conteudo = conteudo.strip()
        if titulo and conteudo and not conteudo.startswith("#"):
            conteudo = f"# {titulo}\n{conteudo}"
        if conteudo:
            r = ao_quadro(conteudo)
            if inspect.isawaitable(r):
                await r

    buf, quadro, titulo, dentro = "", "", "", False
    async for p in pedacos:
        buf += p
        while True:
            m = (_FECHA if dentro else _ABRE).search(buf)
            if m:
                if dentro:
                    quadro += buf[:m.start()]
                    await entregar(titulo, quadro)
                    quadro, titulo = "", ""
                else:
                    if buf[:m.start()]:
                        yield buf[:m.start()]
                    titulo = (m.group(1) or "").strip()
                buf = buf[m.end():]
                dentro = not dentro
                continue
            k = _corte_seguro(buf)
            pronto, buf = buf[:k], buf[k:]
            if dentro:
                quadro += pronto
            elif pronto:
                yield pronto
            break
    if dentro:                  # o modelo esqueceu de fechar o quadro (ou a resposta cortou)
        conteudo, fala = _sobra_falada(quadro + buf)
        await entregar(titulo, conteudo)
        if fala:
            yield fala
    elif buf:
        yield buf
