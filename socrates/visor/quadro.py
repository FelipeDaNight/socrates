"""Desenha o quadro branco: títulos, texto, fórmulas (LaTeX) e gráficos.

O Sócrates escreve o quadro assim (entre [QUADRO] e [/QUADRO]):

    # Fórmula de Bhaskara
    Para resolver $ax^2 + bx + c = 0$:
    $$ x = \\frac{-b \\pm \\sqrt{\\Delta}}{2a} $$
    - onde $\\Delta = b^2 - 4ac$
    grafico: x**2 - 4 | -4 | 4

Usa o "mathtext" do matplotlib: fórmulas bonitas sem precisar instalar LaTeX.
"""

from __future__ import annotations

import ast
import io
import logging
import math
import re
import threading
from dataclasses import dataclass

log = logging.getLogger("socrates.quadro")

PAPEL = "#f8f6f0"
TINTA = "#1e2533"
TITULO = "#c2410c"
CURVA = ["#ea7a12", "#2563eb", "#16a34a"]
MARGEM = 34

_trava = threading.Lock()   # o matplotlib tem configurações globais


@dataclass
class Item:
    tipo: str          # titulo | texto | formula | item | grafico | espaco
    conteudo: str = ""


# ---------------- leitura ----------------

_GRAFICO = re.compile(r"^(gr[aá]fico|plot|curva)\s*:\s*(.+)$", re.IGNORECASE)


def interpretar(texto: str) -> list[Item]:
    itens: list[Item] = []
    for linha in texto.strip().splitlines():
        s = linha.strip()
        if not s:
            if itens and itens[-1].tipo != "espaco":
                itens.append(Item("espaco"))
            continue
        if s.startswith("#"):
            itens.append(Item("titulo", s.lstrip("#").strip()))
        elif (s.startswith("$$") and s.endswith("$$") and len(s) > 4) or \
                (s.startswith("\\[") and s.endswith("\\]")):
            itens.append(Item("formula", s[2:-2].strip()))
        elif m := _GRAFICO.match(s):
            itens.append(Item("grafico", m.group(2)))
        elif s[:2] in ("- ", "* ", "• "):
            itens.append(Item("item", s[2:].strip()))
        else:
            itens.append(Item("texto", s))
    while itens and itens[-1].tipo == "espaco":
        itens.pop()
    return itens


# ---------------- gráficos com avaliação segura ----------------

_FUNCOES = {"sin": "sin", "sen": "sin", "cos": "cos", "tan": "tan", "tg": "tan",
            "sqrt": "sqrt", "raiz": "sqrt", "log": "log", "ln": "log", "log10": "log10",
            "exp": "exp", "abs": "abs"}
_CONSTANTES = {"pi": math.pi, "e": math.e}
_NOS_OK = (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
           ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.USub, ast.UAdd, ast.Mod)


class ErroGrafico(ValueError):
    pass


def compilar_funcao(expr: str):
    """Transforma 'x^2 - 4' numa função segura de numpy. Só aceita matemática:
    nada de importar, abrir arquivos ou chamar qualquer outra coisa."""
    import numpy as np

    expr = expr.strip()
    expr = re.sub(r"^(y|f\s*\(\s*x\s*\))\s*=", "", expr).strip()
    expr = expr.replace("^", "**").replace("−", "-").replace("·", "*")
    expr = re.sub(r"(\d)\s*([a-z(])", r"\1*\2", expr)   # 2x -> 2*x ; 3(x+1) -> 3*(x+1)
    try:
        arvore = ast.parse(expr, mode="eval")
    except SyntaxError as e:
        raise ErroGrafico(f"expressão inválida: {expr}") from e
    for no in ast.walk(arvore):
        if not isinstance(no, _NOS_OK):
            raise ErroGrafico(f"não permitido em gráfico: {type(no).__name__}")
        if isinstance(no, ast.Call):
            if not isinstance(no.func, ast.Name) or no.func.id not in _FUNCOES or no.keywords:
                raise ErroGrafico("função não permitida em gráfico")
        if isinstance(no, ast.Name) and no.id not in _FUNCOES and no.id not in _CONSTANTES \
                and no.id != "x":
            raise ErroGrafico(f"variável desconhecida: {no.id}")
        if isinstance(no, ast.Constant) and not isinstance(no.value, (int, float)):
            raise ErroGrafico("só números são permitidos")
    codigo = compile(arvore, "<grafico>", "eval")
    ambiente = {nome: getattr(np, real) for nome, real in _FUNCOES.items()}
    ambiente.update(_CONSTANTES)

    def f(x):
        with np.errstate(all="ignore"):
            y = eval(codigo, {"__builtins__": {}}, {**ambiente, "x": x})  # noqa: S307 (árvore validada)
        return np.broadcast_to(np.asarray(y, dtype=float), np.shape(x)).copy()
    return f


