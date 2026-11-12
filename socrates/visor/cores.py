"""Cores do visor. Fica fora da janela (Tkinter) para os testes e as ferramentas usarem."""

from __future__ import annotations

import re
import unicodedata

# nome: (cor principal, brilho)
CORES: dict[str, tuple[str, str]] = {
    "laranja": ("#ff8a1c", "#ffd9a0"),
    "azul": ("#2f9bff", "#bfe2ff"),
    "ciano": ("#19d3e6", "#b9f4fa"),
    "verde": ("#2bd97c", "#baf5d4"),
    "roxo": ("#a56bff", "#e2d1ff"),
    "rosa": ("#ff5fa8", "#ffcde2"),
    "vermelho": ("#ff4d4d", "#ffc7c7"),
    "branco": ("#dfe6ee", "#ffffff"),
}
PADRAO = "laranja"
_APELIDOS = {"alaranjado": "laranja", "azul claro": "ciano", "roxa": "roxo", "lilas": "roxo",
             "violeta": "roxo", "vermelha": "vermelho", "branca": "branco", "pink": "rosa",
             "azul escuro": "azul", "amarelo": "laranja"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def _norm(nome: str) -> str:
    t = unicodedata.normalize("NFKD", str(nome)).encode("ascii", "ignore").decode().lower()
    return t.strip(" .!")


def _clarear(cor: str, f: float = 0.7) -> str:
    canais = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * f):02x}" for c in canais)


def nome_da_cor(cor: str) -> str | None:
    """O nome conhecido (ou o próprio #rrggbb) para guardar na configuração."""
    if _HEX.match(str(cor).strip()):
        return str(cor).strip().lower()
    n = _norm(cor)
    n = _APELIDOS.get(n, n)
    return n if n in CORES else None


def resolver(cor: str | None) -> tuple[str, str]:
    """(cor principal, brilho). Cor desconhecida vira a padrão."""
    nome = nome_da_cor(cor or PADRAO) or PADRAO
    if nome.startswith("#"):
        return nome, _clarear(nome)
    return CORES[nome]
