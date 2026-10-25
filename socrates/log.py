"""Log em arquivo (detalhado) — o terminal fica limpo para a conversa."""

import logging
from pathlib import Path


def configurar(nivel: str = "INFO", arquivo: str | None = None) -> None:
    raiz = logging.getLogger("socrates")
    raiz.setLevel(nivel.upper())
    raiz.handlers.clear()
    if arquivo:
        h = logging.FileHandler(Path(arquivo), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
        raiz.addHandler(h)
    else:
        raiz.addHandler(logging.NullHandler())
