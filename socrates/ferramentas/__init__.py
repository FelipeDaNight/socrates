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

# Uma resposta é "sim" se só tiver palavras de concordância ("sim, pode mandar por favor")
_PALAVRAS_SIM = {"sim", "pode", "podes", "mandar", "manda", "confirma", "confirmo", "confirmado",
                 "isso", "mesmo", "claro", "ok", "okay", "beleza", "bora", "vai", "faz", "faca",
                 "fazer", "atualiza", "atualizar", "envia", "enviar", "certo", "certeza", "com",
                 "por", "favor", "socrates", "ai", "la", "e", "yes", "positivo", "perfeito"}
_PALAVRAS_NAO = {"nao", "cancela", "cancelar", "cancelado", "esquece", "deixa", "negativo", "para"}


def _concorda(resposta: str) -> bool | None:
    palavras = resposta.split()
    if not palavras or len(palavras) > 8:
        return None
    if any(p in _PALAVRAS_NAO for p in palavras):
        return False
    if all(p in _PALAVRAS_SIM for p in palavras) and set(palavras) - {"por", "favor", "socrates", "e", "com", "ai", "la"}:
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
    log.info("ferramenta %s(%s) -> %s", nome, argumentos, resultado)
    return str(resultado)
