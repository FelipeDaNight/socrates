"""Deixa o texto pronto para ser falado.

Mesmo com a persona proibindo, o modelo às vezes escapa um asterisco.
Esta é a segunda barreira, para a voz nunca ler "asterisco asterisco".
"""

import re

_LINK = re.compile(r"https?://\S+|www\.\S+")
_EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿️]")
_MARCAS = re.compile(r"[*_`#>|~]+")
_MARCADOR_LISTA = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.MULTILINE)
_ESPACOS = re.compile(r"\s+")


_INVISIVEIS = re.compile("[\u200b-\u200f\u202f\u00a0\u2060\ufeff]")
_RETICENCIAS = re.compile(r"(?:\s*(?:\.\.\.|…)){2,}")


def limpar_para_fala(texto: str) -> str:
    texto = _INVISIVEIS.sub(" ", texto)
    texto = _RETICENCIAS.sub("...", texto)
    texto = _LINK.sub("link", texto)
    texto = _EMOJI.sub("", texto)
    texto = _MARCADOR_LISTA.sub("", texto)
    texto = _MARCAS.sub("", texto)
    return _ESPACOS.sub(" ", texto).strip()
