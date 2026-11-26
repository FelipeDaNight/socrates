"""Desenhos explicativos no quadro: mapa mental, cenários e passo a passo.

O Sócrates escreve no quadro (entre [QUADRO] e [/QUADRO]) uma linha com o tipo e o tema;
depois, os ramos com "- " e os detalhes de cada ramo recuados ("  - "):

    # Poderes da União
    mapa: Poderes (CF, art. 2º)
    - Legislativo
      - Congresso Nacional
    - Executivo
      - Presidente da República
    - Judiciário
      - STF e demais tribunais

Tipos (a palavra antes dos dois-pontos):
- mapa (ou "mapa mental"): o tema no centro e os ramos dos dois lados, em cartões numerados.
- cenarios: a situação à esquerda; cada ramo é uma condição ("Se ...") e os detalhes são o
  que acontece nela, ligados por uma seta. "Se recusar -> multa" numa linha só também vale.
- fluxo: o passo a passo, uma caixa por etapa, de cima para baixo.

Sem a linha do tipo, o quadro continua como antes (texto, fórmulas e gráficos). O desenho
diminui a letra até tudo caber; se nem assim couber, corta os últimos detalhes e põe "…".
"""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass, field

from .quadro import MARGEM, PAPEL, PX_POR_PT, TINTA, TITULO, _altura_titulo, _titulo, _trava

CORES = ("#c2410c", "#1d4ed8", "#15803d", "#7e22ce", "#0f766e", "#be123c")
COR_FLUXO = "#1d4ed8"
BRANCO = "#ffffff"
COR_NOTA = "#475569"
MAXIMO = {"mapa": 6, "cenarios": 5, "fluxo": 7}     # ramos que cabem num quadro
DETALHES = 4                                          # detalhes por ramo
TAMANHOS = (15, 14, 13, 12, 11, 10, 9)                # letra (pt) das caixas, da maior à menor
NOTA_PT = 11.5


# ---------------------------------------------------------------- leitura

@dataclass
class No:
    texto: str
    filhos: list[No] = field(default_factory=list)


@dataclass
class Diagrama:
    tipo: str                    # mapa | cenarios | fluxo
    centro: str                  # o tema, a situação ou o nome do processo
    ramos: list[No]
    titulo: str = ""
    nota: str = ""               # texto solto do quadro, vai embaixo do desenho


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


_DECLARA = re.compile(r"^(?:#+\s*)?(mapa mental|mapa|cenarios?|arvore de cenarios|arvore|"
                      r"fluxograma|fluxo|passo a passo)\s*:\s*(.*)$")
_TIPOS = {"mapa": "mapa", "mapa mental": "mapa", "fluxo": "fluxo", "fluxograma": "fluxo",
          "passo a passo": "fluxo"}
_BALA = re.compile(r"^(\s*)(?:[-*•–+]|\d{1,2}[.)])\s+(.*\S)\s*$")
_SETA = re.compile(r"\s*(?:→|->|=>|⇒|⟶)\s*")


def _limpo(s: str) -> str:
    """Tira o markdown ("**Próprio**") e as marcas de fórmula: no desenho é texto simples."""
    s = re.sub(r"\*\*(.+?)\*\*|__(.+?)__", lambda m: m.group(1) or m.group(2), s)
    s = s.replace("**", "").replace("`", "")
    s = re.sub(r"(?<!\\)\$([^$]+)\$", lambda m: m.group(1).replace("\\", ""), s)
    s = s.replace("\\$", "$")
    return re.sub(r"\s+", " ", s).strip()


def _declaracao(linha: str) -> tuple[str, str] | None:
    m = _DECLARA.match(_sem_acento(linha))
    if not m:
        return None
    return _TIPOS.get(m.group(1), "cenarios"), linha.split(":", 1)[1].strip()


def _arvore(itens: list[tuple[int, str]]) -> list[No]:
    """Itens com recuo -> árvore. O menor recuo é o dos ramos; recuo maior é detalhe do
    item de cima."""
    base = min(r for r, _ in itens)
    ramos: list[No] = []
    pilha: list[tuple[int, No]] = []
    for recuo, texto in itens:
        no = No(texto)
        while pilha and pilha[-1][0] >= recuo:
            pilha.pop()
        if not pilha or recuo <= base:
            ramos.append(no)
            pilha = [(recuo, no)]
        else:
            pilha[-1][1].filhos.append(no)
            pilha.append((recuo, no))
    return ramos


