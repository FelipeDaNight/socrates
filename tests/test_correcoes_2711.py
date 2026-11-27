"""Correções da noite de 26/11 (achadas no registro do Sócrates)."""

import httpx2 as httpx
import pytest

from socrates.estudo import leitor_lei
from socrates.estudo.leitor_lei import url_ascii
from socrates.llm import CerebroCompativelOpenAI, ErroCerebro
from socrates.llm.compativel_openai import nome_do_servico


# ---------------------------------------------------------------- limite fala o serviço certo

def test_nome_do_servico_pelo_endereco():
    assert nome_do_servico("https://api.groq.com/openai/v1") == "Groq"
    assert nome_do_servico("https://generativelanguage.googleapis.com/v1beta/openai/") == "Gemini"
    assert nome_do_servico("https://api.mistral.ai/v1") == "Mistral"
    assert nome_do_servico("https://openrouter.ai/api/v1") == "OpenRouter"


@pytest.mark.asyncio
async def test_limite_do_dia_do_gemini_nao_diz_groq():
    # 26/11, 21h17: o Gemini estourou os 20 pedidos do dia e a mensagem dizia "do Groq"
    def gemini(req):
        return httpx.Response(429, json=[{"error": {
            "code": 429, "status": "RESOURCE_EXHAUSTED",
            "message": "Generate content requests per day limit exceeded on Free Tier."}}])

    cli = httpx.AsyncClient(transport=httpx.MockTransport(gemini))
    c = CerebroCompativelOpenAI("https://generativelanguage.googleapis.com/v1beta/openai/", "k",
                                "gemini-flash-latest", http_client=cli)
    with pytest.raises(ErroCerebro) as erro:
        await c.com_ferramentas([{"role": "user", "content": "oi"}], [], lambda n, a: "")
    assert "limite grátis de hoje do Gemini" in str(erro.value)
    assert "Groq" not in str(erro.value)


# ---------------------------------------------------------------- endereço com acento

def test_url_com_acento_vira_ascii():
    u = url_ascii("https://coggle.it/diagram/W-_1ViXDNK3cYVg1/t/goiás-1-formação-econômica-de-goiás")
    assert u.isascii()
    assert u == ("https://coggle.it/diagram/W-_1ViXDNK3cYVg1/t/"
                 "goi%C3%A1s-1-forma%C3%A7%C3%A3o-econ%C3%B4mica-de-goi%C3%A1s")


def test_url_ascii_nao_mexe_no_que_ja_funciona():
    u = "https://www.planalto.gov.br/ccivil_03/leis/l9503.htm?x=1&y=%C3%A1#art5"
    assert url_ascii(u) == u


def test_url_com_acento_na_busca_e_no_dominio():
    u = url_ascii("https://pt.wikipédia.org/w/index.php?search=efeito Doppler&ação=1")
    assert u.isascii()
    assert u.startswith("https://pt.xn--wikipdia-f1a.org/w/index.php?search=efeito%20Doppler&a")


def test_baixar_manda_o_endereco_ja_em_ascii(monkeypatch):
    visto = {}

    class _Resposta:
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def read(self):
            return "<p>Goiás</p>".encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def abrir(pedido, timeout=None):
        visto["url"] = pedido.full_url
        return _Resposta()

    monkeypatch.setattr(leitor_lei.urllib.request, "urlopen", abrir)
    texto = leitor_lei.baixar("https://coggle.it/t/goiás")
    assert visto["url"] == "https://coggle.it/t/goi%C3%A1s"
    assert "Goiás" in texto
