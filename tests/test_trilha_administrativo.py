"""Trilha de Direito Administrativo: carreira PRF (Lei 9.654 e Decreto 8.282), Lei 8.112, 9.784, 14.133."""

import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

ADM = {t.id: t for t in carregar_trilhas()}["prf-administrativo"]


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/index.json").write_text("[]")
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


def test_trilha_bem_formada():
    assert ADM.atualizado == "2026-11-13" and ADM.plano == "prf" and len(ADM.topicos) == 9
    for t in ADM.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 5 and t.palavras and t.faixas(), t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"Lei \d|CF, art\.|STF|Doutrina|Decreto", it["j"]), (t.id, it["t"])


def test_questoes_da_prova_no_topico_certo():
    ligadas = {int(q.split("item ")[1]): t.id for t in ADM.topicos for q in t.questoes}
    assert ligadas == {86: "controle", 87: "organizacao", 88: "licitacao", 90: "controle",
                       91: "carreira-prf", 92: "carreira-prf"}


@pytest.mark.parametrize("topico,marcas", [
    ("carreira-prf", ["Terceira, Segunda, Primeira e Especial", "120 horas", "150 horas", "360 horas", "40 horas"]),
    ("agentes-publicos", ["30 dias", "15 dias", "3 anos", "até 90 dias", "180 dias", "art. 126"]),
    ("ato-administrativo", ["5 anos", "má-fé", "Súmula 473", "ex nunc"]),
    ("licitacao", ["diálogo competitivo", "Inexigibilidade (art. 74)", "DEPOIS do julgamento", "3 a 6 anos"]),
    ("controle", ["10 dias", "três instâncias", "LEGALIDADE"]),
    ("responsabilidade-civil", ["Tema 940", "OBJETIVA", "Tema 592"]),
    ("poderes", ["Tema 532", "ordem de polícia", "desvio de finalidade"]),
])
def test_conteudo_conferido(topico, marcas):
    texto = " ".join(ADM.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


@pytest.mark.parametrize("pergunta,topico", [
    ("o que é poder de polícia?", "poderes"),
    ("qual o prazo do PAD?", "agentes-publicos"),
    ("como funciona a promoção na PRF?", "carreira-prf"),
    ("a viatura da PRF bateu num carro, quem paga?", "responsabilidade-civil"),
    ("o que é inexigibilidade?", "licitacao"),
    ("primo pode ser nomeado?", "regime-juridico"),
    ("quantos anos de estágio probatório?", "agentes-publicos"),
    ("anular ou revogar um ato?", "ato-administrativo"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr.id == "prf-administrativo" and top.id == topico, (pergunta, tr and tr.id, top and top.id)


def test_legalidade_penal_continua_no_penal(tutor):
    tr, top = tutor._trilha_da_fala("princípio da legalidade")
    assert tr.id == "prf-penal"
