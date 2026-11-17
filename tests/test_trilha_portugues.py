"""Trilha de Língua Portuguesa (PRF): gramática da norma padrão e Manual de Redação da
Presidência da República (3ª ed.), com as questões 9 a 26 da PRF 2021 ligadas a cada tópico."""

import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

TRILHAS = {t.id: t for t in carregar_trilhas()}
PT = TRILHAS["prf-portugues"]


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
    assert PT.atualizado == "2026-11-16" and PT.plano == "prf" and len(PT.topicos) == 14
    for t in PT.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 5 and t.palavras and len(t.pegadinhas) >= 2, t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"Gramática|MRPR|Método|Inferência", it["j"]), (t.id, it["t"])
        for p in t.palavras:
            assert p == p.lower() and not re.search(r"[áàâãéêíóôõúç]", p), (t.id, p)


def test_questoes_da_prova_no_topico_certo():
    ligadas = {}
    for t in PT.topicos:
        for q in t.questoes:
            ligadas.setdefault(int(q.split("item ")[1]), set()).add(t.id)
    assert set(ligadas) == set(range(9, 27))                   # todos os itens de português da PRF 2021
    assert ligadas[18] == {"concordancia"} and ligadas[22] == {"redacao-oficial"}
    assert ligadas[19] == {"periodo", "coesao"} and ligadas[14] == {"interpretacao"}


@pytest.mark.parametrize("topico,marcas", [
    ("redacao-oficial", ["Informatividade' NÃO", "Respeitosamente", "abolidos", "ICP-Brasil", "4 a 5 palavras", "aviso e o memorando"]),
    ("crase", ["palavra masculina", "Facultativa", "horas exatas", "volto da"]),
    ("concordancia", ["impessoais", "Deve haver", "anexas", "item 18"]),
    ("periodo", ["restritiva", "explicativa", "à medida que", "na medida em que"]),
    ("ortografia", ["2009", "micro-ondas", "pôde", "heroico"]),
])
def test_conteudo_conferido(topico, marcas):
    texto = " ".join(PT.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


def test_gabarito_da_prova_bate_com_os_pontos():
    """Os itens da PRF 2021 citados nos pontos têm o gabarito oficial (22 E, 23 E, 24 C, 25 E, 26 C)."""
    ro = " ".join(PT.topico("redacao-oficial").pontos)
    assert "item 22 da PRF 2021" in ro and "item 26, Certo" in ro and "item 24, Certo" in ro
    assert "item 23 da PRF 2021 é Errado" in ro and "item 25 da PRF 2021, Errado" in ro


@pytest.mark.parametrize("pergunta,topico", [
    ("quando usa crase?", "crase"),
    ("questões de concordância", "concordancia"),
    ("vírgula antes do e pode?", "pontuacao"),
    ("qual o fecho de um ofício para o ministro?", "redacao-oficial"),
    ("me ensina colocação pronominal", "colocacao-pronominal"),
    ("diferença entre por que e porque", "ortografia"),
    ("oração adjetiva restritiva e explicativa", "periodo"),
    ("como fazer interpretação de texto da cebraspe", "interpretacao"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr is not None and tr.id == "prf-portugues" and top is not None and top.id == topico, (
        pergunta, tr and tr.id, top and top.id)


def test_portugues_no_brasil_continua_em_constitucional(tutor):
    tr, top = tutor._trilha_da_fala("português no Brasil tem os direitos de brasileiro?")
    assert tr.id == "prf-constitucional" and top.id == "nacionalidade"


def test_aula_de_portugues(tutor):
    s = tutor.atender("me ensina crase")
    assert tutor.aula is not None and tutor.aula.topico.id == "crase" and "Crase" in s.quadro
