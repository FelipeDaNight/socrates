import pytest

from socrates.core.estados import Estado
from socrates.core.frases import em_frases
from socrates.core.orquestrador import Orquestrador
from socrates.ferramentas import REGISTRO, ferramenta
from socrates.llm import ErroCerebro
from socrates.llm.falso import CerebroFalso


async def _juntar(gerador):
    return "".join([p async for p in gerador])


@pytest.mark.asyncio
async def test_conversa_guarda_historico_e_volta_a_dormir():
    soc = Orquestrador(CerebroFalso("Fotossíntese transforma luz em energia."))
    resposta = await _juntar(soc.conversar("O que é fotossíntese?"))
    assert "Fotossíntese" in resposta
    assert [m["role"] for m in soc.historico] == ["user", "assistant"]
    assert soc.estado == Estado.DORMINDO


@pytest.mark.asyncio
async def test_passa_pelos_estados_na_ordem():
    soc = Orquestrador(CerebroFalso("Oi."))
    vistos = []
    soc.ao_mudar_estado(lambda antigo, novo: vistos.append(novo))
    await _juntar(soc.conversar("oi"))
    assert vistos == [Estado.OUVINDO, Estado.PENSANDO, Estado.FALANDO, Estado.DORMINDO]


@pytest.mark.asyncio
async def test_modo_testar_vai_no_prompt_de_sistema():
    cerebro = CerebroFalso("Pergunta 1.")
    soc = Orquestrador(cerebro, modo="testar")
    await _juntar(soc.conversar("Me testa em direito constitucional"))
    sistema = cerebro.recebido[0][0]
    assert sistema["role"] == "system" and "TESTAR" in sistema["content"]


@pytest.mark.asyncio
async def test_historico_respeita_limite():
    cerebro = CerebroFalso("ok")
    soc = Orquestrador(cerebro, historico_max=4)
    for i in range(5):
        await _juntar(soc.conversar(f"pergunta {i}"))
    enviado = cerebro.recebido[-1]
    assert len(enviado) == 1 + 4   # sistema + 4 recentes


@pytest.mark.asyncio
async def test_erro_no_cerebro_nao_suja_historico():
    class Quebrado(CerebroFalso):
        async def responder(self, mensagens):
            raise ErroCerebro("sem internet")
            yield  # pragma: no cover

    soc = Orquestrador(Quebrado())
    with pytest.raises(ErroCerebro):
        await _juntar(soc.conversar("oi"))
    assert soc.historico == [] and soc.estado == Estado.DORMINDO


@pytest.mark.asyncio
async def test_frases_quebram_no_lugar_certo():
    async def fluxo():
        for p in ["A capital de Goiás ", "é Goiânia. Ela foi ", "fundada em 1933! Legal?"]:
            yield p

    frases = [f async for f in em_frases(fluxo())]
    assert frases == ["A capital de Goiás é Goiânia.", "Ela foi fundada em 1933!", "Legal?"]


def test_ferramenta_gera_esquema():
    @ferramenta("Soma dois números", confirmar=True)
    def somar(a: int, b: int = 0) -> int:
        return a + b

    f = REGISTRO["somar"]
    esq = f.esquema()["function"]
    assert f.confirmar and esq["parameters"]["required"] == ["a"]
    assert esq["parameters"]["properties"]["a"]["type"] == "integer"
