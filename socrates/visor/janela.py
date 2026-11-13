"""Janela do visor, estilo HUD do Jarvis, em laranja, com quadro branco ao lado.

Feito com Tkinter, que já vem com o Python do Windows: nada a instalar.
Os desenhos são criados uma vez e só mudam de posição e cor a cada quadro,
para gastar pouca CPU.

  dormindo  apagado, girando devagar, "respira"
  atento    aceso, esperando você falar (não precisa dizer o nome)
  ouvindo   as barras seguem a SUA voz
  pensando  os anéis giram rápido
  falando   o núcleo e as barras pulsam com a voz DELE

Quando o Sócrates escreve no quadro, a janela se alarga e o quadro aparece à direita.
"""

from __future__ import annotations

import base64
import math
import time
import tkinter as tk
from tkinter import font as tkfont

from . import cores
from .painel import Painel

FUNDO = "#05070a"
LARANJA = "#ff8a1c"
BRILHO = "#ffd9a0"
QPS = 30                     # quadros por segundo

# Medidas na escala 1 (a janela inteira multiplica por `escala`)
BASE_LARGURA, BASE_ALTURA = 440, 540
N_MARCAS = 72
N_BARRAS = 64

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


def tamanho_barra(i: int, t: float, nivel: float, maximo: float = 40) -> float:
    """Comprimento da barra i: varia em volta do círculo, como um espectro."""
    onda = (0.55 + 0.25 * math.sin(i * 0.83 + t * 7.0)
            + 0.20 * math.sin(i * 2.31 - t * 11.0))
    return 2.0 + nivel * maximo * onda


def medidas(escala: float, largura_tela: int) -> dict:
    """Tamanho do HUD e do quadro, cabendo na tela (ex.: notebook 1366 px)."""
    hud_l, hud_a = int(BASE_LARGURA * escala), int(BASE_ALTURA * escala)
    quadro_l = int(hud_a * 1.18)
    sobra = largura_tela - hud_l - 40
    quadro_l = max(420, min(quadro_l, sobra))
    return {"hud_l": hud_l, "hud_a": hud_a, "quadro_l": quadro_l,
            "quadro_img": (quadro_l - 32, hud_a - 66)}


