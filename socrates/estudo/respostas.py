"""Entende a resposta FALADA do aluno num treino.

O Whisper escreve "Letra Bê.", "Acho que é errado", "C". Aqui isso vira "B", "E", "C".
E compara a resposta de uma lacuna com o gabarito sem exigir as palavras exatas.
"""

from __future__ import annotations

import difflib
import re
import unicodedata

NUMEROS = {"1": "um", "2": "dois", "3": "tres", "4": "quatro", "5": "cinco", "6": "seis",
           "7": "sete", "8": "oito", "9": "nove", "10": "dez", "11": "onze", "12": "doze",
           "13": "treze", "14": "quatorze", "15": "quinze", "16": "dezesseis", "17": "dezessete",
           "18": "dezoito", "19": "dezenove", "20": "vinte", "30": "trinta", "60": "sessenta",
           "90": "noventa", "100": "cem"}
PALAVRAS_VAZIAS = {"a", "o", "as", "os", "e", "de", "da", "do", "das", "dos", "em", "no", "na",
                   "nos", "nas", "um", "uma", "por", "para", "pra", "com", "que", "se", "ao", "aos",
                   "ou", "eh", "sao", "acho", "resposta", "socrates", "lacuna"}


def norm(texto: str) -> str:
    # "artigo 5º" -> "artigo 5": sem isso o "º" virava "o" ("5o") e "artigo 5" não batia
    texto = re.sub(r"(\d)\s*[ºª°]", r"\1", texto)
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"[^a-z0-9 ]", " ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------- comandos durante o treino ----------

COMANDOS = [   # (comando, frases); a primeira que bater vale
    ("parar", r"^(?:parar?|pare|chega|encerra\w*|termina\w*|finaliza\w*|sai(?:r)?|acabou|"
              r"(?:pode )?parar? (?:o )?(?:treino|simulado|revisao))\b"
              r"|\b(?:encerra\w*|termina\w*|finaliza\w*|para|parar|sair d\w*) (?:o |a )?"
              r"(?:treino|simulado|revisao|questoes|lacunas)\b"),
    ("pular", r"^(?:pula|pular|pule|passa|passar|proxima|proximo|seguinte|next|vai|bora|segue|"
              r"continua|continuar|outra|manda a proxima|(?:pode )?(?:ir|passar) para? a? ?proxima)\b"),
    ("repetir", r"^(?:repete|repetir|repita|de novo|outra vez|fala de novo|le de novo|"
                r"(?:pode )?repetir)\b|\bnao (?:ouvi|escutei)\b"),
    ("texto", r"\b(?:mostra|mostre|abre|abra|le|leia)\b.*\btexto\b|\btexto (?:completo|inteiro|de apoio)\b"),
    ("dica", r"\b(?:dica|pista|me ajuda)\b"),
    ("explicar", r"\b(?:explica|explique|explicar|por que|porque|pq|nao entendi|como assim|"
                 r"justifica|fundamento|qual (?:e )?a regra)\b"
                 # o microfone ouve "Explique, por favor" como "Filipe, por favor" (e parecidos)
                 r"|^(?:filipe|felipe|felippe|cicco|cico|chico|esplica|explico)(?: por favor)?$"),
    ("anterior", r"\b(?:questao|pergunta|item|afirmacao) anterior\b|\banterior a essa\b"
                 r"|^(?:volta|voltar|volte)(?: (?:uma|a|na|para a))?(?: questao| anterior)?$"),
    ("quadro", r"\b(?:mostra|mostre|coloca|coloque|poe|ponha|bota|bote|escreve|escreva|joga|"
               r"deixa)\b.*\bquadro\b|^(?:no )?quadro(?: por favor)?$"),
    ("placar", r"\b(?:placar|quantas (?:eu )?(?:acertei|errei|faltam)|como (?:eu )?(?:estou|to) indo)\b"),
]
_COMANDOS = [(nome, re.compile(rx)) for nome, rx in COMANDOS]


# "Pode seguir para a próxima", "Entendi, pode passar", "Sim, pode passar": seguir em
# qualquer lugar de uma fala curta (antes só valia no começo, e o resto ia para o cérebro,
# que chegou a inventar "a próxima questão").
_SEGUIR = re.compile(r"\b(?:proxima|proximo|seguinte|seguir|segue|siga|sigo|passar|passa|passo|"
                     r"pula|pular|pule|avanca|avancar|avance|continua|continuar|continue)\b")
_NAO_SEGUIR = re.compile(r"\bnao\b.{0,25}\b(?:passa|passar|segue|seguir|pula|pular|avanca|"
                         r"continua|proxima)\b|\b(?:explica|explique|por que|porque|nao entendi|"
                         r"como assim|anterior|ainda nao)\b")


