"""O tamanho e o lugar da janela do visor, por voz.

  "Sócrates, coloca o seu visor grande na tela, no centro"   -> maximiza a janela
  "deixa o visor normal"                                      -> tamanho do config, no centro
  "visor pequeno"                                             -> 60% da tela, no centro

Em 26/11 ele respondia "não consigo mudar o tamanho ou a posição do visor". Agora usa a API
do Windows (user32) pelo ctypes: acha a janela do visor pelo título ("Sócrates": a do Edge ou
a do visor clássico) e muda o tamanho. A escolha fica guardada no config.local.yaml e o visor
já abre assim da próxima vez (no Edge, --start-maximized ou --window-position no centro).
"""

from __future__ import annotations

import logging
import sys
import unicodedata

log = logging.getLogger("socrates.visor")

TAMANHOS = ("grande", "normal", "pequeno")
TITULO = "Sócrates"
CLASSES = ("Chrome_WidgetWin_1", "TkTopLevel")     # janela do Edge/Chrome e a do Tkinter
PROPORCAO_PEQUENO = 0.6
MINIMO = (480, 320)

_SINONIMOS = {
    "grande": ("grande", "maior", "maxim", "tela cheia", "tela inteira", "tela toda", "inteiro",
               "cheio", "enorme", "gigante"),
    "pequeno": ("pequen", "menor", "minim", "reduz", "diminu"),
    "normal": ("normal", "padrao", "medio", "original", "volta", "de sempre", "centro", "centraliz",
               "meio"),
}


def _norm(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()


def nome_do_tamanho(texto: str) -> str | None:
    """ "grande", "maximizado", "tela cheia" -> "grande"; "no centro" -> "normal"."""
    t = _norm(texto).strip()
    for nome, pedacos in _SINONIMOS.items():
        if any(p in t for p in pedacos):
            return nome
    return None


def retangulo(tamanho: str, area: tuple[int, int, int, int], largura: int,
              altura: int) -> tuple[int, int, int, int]:
    """(x, y, largura, altura) da janela no centro da área de trabalho (sem a barra de tarefas)."""
    esquerda, topo, direita, baixo = area
    w_area, h_area = direita - esquerda, baixo - topo
    if tamanho == "pequeno":
        w, h = int(w_area * PROPORCAO_PEQUENO), int(h_area * PROPORCAO_PEQUENO)
    else:
        w, h = largura, altura
    w = max(min(MINIMO[0], w_area), min(w, w_area))
    h = max(min(MINIMO[1], h_area), min(h, h_area))
    return esquerda + (w_area - w) // 2, topo + (h_area - h) // 2, w, h


def achar(janelas: list[tuple[int, str, str]], titulo: str = TITULO) -> int | None:
    """A janela do visor entre as abertas: (hwnd, título, classe)."""
    for hwnd, nome, classe in janelas:
        if nome == titulo and classe in CLASSES:
            return hwnd
    for hwnd, nome, classe in janelas:           # o navegador pode pôr o nome dele depois
        if classe in CLASSES and nome.startswith(titulo + " - "):
            return hwnd
    return None


class Windows:
    """As poucas funções do user32 que o visor usa (nos testes entra uma falsa)."""

    SW_MAXIMIZE, SW_RESTORE = 3, 9
    SWP_NOZORDER, SWP_SHOWWINDOW = 0x0004, 0x0040
    MONITOR_DEFAULTTOPRIMARY, MONITOR_DEFAULTTONEAREST = 1, 2

    def __init__(self):
        import ctypes
        from ctypes import wintypes as wt

        self._ct, self._wt = ctypes, wt
        u = self._u = ctypes.WinDLL("user32", use_last_error=True)
        self._proc = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
        u.EnumWindows.argtypes = [self._proc, wt.LPARAM]
        u.IsWindowVisible.argtypes = [wt.HWND]
        u.GetWindowTextLengthW.argtypes = [wt.HWND]
        u.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
        u.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        u.SetWindowPos.argtypes = [wt.HWND, wt.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, wt.UINT]
        u.SetForegroundWindow.argtypes = [wt.HWND]
        u.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
        u.MonitorFromWindow.restype = wt.HMONITOR
        u.GetMonitorInfoW.argtypes = [wt.HMONITOR, ctypes.c_void_p]

        class RECT(ctypes.Structure):
            _fields_ = [("left", wt.LONG), ("top", wt.LONG), ("right", wt.LONG), ("bottom", wt.LONG)]

        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", RECT), ("rcWork", RECT),
                        ("dwFlags", wt.DWORD)]

        self._info = MONITORINFO

    def janelas(self) -> list[tuple[int, str, str]]:
        achadas: list[tuple[int, str, str]] = []
        ct, u = self._ct, self._u

        def cada(hwnd, _):
            if hwnd and u.IsWindowVisible(hwnd):
                n = u.GetWindowTextLengthW(hwnd)
                if 0 < n < 300:
                    titulo = ct.create_unicode_buffer(n + 1)
                    u.GetWindowTextW(hwnd, titulo, n + 1)
                    classe = ct.create_unicode_buffer(80)
                    u.GetClassNameW(hwnd, classe, 80)
                    achadas.append((hwnd, titulo.value, classe.value))
            return True

        u.EnumWindows(self._proc(cada), 0)
        return achadas

    def area(self, hwnd: int | None) -> tuple[int, int, int, int]:
        """A área de trabalho do monitor da janela (None = o monitor principal)."""
        modo = self.MONITOR_DEFAULTTONEAREST if hwnd else self.MONITOR_DEFAULTTOPRIMARY
        monitor = self._u.MonitorFromWindow(hwnd, modo)
        info = self._info()
        info.cbSize = self._ct.sizeof(self._info)
        if not monitor or not self._u.GetMonitorInfoW(monitor, self._ct.byref(info)):
            raise OSError("não consegui ler o tamanho da tela")
        r = info.rcWork
        return r.left, r.top, r.right, r.bottom

    def maximizar(self, hwnd: int) -> None:
        self._u.ShowWindow(hwnd, self.SW_MAXIMIZE)

    def restaurar(self, hwnd: int) -> None:
        self._u.ShowWindow(hwnd, self.SW_RESTORE)

    def mover(self, hwnd: int, x: int, y: int, w: int, h: int) -> None:
        self._u.SetWindowPos(hwnd, None, x, y, w, h, self.SWP_NOZORDER | self.SWP_SHOWWINDOW)

    def frente(self, hwnd: int) -> None:
        self._u.SetForegroundWindow(hwnd)