def _dividir(no: No, tipo: str) -> No:
    """Ramo sem detalhes escrito numa linha só: "Se recusar -> multa" ou "Próprio: está
    cometendo" viram ramo + detalhe."""
    if no.filhos:
        return no
    partes = _SETA.split(no.texto, maxsplit=1)
    if len(partes) == 2 and partes[0] and partes[1]:
        return No(partes[0], [No(partes[1])])
    if ": " in no.texto:
        cabeca, resto = no.texto.split(": ", 1)
        letras, palavras = (70, 12) if tipo == "cenarios" else (32, 5)
        if resto and 0 < len(cabeca) <= letras and len(cabeca.split()) <= palavras:
            return No(cabeca, [No(resto)])
    return no


def ler(texto: str) -> Diagrama | None:
    """O quadro pede um desenho? Devolve o desenho, ou None (quadro comum)."""
    tipo = centro = None
    titulo, notas, soltas, itens = "", [], [], []
    for bruta in (texto or "").replace("\t", "    ").splitlines():
        if not bruta.strip():
            continue
        limpa = _limpo(bruta)
        if tipo is None:
            achado = _declaracao(limpa)
            if achado:
                tipo, centro = achado
            elif limpa.startswith("#"):
                titulo = titulo or limpa.lstrip("#").strip()
            elif limpa:
                notas.append(limpa.lstrip("-*•– ").strip())
            continue
        m = _BALA.match(bruta)
        if m:
            itens.append((len(m.group(1)), _limpo(m.group(2))))
        elif limpa.startswith("#"):
            titulo = titulo or limpa.lstrip("#").strip()
        elif limpa:
            soltas.append(limpa)
    if tipo is None:
        return None
    if not itens:                           # o modelo esqueceu os "-": cada linha é um ramo
        itens, soltas = [(0, s) for s in soltas], []
    itens = [(r, t) for r, t in itens if t]
    if not itens:
        return None
    ramos = [_dividir(r, tipo) for r in _arvore(itens)]
    sobra = len(ramos) - MAXIMO[tipo]
    if sobra > 0:
        ramos = ramos[:MAXIMO[tipo]]
        soltas.append(f"(mais {sobra} {'ramo' if sobra == 1 else 'ramos'} na explicação)")
    return Diagrama(tipo, centro or titulo or "Tema", ramos, titulo, " ".join(notas + soltas))


def _detalhes(no: No) -> list[str]:
    """Filhos e netos de um ramo, numa lista (netos com "–" na frente)."""
    saida: list[str] = []

    def andar(n: No, nivel: int) -> None:
        for f in n.filhos:
            saida.append(("– " if nivel else "") + f.texto)
            andar(f, nivel + 1)
    andar(no, 0)
    if len(saida) > DETALHES:
        saida = saida[:DETALHES] + ["…"]
    return saida


# ---------------------------------------------------------------- medidas

def _medidor(renderer):
    """Largura (px) de um texto, medida pelo próprio matplotlib (a mesma fonte do desenho)."""
    from matplotlib.font_manager import FontProperties

    fontes: dict = {}
    larguras: dict = {}

    def fonte(pt: float, negrito: bool = False):
        chave = (round(pt, 2), negrito)
        if chave not in fontes:
            fontes[chave] = FontProperties(family="DejaVu Sans", size=pt,
                                           weight="bold" if negrito else "normal")
        return fontes[chave]

    def w(s: str, pt: float, negrito: bool = False) -> float:
        chave = (s, round(pt, 2), negrito)
        if chave not in larguras:
            larguras[chave] = renderer.get_text_width_height_descent(
                s, fonte(pt, negrito), ismath=False)[0]
        return larguras[chave]

    w.fonte = fonte
    w.hifens = 0                 # palavras cortadas com hífen na última montagem
    return w


