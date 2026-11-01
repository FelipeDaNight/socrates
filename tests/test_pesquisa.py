"""Pesquisa na internet e noção de data, sem internet de verdade."""

import json
from datetime import datetime

import httpx2 as httpx
import pytest

from socrates.config import ConfigLLM
from socrates.core import contexto
from socrates.core.orquestrador import Orquestrador
from socrates.llm import CerebroCompativelOpenAI, ErroPesquisa, criar_cerebro
from socrates.llm.falso import CerebroFalso
from socrates.llm.pesquisa import (AVISO, CerebroComPesquisa, limpar_resposta,
                                   precisa_pesquisar)


# ---------- data e cidade ----------

def test_data_por_extenso():
    momento = datetime(2026, 11, 1, 9, 5)
    assert contexto.data_por_extenso(momento) == "domingo, 1 de novembro de 2026, 09:05"


def test_contexto_tem_data_cidade_e_regra_de_pesquisa():
    texto = contexto.montar("Morrinhos, Goiás", True, datetime(2026, 11, 1, 9, 5))
    assert "domingo, 1 de novembro de 2026" in texto
    assert "Morrinhos, Goiás" in texto
    assert "PESQUISAR" in texto
    sem = contexto.montar(None, False, datetime(2026, 11, 1, 9, 5))
    assert "PESQUISAR" not in sem and "NÃO tem acesso à internet" in sem


def test_fuso_de_brasilia():
    assert contexto.agora().utcoffset() is not None


@pytest.mark.asyncio
async def test_orquestrador_manda_a_hora_atual_em_cada_pergunta():
    horas = iter(["Agora é 09:00.", "Agora é 09:30."])
    cerebro = CerebroFalso("ok")
    soc = Orquestrador(cerebro, contexto=lambda: next(horas))
    for _ in range(2):
        async for _p in soc.conversar("que horas são?"):
            pass
    assert "09:00" in cerebro.recebido[0][0]["content"]
    assert "09:30" in cerebro.recebido[1][0]["content"]


# ---------- quando pesquisar ----------

@pytest.mark.parametrize("pergunta,esperado", [
    ("Qual a cotação do dólar hoje?", True),
    ("Vai chover em Morrinhos amanhã?", True),
    ("Quando sai o edital da PRF?", True),
    ("Quem ganhou o jogo do Goiás?", True),
    ("Pesquisa pra mim o horário da farmácia", True),
    ("Procura na internet as últimas notícias", True),
    ("Quanto custa um iPhone?", True),
    ("O que é crase?", False),
    ("Me explica o que aconteceu na Revolução Francesa", False),
    ("Quero estudar português hoje, me testa em crase", False),
    ("Qual a fórmula de Bhaskara?", False),
    ("O que é pesquisa de campo?", False),
    ("Que dia é hoje?", False),
    ("Que horas são agora?", False),
    ("Que dia sai o edital do CBMGO?", True),
])
def test_quando_pesquisar(pergunta, esperado):
    assert precisa_pesquisar(pergunta) is esperado


def test_limpa_citacoes_e_links():
    sujo = ("O dólar fechou a R$ 5,42【2†L6-L10】, segundo o g1 [1]. "
            "Veja em (https://g1.globo.com/economia).")
    assert limpar_resposta(sujo) == "O dólar fechou a R$ 5,42, segundo o g1. Veja em."


# ---------- cérebro com pesquisa ----------

class BaseFalsa(CerebroFalso):
    def __init__(self, resposta, pesquisa="O dólar está em R$ 5,42, segundo o g1.", erro=None):
        super().__init__(resposta)
        self.resposta_pesquisa = pesquisa
        self.erro = erro
        self.pesquisas: list[list] = []

    async def pesquisar(self, mensagens):
        self.pesquisas.append(mensagens)
        if self.erro:
            raise self.erro
        return self.resposta_pesquisa


async def _texto(cerebro, pergunta):
    msgs = [{"role": "system", "content": "persona"}, {"role": "user", "content": pergunta}]
    return "".join([p async for p in cerebro.responder(msgs)])


