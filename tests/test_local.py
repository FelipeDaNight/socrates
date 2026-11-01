"""Cérebro local (Ollama) contra um servidor HTTP falso de verdade, numa porta local."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from socrates.core import contexto
from socrates.core.orquestrador import Orquestrador
from socrates.ferramentas import busca
from socrates.llm.base import ErroCerebro
from socrates.llm.ollama import ClienteOllama, CerebroLocal


class FalsoOllama(BaseHTTPRequestHandler):
    """Fala o protocolo do Ollama: /api/chat (NDJSON), /api/tags, /api/version, /api/pull."""
    pedidos: list = []
    recusar: set = set()        # "think" / "tools": responde 400 como modelo que não aceita
    modelos = ["qwen3.5:4b"]

    def log_message(self, *a):
        pass

    def _json(self, codigo, dados):
        corpo = json.dumps(dados).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _linhas(self, itens):
        self.send_response(200)
        self.send_header("Content-Type", "application/x-ndjson")
        self.end_headers()
        for item in itens:
            self.wfile.write((json.dumps(item) + "\n").encode())
            self.wfile.flush()

    def do_GET(self):
        if self.path == "/api/version":
            return self._json(200, {"version": "0.30.0"})
        if self.path == "/api/tags":
            return self._json(200, {"models": [{"name": m} for m in self.modelos]})
        self._json(404, {"error": "not found"})

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FalsoOllama.pedidos.append(corpo)
        if self.path == "/api/pull":
            FalsoOllama.modelos.append(corpo["model"])
            return self._linhas([{"status": "pulling", "total": 100, "completed": c}
                                 for c in (0, 50, 100)] + [{"status": "success"}])
        if corpo.get("model") not in self.modelos:
            return self._json(404, {"error": f"model '{corpo.get('model')}' not found"})
        if "think" in self.recusar and "think" in corpo:
            return self._json(400, {"error": "model does not support thinking"})
        if "tools" in self.recusar and "tools" in corpo:
            return self._json(400, {"error": "model does not support tools"})
        msgs = corpo.get("messages", [])
        if not msgs:                                    # aquecer
            return self._json(200, {"done": True})
        ultima = msgs[-1]
        if ultima.get("images"):
            return self._json(200, {"message": {"role": "assistant",
                                                "content": "<think>hm</think>Uma questão de crase."}})
        if ultima["role"] == "tool":
            texto = f"Pronto: {ultima['content']}"
        elif corpo.get("tools") and "calculadora" in ultima["content"].lower():
            return self._linhas([
                {"message": {"role": "assistant", "content": "", "tool_calls": [
                    {"function": {"name": "abrir_programa", "arguments": {"nome": "calculadora"}}}]},
                 "done": False},
                {"message": {"role": "assistant", "content": ""}, "done": True}])
        else:
            texto = "<think>pensando</think>Crase é a fusão de duas letras a. Entendeu?"
        partes = [texto[i:i + 7] for i in range(0, len(texto), 7)]
        self._linhas([{"message": {"role": "assistant", "content": p}, "done": False} for p in partes]
                     + [{"message": {"role": "assistant", "content": ""}, "done": True}])


@pytest.fixture
def servidor():
    FalsoOllama.pedidos = []
    FalsoOllama.recusar = set()
    FalsoOllama.modelos = ["qwen3.5:4b"]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), FalsoOllama)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield ClienteOllama(f"http://127.0.0.1:{srv.server_address[1]}")
    srv.shutdown()


ESQUEMA = [{"type": "function", "function": {"name": "abrir_programa", "description": "Abre.",
            "parameters": {"type": "object", "properties": {"nome": {"type": "string"}}}}}]


async def _texto(cerebro, pergunta):
    return "".join([p async for p in cerebro.responder([{"role": "user", "content": pergunta}])])


@pytest.mark.asyncio
async def test_resposta_em_pedacos_sem_o_pensamento(servidor):
    c = CerebroLocal("qwen3.5:4b", servidor)
    assert await _texto(c, "O que é crase?") == "Crase é a fusão de duas letras a. Entendeu?"
    p = FalsoOllama.pedidos[0]
    assert p["think"] is False and p["stream"] is True and p["keep_alive"] == "60m"
    assert p["options"]["num_ctx"] == 6144


@pytest.mark.asyncio
async def test_ferramenta_no_meio_da_conversa(servidor):
    feitas = []

    async def executar(nome, args):
        feitas.append((nome, args))
        return "Abri calculadora."

    c = CerebroLocal("qwen3.5:4b", servidor, ESQUEMA, executar)
    assert await _texto(c, "Abre a calculadora") == "Pronto: Abri calculadora."
    assert feitas == [("abrir_programa", {"nome": "calculadora"})]
    volta = FalsoOllama.pedidos[1]["messages"]
    assert volta[-2]["tool_calls"][0]["function"]["name"] == "abrir_programa"
    assert volta[-1] == {"role": "tool", "content": "Abri calculadora.", "tool_name": "abrir_programa"}


@pytest.mark.asyncio
async def test_modelo_sem_think_tenta_de_novo(servidor):
    FalsoOllama.recusar = {"think"}
    c = CerebroLocal("qwen3.5:4b", servidor)
    assert "Crase" in await _texto(c, "O que é crase?")
    assert "think" not in FalsoOllama.pedidos[-1] and not c.usar_think


@pytest.mark.asyncio
async def test_modelo_sem_ferramentas_responde_mesmo_assim(servidor):
    FalsoOllama.recusar = {"tools"}

    async def executar(nome, args):
        return "x"
    c = CerebroLocal("qwen3.5:4b", servidor, ESQUEMA, executar)
    assert "Crase" in await _texto(c, "O que é crase?")
    assert not c.usar_ferramentas


@pytest.mark.asyncio
async def test_modelo_nao_baixado_explica(servidor):
    with pytest.raises(ErroCerebro, match="não está baixado"):
        await _texto(CerebroLocal("llama9:99b", servidor), "oi")


@pytest.mark.asyncio
async def test_ollama_fechado_explica():
    c = CerebroLocal("qwen3.5:4b", ClienteOllama("http://127.0.0.1:9"))
    with pytest.raises(ErroCerebro, match="Ollama não está aberto"):
        await _texto(c, "oi")


def test_ve_a_tela_com_o_mesmo_modelo(servidor):
    c = CerebroLocal("qwen3.5:4b", servidor)
    assert c.descrever_imagem(b"\xff\xd8jpeg", "O que tem?") == "Uma questão de crase."
    p = FalsoOllama.pedidos[-1]
    assert p["messages"][0]["images"] and "tools" not in p and p["stream"] is False


# ---------- instalador ----------

def test_escolhe_o_modelo_pela_memoria():
    from socrates.instalar_local import escolher_modelo
    assert escolher_modelo(16)[0] == "qwen3.5:4b"
    assert escolher_modelo(8)[0] == "qwen3.5:2b"
    assert escolher_modelo(4)[0] == "qwen3.5:0.8b"


def test_instalador_completo(servidor, tmp_path, monkeypatch):
    from socrates import instalar_local
    monkeypatch.setattr(instalar_local, "RAIZ", tmp_path)
    monkeypatch.setattr(instalar_local, "memoria_gb", lambda: 8.0)
    (tmp_path / "config.local.yaml").write_text("voz:\n  tom: '-8Hz'\n", encoding="utf-8")
    saida = []
    ok = instalar_local.instalar(lambda *a, **k: saida.append(" ".join(map(str, a))), servidor)
    assert ok, "\n".join(saida)
    assert any(p.get("model") == "qwen3.5:2b" for p in FalsoOllama.pedidos)   # baixou o 2b
    texto = "\n".join(saida)
    assert "100%" in texto and "usou a ferramenta certa" in texto
    import yaml
    cfg = yaml.safe_load((tmp_path / "config.local.yaml").read_text(encoding="utf-8"))
    assert cfg == {"voz": {"tom": "-8Hz"}, "cerebro": "local", "local": {"modelo": "qwen3.5:2b"}}


def test_instalador_sem_ollama_ensina_a_instalar():
    from socrates.instalar_local import instalar
    saida = []
    assert not instalar(lambda *a, **k: saida.append(" ".join(map(str, a))),
                        ClienteOllama("http://127.0.0.1:9"))
    assert "winget install Ollama.Ollama" in "\n".join(saida)


# ---------- data no fim (cache do Ollama) ----------

@pytest.mark.asyncio
async def test_data_vai_no_fim_para_o_comeco_ficar_igual():
    from socrates.llm.falso import CerebroFalso
    horas = iter(["Agora é 10:00.", "Agora é 10:01."])
    cerebro = CerebroFalso("ok")
    soc = Orquestrador(cerebro, contexto=lambda: next(horas), contexto_no_fim=True,
                       extra_sistema=contexto.INSTRUCAO_LOCAL)
    for pergunta in ("oi", "tudo bem?"):
        async for _ in soc.conversar(pergunta):
            pass
    a, b = cerebro.recebido
    assert a[0] == b[0]                                    # começo idêntico: cache aproveitado
    assert "pesquisar_na_internet" in a[0]["content"]
    assert b[-2] == {"role": "system", "content": "Agora é 10:01."} and b[-1]["content"] == "tudo bem?"
    assert b[1:3] == [{"role": "user", "content": "oi"}, {"role": "assistant", "content": "ok"}]
    assert a[-2]["content"] == "Agora é 10:00."            # histórico vem antes da data


# ---------- busca ----------

def test_busca_formata_resultados(monkeypatch):
    monkeypatch.setattr(busca, "buscar", lambda c, q=5: [
        {"title": "Dólar hoje", "href": "https://www.g1.globo.com/x", "body": "O dólar fechou a R$ 5,40."}])
    r = busca.pesquisar_na_internet("dólar hoje")
    assert "Dólar hoje (g1.globo.com): O dólar fechou a R$ 5,40." in r


def test_busca_sem_internet_explica(monkeypatch):
    def falha(c, q=5):
        raise RuntimeError("sem rede")
    monkeypatch.setattr(busca, "buscar", falha)
    assert "não respondeu" in busca.pesquisar_na_internet("x")


@pytest.mark.parametrize("pedacos,esperado", [
    (["<think>a</think>Olá."], "Olá."),
    (["<thi", "nk>pensa", "ndo</th", "ink>  Olá", " mundo."], "Olá mundo."),
    (["Sem pensamento < 3."], "Sem pensamento < 3."),
    (["Texto <", "b> e mais"], "Texto <b> e mais"),
    (["<think>nunca fecha"], ""),
])
def test_filtro_de_pensamento(pedacos, esperado):
    from socrates.llm.ollama import FiltroPensamento
    f = FiltroPensamento()
    assert "".join(f.alimentar(p) for p in pedacos) + f.fim() == esperado
