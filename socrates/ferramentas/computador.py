"""Ações no seu computador, feitas pelo próprio Windows (sem API nenhuma).

Ficaram de fora, de propósito, ações que apagam ou desligam coisas.
Programas fora da lista podem ser adicionados em config.yaml (acoes: programas:).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
import urllib.parse
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import ferramenta

WINDOWS = sys.platform == "win32"

# nome falado -> o que o Windows sabe abrir (programa registrado, link ou protocolo)
PROGRAMAS: dict[str, str] = {
    "bloco de notas": "notepad", "notepad": "notepad", "notas": "notepad",
    "calculadora": "calc",
    "explorador de arquivos": "explorer", "explorador": "explorer", "arquivos": "explorer",
    "navegador": "https://www.google.com", "internet": "https://www.google.com",
    "chrome": "chrome", "google chrome": "chrome", "edge": "msedge", "firefox": "firefox",
    "word": "winword", "excel": "excel", "powerpoint": "powerpnt",
    "vscode": "code", "vs code": "code", "visual studio code": "code",
    "spotify": "spotify:", "whatsapp": "whatsapp:",
    "configuracoes": "ms-settings:", "configuracao": "ms-settings:",
    "paint": "mspaint", "prompt de comando": "cmd", "terminal": "wt",
    "gerenciador de tarefas": "taskmgr",
    "relogio": "ms-clock:", "alarmes": "ms-clock:", "camera": "microsoft.windows.camera:",
}

PASTAS = {
    "documentos": "Documents", "downloads": "Downloads", "area de trabalho": "Desktop",
    "imagens": "Pictures", "fotos": "Pictures", "musicas": "Music", "videos": "Videos",
}

PASTA_SOCRATES = Path.home() / "Documents" / "Socrates"

# Quem fala quando o timer acaba (main.py liga isso à voz do Sócrates)
avisar: Callable[[str], None] = lambda texto: print(f"\n[aviso] {texto}")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = t.strip(" .!?,")
    for artigo in ("o ", "a ", "os ", "as ", "meu ", "minha "):
        if t.startswith(artigo):
            t = t[len(artigo):]
    return t


# Onde os programas costumam ficar, se o Windows não achar pelo nome
CAMINHOS = {
    "chrome": [r"%ProgramFiles%\Google\Chrome\Application\chrome.exe",
               r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe",
               r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"],
    "msedge": [r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe",
               r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"],
    "firefox": [r"%ProgramFiles%\Mozilla Firefox\firefox.exe",
                r"%ProgramFiles(x86)%\Mozilla Firefox\firefox.exe"],
    "code": [r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe",
             r"%ProgramFiles%\Microsoft VS Code\Code.exe"],
    "spotify:": [r"%APPDATA%\Spotify\Spotify.exe"],
}
NAVEGADORES = {"chrome", "msedge", "firefox"}


def _candidatos(alvo: str) -> list[str]:
    """Jeitos de achar o programa, do mais simples ao mais insistente."""
    opcoes = [alvo]
    if not any(c in alvo for c in ":\\/."):
        opcoes.append(alvo + ".exe")             # o Windows registra "chrome.exe"
    achado = shutil.which(alvo)
    if achado:
        opcoes.append(achado)
    for caminho in CAMINHOS.get(alvo, []):
        caminho = os.path.expandvars(caminho)
        if os.path.exists(caminho):
            opcoes.append(caminho)
    return opcoes


def _iniciar(alvo: str) -> None:
    """Pede ao sistema para abrir algo (programa, link, pasta)."""
    if WINDOWS:
        # O Windows acha programas registrados (chrome, winword...), links e pastas.
        # Sem passar pelo cmd: um link com "&" não vira outro comando.
        ultimo_erro: OSError | None = None
        for opcao in _candidatos(alvo):
            try:
                os.startfile(opcao)
                return
            except OSError as e:
                ultimo_erro = e
        raise FileNotFoundError(f"o Windows não encontrou '{alvo}' neste computador") from ultimo_erro
    elif alvo.startswith(("http://", "https://")):
        webbrowser.open(alvo)
    else:
        subprocess.Popen(["xdg-open" if sys.platform.startswith("linux") else "open", alvo])


def _tecla(codigo: int, vezes: int = 1) -> None:
    import ctypes
    for _ in range(vezes):
        ctypes.windll.user32.keybd_event(codigo, 0, 0, 0)
        ctypes.windll.user32.keybd_event(codigo, 0, 2, 0)   # 2 = soltar


# ---------------- programas e sites ----------------

@ferramenta("Abre um programa do computador.",
            params={"nome": "Nome do programa, como o aluno falou. Ex.: calculadora, "
                            "bloco de notas, chrome, word, excel, spotify, configurações."})
def abrir_programa(nome: str) -> str:
    chave = _norm(nome)
    alvo = PROGRAMAS.get(chave)
    if alvo is None:
        parecidos = [p for p in PROGRAMAS if chave in p or p in chave]
        alvo = PROGRAMAS[parecidos[0]] if parecidos else None
    if alvo is None:
        return (f"Não conheço o programa '{nome}'. Ele pode ser adicionado em config.yaml, "
                f"em acoes: programas:. Conheço: {', '.join(sorted(set(PROGRAMAS)))}.")
    try:
        _iniciar(alvo)
    except FileNotFoundError:
        if alvo in NAVEGADORES:      # sem esse navegador: usa o navegador padrão
            webbrowser.open("https://www.google.com")
            return f"Não achei o {nome} instalado; abri o seu navegador padrão."
        return (f"O {nome} não foi encontrado neste computador. Se ele estiver instalado, "
                "adicione o caminho do .exe em config.yaml, em acoes: programas:.")
    return f"Abri {nome}."


@ferramenta("Abre um site no navegador.",
            params={"endereco": "Endereço do site, ex.: g1.globo.com, gmail.com, qconcursos.com"})
def abrir_site(endereco: str) -> str:
    endereco = endereco.strip().replace(" ", "")
    if not endereco.startswith(("http://", "https://")):
        endereco = "https://" + endereco
    if urllib.parse.urlparse(endereco).scheme not in ("http", "https"):
        return "Só abro endereços de sites (http ou https)."
    _iniciar(endereco)
    return f"Abri {endereco}."


@ferramenta("Pesquisa no Google ou no YouTube e abre os resultados no navegador. "
            "Use para 'toca tal música', 'abre vídeo de tal assunto', 'procura no Google'.",
            params={"termo": "O que procurar", "onde": "Onde procurar"},
            opcoes={"onde": ["google", "youtube"]})
def buscar_no_navegador(termo: str, onde: str = "google") -> str:
    q = urllib.parse.quote_plus(termo.strip())
    if onde == "youtube":
        _iniciar(f"https://www.youtube.com/results?search_query={q}")
        return f"Abri o YouTube procurando por {termo}."
    _iniciar(f"https://www.google.com/search?q={q}")
    return f"Abri o Google procurando por {termo}."


@ferramenta("Abre uma pasta do computador.",
            params={"nome": "Qual pasta"},
            opcoes={"nome": ["documentos", "downloads", "area de trabalho", "imagens",
                             "musicas", "videos", "anotacoes"]})
def abrir_pasta(nome: str) -> str:
    chave = _norm(nome)
    if chave in ("anotacoes", "socrates"):
        PASTA_SOCRATES.mkdir(parents=True, exist_ok=True)
        caminho = PASTA_SOCRATES
    elif chave in PASTAS:
        caminho = Path.home() / PASTAS[chave]
    else:
        return f"Não conheço a pasta '{nome}'. Conheço: {', '.join(PASTAS)}."
    _iniciar(str(caminho))
    return f"Abri a pasta {nome}."


# ---------------- volume ----------------

@ferramenta("Aumenta, diminui ou silencia o volume do computador.",
            params={"acao": "O que fazer com o volume",
                    "quanto": "Quantos degraus (cada um é 2%). Padrão 5 = 10%."},
            opcoes={"acao": ["aumentar", "diminuir", "mudo"]})
def volume(acao: str, quanto: int = 5) -> str:
    if not WINDOWS:
        return "Controle de volume só funciona no Windows."
    quanto = max(1, min(int(quanto), 50))
    if acao == "mudo":
        _tecla(0xAD)
        return "Liguei ou desliguei o mudo."
    if acao == "aumentar":
        _tecla(0xAF, quanto)
        return f"Aumentei o volume em {quanto * 2}%."
    if acao == "diminuir":
        _tecla(0xAE, quanto)
        return f"Diminuí o volume em {quanto * 2}%."
    return "Ação de volume desconhecida."


# ---------------- timer / pomodoro ----------------

class _Timer:
    def __init__(self):
        self.timer: threading.Timer | None = None
        self.fim = 0.0
        self.motivo = ""

    def iniciar(self, minutos: float, motivo: str) -> None:
        self.cancelar()
        self.fim = time.monotonic() + minutos * 60
        self.motivo = motivo
        self.timer = threading.Timer(minutos * 60, self._tocar)
        self.timer.daemon = True
        self.timer.start()

    def _tocar(self) -> None:
        motivo = f" de {self.motivo}" if self.motivo else ""
        self.timer = None
        avisar(f"Seu tempo{motivo} acabou! Hora de fazer uma pausa.")

    def cancelar(self) -> bool:
        ativo = self.timer is not None
        if self.timer:
            self.timer.cancel()
        self.timer = None
        return ativo

    def restante(self) -> float | None:
        return max(0.0, self.fim - time.monotonic()) if self.timer else None


TIMER = _Timer()


def _minutos_falados(seg: float) -> str:
    m, s = int(seg // 60), int(seg % 60)
    if m and s:
        return f"{m} minutos e {s} segundos"
    return f"{m} minutos" if m else f"{s} segundos"


@ferramenta("Inicia um timer (por exemplo um pomodoro de estudo). Avisa em voz alta quando acabar.",
            params={"minutos": "Duração em minutos. Pomodoro = 25.",
                    "motivo": "Para que é o timer, ex.: estudo, pausa, revisão"})
def iniciar_timer(minutos: float, motivo: str = "") -> str:
    minutos = float(minutos)
    if not 0 < minutos <= 600:
        return "O timer precisa ter entre alguns segundos e 10 horas."
    TIMER.iniciar(minutos, motivo)
    return f"Timer de {_minutos_falados(minutos * 60)} iniciado."


@ferramenta("Diz quanto tempo falta no timer.")
def consultar_timer() -> str:
    resta = TIMER.restante()
    if resta is None:
        return "Não há nenhum timer ativo."
    return f"Faltam {_minutos_falados(resta)}."


@ferramenta("Cancela o timer ativo.")
def cancelar_timer() -> str:
    return "Timer cancelado." if TIMER.cancelar() else "Não havia timer ativo."


# ---------------- anotações ----------------

@ferramenta("Anota um lembrete curto no caderno de anotações do aluno (lista com data). "
            "Para escrever um texto e MOSTRAR no Bloco de Notas, use escrever_no_bloco_de_notas.",
            params={"texto": "O que anotar, já organizado e escrito corretamente"})
def anotar(texto: str) -> str:
    PASTA_SOCRATES.mkdir(parents=True, exist_ok=True)
    arquivo = PASTA_SOCRATES / "anotacoes.md"
    quando = datetime.now().strftime("%d/%m/%Y %H:%M")
    with arquivo.open("a", encoding="utf-8") as f:
        f.write(f"- **{quando}** — {texto.strip()}\n")
    return "Anotado no seu caderno."


@ferramenta("Abre o caderno de anotações do aluno.")
def abrir_anotacoes() -> str:
    arquivo = PASTA_SOCRATES / "anotacoes.md"
    if not arquivo.exists():
        return "Você ainda não tem anotações."
    from .janelas import abrir_no_bloco_de_notas
    abrir_no_bloco_de_notas(arquivo)
    return "Abri suas anotações no Bloco de Notas."


# ---------------- tela ----------------

@ferramenta("Bloqueia a tela do computador (precisa da senha para voltar).")
def bloquear_tela() -> str:
    if not WINDOWS:
        return "Bloquear a tela só funciona no Windows."
    subprocess.Popen(["rundll32.exe", "user32.dll,LockWorkStation"])
    return "Tela bloqueada."


def adicionar_programas(extras: dict[str, str] | None) -> None:
    """Programas do config.yaml (acoes: programas:)."""
    for nome, alvo in (extras or {}).items():
        PROGRAMAS[_norm(nome)] = os.path.expandvars(str(alvo))
