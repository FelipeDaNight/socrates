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
    DORMIR = "dormir"   # encerra a conversa atual, mas continua esperando o nome
    APAGAR_QUADRO = "apagar_quadro"
    SAIR = "sair"


_DIGITADOS = {
    "/explicar": Comando.EXPLICAR,
    "/testar": Comando.TESTAR,
    "/limpar": Comando.LIMPAR,
    "/ajuda": Comando.AJUDA,
    "/dormir": Comando.DORMIR,
    "/apagar": Comando.APAGAR_QUADRO,
    "/quadro": Comando.APAGAR_QUADRO,
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
    Comando.APAGAR_QUADRO: ["apaga o quadro", "apague o quadro", "apagar o quadro", "apagar quadro",
                            "limpa o quadro", "limpe o quadro", "limpar o quadro", "limpar quadro",
                            "fecha o quadro", "feche o quadro", "esconde o quadro", "tira o quadro"],
    Comando.DORMIR: ["obrigado", "obrigada", "valeu", "so isso", "e so isso", "por enquanto e so",
                     "pode descansar", "pode dormir", "dormir", "descansar"],
    Comando.SAIR: ["encerrar", "encerra", "desligar", "desliga", "tchau socrates",
                   "ate logo", "pode encerrar"],
}
_FALADOS_INV = {frase: cmd for cmd, frases in _FALADOS.items() for frase in frases}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z ]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return re.sub(r"^(ei |oi |ok )?socrates ", "", t)   # "Sócrates, modo prova"


# "vou ver o jogo, pode fechar": sem dizer O QUE fechar, é para encerrar a conversa.
# Em 22/11 isso ia para o agente, que respondia "Fechando tudo" sem fechar nada.
_FIM_DE_CONVERSA = re.compile(r"\bpode (fechar|desligar)( ai| tudo| entao| por hoje| por agora)?$")
_COISA_PARA_FECHAR = re.compile(
    r"\b(programa|programas|aplicativo|app|aba|abas|janela|janelas|navegador|chrome|edge|"
    r"firefox|spotify|youtube|bloco|notas|word|excel|code|timer|cronometro|musica|video|"
    r"pasta|arquivo|quadro|explorador|calculadora|discord|whatsapp|computador|pc)\b")


def encerra_conversa(texto: str) -> bool:
    """A frase termina em "pode fechar/desligar" sem nomear um programa?"""
    t = normalizar(texto)
    return (bool(_FIM_DE_CONVERSA.search(t)) and not _COISA_PARA_FECHAR.search(t)
            and len(t.split()) <= 12)


def interpretar(texto: str) -> Comando | None:
    bruto = texto.strip().lower()
    if bruto in _DIGITADOS:
        return _DIGITADOS[bruto]
    comando = _FALADOS_INV.get(normalizar(texto))
    if comando is None and encerra_conversa(texto):
        return Comando.DORMIR
    return comando
