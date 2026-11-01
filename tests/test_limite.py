"""Limite grátis do Groq: esperar, usar o modelo reserva, falar o motivo; pedidos enxutos."""

import json

import httpx2 as httpx
import pytest

from socrates.config import ConfigLLM
from socrates.core.orquestrador import compactar
from socrates.llm import CerebroCompativelOpenAI, ErroCerebro, criar_cerebro
from socrates.llm.acoes import CerebroComAcoes, _com_instrucao


def _ok(texto="ok"):
    return httpx.Response(200, json={
        "id": "1", "object": "chat.completion", "created": 0, "model": "m",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": texto}}]})


def _limite(retry_after=None, msg="Rate limit reached on tokens per minute (TPM): Limit 8000"):
    cab = {"retry-after": str(retry_after)} if retry_after is not None else {}
    return httpx.Response(429, headers=cab, json={"error": {"message": msg,
                                                           "type": "tokens", "code": "rate_limit_exceeded"}})


def _cerebro(responder, reserva="openai/gpt-oss-20b"):
    cli = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    return CerebroCompativelOpenAI("https://api.groq.com/openai/v1", "k", "openai/gpt-oss-120b",
                                   http_client=cli, modelo_reserva=reserva)


async def _ferramentas(c):
    async def executar(n, a):
        return "x"
    return await c.com_ferramentas([{"role": "user", "content": "oi"}], [], executar)


@pytest.mark.asyncio
async def test_espera_o_tempo_que_o_groq_pede(monkeypatch):
    esperas, modelos = [], []
    monkeypatch.setattr("socrates.llm.compativel_openai.asyncio.sleep",
                        lambda s: esperas.append(s) or _nada())

    def groq(req):
        modelos.append(json.loads(req.content)["model"])
        return _limite(retry_after=3) if len(modelos) == 1 else _ok("Pronto.")

    assert await _ferramentas(_cerebro(groq)) == "Pronto."
    assert modelos == ["openai/gpt-oss-120b", "openai/gpt-oss-120b"] and esperas == [3.3]


async def _nada():
    return None


@pytest.mark.asyncio
async def test_espera_longa_vai_para_a_reserva():
    modelos = []

    def groq(req):
        m = json.loads(req.content)["model"]
        modelos.append(m)
        return _limite(retry_after=40) if m == "openai/gpt-oss-120b" else _ok("Pela reserva.")

    c = _cerebro(groq)
    assert await _ferramentas(c) == "Pela reserva."
    assert modelos == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    assert c.modelo_da_vez() == "openai/gpt-oss-20b"     # continua na reserva por um tempo


@pytest.mark.asyncio
async def test_os_dois_no_limite_explica():
    c = _cerebro(lambda req: _limite(retry_after=40))
    with pytest.raises(ErroCerebro, match="limite grátis do Groq"):
        await _ferramentas(c)


@pytest.mark.asyncio
async def test_limite_do_dia_explica():
    c = _cerebro(lambda req: _limite(msg="Rate limit reached on tokens per day (TPD)"), reserva=None)
    with pytest.raises(ErroCerebro, match="limite grátis de hoje"):
        await _ferramentas(c)


def test_acoes_usam_outro_modelo():
    cfg = ConfigLLM("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "k",
                    modelo_acoes="openai/gpt-oss-20b")
    c = criar_cerebro(cfg, pesquisa=True, acoes=True)
    assert isinstance(c, CerebroComAcoes)
    assert c.base.modelo == "openai/gpt-oss-20b" and c.base.modelo_reserva == "openai/gpt-oss-120b"
    assert c.interno.base.modelo == "openai/gpt-oss-120b"
    assert c.interno.base.modelo_reserva == "openai/gpt-oss-20b"


def test_pedido_de_acao_e_enxuto():
    sistema = ("persona enorme " * 400 + "\nAgora é domingo, 1 de novembro de 2026, 12:30.\n"
               "O aluno mora em Morrinhos, Goiás.")
    historico = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"msg {i} " + "x" * 900}
                 for i in range(20)]
    historico.append({"role": "user", "content": "abre a calculadora"})
    msgs = _com_instrucao([{"role": "system", "content": sistema}, *historico])
    assert "persona enorme" not in msgs[0]["content"]
    assert "Agora é domingo" in msgs[0]["content"] and "Morrinhos" in msgs[0]["content"]
    assert len(msgs) == 1 + 6 and msgs[-1]["content"] == "abre a calculadora"
    total = sum(len(m["content"]) for m in msgs)
    assert total < 5000


def test_historico_antigo_fica_curto():
    quadro = "Veja. [QUADRO]\n# Bhaskara\n$$ x = 1 $$\n" + "linha\n" * 200 + "[/QUADRO] Entendeu?"
    hist = [{"role": "user", "content": "me explica Bhaskara"},
            {"role": "assistant", "content": quadro},
            {"role": "user", "content": "e o delta?"},
            {"role": "assistant", "content": "O delta é b² - 4ac."}]
    c = compactar(hist)
    assert c[1]["content"] == "Veja. [quadro mostrado: Bhaskara] Entendeu?"
    assert c[3] == hist[3] and hist[1]["content"] == quadro   # não altera o original
