"""Registro de ferramentas — as ações que o Sócrates pode executar.

Uso (fase 2):

    @ferramenta("Diz a hora atual")
    def hora() -> str: ...

    @ferramenta("Apaga uma anotação", confirmar=True)
    def apagar_nota(titulo: str) -> str: ...

Ferramentas com confirmar=True só rodam depois de você dizer "sim".
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Callable

_TIPOS = {str: "string", int: "integer", float: "number", bool: "boolean"}


@dataclass
class Ferramenta:
    nome: str
    descricao: str
    funcao: Callable
    confirmar: bool = False

    def esquema(self) -> dict:
        """Formato que o cérebro entende para decidir quando chamar a ferramenta."""
        props, obrigatorios = {}, []
        for p in inspect.signature(self.funcao).parameters.values():
            props[p.name] = {"type": _TIPOS.get(p.annotation, "string")}
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


def ferramenta(descricao: str, confirmar: bool = False):
    def decorar(funcao: Callable) -> Callable:
        REGISTRO[funcao.__name__] = Ferramenta(funcao.__name__, descricao, funcao, confirmar)
        return funcao
    return decorar
