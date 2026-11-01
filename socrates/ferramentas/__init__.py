"""Registro de ferramentas — as ações que o Sócrates pode executar no computador.

    @ferramenta("Abre um programa", params={"nome": "qual programa"})
    def abrir_programa(nome: str) -> str: ...

O cérebro (no Groq) só ESCOLHE a ferramenta e os argumentos. Quem executa é o
seu próprio computador, com o Python, sem nenhuma API externa.
"""

from __future__ import annotations

import inspect
import logging
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
               params: dict[str, str] | None = None, opcoes: dict[str, list[str]] | None = None):
    def decorar(funcao: Callable) -> Callable:
        REGISTRO[funcao.__name__] = Ferramenta(funcao.__name__, descricao, funcao, confirmar,
                                               params or {}, opcoes or {})
        return funcao
    return decorar


def executar(nome: str, argumentos: dict) -> str:
    """Roda a ferramenta e SEMPRE devolve um texto (o erro também vira texto,
    para o cérebro poder explicar o que deu errado)."""
    f = REGISTRO.get(nome)
    if f is None:
        return f"Erro: não existe a ferramenta {nome}."
    validos = set(inspect.signature(f.funcao).parameters)
    argumentos = {k: v for k, v in (argumentos or {}).items() if k in validos}
    try:
        resultado = f.funcao(**argumentos)
    except TypeError as e:
        return f"Erro nos argumentos de {nome}: {e}"
    except Exception as e:   # a ação falhou no computador
        log.exception("ferramenta %s falhou", nome)
        return f"Erro ao executar {nome}: {e}"
    log.info("ferramenta %s(%s) -> %s", nome, argumentos, resultado)
    return str(resultado)
