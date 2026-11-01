"""Janela do visor, estilo HUD do Jarvis, em laranja.

Feito com Tkinter, que já vem com o Python do Windows: nada a instalar.
Os desenhos são criados uma vez e só mudam de posição e cor a cada quadro,
para gastar pouca CPU.

  dormindo  apagado, girando devagar, "respira"
  atento    aceso, esperando você falar (não precisa dizer o nome)
  ouvindo   as barras seguem a SUA voz
  pensando  os anéis giram rápido
  falando   o núcleo e as barras pulsam com a voz DELE
"""

from __future__ import annotations

import math
import time
import tkinter as tk
from tkinter import font as tkfont

from .painel import Painel

FUNDO = "#05070a"
LARANJA = "#ff8a1c"
BRILHO = "#ffd9a0"

LARGURA, ALTURA = 440, 540
CX, CY = LARGURA // 2, 228
QPS = 30                     # quadros por segundo

N_MARCAS = 72
N_BARRAS = 64
R_MARCAS = 190
R_ANEL = 158
R_ANEL_INTERNO = 132
R_BARRAS = 84
BARRA_MAX = 40

INTENSIDADE = {"dormindo": 0.32, "atento": 0.8, "ouvindo": 0.95, "pensando": 0.85, "falando": 1.0}
GIRO = {"dormindo": 6, "atento": 18, "ouvindo": 24, "pensando": 140, "falando": 30}  # graus/s
LEGENDA = {
    "dormindo": 'Diga "Sócrates" para me chamar',
    "atento": "Pode falar",
    "ouvindo": "Ouvindo...",
    "pensando": "Pensando...",
    "falando": "",
}


