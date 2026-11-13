"""Registro de ferramentas — as ações que o Sócrates pode executar no computador.

    @ferramenta("Abre um programa", params={"nome": "qual programa"})
    def abrir_programa(nome: str) -> str: ...

O cérebro (no Groq) só ESCOLHE a ferramenta e os argumentos. Quem executa é o
seu próprio computador, com o Python, sem nenhuma API externa.
"""

from __future__ import annotations

import inspect
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("socrates.ferramentas")

_TIPOS = {"str": "string", "int": "integer", "float": "number", "bool": "boolean",
          str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    funcao: Callable
    confirmar: bool = False
    params: dict[str, str] = field(default_factory=dict)        # descrição de cada argumento
    opcoes: dict[str, list[str]] = field(default_factory=dict)  # valores permitidos
    resumo: Callable[[dict], str] | None = None                 # frase para pedir confirmação

    def esquema(self) -> dict:
        """Formato que o cérebro entende para decidir quando chamar a ferramenta."""
        props, obrigatorios = {}, []
        for p in inspect.signature(self.funcao).parameters.values():
            prop = {"type": _TIPOS.get(p.annotation, "string")}
            if p.name in self.params:
                prop["description"] = self.params[p.name]
            if p.name in self.opcoes:
                prop["enum"] = self.opcoes[p.name]
            props[p.name] = prop
            if p.default is inspect.Parameter.empty:
                obrigatorios.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.nome,
                "description": self.descricao,
                "parameters": {"type": "object", "properties": props,
                               "required": obrigatorios},
            },
        }


REGISTRO: dict[str, Ferramenta] = {}


# ---------------- memória curta ----------------
# O que ele acabou de VER (a tela, o texto copiado) fica disponível por alguns minutos,
# para as perguntas seguintes ("e qual é a última palavra?") não ficarem sem resposta.

LEMBRAR = {"ver_tela": "a tela do aluno", "ler_area_de_transferencia": "o texto que o aluno copiou"}
VALIDADE_LEMBRANCA_SEG = 300
CORTE_LEMBRANCA = 1500


@dataclass
class Lembranca:
    o_que: str
    texto: str
    quando: float


LEMBRANCA: Lembranca | None = None


def lembranca_valida() -> Lembranca | None:
    if LEMBRANCA and time.monotonic() - LEMBRANCA.quando <= VALIDADE_LEMBRANCA_SEG:
        return LEMBRANCA
    return None


def texto_da_lembranca() -> str:
    """Uma linha para o cérebro: o que ele viu há pouco (ou "" se não viu nada)."""
    m = lembranca_valida()
    if m is None:
        return ""
    minutos = int((time.monotonic() - m.quando) // 60)
    quando = "agora há pouco" if minutos < 1 else f"há {minutos} min"
    conteudo = " / ".join(l.strip() for l in m.texto.splitlines() if l.strip())[:CORTE_LEMBRANCA]
    return (f"Há pouco você viu {m.o_que} ({quando}): {conteudo} "
            "(Use isso se ele perguntar a respeito; para olhar de novo, use a ferramenta.)")


# Depois de abrir um vídeo ou uma música, o som do PC entra pelo microfone. A conversa
# vê este aviso e volta a exigir o nome "Sócrates", para não responder ao vídeo.
SOM_LIGADO = threading.Event()


def ferramenta(descricao: str, confirmar: bool = False,
               params: dict[str, str] | None = None, opcoes: dict[str, list[str]] | None = None,
               resumo: Callable[[dict], str] | None = None):
    def decorar(funcao: Callable) -> Callable:
        REGISTRO[funcao.__name__] = Ferramenta(funcao.__name__, descricao, funcao, confirmar,
                                               params or {}, opcoes or {}, resumo)
        return funcao
    return decorar


# ---------------- confirmação por voz ----------------
# Ferramentas com confirmar=True não rodam de primeira: ficam esperando o aluno
# dizer "sim". Quem resolve é a conversa, ANTES de mandar a fala para o cérebro.

VALIDADE_SEG = 90


@dataclass
class Pendente:
    nome: str
    argumentos: dict
    resumo: str
    criado: float


PENDENTE: Pendente | None = None

# "Sim" de verdade costuma vir com mais palavras: "Sim, coloque no chat dele, muda a cor".
# Vale como sim a frase que COMEÇA concordando; vale como não a que traz um "não".
_COMECO_SIM = {"sim", "pode", "claro", "isso", "manda", "mande", "mandar", "confirmo", "confirma",
               "confirmado", "ok", "okay", "beleza", "positivo", "perfeito", "exato", "exatamente",
               "bora", "envia", "envie", "enviar", "certo", "correto", "faz", "faca", "vai",
               "aham", "uhum", "yes", "atualiza", "atualize", "atualizar", "quero", "isso mesmo"}
_PALAVRAS_SIM = _COMECO_SIM | {"podes", "mesmo", "fazer", "certeza", "com", "por", "favor",
                               "socrates", "ai", "la", "e", "ta", "bom", "tudo", "bem", "que", "agora"}
_COMECO_NAO = {"nao", "cancela", "cancelar", "cancele", "cancelado", "esquece", "esqueca",
               "deixa", "negativo", "espera", "pera", "para", "pare", "nunca"}
_NAO_NO_MEIO = {"nao", "cancela", "cancelar", "cancele", "esquece", "esqueca"}   # "pode não"
_ENFEITES = {"socrates", "ah", "eh", "entao", "bom", "olha", "ei", "opa"}   # antes da resposta


def _concorda(resposta: str) -> bool | None:
    """True = sim, False = não, None = falou de outra coisa."""
    palavras = resposta.split()
    while palavras and palavras[0] in _ENFEITES:
        palavras = palavras[1:]
    if not palavras:
        return None
    if palavras[0] in _COMECO_NAO or any(p in _NAO_NO_MEIO for p in palavras[:6]):
        return False
    if "mas" in palavras[:3]:              # "sim, mas muda o texto": não é um sim limpo
        return None
    if palavras[0] in _COMECO_SIM:
        return True
    enfeite = {"por", "favor", "socrates", "e", "com", "ai", "la", "que", "agora"}
    if len(palavras) <= 8 and all(p in _PALAVRAS_SIM for p in palavras) and set(palavras) - enfeite:
        return True
    return None


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z ]", " ", t)).strip()