def _quebrar(texto: str, largura: float, pt: float, negrito: bool, w) -> list[str]:
    linhas, atual = [], ""
    for palavra in texto.split():
        tentativa = f"{atual} {palavra}" if atual else palavra
        if atual and w(tentativa, pt, negrito) > largura:
            linhas.append(atual)
            atual = palavra
        else:
            atual = tentativa
    if atual:
        linhas.append(atual)
    saida = []
    for linha in linhas:                    # palavra maior que a caixa: corta com hífen
        while len(linha) > 3 and w(linha, pt, negrito) > largura:
            w.hifens = getattr(w, "hifens", 0) + 1
            k = len(linha) - 1
            while k > 2 and w(linha[:k] + "-", pt, negrito) > largura:
                k -= 1
            saida.append(linha[:k] + "-")
            linha = linha[k:]
        saida.append(linha)
    return saida


@dataclass
class Caixa:
    w: float
    h: float
    cabeca: list[str]
    corpo: list[list[str]]
    pt: float
    cor: str
    fundo: str = BRANCO
    cor_cabeca: str = ""
    numero: str = ""
    raiz: bool = False
    x: float = 0.0
    y: float = 0.0               # base (o matplotlib conta de baixo para cima)

    @property
    def meio_y(self) -> float:
        return self.y + self.h / 2


def _caixa(texto: str, detalhes: list[str], largura: float, pt: float, w, cor: str = TINTA,
           numero: str = "", raiz: bool = False, fundo: str = BRANCO, cor_cabeca: str = "") -> Caixa:
    px = pt * PX_POR_PT
    folga_x, folga_y, lh = 0.75 * px, 0.6 * px, 1.3 * px
    bola = 1.35 * px + 6 if numero else 0
    pt_cabeca = pt + 2 if raiz else pt + 0.5
    cabeca = _quebrar(texto, largura - 2 * folga_x - bola, pt_cabeca, True, w) if texto else []
    recuo = 0.95 * px if len(detalhes) > 1 else 0
    corpo = [_quebrar(d, largura - 2 * folga_x - recuo, pt, False, w) for d in detalhes]
    h = 2 * folga_y + len(cabeca) * lh * (pt_cabeca / pt)
    if corpo:
        h += (0.35 * lh if cabeca else 0) + sum(len(c) for c in corpo) * lh + 0.2 * lh * (len(corpo) - 1)
    if numero:
        h = max(h, 2 * folga_y + 1.35 * px)
    return Caixa(largura, h, cabeca, corpo, pt, cor, fundo,
                 cor_cabeca or (BRANCO if raiz else cor), numero, raiz)


def _tom(cor: str, quanto: float = 0.13) -> str:
    """A cor bem clarinha (fundo das condições nos cenários)."""
    from matplotlib.colors import to_hex, to_rgb
    r, g, b = to_rgb(cor)
    return to_hex((1 - quanto + quanto * r, 1 - quanto + quanto * g, 1 - quanto + quanto * b))


# ---------------------------------------------------------------- montagem

@dataclass
class Montagem:
    cabe: bool
    caixas: list[Caixa] = field(default_factory=list)
    curvas: list[tuple] = field(default_factory=list)      # (x0, y0, x1, y1, cor)
    setas: list[tuple] = field(default_factory=list)       # (x0, y0, x1, y1, cor)


def _largura_raiz(texto: str, base: float, maximo: float, pt: float, w) -> float:
    """A caixa do centro cresce até caber a maior palavra (sem "invioláv-el")."""
    px = pt * PX_POR_PT
    maior = max((w(p, pt + 2, True) for p in texto.split()), default=0.0)
    return min(max(base, maior + 1.5 * px + 6), maximo)


def _espalhar(alturas: list[float], espaco: float, minimo: float) -> float:
    """Espaço entre caixas: o mínimo, ou mais se sobrar lugar (até 3x)."""
    if len(alturas) < 2:
        return minimo
    livre = espaco - sum(alturas)
    return max(minimo, min(livre / (len(alturas) + 1), 3 * minimo))


