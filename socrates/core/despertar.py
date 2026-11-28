"""Reconhece quando você chamou o Sócrates.

Vale no começo ("Sócrates, o que é crase?", "Ei Sócrates...") ou no fim
("O que é crase, Sócrates?"). No meio não vale: "o que Sócrates dizia sobre
a ética" é uma pergunta SOBRE o filósofo, não um chamado.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

# Jeitos como o Whisper costuma escrever o nome
NOMES = {"socrates", "socrate", "socratis", "socratas", "socrats", "socratz", "socratez", "socratiz",
         "socretis"}
# O Whisper erra o nome de muitos jeitos ("Socates", "Sucrates", "Sokrates", "Socrades"): vale
# a palavra bem parecida com "socrates". 0,8 deixa de fora "socrático", "democrates", "sorteios".
PARECIDO = 0.8
NOMES_PARTIDOS = {("so", "crates"), ("so", "cratis"), ("socra", "tes")}
INTERJEICOES = {"ei", "oi", "ok", "o", "e", "ai", "fala", "hey", "alo", "opa", "bom", "dia",
                "boa", "tarde", "noite", "ola", "salve", "psiu", "escuta", "cade", "ta", "tá"}
MAX_INTERJEICOES = 2
# Só chamando, sem pedido: "Sócrates, alô? Sócrates?", "tá aí, Sócrates?", "Sócrates, tá me
# ouvindo?". Em 26/11 (21h24) "SÓCRATES, ALÔ? SÓCRATES? SÓCRATES." foi ao cérebro como pedido,
# e ele abriu o Spotify e repetiu a pesquisa de duas horas antes. Saudação ("bom dia") fica de
# fora: essa ele responde.
SO_CHAMANDO = {"alo", "oi", "ei", "e", "o", "opa", "psiu", "hey", "ta", "ai", "voce", "esta",
               "tu", "me", "ouve", "ouvindo", "escuta", "escutando", "acorda", "acordado", "cade",
               "aqui", "ainda", "hein", "ne", "la"}

_PALAVRA = re.compile(r"[^\W\d_]+", re.UNICODE)
_BORDAS = " \t\n,.;:!-–—"


def _norm(palavra: str) -> str:
    return unicodedata.normalize("NFKD", palavra).encode("ascii", "ignore").decode().lower()


def e_o_nome(palavra: str) -> bool:
    return palavra in NOMES or (
        len(palavra) >= 6 and SequenceMatcher(None, palavra, "socrates").ratio() >= PARECIDO)


def _nome_em(tokens: list[tuple[str, int, int]], i: int) -> int:
    """Quantas palavras o nome ocupa a partir de i (0 = não é o nome)."""
    if i < len(tokens) and e_o_nome(tokens[i][0]):
        return 1
    if i + 1 < len(tokens) and (tokens[i][0], tokens[i + 1][0]) in NOMES_PARTIDOS:
        return 2
    return 0


def so_chamando(resto: str) -> bool:
    """O que sobrou depois do nome é só "alô", "tá aí?", "me ouve?" ou o nome de novo."""
    palavras = [_norm(m.group()) for m in _PALAVRA.finditer(resto)]
    return bool(palavras) and len(palavras) <= 6 and all(
        p in SO_CHAMANDO or e_o_nome(p) for p in palavras)


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
        j = i + tamanho
        while _nome_em(tokens, j):            # "Alô, Sócrates, Sócrates, Sócrates."
            j += _nome_em(tokens, j)
        fim = tokens[j - 1][2]
        resto = texto[fim:].lstrip(_BORDAS + "?").rstrip()
        return True, resto if _PALAVRA.search(resto) and not so_chamando(resto) else ""

    # No fim
    for tamanho in (1, 2):
        inicio = len(tokens) - tamanho
        if inicio >= 0 and _nome_em(tokens, inicio) == tamanho:
            antes = texto[: tokens[inicio][1]].rstrip(_BORDAS)
            final = texto.rstrip()[-1:]
            if antes and final in "?!" and not antes.endswith(final):
                antes += final
            return True, "" if so_chamando(antes) else antes

    return False, texto.strip()


# O Whisper escreve "Claude" (o app onde o programador do Sócrates trabalha) como "Cloud",
# "Clout", "Claudio"... e o cérebro entendia "integrar o serviço Cloud para sincronizar".
_CLAUDE = re.compile(r"\b(?:cloud|clout|claud|clode|cloude|claudio|cláudio)\b", re.I)
_NUVEM = re.compile(r"\b(?:computa\w* em nuvem|nuvem|cloud computing|armazenamento|saas|iaas|paas|"
                    r"icloud|google cloud|onedrive|backup)\b", re.I)


def nome_do_claude(texto: str) -> str:
    """ "manda pro Cloud" -> "manda pro Claude" (mas "computação em nuvem/cloud" fica)."""
    if not texto or _NUVEM.search(texto):
        return texto
    return _CLAUDE.sub("Claude", texto)
