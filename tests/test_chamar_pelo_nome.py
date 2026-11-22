""""Ele não está entendendo quando chamo ele" (22/11/2026).

No registro: depois de atualizar, 4 minutos de chamados sem nenhuma transcrição, e depois
"Alô, Sócrates, Sócrates, Sócrates". Fora da janela de conversa, a falha da transcrição era
engolida calada (internet lenta naquela hora: a busca do autoestudo deu "operation timed
out"), e a transcrição não tinha limite de tempo (até 10 min presa). Também: o Whisper erra
o nome ("Socates", "Sucrates") e o autoestudo disputava o limite grátis com a conversa.
"""

import asyncio
import logging

import numpy as np
import pytest

from socrates.audio.escuta import Escuta
from socrates.core.despertar import chamou, e_o_nome
from socrates.stt import ErroOuvido
from socrates.visor.quadro import interpretar

from test_maos_livres import _montar, _rodar


@pytest.mark.parametrize("fala,pedido", [
    ("Alô, Sócrates, Sócrates, Sócrates.", ""),
    ("Sócrates, Sócrates, abre o bloco de notas", "abre o bloco de notas"),
    ("Socates, que horas são?", "que horas são?"),
    ("Sucrates me ajuda", "me ajuda"),
    ("Ei Socrades, abre o Spotify", "abre o Spotify"),
    ("Sokrates.", ""),
])
def test_nome_mal_ouvido_ainda_chama(fala, pedido):
    assert chamou(fala) == (True, pedido)


@pytest.mark.parametrize("fala", ["o método socrático é bom", "Democrates venceu a eleição",
                                  "Sorteios de hoje", "o que Sócrates dizia sobre ética"])
def test_palavras_parecidas_nao_chamam(fala):
    assert chamou(fala)[0] is False


def test_e_o_nome():
    assert e_o_nome("socrates") and e_o_nome("socates") and not e_o_nome("sorte")


def test_transcricao_tem_limite_de_tempo():
    from socrates.stt.groq_whisper import TEMPO_MAXIMO, OuvidoWhisper
    o = OuvidoWhisper("http://x", "k")
    assert o._cliente.timeout == TEMPO_MAXIMO <= 30 and o._cliente.max_retries == 1


class OuvidoQueFalha:
    def __init__(self, vezes):
        self.vezes = vezes
        self.chamadas = 0

    async def transcrever(self, wav, dica=None):
        self.chamadas += 1
        if self.chamadas <= self.vezes:
            raise ErroOuvido("Sem conexão para transcrever. Verifique a internet.")
        return "Sócrates, oi"


@pytest.mark.asyncio
async def test_falha_ao_chamar_nao_fica_calada(caplog):
    conversa, s, *_ = _montar()
    s.ouvido = OuvidoQueFalha(2)
    audio = np.full(1600, 1, dtype=np.int16)
    with caplog.at_level(logging.WARNING, logger="socrates.conversa"):
        await _rodar(conversa, [audio, audio, audio])
    assert sum("não consegui transcrever" in r.message for r in caplog.records) == 2
    assert any("Não estou conseguindo te ouvir" in f for f in s.voz.faladas)
    assert "não consegui ouvir" in conversa.painel.aprendendo
    assert conversa._falhas_ouvido == 0                 # a 3ª deu certo: zera


@pytest.mark.asyncio
async def test_aviso_falado_no_maximo_a_cada_5_minutos():
    conversa, s, *_ = _montar()
    s.ouvido = OuvidoQueFalha(6)
    audio = np.full(1600, 1, dtype=np.int16)
    await _rodar(conversa, [audio] * 6)
    assert sum("Não estou conseguindo te ouvir" in f for f in s.voz.faladas) == 1


def test_microfone_registra_chamado_baixo_demais(caplog):
    e = Escuta()
    e.seg.piso = 400.0                                   # limiar = 1200
    with caplog.at_level(logging.INFO, logger="socrates.escuta"):
        e._diagnosticar(900.0, None, agora=e._pico_desde + 1)
        e._diagnosticar(100.0, None, agora=e._pico_desde + 61)
    assert any("perto do limiar" in r.message and "pico 900" in r.message for r in caplog.records)
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="socrates.escuta"):
        e._diagnosticar(100.0, None, agora=e._pico_desde + 61)   # sala quieta: nada
    assert not caplog.records


def test_quadro_sem_asteriscos_do_markdown():
    itens = interpretar("# Art. 5º\n- **Caput**: todos são iguais\n1. Inciso I\n**Atenção** ao $x^2$")
    assert [i.conteudo for i in itens] == ["Art. 5º", "Caput: todos são iguais", "1. Inciso I",
                                           "Atenção ao $x^2$"]
    assert itens[2].tipo == "item"


@pytest.mark.asyncio
async def test_autoestudo_espera_a_conversa():
    from socrates.estudo.autoestudo import Autoestudo
    from socrates.estudo.plano import carregar_planos
    estado = {"ocupado": True}
    a = Autoestudo(carregar_planos(ids=["prf"]), escritor=None, buscar=None, ler=None,
                   ocupado=lambda: estado["ocupado"])

    async def soltar():
        await asyncio.sleep(1.2)
        estado["ocupado"] = False

    inicio = asyncio.get_running_loop().time()
    await asyncio.gather(a._esperar_conversa(maximo=5), soltar())
    assert 1.0 <= asyncio.get_running_loop().time() - inicio < 4
