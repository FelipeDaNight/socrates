"""Rodízio de cérebros grátis: Groq -> Mistral -> Gemini."""

import json
import time

import httpx2 as httpx
import pytest

from socrates.config import ConfigLLM, carregar
from socrates.ferramentas import tela
from socrates.llm import CerebroCompativelOpenAI, ErroCerebro, ErroPesquisa
from socrates.llm.rodizio import CerebroRodizio


def _ok(texto):
    return httpx.Response(200, json={
        "id": "1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": texto}}]})


def _sse(texto):
    pedacos = [{"id": "1", "object": "chat.completion.chunk", "created": 0, "model": "m",
                "choices": [{"index": 0, "delta": {"content": p}, "finish_reason": None}]}
               for p in texto.replace(" ", " \0").split("\0")]
    corpo = "".join(f"data: {json.dumps(p)}\n\n" for p in pedacos) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=corpo.encode())


def _limite(espera=None, dia=False):
    msg = "Rate limit reached on tokens per " + ("day (TPD)" if dia else "minute (TPM)")
    cab = {"retry-after": str(espera)} if espera else {}
    return httpx.Response(429, headers=cab, json={"error": {"message": msg, "type": "tokens"}})


class Servico:
    """Um provedor falso: responde, ou bate no limite, ou cai."""
    def __init__(self, nome, url, modelo, modo="ok"):
        self.nome, self.modo, self.chamadas = nome, modo, 0
        self.cerebro = CerebroCompativelOpenAI(
            url, "k", modelo, nome=nome,
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(self._responder)))

    def _responder(self, req):
        self.chamadas += 1
        if self.modo == "limite":
            return _limite(espera=40)
        if self.modo == "dia":
            return _limite(dia=True)
        if self.modo == "caiu":
            return httpx.Response(503, json={"error": {"message": "fora do ar"}})
        corpo = json.loads(req.content)
        if corpo.get("stream"):
            return _sse(f"Resposta do {self.nome}.")
        return _ok(f"Resposta do {self.nome}.")


def _rodizio(*modos):
    servicos = [Servico("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", modos[0]),
                Servico("mistral", "https://api.mistral.ai/v1", "mistral-medium-latest", modos[1]),
                Servico("gemini", "https://g.example/v1beta/openai/", "gemini-flash-latest", modos[2])]
    return CerebroRodizio([s.cerebro for s in servicos]), servicos


async def _conversa(c):
    return "".join([p async for p in c.responder([{"role": "user", "content": "oi"}])])


@pytest.mark.asyncio
async def test_usa_o_primeiro_quando_ele_funciona():
    c, (g, m, ge) = _rodizio("ok", "ok", "ok")
    assert (await _conversa(c)).strip() == "Resposta do groq."
    assert (m.chamadas, ge.chamadas) == (0, 0)


@pytest.mark.asyncio
async def test_groq_no_limite_passa_para_o_mistral():
    c, (g, m, ge) = _rodizio("limite", "ok", "ok")
    assert (await _conversa(c)).strip() == "Resposta do mistral."
    assert c.ultimo_usado is m.cerebro


@pytest.mark.asyncio
async def test_quem_estourou_descansa():
    c, (g, m, ge) = _rodizio("limite", "ok", "ok")
    await _conversa(c)
    await _conversa(c)
    assert g.chamadas == 1          # não insistiu no Groq na segunda pergunta
    assert m.chamadas == 2


@pytest.mark.asyncio
async def test_cair_tambem_troca():
    c, (g, m, ge) = _rodizio("caiu", "dia", "ok")
    assert (await _conversa(c)).strip() == "Resposta do gemini."
    assert m.cerebro.descansar_ate - time.monotonic() > 3600     # limite do dia: descanso longo


@pytest.mark.asyncio
async def test_todos_no_limite_explica():
    c, _ = _rodizio("limite", "limite", "limite")
    with pytest.raises(ErroCerebro, match="limite grátis"):
        await _conversa(c)


@pytest.mark.asyncio
async def test_todos_descansando_tenta_o_que_libera_primeiro():
    c, (g, m, ge) = _rodizio("ok", "ok", "ok")
    agora = time.monotonic()
    g.cerebro.descansar_ate, m.cerebro.descansar_ate, ge.cerebro.descansar_ate = \
        agora + 300, agora + 5, agora + 900
    assert (await _conversa(c)).strip() == "Resposta do mistral."


@pytest.mark.asyncio
async def test_acoes_no_rodizio():
    c, (g, m, ge) = _rodizio("limite", "ok", "ok")

    async def executar(n, a):
        return "x"
    texto = await c.com_ferramentas([{"role": "user", "content": "abre a calculadora"}], [], executar)
    assert texto == "Resposta do mistral."


