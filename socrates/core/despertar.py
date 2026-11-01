"""Reconhece quando você chamou o Sócrates.

Vale no começo ("Sócrates, o que é crase?", "Ei Sócrates...") ou no fim
("O que é crase, Sócrates?"). No meio não vale: "o que Sócrates dizia sobre
a ética" é uma pergunta SOBRE o filósofo, não um chamado.
"""

from __future__ import annotations

import re
import unicodedata

# Jeitos como o Whisper costuma escrever o nome
NOMES = {"socrates", "socrate", "socratis", "socratas", "socrats", "socratz", "socratez"}
NOMES_PARTIDOS = {("so", "crates"), ("so", "cratis"), ("socra", "tes")}
INTERJEICOES = {"ei", "oi", "ok", "o", "e", "ai", "fala", "hey", "alo", "opa", "bom", "dia",
                "boa", "tarde", "noite", "ola", "salve"}
MAX_INTERJEICOES = 2

_PALAVRA = re.compile(r"[^\W\d_]+", re.UNICODE)
_BORDAS = " \t\n,.;:!-–—"


def _norm(palavra: str) -> str:
    return unicodedata.normalize("NFKD", palavra).encode("ascii", "ignore").decode().lower()


def _nome_em(tokens: list[tuple[str, int, int]], i: int) -> int:
    """Quantas palavras o nome ocupa a partir de i (0 = não é o nome)."""
    if i < len(tokens) and tokens[i][0] in NOMES:
        return 1
    if i + 1 < len(tokens) and (tokens[i][0], tokens[i + 1][0]) in NOMES_PARTIDOS:
        return 2
    return 0


def chamou(texto: str) -> tuple[bool, str]:
    """Devolve (foi chamado?, o pedido sem o nome)."""
    tokens = [(_norm(m.group()), m.start(), m.end()) for m in _PALAVRA.finditer(texto)]
    if not tokens:
        return False, texto.strip()

    # No começo, depois de no máximo 2 interjeições ("ei", "bom dia")
    i = 0
    while i < len(tokens) and i < MAX_INTERJEICOES and tokens[i][0] in INTERJEICOES:
        if _nome_em(tokens, i):
            break
        i += 1
    tamanho = _nome_em(tokens, i)
    if tamanho:
        fim = tokens[i + tamanho - 1][2]
        resto = texto[fim:].lstrip(_BORDAS + "?").rstrip()
        return True, resto if _PALAVRA.search(resto) else ""

    # No fim
    for tamanho in (1, 2):
        inicio = len(tokens) - tamanho
        if inicio >= 0 and _nome_em(tokens, inicio) == tamanho:
            antes = texto[: tokens[inicio][1]].rstrip(_BORDAS)
            final = texto.rstrip()[-1:]
            if antes and final in "?!" and not antes.endswith(final):
                antes += final
            return True, antes

    return False, texto.strip()