def _mapa(d: Diagrama, ramos, x0, x1, y0, y1, pt, w) -> Montagem:
    A = x1 - x0
    R = _largura_raiz(d.centro, min(max(0.2 * A, 120.0), 180.0), 0.3 * A, pt, w)
    G = max(34.0, 0.07 * A)
    C = (A - R - 2 * G) / 2
    raiz = _caixa(d.centro, [], R, pt, w, cor=TITULO, raiz=True, fundo=TINTA)
    k = (len(ramos) + 1) // 2 if len(ramos) > 1 else 0      # à esquerda; o resto à direita
    lados = [(ramos[:k], -1, 0), (ramos[k:], 1, k)]
    minimo = 0.9 * pt * PX_POR_PT
    colunas = []
    for grupo, lado, ini in lados:
        caixas = []
        for i, (t, dets) in enumerate(grupo):
            cor, numero = CORES[(ini + i) % len(CORES)], str(ini + i + 1)
            c = _caixa(t, dets, C, pt, w, cor=cor, numero=numero)
            if not dets and len(c.cabeca) == 1:     # só o nome: a caixa abraça o texto
                px = pt * PX_POR_PT
                justa = w(c.cabeca[0], pt + 0.5, True) + 1.5 * px + 1.35 * px + 6 + 8
                c = _caixa(t, dets, min(C, max(justa, 0.45 * C)), pt, w, cor=cor, numero=numero)
            caixas.append(c)
        colunas.append((caixas, lado))
    espaco = y1 - y0
    precisa = max([raiz.h] + [sum(c.h for c in cs) + minimo * (len(cs) - 1) for cs, _ in colunas])
    m = Montagem(precisa <= espaco)
    cy = (y0 + y1) / 2
    raiz.x, raiz.y = x0 + (A - R) / 2, cy - raiz.h / 2
    m.caixas.append(raiz)
    for caixas, lado in colunas:
        if not caixas:
            continue
        entre = _espalhar([c.h for c in caixas], espaco, minimo)
        topo = cy + (sum(c.h for c in caixas) + entre * (len(caixas) - 1)) / 2
        for c in caixas:
            c.x, c.y = (x0 + C - c.w if lado < 0 else x1 - C), topo - c.h
            topo -= c.h + entre
            folga = max(raiz.h / 2 - 8, 0)
            ys = cy + max(-folga, min(folga, (c.meio_y - cy) * 0.3))
            xs = raiz.x if lado < 0 else raiz.x + R
            xe = c.x + c.w if lado < 0 else c.x
            m.curvas.append((xs, ys, xe, c.meio_y, c.cor))
            m.caixas.append(c)
    return m


def _cenarios(d: Diagrama, ramos, x0, x1, y0, y1, pt, w) -> Montagem:
    A = x1 - x0
    R = _largura_raiz(d.centro, min(max(0.19 * A, 110.0), 170.0), 0.28 * A, pt, w)
    G1, G2 = max(30.0, 0.055 * A), max(30.0, 0.05 * A)
    resto = A - R - G1 - G2
    C1 = 0.42 * resto
    C2 = resto - C1
    raiz = _caixa(d.centro, [], R, pt, w, cor=TITULO, raiz=True, fundo=TINTA)
    linhas = []
    for i, (t, dets) in enumerate(ramos):
        cor = CORES[i % len(CORES)]
        if dets:
            cond = _caixa(t, [], C1, pt, w, cor=cor, numero=str(i + 1), fundo=_tom(cor), cor_cabeca=TINTA)
            cons = _caixa("", dets, C2, pt, w, cor=cor)
        else:
            cond = _caixa(t, [], C1 + G2 + C2, pt, w, cor=cor, numero=str(i + 1), fundo=_tom(cor),
                          cor_cabeca=TINTA)
            cons = None
        linhas.append((cond, cons))
    minimo = 0.8 * pt * PX_POR_PT
    alturas = [max(c.h, k.h if k else 0) for c, k in linhas]
    espaco = y1 - y0
    m = Montagem(max(raiz.h, sum(alturas) + minimo * (len(alturas) - 1)) <= espaco)
    cy = (y0 + y1) / 2
    raiz.x, raiz.y = x0, cy - raiz.h / 2
    m.caixas.append(raiz)
    entre = _espalhar(alturas, espaco, minimo)
    topo = cy + (sum(alturas) + entre * (len(alturas) - 1)) / 2
    for (cond, cons), h in zip(linhas, alturas):
        meio = topo - h / 2
        cond.x, cond.y = x0 + R + G1, meio - cond.h / 2
        folga = max(raiz.h / 2 - 8, 0)
        m.curvas.append((x0 + R, cy + max(-folga, min(folga, (meio - cy) * 0.3)), cond.x, meio, cond.cor))
        m.caixas.append(cond)
        if cons is not None:
            cons.x, cons.y = x1 - C2, meio - cons.h / 2
            m.setas.append((cond.x + C1 + 3, meio, cons.x - 3, meio, cond.cor))
            m.caixas.append(cons)
        topo -= h + entre
    return m