@pytest.mark.asyncio
async def test_pergunta_atual_vai_direto_para_a_pesquisa():
    base = BaseFalsa("não deveria aparecer")
    texto = await _texto(CerebroComPesquisa(base), "Qual a cotação do dólar hoje?")
    assert texto == AVISO + "O dólar está em R$ 5,42, segundo o g1."
    assert base.recebido == []   # nem tentou responder sem pesquisar
    assert "pesquisar na internet" in base.pesquisas[0][0]["content"]
    assert base.pesquisas[0][0]["content"].startswith("persona")


@pytest.mark.asyncio
async def test_modelo_pede_pesquisa_com_o_marcador():
    base = BaseFalsa("PESQUISAR")
    texto = await _texto(CerebroComPesquisa(base), "Quem é o técnico da seleção?")
    assert "PESQUISAR" not in texto
    assert texto.startswith(AVISO) and len(base.pesquisas) == 1


@pytest.mark.asyncio
async def test_pergunta_de_estudo_responde_sem_pesquisar():
    base = BaseFalsa("Crase é a fusão de duas letras a. Entendeu?")
    texto = await _texto(CerebroComPesquisa(base), "O que é crase?")
    assert texto.strip() == "Crase é a fusão de duas letras a. Entendeu?"
    assert base.pesquisas == []


@pytest.mark.asyncio
async def test_resposta_curta_nao_e_confundida_com_o_marcador():
    base = BaseFalsa("Sim.")
    assert (await _texto(CerebroComPesquisa(base), "Dois mais dois é quatro?")).strip() == "Sim."
    assert base.pesquisas == []


@pytest.mark.asyncio
async def test_falha_na_pesquisa_vira_frase_falada():
    base = BaseFalsa("x", erro=ErroPesquisa("Limite de pesquisas atingido. Espere um pouco."))
    texto = await _texto(CerebroComPesquisa(base), "Qual a cotação do dólar?")
    assert texto == AVISO + "Não consegui pesquisar agora. Limite de pesquisas atingido. Espere um pouco."


def test_fabrica_so_liga_pesquisa_no_groq_gpt_oss():
    groq = ConfigLLM("groq", "https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "k")
    gemini = ConfigLLM("gemini", "https://x", "gemini-flash-latest", "k")
    assert isinstance(criar_cerebro(groq, pesquisa=True), CerebroComPesquisa)
    assert not isinstance(criar_cerebro(gemini, pesquisa=True), CerebroComPesquisa)
    assert not isinstance(criar_cerebro(groq, pesquisa=False), CerebroComPesquisa)


# ---------- pedido real ao Groq (simulado) ----------

def _groq(responder):
    cliente = httpx.AsyncClient(transport=httpx.MockTransport(responder))
    return CerebroCompativelOpenAI("https://api.groq.com/openai/v1", "chave", "openai/gpt-oss-120b",
                                   http_client=cliente, tentativas=1)


@pytest.mark.asyncio
async def test_pedido_de_pesquisa_no_formato_do_groq():
    pedidos = []

    def responder(req):
        pedidos.append(json.loads(req.content))
        return httpx.Response(200, json={
            "id": "1", "object": "chat.completion", "created": 0, "model": "openai/gpt-oss-120b",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant",
                                     "content": "O dólar fechou a R$ 5,42【0†L1-L3】."}}],
        })

    texto = await _groq(responder).pesquisar([{"role": "user", "content": "dólar hoje?"}])
    corpo = pedidos[0]
    assert corpo["tools"] == [{"type": "browser_search"}]
    assert corpo["tool_choice"] == "required"
    assert corpo["reasoning_effort"] == "low"
    assert corpo["stream"] is False
    assert limpar_resposta(texto) == "O dólar fechou a R$ 5,42."


@pytest.mark.asyncio
async def test_groq_recusando_a_pesquisa_explica_o_motivo():
    def responder(req):
        return httpx.Response(400, json={"error": {
            "message": "browser_search is not available on the free tier",
            "type": "invalid_request_error"}})

    with pytest.raises(ErroPesquisa, match="free tier"):
        await _groq(responder).pesquisar([{"role": "user", "content": "dólar?"}])