def ler_grafico(spec: str) -> tuple[list[str], float, float]:
    partes = [p.strip() for p in spec.split("|")]
    exprs = [e.strip() for e in partes[0].split(";") if e.strip()]
    try:
        xmin = float(partes[1]) if len(partes) > 1 else -5.0
        xmax = float(partes[2]) if len(partes) > 2 else 5.0
    except ValueError:
        xmin, xmax = -5.0, 5.0
    if not xmin < xmax:
        xmin, xmax = -5.0, 5.0
    return exprs[:3], xmin, xmax


# ---------------- desenho ----------------

def _math_ok(trecho: str) -> bool:
    from matplotlib.mathtext import math_to_image
    try:
        math_to_image(trecho, io.BytesIO(), dpi=40, format="png")
        return True
    except Exception:
        return False


def _seguro(texto: str) -> str:
    """Fórmulas que o matplotlib não entende viram texto simples (em vez de travar)."""
    def trocar(m):
        return m.group(0) if _math_ok(m.group(0)) else m.group(1).replace("\\", "")
    return re.sub(r"\$([^$]+)\$", trocar, texto)


def _quebrar(texto: str, max_chars: int) -> list[str]:
    pedacos = re.split(r"(\$[^$]+\$)", texto)
    palavras: list[str] = []
    for p in pedacos:
        if p.startswith("$"):
            palavras.append(p)
        else:
            palavras.extend(p.split())
    linhas, atual, tam = [], "", 0
    for w in palavras:
        peso = len(re.sub(r"\\[a-zA-Z]+|[{}$_^]", "x", w)) * (0.7 if w.startswith("$") else 1)
        if atual and tam + peso + 1 > max_chars:
            linhas.append(atual)
            atual, tam = w, peso
        else:
            atual, tam = (f"{atual} {w}" if atual else w), tam + peso + 1
    if atual:
        linhas.append(atual)
    return linhas or [""]


def _altura(item: Item, largura: int, esc: float) -> float:
    corpo = 19 * esc
    if item.tipo == "titulo":
        return 44 * esc
    if item.tipo == "formula":
        alta = any(k in item.conteudo for k in ("\\frac", "\\sum", "\\int", "\\sqrt"))
        return (88 if alta else 62) * esc
    if item.tipo == "grafico":
        return 270 * esc
    if item.tipo == "espaco":
        return 10 * esc
    max_chars = int((largura - 2 * MARGEM - 24) / (corpo * 0.52))
    return len(_quebrar(item.conteudo, max_chars)) * corpo * 1.55 + 6 * esc