class Visor:
    def __init__(self, raiz: tk.Tk, painel: Painel, nome: str = "Sócrates",
                 sempre_no_topo: bool = False, escala: float = 1.25):
        self.raiz = raiz
        self.painel = painel
        self.nome = nome
        self.nivel = 0.0
        self.t0 = time.monotonic()
        self.e = escala
        self.m = medidas(escala, raiz.winfo_screenwidth())
        self.cx, self.cy = self.m["hud_l"] // 2, int(228 * escala)
        self._versao_quadro = -1
        self._cor_nome = None
        self.laranja, self.brilho = cores.resolver(painel.cor)
        self._foto = None
        self.quadro_visivel = False

        painel.tem_visor = True
        painel.quadro_tamanho = self.m["quadro_img"]

        raiz.title(nome)
        raiz.configure(bg=FUNDO)
        raiz.geometry(f"{self.m['hud_l']}x{self.m['hud_a']}")
        raiz.resizable(False, False)
        raiz.attributes("-topmost", sempre_no_topo)
        raiz.protocol("WM_DELETE_WINDOW", self.fechar)
        raiz.bind("<space>", self._interromper)        # cala o Sócrates no meio da fala
        raiz.bind("<Escape>", self._interromper)

        largura_max = self.m["hud_l"] + self.m["quadro_l"]
        self.c = tk.Canvas(raiz, width=largura_max, height=self.m["hud_a"], bg=FUNDO,
                           highlightthickness=0)
        self.c.place(x=0, y=0)
        familias = set(tkfont.families())
        fonte = next((f for f in ("Segoe UI", "Bahnschrift", "DejaVu Sans") if f in familias),
                     "TkDefaultFont")
        self._criar(fonte)
        self.c.bind("<Button-1>", self._interromper)

    def _interromper(self, _evento=None) -> None:
        if self.painel.interromper and self.painel.falando():
            self.painel.interromper()

    # ---------- geometria ----------
    def _polar(self, r: float, ang: float) -> tuple[float, float]:
        a = math.radians(ang)
        return self.cx + r * self.e * math.cos(a), self.cy - r * self.e * math.sin(a)

    def _caixa(self, r: float) -> tuple[float, float, float, float]:
        r *= self.e
        return self.cx - r, self.cy - r, self.cx + r, self.cy + r

    # ---------- criação (uma vez) ----------
    def _criar(self, fonte: str) -> None:
        c, e = self.c, self.e
        self.marcas = [c.create_line(0, 0, 0, 0, width=max(2, round(2 * e))) for _ in range(N_MARCAS)]
        self.circulo_fino = c.create_oval(*self._caixa(174), width=1)
        self.arcos = [c.create_arc(*self._caixa(158), style="arc", width=round(7 * e), extent=52)
                      for _ in range(4)]
        self.arcos_internos = [c.create_arc(*self._caixa(132), style="arc", width=max(2, round(2 * e)),
                                            extent=78) for _ in range(3)]
        self.barras = [c.create_line(0, 0, 0, 0, width=round(3 * e), capstyle="round")
                       for _ in range(N_BARRAS)]
        self.brilhos = [c.create_oval(0, 0, 0, 0, width=0) for _ in range(4)]
        self.anel_nucleo = c.create_oval(0, 0, 0, 0, width=2)
        self.nucleo = c.create_oval(0, 0, 0, 0, width=0)
        self.centro = c.create_oval(0, 0, 0, 0, width=0)

        letras = "  ".join(self.nome.upper())
        self.titulo = c.create_text(self.cx, 448 * e, text=letras, font=(fonte, round(15 * e), "bold"))
        self.status = c.create_text(self.cx, 478 * e, text="", font=(fonte, round(11 * e)))
        self.fala = c.create_text(self.cx, 508 * e, text="", font=(fonte, round(10 * e), "italic"),
                                  width=self.m["hud_l"] - 40)
        # autoestudo: no canto de cima, pequeno (o anel não chega lá)
        self.aprendendo = c.create_text(
            12 * e, 10 * e, text="", anchor="nw", font=(fonte, round(8 * e)), width=round(150 * e))

        # Quadro (escondido até ter conteúdo)
        x0 = self.m["hud_l"]
        self.moldura = c.create_rectangle(x0 + 6, 14, x0 + self.m["quadro_l"] - 8,
                                          self.m["hud_a"] - 14, outline=misturar(LARANJA, FUNDO, 0.5),
                                          width=2, state="hidden")
        self.rotulo_quadro = c.create_text(x0 + 20, 30, text="Q U A D R O", anchor="w",
                                           font=(fonte, round(9 * e), "bold"),
                                           fill=misturar(LARANJA, FUNDO, 0.7), state="hidden")
        self.imagem = c.create_image(x0 + 14, 46, anchor="nw", state="hidden")

    # ---------- quadro ----------
    def _atualizar_quadro(self) -> None:
        p = self.painel
        if p.quadro_versao == self._versao_quadro:
            return
        self._versao_quadro = p.quadro_versao
        png = p.quadro_png
        if png is None:
            self._mostrar_quadro(False)
            return
        self._foto = tk.PhotoImage(data=base64.b64encode(png).decode())   # PNG direto no Tk
        self.c.itemconfigure(self.imagem, image=self._foto)
        self._mostrar_quadro(True)

    def _mostrar_quadro(self, mostrar: bool) -> None:
        if mostrar == self.quadro_visivel:
            return
        self.quadro_visivel = mostrar
        estado = "normal" if mostrar else "hidden"
        for item in (self.moldura, self.rotulo_quadro, self.imagem):
            self.c.itemconfigure(item, state=estado)
        largura = self.m["hud_l"] + (self.m["quadro_l"] if mostrar else 0)
        x, y = self.raiz.winfo_x(), self.raiz.winfo_y()
        tela = self.raiz.winfo_screenwidth()
        if x + largura > tela:                     # não deixa o quadro sair da tela
            x = max(0, tela - largura - 8)
        self.raiz.geometry(f"{largura}x{self.m['hud_a']}+{x}+{y}")

    # ---------- cada quadro de animação ----------
    def _quadro(self) -> None:
        if self.painel.encerrado:
            self.raiz.destroy()
            return
        agora = time.monotonic()
        t = agora - self.t0
        p = self.painel
        visual = p.visual(agora)
        luz = INTENSIDADE[visual]
        if p.cor != self._cor_nome:
            self._cor_nome = p.cor
            self.laranja, self.brilho = cores.resolver(p.cor)
            self.c.itemconfigure(self.moldura, outline=misturar(self.laranja, FUNDO, 0.5))
            self.c.itemconfigure(self.rotulo_quadro, fill=misturar(self.laranja, FUNDO, 0.7))
        self._atualizar_quadro()

        alvo = nivel_alvo(visual, p, t, agora)
        sobe = 0.55 if alvo > self.nivel else 0.18   # sobe rápido, desce suave
        self.nivel += (alvo - self.nivel) * sobe
        nivel = self.nivel
        respira = 0.5 + 0.5 * math.sin(t * 1.6) if visual == "dormindo" else 1.0
        giro = t * GIRO[visual]
        c = self.c

        cor_marca = misturar(self.laranja, FUNDO, 0.30 * luz)
        cor_marca_forte = misturar(self.laranja, FUNDO, 0.65 * luz)
        for i, item in enumerate(self.marcas):
            ang = i * 360 / N_MARCAS + giro * 0.25
            longa = i % 6 == 0
            x0, y0 = self._polar(190 - (11 if longa else 5), ang)
            x1, y1 = self._polar(190, ang)
            c.coords(item, x0, y0, x1, y1)
            c.itemconfigure(item, fill=cor_marca_forte if longa else cor_marca)

        c.itemconfigure(self.circulo_fino, outline=misturar(self.laranja, FUNDO, 0.22 * luz))

        cor_arco = misturar(self.laranja, FUNDO, (0.55 + 0.35 * nivel) * luz * (0.7 + 0.3 * respira))
        for i, item in enumerate(self.arcos):
            c.itemconfigure(item, start=(i * 90 + giro) % 360, outline=cor_arco)
        cor_interna = misturar(self.brilho, FUNDO, 0.45 * luz)
        for i, item in enumerate(self.arcos_internos):
            c.itemconfigure(item, start=(i * 120 - giro * 1.6) % 360, outline=cor_interna)

        for i, item in enumerate(self.barras):
            ang = i * 360 / N_BARRAS + 90
            tam = tamanho_barra(i, t, nivel)
            x0, y0 = self._polar(84, ang)
            x1, y1 = self._polar(84 + tam, ang)
            c.coords(item, x0, y0, x1, y1)
            forca = 0.35 + 0.65 * min(1.0, tam / 40)
            c.itemconfigure(item, fill=misturar(self.laranja, FUNDO, forca * luz))

        r = 50 + 16 * nivel + 2 * respira
        for i, item in enumerate(self.brilhos):     # halo: círculos cada vez mais fracos
            c.coords(item, *self._caixa(r + 26 - i * 7))
            c.itemconfigure(item, fill=misturar(self.laranja, FUNDO,
                                                (0.07 + i * 0.06) * luz * (0.6 + 0.4 * nivel)))
        c.coords(self.anel_nucleo, *self._caixa(r + 6))
        c.itemconfigure(self.anel_nucleo, outline=misturar(self.brilho, FUNDO, 0.6 * luz))
        c.coords(self.nucleo, *self._caixa(r))
        c.itemconfigure(self.nucleo, fill=misturar(self.laranja, FUNDO, (0.75 + 0.25 * nivel) * luz))
        c.coords(self.centro, *self._caixa(r * (0.42 + 0.18 * nivel)))
        c.itemconfigure(self.centro, fill=misturar(self.brilho, FUNDO, (0.7 + 0.3 * nivel) * luz))

        c.itemconfigure(self.titulo, fill=misturar(self.laranja, FUNDO, 0.85 * max(luz, 0.5)))
        c.itemconfigure(self.status, text=LEGENDA[visual], fill=misturar(self.brilho, FUNDO, 0.55))
        aprendendo = p.aprendendo if len(p.aprendendo) <= 80 else p.aprendendo[:77] + "..."
        c.itemconfigure(self.aprendendo, text=f"◆ {aprendendo}" if aprendendo else "",
                        fill=misturar(self.brilho, FUNDO, 0.4))
        legenda = p.legenda if len(p.legenda) <= 90 else p.legenda[:87] + "..."
        c.itemconfigure(self.fala, text=f"“{legenda}”" if legenda else "",
                        fill=misturar(self.brilho, FUNDO, 0.35))

        self.raiz.after(int(1000 / QPS), self._quadro)

    def fechar(self) -> None:
        self.painel.fechou = True
        self.painel.tem_visor = False
        if self.painel.ao_fechar:
            self.painel.ao_fechar()
        self.raiz.destroy()

    def rodar(self) -> None:
        self._quadro()
        try:
            self.raiz.mainloop()
        except KeyboardInterrupt:
            self.fechar()


def abrir(painel: Painel, nome: str = "Sócrates", sempre_no_topo: bool = False,
          escala: float = 1.25) -> None:
    """Abre o visor e só volta quando ele fechar. Precisa rodar na thread principal."""
    try:   # nitidez em telas com escala (125%, 150%) no Windows
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    Visor(tk.Tk(), painel, nome, sempre_no_topo, escala).rodar()
