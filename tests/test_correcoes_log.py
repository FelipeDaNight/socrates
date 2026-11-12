"""Problemas que apareceram no uso real (socrates.log de 1º/11/2026)."""

import asyncio
import time

import numpy as np
import pytest

from socrates import ferramentas
from socrates.audio.escuta import Fala
from socrates.ferramentas import _concorda, _norm, computador
from socrates.llm.acoes import pede_acao
from socrates.llm.pesquisa import precisa_pesquisar
from socrates.stt.groq_whisper import DICA, avaliar, e_eco, sem_repeticoes
from socrates.visor import cores
from test_maos_livres import _montar, _rodar


# ---------- ouvido ----------

@pytest.mark.parametrize("texto", [
    "Fórmula de Bhaskara, teorema de Pitágoras, delta, seno, cosseno.",   # dica antiga ecoada
    "Bhaskara, Pitágoras, logaritmo, crase.",
    "Fuvest, ENEM, pomodoro, lacunas, Claude.",
])
def test_eco_da_dica_e_descartado(texto):
    from socrates.stt.groq_whisper import DICA as nova
    antiga = ("Conversa com Sócrates, assistente de estudo para concursos e vestibulares. "
              "Fórmula de Bhaskara, teorema de Pitágoras, delta, seno, cosseno, logaritmo, "
              "crase, concordância, regência, Constituição, PRF, CBMGO, Fuvest, ENEM, pomodoro, quadro.")
    assert e_eco(texto, nova) or e_eco(texto, antiga)


@pytest.mark.parametrize("texto", [
    "Sócrates, me mostra a fórmula de Bhaskara",
    "o que cai de crase e regência na PRF?",
    "Pede pro Claude mudar a cor",
])
def test_pedido_de_verdade_nao_e_eco(texto):
    assert not e_eco(texto, DICA)


def test_repeticao_alucinada_some():
    assert sem_repeticoes("Pagos, Pagos, Pagos, Pagos.") == ""
    assert sem_repeticoes("delta, seno, cosseno, cosseno, cosseno, cosseno, cosseno") == ""
    assert sem_repeticoes("Não, não, não.") == "Não, não, não."   # 3 é normal


def test_trecho_com_cara_de_ruido_e_descartado():
    resposta = {"text": "x", "segments": [
        {"text": "Sócrates, abre o Spotify.", "avg_logprob": -0.2, "no_speech_prob": 0.05,
         "compression_ratio": 1.1},
        {"text": "Obrigada.", "avg_logprob": -0.9, "no_speech_prob": 0.85, "compression_ratio": 0.8},
        {"text": "C C C C C C", "avg_logprob": -0.4, "no_speech_prob": 0.1, "compression_ratio": 3.4},
    ]}
    texto, medida = avaliar(resposta)
    assert texto == "Sócrates, abre o Spotify." and medida.descartados == 2


# ---------- confirmação ----------

@pytest.mark.parametrize("fala,esperado", [
    ("Sim, coloque no chat dele, mude minha cor pra azul.", True),   # recusado 3x no log
    ("Pode mandar, por favor", True),
    ("Ah, pode sim", True),
    ("Tá, abre o Spotify.", None),       # mudou de assunto
    ("Alô, você tem acesso ao chat?", None),
    ("Não, cancela", False),
    ("pode não", False),
    ("sim, mas muda o texto", None),
])
def test_confirmacao_entende_frases_naturais(fala, esperado):
    assert _concorda(_norm(fala)) is esperado


# ---------- roteamento ----------

def test_agora_no_meio_da_frase_nao_vira_pesquisa():
    assert not precisa_pesquisar("Sim, mas coloque no quadro agora a terceira lei de Newton")
    assert not precisa_pesquisar("O que eu reviso hoje?")
    assert precisa_pesquisar("Qual a cotação do dólar hoje?")


@pytest.mark.parametrize("frase", ["Passe a música no Spotify.", "pausa a música",
                                   "muda a cor do visor para azul", "volta o vídeo"])
def test_pedidos_de_musica_e_visor_sao_acao(frase):
    assert pede_acao(frase)


# ---------- janela pelo começo da fala ----------

