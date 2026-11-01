"""Cérebro LOCAL: roda no seu computador com o Ollama (sem internet, sem chave, sem limite).

Usa a API nativa do Ollama (http://localhost:11434), que permite:
  - desligar o "pensamento" do modelo (think: false): responde bem mais rápido
  - mandar as ferramentas em TODO pedido: o modelo decide sozinho quando agir
  - manter o modelo carregado na memória (keep_alive) entre as perguntas
  - mandar imagens (o mesmo modelo vê a tela)

Velocidade no processador: o que mais pesa é ler o começo do pedido (persona +
ferramentas). O Ollama guarda esse começo; por isso ele é sempre igual, e a data
e a hora vão no FIM (ver core/orquestrador.py, contexto_no_fim).
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
import threading
import urllib.error
import urllib.request
from typing import AsyncIterator, Awaitable, Callable

from .base import Cerebro, ErroCerebro, Mensagem

log = logging.getLogger("socrates.ollama")

URL_PADRAO = "http://localhost:11434"
MANTER_CARREGADO = "60m"
_PENSAMENTO = re.compile(r"<think>.*?</think>\s*", re.S)


class ErroOllama(ErroCerebro):
    pass


def _corpo(e: urllib.error.HTTPError) -> str:
    """O corpo do erro só pode ser lido uma vez: guarda."""
    if not hasattr(e, "_corpo_lido"):
        try:
            e._corpo_lido = e.read().decode("utf-8", "ignore")
        except Exception:
            e._corpo_lido = ""
    return e._corpo_lido


def _erro_amigavel(e: Exception, modelo: str) -> ErroOllama:
    if isinstance(e, urllib.error.HTTPError):
        corpo = _corpo(e)
        if e.code == 404 or "not found" in corpo:
            return ErroOllama(f"O modelo {modelo} não está baixado. Rode: main.py --local")
        return ErroOllama(f"O Ollama recusou o pedido ({e.code}): {corpo[:200]}")
    if isinstance(e, (urllib.error.URLError, ConnectionError, TimeoutError)):
        return ErroOllama("O Ollama não está aberto. Abra o aplicativo Ollama e tente de novo.")
    return ErroOllama(f"Erro no Ollama: {e}")


class ClienteOllama:
    """Conversa com o servidor do Ollama usando só a biblioteca padrão (urllib)."""

    def __init__(self, url: str = URL_PADRAO, tempo_limite: float = 600):
        self.url = url.rstrip("/")
        self.tempo_limite = tempo_limite

    def _req(self, caminho: str, dados: dict | None = None) -> urllib.request.Request:
        corpo = json.dumps(dados).encode() if dados is not None else None
        return urllib.request.Request(self.url + caminho, data=corpo,
                                      method="POST" if dados is not None else "GET",
                                      headers={"Content-Type": "application/json"})

    def get(self, caminho: str) -> dict:
        with urllib.request.urlopen(self._req(caminho), timeout=10) as r:
            return json.loads(r.read())

    def post(self, caminho: str, dados: dict) -> dict:
        with urllib.request.urlopen(self._req(caminho, dados), timeout=self.tempo_limite) as r:
            return json.loads(r.read())

    def linhas(self, caminho: str, dados: dict):
        """Resposta em pedaços (uma linha JSON por pedaço). Bloqueia: rode em thread."""
        with urllib.request.urlopen(self._req(caminho, dados), timeout=self.tempo_limite) as r:
            for linha in r:
                linha = linha.strip()
                if linha:
                    yield json.loads(linha)

    async def linhas_async(self, caminho: str, dados: dict) -> AsyncIterator[dict]:
        """As mesmas linhas, sem travar o asyncio (uma thread lê, a fila entrega)."""
        loop = asyncio.get_running_loop()
        fila: asyncio.Queue = asyncio.Queue()
        FIM = object()

        def ler():
            try:
                for item in self.linhas(caminho, dados):
                    loop.call_soon_threadsafe(fila.put_nowait, item)
            except Exception as e:   # entregue ao asyncio para virar erro amigável
                loop.call_soon_threadsafe(fila.put_nowait, e)
            finally:
                loop.call_soon_threadsafe(fila.put_nowait, FIM)

        threading.Thread(target=ler, name="ollama", daemon=True).start()
        while (item := await fila.get()) is not FIM:
            if isinstance(item, Exception):
                raise item
            yield item

    # ---------- utilidades ----------
    def modelos(self) -> list[str]:
        return [m["name"] for m in self.get("/api/tags").get("models", [])]

    def aberto(self) -> bool:
        try:
            self.get("/api/version")
            return True
        except Exception:
            return False


class FiltroPensamento:
    """Tira <think>...</think> do texto, mesmo com as marcas picotadas entre pedaços."""
    ABRE, FECHA = "<think>", "</think>"

    def __init__(self):
        self.buf = ""
        self.dentro = False

    @staticmethod
    def _parcial(texto: str, marca: str) -> int:
        for n in range(min(len(marca) - 1, len(texto)), 0, -1):
            if marca.startswith(texto[-n:]):
                return n
        return 0

    def alimentar(self, parte: str) -> str:
        self.buf += parte
        saida = ""
        while True:
            marca = self.FECHA if self.dentro else self.ABRE
            i = self.buf.find(marca)
            if i >= 0:
                if not self.dentro:
                    saida += self.buf[:i]
                self.buf = self.buf[i + len(marca):]
                self.dentro = not self.dentro
                if not self.dentro:
                    self.buf = self.buf.lstrip()
                continue
            k = self._parcial(self.buf, marca)
            if not self.dentro:
                saida += self.buf[:len(self.buf) - k]
            self.buf = self.buf[len(self.buf) - k:]
            return saida

    def fim(self) -> str:
        resto, self.buf = ("" if self.dentro else self.buf), ""
        return resto


class CerebroLocal(Cerebro):
    """Responde com streaming e, se o modelo pedir, roda ferramentas no meio."""

    def __init__(self, modelo: str, cliente: ClienteOllama | None = None,
                 esquemas: list[dict] | None = None,
                 executar: Callable[[str, dict], Awaitable[str]] | None = None,
                 contexto: int = 6144, temperatura: float = 0.5, max_rodadas: int = 4):
        self.nome = "local"
        self.modelo = modelo
        self.cliente = cliente or ClienteOllama()
        self.esquemas = esquemas or []
        self.executar = executar
        self.opcoes = {"num_ctx": contexto, "temperature": temperatura}
        self.max_rodadas = max_rodadas
        self.pesquisa_ok = False   # a pesquisa local é uma ferramenta, não a busca do Groq
        self.usar_think = True     # desligado se o modelo não aceitar o parâmetro
        self.usar_ferramentas = True

    def _pedido(self, mensagens: list, com_ferramentas: bool = True, stream: bool = True) -> dict:
        pedido = {"model": self.modelo, "messages": mensagens, "stream": stream,
                  "keep_alive": MANTER_CARREGADO, "options": self.opcoes}
        if self.usar_think:
            pedido["think"] = False   # sem "pensar alto": responde bem mais rápido
        if com_ferramentas and self.usar_ferramentas and self.esquemas and self.executar:
            pedido["tools"] = self.esquemas
        return pedido

    def _ajustar_ao_modelo(self, e: Exception) -> bool:
        """Modelo que não aceita 'think' ou ferramentas: tira e tenta de novo."""
        if not isinstance(e, urllib.error.HTTPError) or e.code != 400:
            return False
        corpo = _corpo(e).lower()
        if "think" in corpo and self.usar_think:
            log.warning("o modelo %s não aceita 'think'; seguindo sem", self.modelo)
            self.usar_think = False
            return True
        if "tools" in corpo and self.usar_ferramentas:
            log.warning("o modelo %s não aceita ferramentas; ações no PC desligadas", self.modelo)
            self.usar_ferramentas = False
            return True
        return False

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        msgs: list = [dict(m) for m in mensagens]
        rodada = 0
        while rodada < self.max_rodadas:
            rodada += 1
            texto, chamadas = "", []
            filtro = FiltroPensamento()   # alguns modelos ainda mandam <think>: não falar isso
            try:
                async for pedaco in self.cliente.linhas_async("/api/chat", self._pedido(msgs)):
                    if pedaco.get("error"):
                        raise ErroOllama(f"Erro no Ollama: {pedaco['error']}")
                    msg = pedaco.get("message") or {}
                    chamadas += msg.get("tool_calls") or []
                    parte = filtro.alimentar(msg.get("content") or "")
                    if parte:
                        texto += parte
                        yield parte
                resto = filtro.fim()
                if resto:
                    texto += resto
                    yield resto
            except ErroOllama:
                raise
            except Exception as e:
                if not texto and self._ajustar_ao_modelo(e):
                    rodada -= 1
                    continue
                raise _erro_amigavel(e, self.modelo) from e

            if not chamadas:
                return
            msgs.append({"role": "assistant", "content": texto, "tool_calls": chamadas})
            for c in chamadas:
                f = c.get("function") or {}
                nome, args = f.get("name", ""), f.get("arguments") or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                log.info("ferramenta pedida pelo modelo local: %s(%s)", nome, args)
                resultado = await self.executar(nome, args)
                msgs.append({"role": "tool", "content": resultado, "tool_name": nome})
        yield " Não consegui terminar o pedido."

    # ---------- visão ----------
    def descrever_imagem(self, jpeg: bytes, pergunta: str) -> str:
        msg = {"role": "user", "content": pergunta, "images": [base64.b64encode(jpeg).decode()]}
        try:
            r = self.cliente.post("/api/chat", self._pedido([msg], com_ferramentas=False,
                                                            stream=False))
        except Exception as e:
            raise _erro_amigavel(e, self.modelo) from e
        return _PENSAMENTO.sub("", (r.get("message") or {}).get("content", "")).strip()

    # ---------- preparo ----------
    def aquecer(self) -> None:
        """Carrega o modelo na memória antes da primeira pergunta."""
        try:
            self.cliente.post("/api/chat", {"model": self.modelo, "messages": [],
                                            "keep_alive": MANTER_CARREGADO})
        except Exception as e:
            log.warning("não consegui aquecer o modelo local: %s", e)
