"""main.py --local: prepara o cérebro LOCAL (Ollama) no seu computador.

1. Confere se o Ollama está aberto (e explica como instalar, se não estiver)
2. Mede a memória (RAM) e escolhe o tamanho do modelo
3. Baixa o modelo, mostrando o progresso
4. Testa: velocidade da resposta e se ele sabe usar as ferramentas
5. Grava "cerebro: local" no config.local.yaml (o config.yaml não é mexido)
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
import time
from pathlib import Path

import yaml

from .config import RAIZ, mesclar
from .llm.ollama import ClienteOllama, CerebroLocal

# (RAM mínima em GB, modelo, como fica)
MODELOS = [
    (12, "qwen3.5:4b", "o mais esperto que cabe no seu PC (3,4 GB)"),
    (6, "qwen3.5:2b", "mais leve, para PC com pouca memória (2,7 GB)"),
    (0, "qwen3.5:0.8b", "o mínimo: responde, mas é bem simples (1 GB)"),
]

COMO_INSTALAR = """O Ollama não está aberto (ou não está instalado).

Para instalar, no PowerShell:
    winget install Ollama.Ollama
ou baixe em https://ollama.com/download (botão "Download for Windows").

Depois de instalar, ele fica rodando sozinho (ícone de lhama perto do relógio).
Então rode de novo:  .venv\\Scripts\\python main.py --local"""


def memoria_gb() -> float:
    if sys.platform == "win32":
        class Status(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        st = Status()
        st.dwLength = ctypes.sizeof(Status)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
        return st.ullTotalPhys / 1024 ** 3
    return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1024 ** 3


def escolher_modelo(ram_gb: float) -> tuple[str, str]:
    for minimo, modelo, descricao in MODELOS:
        if ram_gb >= minimo:
            return modelo, descricao
    return MODELOS[-1][1], MODELOS[-1][2]


def baixar(cliente: ClienteOllama, modelo: str, escrever=print) -> None:
    ultimo = -1
    for passo in cliente.linhas("/api/pull", {"model": modelo, "stream": True}):
        if passo.get("error"):
            raise RuntimeError(passo["error"])
        total, feito = passo.get("total"), passo.get("completed")
        if total and feito:
            pct = int(feito * 100 / total)
            if pct != ultimo and pct % 5 == 0:
                barra = "#" * (pct // 5) + "." * (20 - pct // 5)
                escrever(f"\r     [{barra}] {pct:3d}%  ({feito / 1e9:.1f} de {total / 1e9:.1f} GB)",
                         end="", flush=True)
                ultimo = pct
    escrever("")


def descrever_modelo(modelo: str) -> str:
    for _, nome, descricao in MODELOS:
        if nome == modelo:
            return descricao
    return "escolhido por você"


def gravar_config_local(modelo: str | None, caminho: Path | None = None,
                        cerebro: str = "local") -> Path:
    from .config import gravar_local
    extra = {"cerebro": cerebro}
    if modelo:
        extra["local"] = {"modelo": modelo}
    return gravar_local(extra, caminho or RAIZ / "config.local.yaml")


async def _testar(cerebro: CerebroLocal, escrever=print) -> None:
    escrever("\n4/5  Testando a velocidade (a 1ª vez é mais lenta: ele carrega o modelo)")
    msgs = [{"role": "system", "content": "Responda em português do Brasil, em uma frase."},
            {"role": "user", "content": "O que é crase?"}]
    for rodada in (1, 2):
        inicio = time.monotonic()
        primeiro, texto = None, ""
        async for parte in cerebro.responder(msgs):
            primeiro = primeiro or time.monotonic()
            texto += parte
        fim = time.monotonic()
        escrever(f"     {rodada}ª resposta: começou a falar em {primeiro - inicio:.1f} s, "
                 f"terminou em {fim - inicio:.1f} s")
    escrever(f"     \"{texto.strip()[:150]}\"")

    escrever("\n5/5  Testando as ferramentas (nada é aberto de verdade)")
    pedidas = []

    async def anotar_pedido(nome, args):
        pedidas.append(nome)
        return "Abri calculadora."

    teste = CerebroLocal(cerebro.modelo, cerebro.cliente, [{
        "type": "function", "function": {
            "name": "abrir_programa", "description": "Abre um programa.",
            "parameters": {"type": "object", "properties": {"nome": {"type": "string"}},
                           "required": ["nome"]}}}], anotar_pedido)
    resposta = ""
    async for parte in teste.responder([{"role": "user", "content": "Abre a calculadora."}]):
        resposta += parte
    if pedidas == ["abrir_programa"]:
        escrever(f"     OK, ele usou a ferramenta certa. Respondeu: \"{resposta.strip()[:80]}\"")
    else:
        escrever("     ATENÇÃO: ele não usou a ferramenta. As ações no PC podem falhar com este modelo.")


def instalar(escrever=print, cliente: ClienteOllama | None = None,
             modelo: str | None = None) -> bool:
    cliente = cliente or ClienteOllama()
    escrever("=== Cérebro local (Ollama) ===\n")
    escrever("1/5  Procurando o Ollama...")
    if not cliente.aberto():
        escrever("\n" + COMO_INSTALAR)
        return False
    escrever("     OK, o Ollama está aberto.")

    ram = memoria_gb()
    sugerido, _ = escolher_modelo(ram)
    modelo = modelo or sugerido
    descricao = descrever_modelo(modelo)
    escrever(f"\n2/5  Memória do PC: {ram:.0f} GB  ->  modelo {modelo}: {descricao}")

    escrever(f"\n3/5  Baixando {modelo} (só na primeira vez; pode demorar alguns minutos)")
    if modelo in cliente.modelos():
        escrever("     Já estava baixado.")
    else:
        try:
            baixar(cliente, modelo, escrever)
        except Exception as e:
            escrever(f"     FALHOU ao baixar: {e}")
            return False

    cerebro = CerebroLocal(modelo, cliente)
    try:
        asyncio.run(_testar(cerebro, escrever))
    except Exception as e:
        escrever(f"     FALHOU no teste: {e}")
        return False

    caminho = gravar_config_local(modelo)
    escrever(f"\nPronto! Gravei \"cerebro: local\" em {caminho.name}.")
    escrever("Rode:  .venv\\Scripts\\python main.py")
    escrever("Para voltar para a nuvem, troque para \"cerebro: nuvem\" no config.local.yaml.")
    return True


def voltar_para_nuvem(escrever=print) -> None:
    """main.py --nuvem: grava "cerebro: nuvem" (o modelo baixado fica no PC)."""
    caminho = gravar_config_local(None, cerebro="nuvem")
    escrever(f"Pronto! Gravei \"cerebro: nuvem\" em {caminho.name}.")
    escrever("O Sócrates volta a pensar no Groq/Mistral/Gemini. Rode:  .venv\\Scripts\\python main.py")
    escrever("Para usar o local de novo:  .venv\\Scripts\\python main.py --local")