def renderizar(texto: str, largura: int = 760, altura: int = 640) -> bytes:
    """Devolve a imagem PNG do quadro."""
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure

    itens = interpretar(texto)
    with _trava, matplotlib.rc_context({"mathtext.fontset": "cm", "font.family": "DejaVu Sans"}):
        for it in itens:
            if it.tipo in ("titulo", "texto", "item"):
                it.conteudo = _seguro(it.conteudo)
        dpi = 100
        fig = Figure(figsize=(largura / dpi, altura / dpi), dpi=dpi, facecolor=PAPEL)
        FigureCanvasAgg(fig)

        util = altura - 2 * MARGEM
        total = sum(_altura(i, largura, 1.0) for i in itens) or 1
        esc = max(0.55, min(1.0, util / total))
        y = altura - MARGEM
        n_grafico = 0

        def px(v, eixo):
            return v / (largura if eixo == "x" else altura)

        for it in itens:
            h = _altura(it, largura, esc)
            if y - h < MARGEM * 0.5 and it.tipo != "espaco":
                fig.text(px(MARGEM, "x"), px(y, "y"), "...", color=TINTA, va="top",
                         fontsize=18 * esc)
                break
            if it.tipo == "titulo":
                fig.text(px(MARGEM, "x"), px(y, "y"), it.conteudo, color=TITULO, va="top",
                         fontsize=25 * esc, fontweight="bold")
                yl = y - 36 * esc
                fig.add_artist(matplotlib.lines.Line2D(
                    [px(MARGEM, "x"), px(largura - MARGEM, "x")], [px(yl, "y")] * 2,
                    color=TITULO, alpha=0.35, linewidth=1.2))
            elif it.tipo == "formula":
                conteudo = f"${it.conteudo}$"
                if not _math_ok(conteudo):
                    conteudo = it.conteudo.replace("\\", "")
                fig.text(0.5, px(y - h / 2, "y"), conteudo, color=TINTA, ha="center",
                         va="center", fontsize=30 * esc)
            elif it.tipo in ("texto", "item"):
                corpo = 19 * esc
                recuo = 24 if it.tipo == "item" else 0
                max_chars = int((largura - 2 * MARGEM - 24) / (corpo * 0.52))
                linhas = _quebrar(it.conteudo, max_chars)
                for k, linha in enumerate(linhas):
                    yy = y - k * corpo * 1.55
                    if it.tipo == "item" and k == 0:
                        fig.text(px(MARGEM + 4, "x"), px(yy, "y"), "•", color=TITULO,
                                 va="top", fontsize=corpo)
                    fig.text(px(MARGEM + recuo, "x"), px(yy, "y"), linha, color=TINTA,
                             va="top", fontsize=corpo)
            elif it.tipo == "grafico" and n_grafico == 0:
                n_grafico += 1
                _desenhar_grafico(fig, it.conteudo, px(MARGEM + 40, "x"),
                                  px(y - h + 8 * esc, "y"),
                                  px(largura - 2 * MARGEM - 50, "x"), px(h - 20 * esc, "y"), esc)
            y -= h

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=PAPEL)
    return buf.getvalue()


def _desenhar_grafico(fig, spec: str, x, y, w, h, esc: float) -> None:
    import numpy as np

    ax = fig.add_axes([x, y, w, h], facecolor="#ffffff")
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    ax.tick_params(colors=TINTA, labelsize=11 * esc)
    ax.grid(True, color="#e5e1d6", linewidth=0.8)
    exprs, xmin, xmax = ler_grafico(spec)
    xs = np.linspace(xmin, xmax, 600)
    desenhou = False
    for cor, expr in zip(CURVA, exprs):
        try:
            ys = compilar_funcao(expr)(xs)
        except ErroGrafico as e:
            log.warning("gráfico recusado: %s", e)
            continue
        ys[~np.isfinite(ys)] = np.nan
        ax.plot(xs, ys, color=cor, linewidth=2.6, label=f"y = {expr.replace('**', '^')}")
        desenhou = True
    ax.axhline(0, color=TINTA, linewidth=0.9)
    ax.axvline(0, color=TINTA, linewidth=0.9) if xmin < 0 < xmax else None
    if desenhou:
        ax.legend(loc="best", fontsize=12 * esc, frameon=False)
    else:
        ax.text(0.5, 0.5, "não consegui desenhar esse gráfico", ha="center",
                transform=ax.transAxes, color=TITULO)
