"""Comandos que funcionam digitados ou falados.

Falados, só valem se a frase for SÓ o comando ("modo prova"), para
"me testa em crase" não ser confundido com um comando.
"""

from __future__ import annotations

import re
import unicodedata
from enum import Enum


class Comando(Enum):
    EXPLICAR = "explicar"
    TESTAR = "testar"
    LIMPAR = "limpar"
    AJUDA = "ajuda"
    SAIR = "sair"


_DIGITADOS = {
    "/explicar": Comando.EXPLICAR,
    "/testar": Comando.TESTAR,
    "/limpar": Comando.LIMPAR,
    "/ajuda": Comando.AJUDA,
    "/help": Comando.AJUDA,
    "/sair": Comando.SAIR,
    "sair": Comando.SAIR,
}

_FALADOS = {
    Comando.EXPLICAR: ["modo explicar", "modo explicacao", "modo de explicacao", "modo aula",
                       "modo explica"],
    Comando.TESTAR: ["modo testar", "modo teste", "modo de teste", "modo prova",
                     "modo de prova", "modo simulado", "modo questao", "modo questoes"],
    Comando.LIMPAR: ["limpar conversa", "limpa a conversa", "esquece a conversa",
                     "esquecer conversa", "nova conversa"],
    Comando.AJUDA: ["ajuda", "quais sao os comandos"],
    Comando.SAIR: ["encerrar", "encerra", "desligar", "desliga", "tchau socrates",
                   "ate logo", "pode encerrar"],
}
_FALADOS_INV = {frase: cmd for cmd, frases in _FALADOS.items() for frase in frases}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"^(ei |oi |ok )?socrates ", "", t)   # "Sócrates, modo prova"


def interpretar(texto: str) -> Comando | None:
    bruto = texto.strip().lower()
    if bruto in _DIGITADOS:
        return _DIGITADOS[bruto]
    return _FALADOS_INV.get(normalizar(texto))