@pytest.mark.asyncio
async def test_fala_que_comecou_dentro_da_janela_vale():
    conversa, s, painel, cerebro, _ = _montar(janela=0.2)
    o = s.ouvido
    fila = asyncio.Queue()
    tarefa = asyncio.create_task(conversa.rodar(fila))
    fila.put_nowait(o.fala("Sócrates, o que é crase?"))
    await asyncio.sleep(0.38)           # respondeu e abriu a janela de 0,2 s
    comecou = time.monotonic()          # começou a falar dentro da janela...
    await asyncio.sleep(0.4)            # ...mas a frase foi longa e terminou depois
    fila.put_nowait(Fala(o.fala("Me explica a regência também, com exemplos"), comecou))
    await asyncio.sleep(0.1)
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)
    assert len(cerebro.recebido) == 2


@pytest.mark.asyncio
async def test_depois_de_abrir_video_volta_a_exigir_o_nome():
    from socrates.llm.falso import CerebroFalso

    class AbreVideo(CerebroFalso):
        async def responder(self, mensagens):
            self.recebido.append(mensagens)
            ferramentas.SOM_LIGADO.set()
            yield "Pronto, abri o vídeo."

    conversa, s, painel, cerebro, _ = _montar(cerebro=AbreVideo())
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, toca lo-fi no YouTube"),
                            o.fala("Miria!"), o.fala("Os cossos ali.")])   # som do vídeo
    assert len(cerebro.recebido) == 1


@pytest.mark.asyncio
async def test_clique_no_visor_interrompe_a_fala():
    from socrates.llm.falso import CerebroFalso

    class Longo(CerebroFalso):
        async def responder(self, mensagens):
            self.recebido.append(mensagens)
            for i in range(30):
                yield f"Frase número {i} da explicação. "
                await asyncio.sleep(0.02)

    conversa, s, painel, cerebro, _ = _montar(cerebro=Longo())
    painel.falando = lambda agora=None: True
    fila = asyncio.Queue()
    tarefa = asyncio.create_task(conversa.rodar(fila))
    fila.put_nowait(s.ouvido.fala("Sócrates, explica crase"))
    await asyncio.sleep(0.15)
    painel.interromper()
    await asyncio.sleep(0.1)
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)
    assert conversa.interrompido and len(s.voz.faladas) < 10
    assert conversa.soc.historico == []      # pergunta sem resposta não fica


# ---------- cor do visor e música ----------

def test_cor_do_visor_por_nome(tmp_path, monkeypatch):
    from socrates import config
    from socrates.ferramentas import aparencia
    from socrates.visor.painel import Painel
    monkeypatch.setattr(config, "RAIZ", tmp_path)
    (tmp_path / "config.local.yaml").write_text("cerebro: nuvem\n", encoding="utf-8")
    aparencia.PAINEL = Painel()
    assert "azul" in aparencia.mudar_cor_do_visor("Azul")
    assert aparencia.PAINEL.cor == "azul"
    import yaml
    salvo = yaml.safe_load((tmp_path / "config.local.yaml").read_text(encoding="utf-8"))
    assert salvo == {"cerebro": "nuvem", "visor": {"cor": "azul"}}
    assert "Não tenho" in aparencia.mudar_cor_do_visor("xadrez")
    assert cores.resolver("lilás")[0] == cores.CORES["roxo"][0]
    aparencia.PAINEL = None


def test_spotify_busca_e_marca_som(monkeypatch):
    abertos = []
    monkeypatch.setattr(computador, "_iniciar", abertos.append)
    ferramentas.SOM_LIGADO.clear()
    computador.buscar_no_navegador("lo-fi", "spotify")
    assert abertos == ["spotify:search:lo-fi"] and ferramentas.SOM_LIGADO.is_set()
    ferramentas.SOM_LIGADO.clear()


def test_lembra_o_que_viu_na_tela(monkeypatch):
    from socrates.core import contexto
    from socrates.ferramentas import tela
    monkeypatch.setitem(tela.VISAO, "captura", lambda: b"jpeg")
    monkeypatch.setitem(tela.VISAO, "local", None)
    monkeypatch.setattr(tela, "VISOES", [])
    monkeypatch.setattr(tela, "descrever", lambda j, p: "Chat do Claude; última mensagem: 'pronto'.")
    ferramentas.executar("ver_tela", {"pergunta": "o chat"})
    texto = contexto.montar(None, False, acoes=True)
    assert "Há pouco você viu a tela do aluno" in texto and "pronto" in texto
    ferramentas.LEMBRANCA = None


def test_visao_tira_blocos_repetidos():
    from socrates.ferramentas.tela import sem_repeticao
    bloco = "O resultado do df -h mostra que o disco está cheio para uma pasta."
    assert sem_repeticao(f"{bloco}\nA) apt clean\n{bloco}\nB) du -sh").count("df -h") == 1