@pytest.mark.asyncio
async def test_acao_feita_nao_e_repetida_quando_o_limite_chega_no_meio():
    chamadas, executadas = [], []

    def groq(req):
        chamadas.append(1)
        if len(chamadas) == 1:
            return httpx.Response(200, json={
                "id": "1", "object": "chat.completion", "created": 0, "model": "m",
                "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                    "role": "assistant", "content": None, "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "abrir_programa", "arguments": '{"nome":"calculadora"}'}}]}}]})
        return _limite(espera=40)

    groq_c = CerebroCompativelOpenAI("https://api.groq.com/openai/v1", "k", "openai/gpt-oss-20b",
                                     http_client=httpx.AsyncClient(transport=httpx.MockTransport(groq)))
    mistral = Servico("mistral", "https://api.mistral.ai/v1", "mistral-small-latest")
    c = CerebroRodizio([groq_c, mistral.cerebro])

    async def executar(n, a):
        executadas.append(n)
        return "Abri calculadora."
    assert await c.com_ferramentas([{"role": "user", "content": "abre a calculadora"}], [], executar) \
        == "Abri calculadora."
    assert executadas == ["abrir_programa"] and mistral.chamadas == 0


@pytest.mark.asyncio
async def test_pesquisa_so_nos_que_tem_busca():
    c, (g, m, ge) = _rodizio("limite", "ok", "ok")
    assert c.pesquisa_ok
    with pytest.raises(ErroPesquisa):           # só o Groq tem busca, e ele está no limite
        await c.pesquisar([{"role": "user", "content": "dólar?"}])
    assert m.chamadas == 0 and ge.chamadas == 0


# ---------- configuração ----------

CONFIG = """
llm:
  rodizio: [groq, mistral, gemini, groq_leve]
  rodizio_acoes: [groq_leve, mistral_leve]
provedores:
  groq: {base_url: https://api.groq.com/openai/v1, chave_env: GROQ_API_KEY, modelo: openai/gpt-oss-120b}
  groq_leve: {base_url: https://api.groq.com/openai/v1, chave_env: GROQ_API_KEY, modelo: openai/gpt-oss-20b}
  mistral: {base_url: https://api.mistral.ai/v1, chave_env: MISTRAL_API_KEY, modelo: mistral-medium-latest}
  mistral_leve: {base_url: https://api.mistral.ai/v1, chave_env: MISTRAL_API_KEY, modelo: mistral-small-latest}
  gemini: {base_url: https://g/v1beta/openai/, chave_env: GEMINI_API_KEY, modelo: gemini-flash-latest}
visao:
  modelo: qwen/qwen3.8-27b
  reservas: {mistral: mistral-medium-latest, gemini: gemini-flash-latest}
"""


@pytest.fixture
def arquivo(tmp_path):
    (tmp_path / "config.yaml").write_text(CONFIG, encoding="utf-8")
    return tmp_path / "config.yaml"


def test_sem_chave_e_pulado(arquivo, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "g")
    monkeypatch.setenv("MISTRAL_API_KEY", "")
    monkeypatch.setenv("GEMINI_API_KEY", "")
    cfg = carregar(arquivo)
    assert [c.modelo for c in cfg.rodizio] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert {"mistral", "gemini"} <= set(cfg.sem_chave)
    assert [v["nome"] for v in cfg.visoes] == ["groq"]


def test_com_todas_as_chaves(arquivo, monkeypatch):
    for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(k, "x")
    cfg = carregar(arquivo)
    assert [c.provedor for c in cfg.rodizio] == ["groq", "mistral", "gemini", "groq_leve"]
    assert [c.provedor for c in cfg.rodizio_acoes] == ["groq_leve", "mistral_leve"]
    assert [v["nome"] for v in cfg.visoes] == ["groq", "mistral", "gemini"]


def test_sem_nenhuma_chave_explica(arquivo, monkeypatch):
    from socrates.config import ErroConfig
    for k in ("GROQ_API_KEY", "MISTRAL_API_KEY", "GEMINI_API_KEY"):
        monkeypatch.setenv(k, "")
    with pytest.raises(ErroConfig, match="GROQ_API_KEY"):
        carregar(arquivo)


# ---------- visão com reservas ----------

def test_visao_tenta_a_reserva(monkeypatch):
    from PIL import Image
    usados = []

    class Cliente:
        def __init__(self, base_url, api_key, timeout, max_retries):
            self.url = base_url
            self.chat = self.completions = self

        def create(self, **kw):
            usados.append(kw["model"])
            if "groq" in self.url:
                raise RuntimeError("429 limite")
            msg = type("M", (), {"content": "Uma questão de crase."})
            return type("R", (), {"choices": [type("C", (), {"message": msg})]})

    import openai
    monkeypatch.setattr(openai, "OpenAI", Cliente)
    monkeypatch.setitem(tela.VISAO, "captura", lambda: tela.preparar(Image.new("RGB", (20, 20))))
    monkeypatch.setattr(tela, "VISOES", [
        {"nome": "groq", "base_url": "https://api.groq.com/openai/v1", "chave": "k", "modelo": "qwen"},
        {"nome": "mistral", "base_url": "https://api.mistral.ai/v1", "chave": "k",
         "modelo": "mistral-medium-latest"}])
    assert tela.ver_tela("o que é?") == "O que está na tela:\nUma questão de crase."
    assert usados == ["qwen", "mistral-medium-latest"]
