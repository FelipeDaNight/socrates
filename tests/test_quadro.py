"""Quadro branco: separar da fala, interpretar, desenhar e gráficos seguros."""

import asyncio

import numpy as np
import pytest

from socrates.core.comandos import Comando, interpretar as comando
from socrates.core.quadro_fluxo import separar_quadro
from socrates.visor.quadro import (ErroGrafico, compilar_funcao, interpretar, ler_grafico,
                                   renderizar)


async def _fluxo(*pedacos):
    for p in pedacos:
        await asyncio.sleep(0)
        yield p


async def _separar(*pedacos):
    quadros = []
    fala = "".join([p async for p in separar_quadro(_fluxo(*pedacos), quadros.append)])
    return fala, quadros


# ---------- separar fala e quadro ----------

@pytest.mark.asyncio
async def test_quadro_sai_da_fala():
    fala, quadros = await _separar("Veja no quadro. [QUADRO]# Bhaskara\n$$x=1$$[/QUADRO] Entendeu?")
    assert fala == "Veja no quadro.  Entendeu?"
    assert quadros == ["# Bhaskara\n$$x=1$$"]


@pytest.mark.asyncio
async def test_marcas_quebradas_entre_pedacos():
    fala, quadros = await _separar("Olha [QUA", "DRO]# Tí", "tulo[/QUA", "DRO] fim.")
    assert fala == "Olha  fim." and quadros == ["# Título"]


@pytest.mark.asyncio
async def test_colchete_comum_nao_some():
    fala, quadros = await _separar("A lista [1, 2", "] e o [Q] ficam.")
    assert fala == "A lista [1, 2] e o [Q] ficam." and quadros == []


@pytest.mark.asyncio
async def test_quadro_sem_fechar_ainda_aparece():
    fala, quadros = await _separar("Veja. [quadro]# Título\n- item")
    assert fala == "Veja. " and quadros == ["# Título\n- item"]


@pytest.mark.asyncio
async def test_aceita_funcao_async():
    recebidos = []

    async def guardar(q):
        recebidos.append(q)

    fala = "".join([p async for p in separar_quadro(_fluxo("a [QUADRO]x[/QUADRO] b"), guardar)])
    assert fala == "a  b" and recebidos == ["x"]


# ---------- interpretar ----------

def test_interpreta_cada_tipo_de_linha():
    itens = interpretar("# Título\nTexto $x$\n\n$$ \\frac{1}{2} $$\n- item\ngráfico: x^2 | -2 | 2\n\n")
    assert [i.tipo for i in itens] == ["titulo", "texto", "espaco", "formula", "item", "grafico"]
    assert itens[3].conteudo == "\\frac{1}{2}" and itens[5].conteudo == "x^2 | -2 | 2"


def test_le_grafico():
    assert ler_grafico("x^2; 2x+1 | -3 | 3") == (["x^2", "2x+1"], -3.0, 3.0)
    assert ler_grafico("sin(x)") == (["sin(x)"], -5.0, 5.0)
    assert ler_grafico("x | 5 | 1") == (["x"], -5.0, 5.0)


# ---------- gráficos seguros ----------

@pytest.mark.parametrize("expr,x,esperado", [
    ("x^2 - 4", 3.0, 5.0),
    ("y = 2x + 1", 2.0, 5.0),
    ("f(x) = sen(x)", 0.0, 0.0),
    ("raiz(x) + abs(-1)", 4.0, 3.0),
    ("3(x+1)", 1.0, 6.0),
    ("pi", 0.0, np.pi),
])
def test_funcoes_matematicas(expr, x, esperado):
    assert compilar_funcao(expr)(np.array([x]))[0] == pytest.approx(esperado)


@pytest.mark.parametrize("ataque", [
    "__import__('os').system('calc')",
    "x.__class__",
    "open('arquivo')",
    "[x for x in ()]",
    "lambda: 1",
    "'texto'",
    "y + 1",
])
def test_bloqueia_codigo_no_grafico(ataque):
    with pytest.raises(ErroGrafico):
        compilar_funcao(ataque)


def test_divisao_por_zero_nao_quebra():
    ys = compilar_funcao("1/x")(np.array([0.0, 2.0]))
    assert ys[1] == 0.5


# ---------- desenho ----------

def _png_ok(png: bytes, w: int, h: int):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    largura = int.from_bytes(png[16:20], "big")
    altura = int.from_bytes(png[20:24], "big")
    assert (largura, altura) == (w, h)


def test_desenha_quadro_completo():
    texto = ("# Bhaskara\nPara $ax^2+bx+c=0$:\n$$ x = \\frac{-b \\pm \\sqrt{\\Delta}}{2a} $$\n"
             "- Se $\\Delta < 0$, sem raiz real\ngrafico: x^2 - 4 | -4 | 4")
    _png_ok(renderizar(texto, 700, 600), 700, 600)


def test_latex_que_o_matplotlib_nao_entende_nao_derruba():
    _png_ok(renderizar("# Teste\n$$ \\begin{matrix} 1 \\end{matrix} $$\nTexto $\\fraaac{1}$",
                       500, 400), 500, 400)


def test_quadro_comprido_cabe():
    texto = "# Lista\n" + "\n".join(f"- item número {i} com bastante texto" for i in range(40))
    _png_ok(renderizar(texto, 600, 500), 600, 500)


# ---------- comando ----------

@pytest.mark.parametrize("fala", ["Apaga o quadro.", "Sócrates, limpa o quadro", "/apagar"])
def test_comando_apagar_quadro(fala):
    assert comando(fala) is Comando.APAGAR_QUADRO