def _api(api=None):
    if api is not None:
        return api
    if sys.platform != "win32":
        return None
    try:
        return Windows()
    except (OSError, AttributeError) as e:
        log.warning("visor: sem a API de janelas do Windows (%s)", e)
        return None


FEITO = {"grande": "Pronto, deixei o visor grande, ocupando a tela.",
         "normal": "Pronto, o visor voltou ao tamanho normal, no centro da tela.",
         "pequeno": "Pronto, deixei o visor pequeno, no centro da tela."}


def ajustar(tamanho: str, largura: int = 1280, altura: int = 760, api=None) -> str:
    """Muda a janela do visor agora. Devolve o que dizer ao aluno."""
    api = _api(api)
    if api is None:
        return "Mudar o tamanho do visor só funciona no Windows."
    try:
        hwnd = achar(api.janelas())
        if hwnd is None:
            return "Não achei a janela do visor aberta."
        if tamanho == "grande":
            api.maximizar(hwnd)
        else:
            api.restaurar(hwnd)
            api.mover(hwnd, *retangulo(tamanho, api.area(hwnd), largura, altura))
        try:
            api.frente(hwnd)
        except OSError:
            pass                                 # o Windows às vezes não deixa: tudo bem
    except OSError as e:
        log.warning("visor: não consegui mudar o tamanho (%s)", e)
        return "Não consegui mudar o tamanho do visor agora."
    return FEITO[tamanho]


def argumentos_de_abertura(tamanho: str, largura: int, altura: int, api=None) -> list[str]:
    """Como o Edge abre o visor: maximizado ou no centro da tela, no tamanho guardado."""
    if tamanho == "grande":
        return [f"--window-size={largura},{altura}", "--start-maximized"]
    api = _api(api)
    try:
        area = api.area(None) if api is not None else None
    except OSError:
        area = None
    if area is None:
        return [f"--window-size={largura},{altura}"]
    x, y, w, h = retangulo(tamanho, area, largura, altura)
    return [f"--window-size={w},{h}", f"--window-position={x},{y}"]