def _fluxo(d: Diagrama, ramos, x0, x1, y0, y1, pt, w) -> Montagem:
    A = x1 - x0
    L = min(A, 640.0)
    xs = x0 + (A - L) / 2
    caixas = []
    if d.centro and _sem_acento(d.centro) not in _sem_acento(d.titulo or ""):
        caixas.append(_caixa(d.centro, [], min(L, 380.0), pt, w, cor=TITULO, raiz=True, fundo=TINTA))
    for i, (t, dets) in enumerate(ramos):
        cor = TITULO if i == len(ramos) - 1 and len(ramos) > 2 else COR_FLUXO
        caixas.append(_caixa(t, dets, L, pt, w, cor=cor, numero=str(i + 1)))
    seta = 0.9 * pt * PX_POR_PT + 10
    precisa = sum(c.h for c in caixas) + seta * (len(caixas) - 1)
    m = Montagem(precisa <= y1 - y0)
    topo = (y0 + y1) / 2 + precisa / 2
    anterior = None
    for c in caixas:
        c.x, c.y = xs + (L - c.w) / 2, topo - c.h
        if anterior is not None:
            meio_x = xs + L / 2
            m.setas.append((meio_x, anterior.y - 2, meio_x, topo + 2, COR_FLUXO))
        m.caixas.append(c)
        anterior = c
        topo -= c.h + seta
    return m


_MONTAR = {"mapa": _mapa, "cenarios": _cenarios, "fluxo": _fluxo}


def _podar(ramos: list[tuple[str, list[str]]]) -> bool:
    """Não coube nem com a menor letra: tira o último detalhe do ramo mais cheio."""
    cheio = max(range(len(ramos)), key=lambda i: (len([d for d in ramos[i][1] if d != "…"]), i),
                default=None)
    if cheio is None:
        return False
    t, dets = ramos[cheio]
    reais = [d for d in dets if d != "…"]
    if reais:
        ramos[cheio] = (t, reais[:-1] + ["…"])
        return True
    if len(ramos) > 1:
        ramos.pop()
        return True
    return False


def montar(d: Diagrama, largura: int, altura: int, w) -> tuple[tuple | None, list[str], Montagem]:
    """(título, linhas da nota, montagem) — tudo posicionado em pixels."""
    x0, x1, y0, y1 = MARGEM, largura - MARGEM, MARGEM, altura - MARGEM
    titulo = None
    if d.titulo:
        fs, linhas = _titulo(d.titulo, largura, 1.0, lambda s, pt: w(s, pt, True))
        titulo = (fs, linhas)
        y1 -= _altura_titulo(fs, len(linhas)) + 18
    nota = _quebrar(d.nota, x1 - x0, NOTA_PT, False, w)[:2] if d.nota else []
    if nota:
        y0 += len(nota) * NOTA_PT * PX_POR_PT * 1.3 + 12
    ramos = [(r.texto, _detalhes(r)) for r in d.ramos]
    fazer = _MONTAR[d.tipo]
    melhor = None
    for pt in TAMANHOS:                 # a maior letra que cabe sem cortar palavra com hífen
        w.hifens = 0
        m = fazer(d, ramos, x0, x1, y0, y1, pt, w)
        if m.cabe and not w.hifens:
            melhor = m
            break
        if m.cabe and melhor is None:
            melhor = m
    m = melhor or m
    while not m.cabe and _podar(ramos):
        m = fazer(d, ramos, x0, x1, y0, y1, TAMANHOS[-1], w)
    return titulo, nota, m


# ---------------------------------------------------------------- desenho

def _tinta(s: str) -> str:
    return s.replace("$", r"\$")        # "R$ 5" não pode virar fórmula