def comando(texto: str, solto: bool = True) -> str | None:
    """`solto=False`: só os comandos claros (a resposta de uma lacuna pode ter "seguinte")."""
    t = norm(texto)
    t = re.sub(r"^(?:socrates|ei|ok|ta|entao|bom)\s+", "", t)
    for nome, rx in _COMANDOS:
        if rx.search(t):
            return nome
    if solto and len(t.split()) <= 8 and _SEGUIR.search(t) and not _NAO_SEGUIR.search(t):
        return "pular"
    return None


def quer_seguir(texto: str) -> bool:
    """A fala pede para seguir/avançar (em qualquer lugar de uma frase curta)?"""
    return comando(texto) == "pular"


# ---------- certo / errado ----------

_CERTO = re.compile(r"\b(certo|certa|correto|correta|verdadeiro|verdadeira|verdade)\b")
_ERRADO = re.compile(r"\b(errado|errada|incorreto|incorreta|falso|falsa|mentira)\b")


def certo_ou_errado(texto: str) -> str | None:
    """'C', 'E' ou None. Se aparecerem os dois numa frase, vale o último dito ("acho que
    certo... não, errado"); numa fala curta ("Errado, certo?") é ambíguo: None."""
    t = norm(texto)
    if t in ("c", "letra c"):
        return "C"
    if t == "letra e":         # "é" sozinho não: é o verbo, não a letra
        return "E"
    marcas = [(m.start(), "C") for m in _CERTO.finditer(t)] + \
             [(m.start(), "E") for m in _ERRADO.finditer(t)]
    if not marcas:
        return None
    if ambiguo(texto):
        return None
    return max(marcas)[1]


_CORRIGIU = re.compile(r"\b(?:nao|quer dizer|digo|ops|opa|melhor)\b")


def ambiguo(texto: str) -> bool:
    """Disse certo E errado numa fala curta, sem se corrigir ("Errado, certo." pode ser
    "errado, né?"): melhor perguntar do que chutar. "Errado, não, certo!" vale certo."""
    t = norm(texto)
    return bool(_CERTO.search(t) and _ERRADO.search(t) and len(t.split()) <= 3
                and not _CORRIGIU.search(t))


# ---------- alternativas A a E ----------

_LETRAS = {"a": "A", "b": "B", "be": "B", "bee": "B", "c": "C", "ce": "C", "se": "C",
           "d": "D", "de": "D", "e": "E", "eh": "E"}
_COM_PREFIXO = re.compile(r"\b(?:letra|alternativa|opcao|item)\s+(a|b|be|bee|c|ce|se|d|de|e|eh)\b")
_ENCHIMENTO = re.compile(r"^(?:(?:acho|creio|penso) que |minha resposta (?:e |eh )?|(?:e|eh|seria|sera) )*"
                         r"(?:a |o )?")


def alternativa(texto: str, letras: str = "ABCDE") -> str | None:
    t = norm(texto)
    achadas = _COM_PREFIXO.findall(t)
    if achadas:
        letra = _LETRAS[achadas[-1]]
        return letra if letra in letras else None
    resto = _ENCHIMENTO.sub("", t).strip()
    letra = _LETRAS.get(resto)
    return letra if letra and letra in letras else None


# ---------- lacunas ----------

def _palavras_chave(texto: str) -> list[str]:
    t = norm(texto)
    saida = []
    for p in t.split():
        p = NUMEROS.get(p, p)
        if p not in PALAVRAS_VAZIAS:
            saida.append(p)
    return saida


def _parecida(p: str, lista: set[str]) -> bool:
    if p in lista:
        return True
    if len(p) < 5:
        return False
    # erro de transcrição costuma ser no fim da palavra; "subjetivamente" no lugar de
    # "objetivamente" é outra resposta, por isso o começo tem que bater
    return any(len(q) >= 5 and q[:3] == p[:3]
               and difflib.SequenceMatcher(None, p, q).ratio() >= 0.8 for q in lista)


def nota_lacuna(resposta: str, gabarito: str) -> float:
    """0 a 1: quanto das palavras importantes do gabarito o aluno disse."""
    esperadas = _palavras_chave(gabarito)
    if not esperadas:
        return 1.0 if norm(resposta) == norm(gabarito) else 0.0
    ditas = set(_palavras_chave(resposta))
    unicas = list(dict.fromkeys(esperadas))
    return sum(1 for p in unicas if _parecida(p, ditas)) / len(unicas)


def lacuna_certa(resposta: str, gabarito: str) -> bool:
    """O gabarito pode trazer o número escrito duas vezes ("12 (doze) meses"): dizer
    qualquer uma das formas vale. Basta acertar a maior parte das palavras-chave."""
    sem_parenteses = re.sub(r"\([^)]*\)", " ", gabarito)
    return max(nota_lacuna(resposta, gabarito), nota_lacuna(resposta, sem_parenteses)) >= 0.6
