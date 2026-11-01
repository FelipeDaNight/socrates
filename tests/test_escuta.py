"""Escuta contínua, palavra de ativação e painel do visor."""

import asyncio

import numpy as np
import pytest

from socrates.audio.escuta import Escuta
from socrates.audio.microfone import AjustesMic, Segmentador
from socrates.core.despertar import chamou
from socrates.visor.painel import Painel, envelope

TAXA = 16_000
BLOCO = 480


def _ruido(seg, nivel=60, semente=0):
    return np.random.default_rng(semente).normal(0, nivel, int(TAXA * seg)).astype(np.int16)


def _voz(seg, amplitude=3000):
    t = np.arange(int(TAXA * seg)) / TAXA
    return (amplitude * np.sin(2 * np.pi * 220 * t)).astype(np.int16)


def _alimentar(alvo, sinal):
    falas = []
    for i in range(0, len(sinal) - BLOCO + 1, BLOCO):
        f = alvo(sinal[i:i + BLOCO])
        if f is not None:
            falas.append(f)
    return falas


# ---------- segmentador contínuo ----------

def test_segmentador_entrega_varias_falas_seguidas():
    sinal = np.concatenate([_ruido(1), _voz(1.5), _ruido(2, semente=1), _voz(0.8),
                            _ruido(2, semente=2)])
    falas = _alimentar(Segmentador().alimentar, sinal)
    assert len(falas) == 2
    assert 2.5 < len(falas[0]) / TAXA < 3.2
    assert 1.8 < len(falas[1]) / TAXA < 2.6


def test_segmentador_ignora_estalo_curto():
    sinal = np.concatenate([_ruido(1), _voz(0.12), _ruido(2, semente=1)])
    assert _alimentar(Segmentador().alimentar, sinal) == []


def test_segmentador_nao_desiste_no_silencio_longo():
    sinal = np.concatenate([_ruido(1), _ruido(20, semente=1), _voz(1), _ruido(2, semente=2)])
    assert len(_alimentar(Segmentador().alimentar, sinal)) == 1


def test_segmentador_reaprende_ruido_que_aumentou():
    seg = Segmentador()
    _alimentar(seg.alimentar, _ruido(1, nivel=50))
    limiar_antes = seg.limiar
    _alimentar(seg.alimentar, _ruido(6, nivel=400, semente=3))   # ventilador ligou
    assert seg.limiar > limiar_antes * 4
    assert not seg.falando


def test_segmentador_corta_fala_longa_demais():
    sinal = np.concatenate([_ruido(1), _voz(12), _ruido(2, semente=1)])
    falas = _alimentar(Segmentador(AjustesMic(max_seg=5)).alimentar, sinal)
    assert falas and len(falas[0]) / TAXA <= 5.1


# ---------- escuta ----------

def test_escuta_pausada_nao_ouve_nada():
    painel = Painel()
    esc = Escuta(painel=painel)
    _alimentar(esc.processar, _ruido(1))
    esc.pausar()
    assert _alimentar(esc.processar, np.concatenate([_voz(1.5), _ruido(2)])) == []
    assert painel.nivel_mic == 0
    esc.pausada = False
    falas = _alimentar(esc.processar, np.concatenate([_voz(1.5), _ruido(2, semente=4)]))
    assert len(falas) == 1


def test_escuta_mostra_no_painel_que_alguem_fala():
    painel = Painel()
    esc = Escuta(painel=painel)
    _alimentar(esc.processar, np.concatenate([_ruido(1), _voz(0.5)]))
    assert painel.ouvindo and painel.nivel_mic > 0.5


@pytest.mark.asyncio
async def test_retomar_descarta_falas_velhas_mas_mantem_texto_digitado():
    esc = Escuta()
    esc.fila = asyncio.Queue()
    esc.fila.put_nowait(np.zeros(10, dtype=np.int16))   # o eco da própria voz
    esc.fila.put_nowait("/testar")                      # algo que você digitou
    esc.pausar()
    esc.retomar()
    assert esc.fila.qsize() == 1 and esc.fila.get_nowait() == "/testar"


# ---------- palavra de ativação ----------

@pytest.mark.parametrize("fala,esperado", [
    ("Sócrates, o que é crase?", (True, "o que é crase?")),
    ("Sócrates. Me testa em crase.", (True, "Me testa em crase.")),
    ("Ei, Sócrates, modo prova.", (True, "modo prova.")),
    ("Bom dia, Sócrates!", (True, "")),
    ("Sócrates?", (True, "")),
    ("Socrates explica concordância", (True, "explica concordância")),
    ("Só crates, tudo bem?", (True, "tudo bem?")),
    ("O que é crase, Sócrates?", (True, "O que é crase?")),
    ("Me explica isso Sócrates", (True, "Me explica isso")),
    ("O que Sócrates dizia sobre a ética?", (False, "O que Sócrates dizia sobre a ética?")),
    ("Vou almoçar agora.", (False, "Vou almoçar agora.")),
    ("", (False, "")),
])
def test_palavra_de_ativacao(fala, esperado):
    assert chamou(fala) == esperado


# ---------- painel ----------

def test_painel_estados_visuais():
    p = Painel()
    assert p.visual(100) == "dormindo"
    p.janela_ate = 200
    assert p.visual(100) == "atento"
    p.ouvindo = True
    assert p.visual(100) == "ouvindo"
    p.estado = "pensando"
    assert p.visual(100) == "pensando"
    p.iniciar_fala(np.ones(10))
    assert p.visual(100) == "falando"


def test_painel_segue_falando_entre_frases():
    p = Painel()
    p.iniciar_fala(np.ones(5))
    p.fim_fala()
    assert p.falando()                  # a próxima frase vem logo
    assert not p.falando(p._env_fim + 1)


def test_envelope_acompanha_o_volume():
    taxa = 24_000
    t = np.arange(taxa) / taxa
    som = (np.sin(2 * np.pi * 200 * t) * np.where(t < 0.5, 8000, 800)).astype(np.int16)
    env = envelope(som, taxa)
    assert len(env) == 33
    assert env[:15].mean() > 0.9 and env[-15:].mean() < 0.15


def test_nivel_da_voz_segue_o_tempo():
    p = Painel()
    p.iniciar_fala(np.array([0.1, 0.9, 0.3]))
    inicio = p._env_inicio
    assert p.nivel_voz(inicio + 0.01) == pytest.approx(0.1)
    assert p.nivel_voz(inicio + 0.04) == pytest.approx(0.9)
    assert p.nivel_voz(inicio + 5) == 0.0