def _pintar(ax, c: Caixa, w) -> None:
    from matplotlib.patches import Circle, FancyBboxPatch

    px = c.pt * PX_POR_PT
    folga_x, folga_y, lh = 0.75 * px, 0.6 * px, 1.3 * px
    pt_cabeca = c.pt + 2 if c.raiz else c.pt + 0.5
    ax.add_patch(FancyBboxPatch((c.x, c.y), c.w, c.h, zorder=3,
                                boxstyle=f"round,pad=0,rounding_size={min(10.0, c.h / 4):.1f}",
                                fc=c.fundo, ec=c.cor, lw=2.6 if c.raiz else 2.0))
    topo = c.y + c.h - folga_y
    x_texto = c.x + folga_x
    if c.numero:
        d = 1.35 * px
        ax.add_patch(Circle((x_texto + d / 2, topo - d / 2), d / 2, fc=c.cor, ec="none", zorder=4))
        ax.text(x_texto + d / 2, topo - d / 2, c.numero, ha="center", va="center", color=BRANCO,
                fontproperties=w.fonte(c.pt - 1.5, True), zorder=5)
        x_texto += d + 6
    passo_cabeca = lh * (pt_cabeca / c.pt)
    for k, linha in enumerate(c.cabeca):
        x, ha = ((c.x + c.w / 2, "center") if c.raiz else (x_texto, "left"))
        ax.text(x, topo - k * passo_cabeca, _tinta(linha), ha=ha, va="top", color=c.cor_cabeca,
                fontproperties=w.fonte(pt_cabeca, True), zorder=5)
    y = topo - len(c.cabeca) * passo_cabeca - (0.35 * lh if c.cabeca else 0)
    marcar = len(c.corpo) > 1
    for linhas in c.corpo:
        neto = linhas[0].startswith("– ")          # detalhe do detalhe: só o traço, sem bolinha
        if marcar and not neto:
            ax.text(c.x + folga_x, y, "•", va="top", color=c.cor,
                    fontproperties=w.fonte(c.pt, True), zorder=5)
        for k, linha in enumerate(linhas):
            ax.text(c.x + folga_x + (0.95 * px if marcar else 0), y - k * lh, _tinta(linha),
                    va="top", color=TINTA, fontproperties=w.fonte(c.pt), zorder=5)
        y -= len(linhas) * lh + 0.2 * lh


def desenhar(d: Diagrama, largura: int = 760, altura: int = 640) -> bytes:
    """Imagem PNG do desenho, do tamanho do quadro."""
    import matplotlib
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.patches import FancyArrowPatch, PathPatch
    from matplotlib.path import Path

    with _trava, matplotlib.rc_context({"font.family": "DejaVu Sans"}):
        fig = Figure(figsize=(largura / 100, altura / 100), dpi=100, facecolor=PAPEL)
        renderer = FigureCanvasAgg(fig).get_renderer()
        w = _medidor(renderer)
        ax = fig.add_axes((0, 0, 1, 1))
        ax.set_xlim(0, largura)
        ax.set_ylim(0, altura)
        ax.axis("off")
        titulo, nota, m = montar(d, largura, altura, w)

        if titulo:
            fs, linhas = titulo
            passo = fs * PX_POR_PT * 1.2
            for k, linha in enumerate(linhas):
                ax.text(MARGEM, altura - MARGEM - k * passo, _tinta(linha), va="top", color=TITULO,
                        fontproperties=w.fonte(fs, True))
            yl = altura - MARGEM - (len(linhas) - 1) * passo - fs * PX_POR_PT * 1.04
            ax.plot([MARGEM, largura - MARGEM], [yl, yl], color=TITULO, alpha=0.35, linewidth=1.2)

        for x0, y0, x1, y1, cor in m.curvas:
            dx = (x1 - x0) * 0.55
            caminho = Path([(x0, y0), (x0 + dx, y0), (x1 - dx, y1), (x1, y1)],
                           [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4])
            ax.add_patch(PathPatch(caminho, fc="none", ec=cor, lw=2.6, alpha=0.9,
                                   capstyle="round", zorder=2))
        for x0, y0, x1, y1, cor in m.setas:
            ax.add_patch(FancyArrowPatch((x0, y0), (x1, y1), arrowstyle="-|>", mutation_scale=16,
                                         color=cor, lw=2.2, shrinkA=0, shrinkB=0, zorder=2))
        for c in m.caixas:
            _pintar(ax, c, w)

        for k, linha in enumerate(nota):
            ax.text(MARGEM, MARGEM + (len(nota) - 1 - k) * NOTA_PT * PX_POR_PT * 1.3, _tinta(linha),
                    va="bottom", color=COR_NOTA, fontproperties=w.fonte(NOTA_PT))

        buf = io.BytesIO()
        fig.savefig(buf, format="png", facecolor=PAPEL)
    return buf.getvalue()