def misturar(cor: str, fundo: str, f: float) -> str:
    """Cor entre o fundo (f=0) e a cor cheia (f=1)."""
    f = max(0.0, min(1.0, f))
    a = [int(cor[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(fundo[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(y + (x - y) * f):02x}" for x, y in zip(a, b))


def nivel_alvo(visual: str, painel: Painel, t: float, agora: float) -> float:
    """Quanto o visor deve pulsar agora (0 a 1)."""
    if visual == "falando":
        return painel.nivel_voz(agora)
    if visual == "ouvindo":
        return painel.nivel_mic
    if visual == "atento":
        return painel.nivel_mic * 0.6
    if visual == "pensando":
        return 0.18 + 0.12 * math.sin(t * 6)
    return painel.nivel_mic * 0.25


def tamanho_barra(i: int, t: float, nivel: float) -> float:
    """Comprimento da barra i: varia em volta do círculo, como um espectro."""
    onda = (0.55 + 0.25 * math.sin(i * 0.83 + t * 7.0)
            + 0.20 * math.sin(i * 2.31 - t * 11.0))
    return 2.0 + nivel * BARRA_MAX * onda


def _polar(r: float, ang_graus: float) -> tuple[float, float]:
    a = math.radians(ang_graus)
    return CX + r * math.cos(a), CY - r * math.sin(a)


def _caixa(r: float) -> tuple[float, float, float, float]:
    return CX - r, CY - r, CX + r, CY + r


class Visor:
    def __init__(self, raiz: tk.Tk, painel: Painel, nome: str = "Sócrates",
                 sempre_no_topo: bool = False):
        self.raiz = raiz
        self.painel = painel
        self.nome = nome
        self.nivel = 0.0
        self.t0 = time.monotonic()

        raiz.title(nome)
        raiz.configure(bg=FUNDO)
        raiz.geometry(f"{LARGURA}x{ALTURA}")
        raiz.resizable(False, False)
        raiz.attributes("-topmost", sempre_no_topo)
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)

        self.c = tk.Canvas(raiz, width=LARGURA, height=ALTURA, bg=FUNDO, highlightthickness=0)
        self.c.pack()
        familias = set(tkfont.families())
        fonte = next((f for f in ("Segoe UI", "Bahnschrift", "DejaVu Sans") if f in familias),
                     "TkDefaultFont")
        self._criar(fonte)

    # ---------- criação (uma vez) ----------
    def _criar(self, fonte: str) -> None:
        c = self.c
        self.marcas = [c.create_line(0, 0, 0, 0, width=2) for _ in range(N_MARCAS)]
        self.circulo_fino = c.create_oval(*_caixa(R_ANEL + 16), width=1)
        self.arcos = [c.create_arc(*_caixa(R_ANEL), style="arc", width=7, extent=52)
                      for _ in range(4)]
        self.arcos_internos = [c.create_arc(*_caixa(R_ANEL_INTERNO), style="arc", width=2,
                                            extent=78) for _ in range(3)]
        self.barras = [c.create_line(0, 0, 0, 0, width=3, capstyle="round")
                       for _ in range(N_BARRAS)]
        self.brilhos = [c.create_oval(0, 0, 0, 0, width=0) for _ in range(4)]
        self.anel_nucleo = c.create_oval(0, 0, 0, 0, width=2)
        self.nucleo = c.create_oval(0, 0, 0, 0, width=0)
        self.centro = c.create_oval(0, 0, 0, 0, width=0)

        letras = "  ".join(self.nome.upper())
        self.titulo = c.create_text(CX, 448, text=letras, font=(fonte, 15, "bold"))
        self.status = c.create_text(CX, 478, text="", font=(fonte, 11))
        self.fala = c.create_text(CX, 508, text="", font=(fonte, 10, "italic"),
                                  width=LARGURA - 40)

    # ---------- cada quadro ----------
    def _quadro(self) -> None:
        if self.painel.encerrado:
            self.raiz.destroy()
            return
        agora = time.monotonic()
        t = agora - self.t0
        p = self.painel
        visual = p.visual(agora)
        luz = INTENSIDADE[visual]

        alvo = nivel_alvo(visual, p, t, agora)
        sobe = 0.55 if alvo > self.nivel else 0.18   # sobe rápido, desce suave
        self.nivel += (alvo - self.nivel) * sobe
        nivel = self.nivel
        respira = 0.5 + 0.5 * math.sin(t * 1.6) if visual == "dormindo" else 1.0
        giro = t * GIRO[visual]
        c = self.c

        cor_marca = misturar(LARANJA, FUNDO, 0.30 * luz)
        cor_marca_forte = misturar(LARANJA, FUNDO, 0.65 * luz)
        for i, item in enumerate(self.marcas):
            ang = i * 360 / N_MARCAS + giro * 0.25
            longa = i % 6 == 0
            x0, y0 = _polar(R_MARCAS - (11 if longa else 5), ang)
            x1, y1 = _polar(R_MARCAS, ang)
            c.coords(item, x0, y0, x1, y1)
            c.itemconfigure(item, fill=cor_marca_forte if longa else cor_marca)

        c.itemconfigure(self.circulo_fino, outline=misturar(LARANJA, FUNDO, 0.22 * luz))

        cor_arco = misturar(LARANJA, FUNDO, (0.55 + 0.35 * nivel) * luz * (0.7 + 0.3 * respira))
        for i, item in enumerate(self.arcos):
            c.itemconfigure(item, start=(i * 90 + giro) % 360, outline=cor_arco)
        cor_interna = misturar(BRILHO, FUNDO, 0.45 * luz)
        for i, item in enumerate(self.arcos_internos):
            c.itemconfigure(item, start=(i * 120 - giro * 1.6) % 360, outline=cor_interna)

        for i, item in enumerate(self.barras):
            ang = i * 360 / N_BARRAS + 90
            tam = tamanho_barra(i, t, nivel)
            x0, y0 = _polar(R_BARRAS, ang)
            x1, y1 = _polar(R_BARRAS + tam, ang)
            c.coords(item, x0, y0, x1, y1)
            forca = 0.35 + 0.65 * min(1.0, tam / BARRA_MAX)
            c.itemconfigure(item, fill=misturar(LARANJA, FUNDO, forca * luz))

        r = 50 + 16 * nivel + 2 * respira
        for i, item in enumerate(self.brilhos):     # halo: círculos cada vez mais fracos
            rb = r + 26 - i * 7
            c.coords(item, *_caixa(rb))
            c.itemconfigure(item, fill=misturar(LARANJA, FUNDO, (0.07 + i * 0.06) * luz * (0.6 + 0.4 * nivel)))
        c.coords(self.anel_nucleo, *_caixa(r + 6))
        c.itemconfigure(self.anel_nucleo, outline=misturar(BRILHO, FUNDO, 0.6 * luz))
        c.coords(self.nucleo, *_caixa(r))
        c.itemconfigure(self.nucleo, fill=misturar(LARANJA, FUNDO, (0.75 + 0.25 * nivel) * luz))
        rc = r * (0.42 + 0.18 * nivel)
        c.coords(self.centro, *_caixa(rc))
        c.itemconfigure(self.centro, fill=misturar(BRILHO, FUNDO, (0.7 + 0.3 * nivel) * luz))

        c.itemconfigure(self.titulo, fill=misturar(LARANJA, FUNDO, 0.85 * max(luz, 0.5)))
        c.itemconfigure(self.status, text=LEGENDA[visual],
                        fill=misturar(BRILHO, FUNDO, 0.55))
        legenda = p.legenda if len(p.legenda) <= 90 else p.legenda[:87] + "..."
        c.itemconfigure(self.fala, text=f"“{legenda}”" if legenda else "",
                        fill=misturar(BRILHO, FUNDO, 0.35))

        self.raiz.after(int(1000 / QPS), self._quadro)

    def fechar(self) -> None:
        self.painel.fechou = True
        if self.painel.ao_fechar:
            self.painel.ao_fechar()
        self.raiz.destroy()

    def rodar(self) -> None:
        self._quadro()
        try:
            self.raiz.mainloop()
        except KeyboardInterrupt:
            self.fechar()


def abrir(painel: Painel, nome: str = "Sócrates", sempre_no_topo: bool = False) -> None:
    """Abre o visor e só volta quando ele fechar. Precisa rodar na thread principal."""
    try:   # nitidez em telas com escala (125%, 150%) no Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Visor(tk.Tk(), painel, nome, sempre_no_topo).rodar()
