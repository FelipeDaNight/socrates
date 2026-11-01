"""Janelas, área de transferência e bloco de notas — pelo próprio Windows.

Usa o PowerShell que já vem no Windows. O script vai em -EncodedCommand e todo
texto vindo de fora entra como literal entre aspas simples (com as aspas
dobradas), então um título de janela ou um texto copiado nunca vira comando.
"""

from __future__ import annotations

import base64
import json
import subprocess
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

from . import ferramenta

WINDOWS = sys.platform == "win32"

# Nunca fechar: o terminal onde o Sócrates roda, o próprio Sócrates e o Windows
PROTEGIDOS = {"powershell", "pwsh", "windowsterminal", "cmd", "conhost", "python", "pythonw",
              "py", "explorer", "claude", "dwm", "winlogon", "csrss", "taskmgr"}
TITULOS_PROTEGIDOS = ("socrates", "powershell", "prompt de comando", "terminal")

APELIDOS = {
    "navegador": ["chrome", "msedge", "firefox", "opera", "brave"],
    "chrome": ["chrome"], "google chrome": ["chrome"], "edge": ["msedge"],
    "bloco de notas": ["notepad"], "word": ["winword"], "excel": ["excel"],
    "powerpoint": ["powerpnt"], "calculadora": ["calculatorapp", "calculator"],
    "vscode": ["code"], "vs code": ["code"], "spotify": ["spotify"], "whatsapp": ["whatsapp"],
}


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower().strip(" .!?")
    for artigo in ("o ", "a ", "os ", "as "):
        if t.startswith(artigo):
            t = t[len(artigo):]
    return t


def _literal(texto: str) -> str:
    """Texto como literal do PowerShell: aspas simples, sem interpretação nenhuma."""
    return "'" + texto.replace("'", "''") + "'"


def _powershell(script: str, timeout: float = 15) -> str:
    if not WINDOWS:
        raise OSError("isso só funciona no Windows")
    script = "[Console]::OutputEncoding = [Text.Encoding]::UTF8\n" + script
    codificado = base64.b64encode(script.encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", codificado],
                       capture_output=True, timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise OSError(r.stderr.decode("utf-8", "ignore").strip()[:300] or "erro no PowerShell")
    return r.stdout.decode("utf-8", "ignore").strip()


# ---------------- janelas ----------------

def listar_janelas() -> list[dict]:
    """[{processo, titulo, id}] das janelas abertas (visíveis)."""
    saida = _powershell(
        "Get-Process | Where-Object { $_.MainWindowTitle } | "
        "Select-Object @{n='processo';e={$_.ProcessName}}, @{n='titulo';e={$_.MainWindowTitle}}, "
        "@{n='id';e={$_.Id}} | ConvertTo-Json -Compress")
    if not saida:
        return []
    dados = json.loads(saida)
    return dados if isinstance(dados, list) else [dados]


def _protegida(janela: dict) -> bool:
    titulo = _norm(janela.get("titulo", ""))
    return (janela.get("processo", "").lower() in PROTEGIDOS
            or any(t in titulo for t in TITULOS_PROTEGIDOS))


def achar_janelas(nome: str, janelas: list[dict]) -> list[dict]:
    """Janelas cujo processo ou título combinam com o nome falado."""
    chave = _norm(nome)
    processos = APELIDOS.get(chave, [chave.replace(" ", "")])
    achadas = [j for j in janelas
               if j.get("processo", "").lower() in processos or chave in _norm(j.get("titulo", ""))]
    return [j for j in achadas if not _protegida(j)]


@ferramenta("Lista os programas e janelas abertos agora no computador do aluno "
            "(rápido, não tira print). Use para saber o que ele está fazendo.")
def janelas_abertas() -> str:
    janelas = [j for j in listar_janelas() if not _protegida(j)]
    if not janelas:
        return "Não há janelas abertas além do Sócrates e do terminal."
    linhas = [f"- {j['titulo']} ({j['processo']})" for j in janelas[:25]]
    return "Janelas abertas:\n" + "\n".join(linhas)


@ferramenta("Fecha um programa ou janela aberta, do jeito normal (se houver algo sem salvar, "
            "o próprio programa pergunta).",
            params={"nome": "Programa ou parte do título da janela. Ex.: bloco de notas, chrome, word"})
def fechar_programa(nome: str) -> str:
    alvos = achar_janelas(nome, listar_janelas())
    if not alvos:
        return f"Não encontrei nenhuma janela aberta de '{nome}'."
    ids = ",".join(str(int(j["id"])) for j in alvos)
    _powershell(f"foreach ($i in @({ids})) {{ (Get-Process -Id $i -ErrorAction SilentlyContinue)"
                ".CloseMainWindow() | Out-Null }")
    titulos = "; ".join(j["titulo"] for j in alvos[:3])
    return f"Pedi para fechar: {titulos}."


@ferramenta("Traz uma janela aberta para a frente da tela.",
            params={"nome": "Programa ou parte do título da janela"})
def mostrar_janela(nome: str) -> str:
    alvos = achar_janelas(nome, listar_janelas())
    if not alvos:
        return f"Não encontrei nenhuma janela aberta de '{nome}'."
    j = alvos[0]
    _powershell(f"(New-Object -ComObject WScript.Shell).AppActivate({int(j['id'])}) | Out-Null")
    return f"Coloquei na frente: {j['titulo']}."


# ---------------- área de transferência ----------------

@ferramenta("Lê o texto que o aluno copiou (Ctrl+C). Use quando ele disser 'o que eu copiei', "
            "'a questão que eu copiei', 'explica isso que copiei'.")
def ler_area_de_transferencia() -> str:
    texto = _powershell("Get-Clipboard -Raw")
    if not texto:
        return "A área de transferência está vazia (ou tem uma imagem, não texto)."
    return "Texto copiado pelo aluno:\n" + texto[:6000]


@ferramenta("Copia um texto para a área de transferência, para o aluno colar (Ctrl+V).",
            params={"texto": "O texto a copiar"})
def copiar_texto(texto: str) -> str:
    _powershell(f"Set-Clipboard -Value {_literal(texto)}")
    return "Copiei. É só colar com Ctrl+V."


# ---------------- bloco de notas ----------------

PASTA_NOTAS = Path.home() / "Documents" / "Socrates" / "notas"


@ferramenta("Escreve um texto num arquivo novo e abre no Bloco de Notas para o aluno ver. "
            "Use quando ele pedir para escrever, criar uma nota ou um resumo no bloco de notas.",
            params={"texto": "O texto completo, já escrito e organizado",
                    "titulo": "Nome curto para o arquivo, ex.: resumo crase"})
def escrever_no_bloco_de_notas(texto: str, titulo: str = "") -> str:
    PASTA_NOTAS.mkdir(parents=True, exist_ok=True)
    nome = "".join(c for c in (titulo or "nota") if c.isalnum() or c in " -_").strip()[:50] or "nota"
    arquivo = PASTA_NOTAS / f"{datetime.now():%Y-%m-%d %H-%M} {nome}.txt"
    arquivo.write_text(texto.strip() + "\n", encoding="utf-8")
    abrir_no_bloco_de_notas(arquivo)
    return f"Escrevi e abri no Bloco de Notas ({arquivo.name})."


def abrir_no_bloco_de_notas(arquivo: Path) -> None:
    if WINDOWS:
        subprocess.Popen(["notepad.exe", str(arquivo)])
    else:
        subprocess.Popen(["xdg-open", str(arquivo)])