def pendente_valido() -> Pendente | None:
    global PENDENTE
    if PENDENTE and time.monotonic() - PENDENTE.criado > VALIDADE_SEG:
        PENDENTE = None
    return PENDENTE


def resolver_confirmacao(fala: str) -> str | None:
    """Se há uma ação esperando confirmação e a fala é sim/não, resolve e devolve
    o que dizer. Devolve None se não havia nada pendente ou a fala é outra coisa
    (nesse caso a ação pendente é descartada: o aluno mudou de assunto)."""
    global PENDENTE
    p = pendente_valido()
    if p is None:
        return None
    decisao = _concorda(_norm(fala))
    PENDENTE = None
    if decisao is True:
        return executar(p.nome, p.argumentos, confirmado=True)
    if decisao is False:
        return "Tudo bem, cancelei."
    log.info("confirmação de %s descartada pela fala %r", p.nome, fala)
    return None


def executar(nome: str, argumentos: dict, confirmado: bool = False) -> str:
    """Roda a ferramenta e SEMPRE devolve um texto (o erro também vira texto,
    para o cérebro poder explicar o que deu errado)."""
    global PENDENTE
    f = REGISTRO.get(nome)
    if f is None:
        return f"Erro: não existe a ferramenta {nome}."
    validos = set(inspect.signature(f.funcao).parameters)
    argumentos = {k: v for k, v in (argumentos or {}).items() if k in validos}
    if f.confirmar and not confirmado:
        resumo = f.resumo(argumentos) if f.resumo else f"{nome}({argumentos})"
        PENDENTE = Pendente(nome, argumentos, resumo, time.monotonic())
        log.info("aguardando confirmação: %s", resumo)
        return (f"AGUARDANDO CONFIRMAÇÃO. Ainda NÃO foi feito. Pergunte ao aluno, em uma frase, "
                f"se pode {resumo}. Ele vai responder sim ou não.")
    try:
        resultado = f.funcao(**argumentos)
    except TypeError as e:
        return f"Erro nos argumentos de {nome}: {e}"
    except Exception as e:   # a ação falhou no computador
        log.exception("ferramenta %s falhou", nome)
        return f"Erro ao executar {nome}: {e}"
    global LEMBRANCA
    if nome in LEMBRAR and not str(resultado).startswith("Erro"):
        LEMBRANCA = Lembranca(LEMBRAR[nome], str(resultado), time.monotonic())
    log.info("ferramenta %s(%s) -> %s", nome, argumentos, resultado)
    return str(resultado)


def nomes_das_acoes(com_busca: bool = False, extras: tuple[str, ...] = ()) -> list[str]:
    """As ferramentas que o cérebro pode usar (importar o módulo registra as dele)."""
    import importlib
    modulos = ["computador", "janelas", "tela", "claude", "aparencia", "estudo", *extras]
    if com_busca:
        modulos.append("busca")
    nomes_mod = {importlib.import_module(f"{__name__}.{m}").__name__ for m in modulos}
    return [n for n, f in REGISTRO.items() if f.funcao.__module__ in nomes_mod]
