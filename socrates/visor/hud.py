"""O visor novo, estilo HUD do Jarvis: uma página no Edge em modo aplicativo (sem barra de
endereço) que conversa com um servidorzinho local, o qual lê o Painel.

    Sócrates (asyncio) --escreve--> Painel <--lê-- servidor (thread) <--fetch-- página (Edge)

Nada a instalar: o servidor é o http.server do Python e o Edge já vem no Windows. Se o Edge
não abrir (ou a página não carregar), main.py volta para o visor clássico (Tkinter).

O quadro de texto (lei, aula, lista) a página desenha com HTML; o mapa mental, as fórmulas e
os gráficos chegam como imagem, feita pelo quadro.py no tema HUD, no tamanho exato do painel.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import cores
from .painel import Painel
from .tamanho import argumentos_de_abertura

log = logging.getLogger("socrates.hud")

PAGINA = Path(__file__).with_name("hud") / "index.html"
PORTA = 47265                 # fixa: o Edge lembra o tamanho e a posição da janela
ESPERA_CONTATO = 10.0         # a página tem que chamar o servidor em até tantos segundos
ESPERA_FECHAR = 4.0           # a página avisou que fechou: se não voltar (F5), encerra
_FORMULA = re.compile(r"(?<!\\)\$[^$\n]+(?<!\\)\$")


# ---------------------------------------------------------------- o que a página lê

def _chamar(funcao, padrao):
    if funcao is None:
        return padrao
    try:
        return funcao()
    except Exception:            # o visor nunca derruba nada
        log.debug("visor: falhou ao ler um dado", exc_info=True)
        return padrao


def nivel(painel: Painel, visual: str, agora: float) -> float:
    """Quanto o núcleo pulsa agora (0 a 1): a voz dele, ou a sua no microfone."""
    if visual == "falando":
        return painel.nivel_voz(agora)
    if visual == "ouvindo":
        return painel.nivel_mic
    if visual == "atento":
        return painel.nivel_mic * 0.6
    return painel.nivel_mic * 0.25


def estado(painel: Painel) -> dict:
    agora = time.monotonic()
    visual = painel.visual(agora)
    principal, brilho = cores.resolver(painel.cor)
    return {
        "visual": visual,
        "nivel": round(nivel(painel, visual, agora), 3),
        "cor": principal, "brilho": brilho,
        "legenda": painel.legenda,
        "aprendendo": painel.aprendendo,
        "quadro": painel.quadro_versao,
        "registro": [list(r) for r in list(painel.registro)],   # list() primeiro: a outra thread mexe
        "registro_versao": painel.registro_versao,
        "cerebro": _chamar(painel.qual_cerebro, ""),
        "resposta": painel.resposta_seg,
        "inicio": painel.inicio,
        "falas": painel.falas,
        "estudo": _chamar(painel.info_estudo, None),
        "timer": _chamar(painel.info_timer, None),
        "noticias": list(painel.noticias or []),
        "encerrado": painel.encerrado,
    }


def descrever_quadro(fonte: str) -> dict:
    """Texto comum vira HTML na página; desenho, fórmula e gráfico vêm como imagem."""
    from .diagrama import ler
    from .quadro import interpretar

    if ler(fonte) is not None:
        return {"tipo": "imagem"}
    itens = interpretar(fonte)
    if any(i.tipo in ("formula", "grafico") or _FORMULA.search(i.conteudo) for i in itens):
        return {"tipo": "imagem"}
    return {"tipo": "texto",
            "itens": [{"tipo": i.tipo, "texto": i.conteudo.replace("\\$", "$")} for i in itens]}


def quadro(painel: Painel) -> dict:
    fonte, versao = painel.quadro_fonte, painel.quadro_versao
    if fonte:
        return {"versao": versao, **descrever_quadro(fonte)}
    if painel.quadro_png:
        return {"versao": versao, "tipo": "imagem"}
    return {"versao": versao, "tipo": "vazio"}


# ---------------------------------------------------------------- dados do estudo

def rotulo_cerebro(m) -> str:
    """"groq_qwen" + "qwen/qwen3.8-27b" -> "GROQ · QWEN3.8-27B"."""
    if m is None:
        return ""
    provedor = str(getattr(m, "nome", "") or "").split("_")[0].upper()
    modelo = str(getattr(m, "modelo", "") or "").split("/")[-1].replace("-latest", "").upper()
    return " · ".join(p for p in (provedor, modelo) if p)


_revisoes: dict = {"quando": 0.0, "n": None}


def info_estudo(tutor) -> dict:
    """A aula ou o treino em andamento (para o cabeçalho e o painel) e as revisões do dia."""
    d = {"modo": "", "titulo": "", "progresso": "", "acertos": "", "revisoes": None}
    aula, sessao = getattr(tutor, "aula", None), getattr(tutor, "sessao", None)
    if aula is not None:
        d.update(modo="aula", titulo=aula.topico.titulo, progresso=f"{aula.k + 1}/{aula.n}")
    elif sessao is not None:
        total = len(sessao.itens)
        d.update(modo="revisao" if sessao.modo == "revisao" else "treino", titulo=sessao.titulo,
                 progresso=f"{min(sessao.pos + 1, total)}/{total}")
        if sessao.registros:
            certas = sum(1 for r in sessao.registros if r.ok)
            d["acertos"] = f"{certas}/{len(sessao.registros)}"
    agora = time.monotonic()
    if agora - _revisoes["quando"] > 60:          # conta no máximo uma vez por minuto
        _revisoes["quando"] = agora
        try:
            _revisoes["n"] = len(tutor.caderno.vencidos())
        except Exception:
            pass
    d["revisoes"] = _revisoes["n"]
    return d


def info_timer() -> dict | None:
    from ..ferramentas import computador

    t = computador.TIMER
    resta = t.restante()
    if resta is None:
        return None
    return {"resta": round(resta), "total": round(getattr(t, "total", 0) or 0),
            "motivo": getattr(t, "motivo", "") or ""}


# ---------------------------------------------------------------- servidor

class _Pedido(BaseHTTPRequestHandler):
    server: "_Servidor"

    def log_message(self, *args) -> None:       # nada de linhas no terminal a cada pedido
        pass

    def _enviar(self, codigo: int, tipo: str = "", corpo: bytes = b"") -> None:
        self.send_response(codigo)
        if tipo:
            self.send_header("Content-Type", tipo)
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if corpo:
            self.wfile.write(corpo)

    def _json(self, dados: dict) -> None:
        self._enviar(200, "application/json; charset=utf-8",
                     json.dumps(dados, ensure_ascii=False).encode("utf-8"))

    def do_GET(self) -> None:
        hud = self.server.hud
        url = urlparse(self.path)
        try:
            if url.path in ("/", "/index.html"):
                self._enviar(200, "text/html; charset=utf-8", hud.pagina())
            elif url.path == "/estado":
                hud.viu()
                self._json(estado(hud.painel))
            elif url.path == "/quadro":
                self._json(quadro(hud.painel))
            elif url.path == "/quadro.png":
                q = parse_qs(url.query)
                pegar = lambda k, p: float((q.get(k) or [p])[0])   # noqa: E731
                self._enviar(200, "image/png", hud.imagem(pegar("w", 760), pegar("h", 600),
                                                          pegar("s", 1)))
            else:
                self._enviar(404, "text/plain; charset=utf-8", "não achei".encode())
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            log.exception("visor: erro em %s", url.path)
            try:
                self._enviar(500, "text/plain; charset=utf-8", b"erro")
            except OSError:
                pass

    def do_POST(self) -> None:
        hud = self.server.hud
        tamanho = int(self.headers.get("Content-Length") or 0)
        if tamanho:
            self.rfile.read(min(tamanho, 4096))
        caminho = urlparse(self.path).path
        if caminho == "/interromper":
            hud.interromper()
        elif caminho == "/fechou":
            hud.pagina_fechou()
        self._enviar(204)


class _Servidor(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    hud: "Hud"


class Hud:
    def __init__(self, painel: Painel, porta: int = PORTA):
        self.painel = painel
        try:
            self.servidor = _Servidor(("127.0.0.1", porta), _Pedido)
        except OSError:                          # porta ocupada (outro Sócrates aberto?)
            self.servidor = _Servidor(("127.0.0.1", 0), _Pedido)
        self.servidor.hud = self
        self.url = f"http://127.0.0.1:{self.servidor.server_address[1]}/"
        self.contato = 0.0                       # última vez que a página falou com a gente
        self._fechou_em: float | None = None
        self._encerrou = False
        self.navegador: subprocess.Popen | None = None
        self._cache: dict = {}
        self._trava = threading.Lock()
        self._contatou = threading.Event()

    # ---------- pedidos da página ----------
    def pagina(self) -> bytes:
        return PAGINA.read_bytes()

    def viu(self) -> None:
        self.contato = time.monotonic()
        self._fechou_em = None
        self._contatou.set()

    def interromper(self) -> None:
        if self.painel.interromper and self.painel.falando():
            self.painel.interromper()

    def pagina_fechou(self) -> None:
        self._fechou_em = time.monotonic()

    def imagem(self, largura: float, altura: float, escala: float) -> bytes:
        """O quadro como imagem, no tamanho do painel (2x em telas com zoom)."""
        from .quadro import HUD, renderizar

        largura = int(max(320, min(2400, largura)))
        altura = int(max(240, min(1600, altura)))
        escala = 2.0 if escala >= 1.5 else 1.0
        fonte, png = self.painel.quadro_fonte, self.painel.quadro_png
        chave = (self.painel.quadro_versao, largura, altura, escala)
        with self._trava:
            if chave in self._cache:
                return self._cache[chave]
        if fonte:
            dados = renderizar(fonte, largura, altura, HUD, escala)
        else:
            dados = png or b""
        with self._trava:
            if len(self._cache) > 6:
                self._cache.clear()
            self._cache[chave] = dados
        return dados

    # ---------- vida ----------
    def iniciar(self) -> None:
        threading.Thread(target=self.servidor.serve_forever, name="visor-hud", daemon=True).start()
        threading.Thread(target=self._vigiar, name="visor-vigia", daemon=True).start()

    def esperar_contato(self, segundos: float = ESPERA_CONTATO) -> bool:
        return self._contatou.wait(segundos)

    def _janela_fechou(self) -> bool:
        agora = time.monotonic()
        if self._fechou_em is not None and agora - self._fechou_em > ESPERA_FECHAR \
                and self.contato < self._fechou_em:
            return True                          # avisou que fechou e não voltou (não foi F5)
        morreu = self.navegador is not None and self.navegador.poll() is not None
        return morreu and agora - self.contato > ESPERA_FECHAR

    def _vigiar(self) -> None:
        """Você fechou a janela do visor: o Sócrates encerra, como no visor clássico."""
        while not self.painel.encerrado and not self._encerrou:
            time.sleep(0.5)
            if self._contatou.is_set() and self._janela_fechou():
                log.info("visor: a janela foi fechada")
                self.painel.fechou = True
                self.painel.tem_visor = False
                if self.painel.ao_fechar:
                    self.painel.ao_fechar()
                return

    def abrir_janela(self, largura: int = 1280, altura: int = 760, tamanho: str = "normal") -> bool:
        exe = achar_navegador()
        if exe is None:
            log.warning("visor: não achei o Edge nem o Chrome")
            return False
        perfil = pasta_do_perfil()
        try:
            janela = argumentos_de_abertura(tamanho, largura, altura)
        except Exception as e:                   # sem a medida da tela: abre no tamanho do config
            log.warning("visor: não medi a tela (%s)", e)
            janela = [f"--window-size={largura},{altura}"]
        try:
            perfil.mkdir(parents=True, exist_ok=True)
            self.navegador = subprocess.Popen(
                [exe, f"--app={self.url}", *janela,
                 f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
                 "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
                 "--disable-backgrounding-occluded-windows", "--disable-features=Translate"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            log.warning("visor: não consegui abrir %s (%s)", exe, e)
            return False
        return True

    def parar(self) -> None:
        self._encerrou = True
        if self.navegador is not None and self.navegador.poll() is None:
            time.sleep(0.6)                      # a página vê "encerrado" e mostra a despedida
            try:
                self.navegador.terminate()
            except OSError:
                pass
        try:
            self.servidor.shutdown()
            self.servidor.server_close()
        except OSError:
            pass


def achar_navegador() -> str | None:
    """Edge (vem no Windows) ou Chrome, para abrir a página como aplicativo."""
    for nome in ("msedge", "microsoft-edge", "microsoft-edge-stable", "chrome", "google-chrome",
                 "chromium", "chromium-browser"):
        achado = shutil.which(nome)
        if achado:
            return achado
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"),
                 os.environ.get("LOCALAPPDATA")):
        if not base:
            continue
        for resto in (r"Microsoft\Edge\Application\msedge.exe", r"Google\Chrome\Application\chrome.exe"):
            caminho = Path(base) / resto
            if caminho.exists():
                return str(caminho)
    return None


def pasta_do_perfil() -> Path:
    """Perfil só do visor (fora da pasta do Sócrates, para não sujar o git)."""
    base = os.environ.get("LOCALAPPDATA")
    return (Path(base) if base else Path.home() / ".socrates") / "Socrates" / "visor-edge"


def abrir(painel: Painel, largura: int = 1280, altura: int = 760, porta: int = PORTA,
          espera: float = ESPERA_CONTATO, tamanho: str = "normal") -> Hud | None:
    """Abre o visor novo. None = não deu (sem Edge, página não carregou): use o clássico."""
    try:
        hud = Hud(painel, porta)
    except OSError as e:
        log.warning("visor: servidor não subiu (%s)", e)
        return None
    hud.iniciar()
    if not hud.abrir_janela(largura, altura, tamanho):
        hud.parar()
        return None
    if not hud.esperar_contato(espera):
        log.warning("visor: a página não carregou em %.0f s", espera)
        hud.parar()
        return None
    painel.tem_visor = True
    painel.quadro_por_fonte = True
    return hud
