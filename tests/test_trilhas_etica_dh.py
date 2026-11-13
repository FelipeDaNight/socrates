"""Trilhas de Ética e Cidadania e de Direitos Humanos: decretos de ética, LAI, conflito de
interesses, governança, tratados, DUDH e Pacto de São José."""

import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

TRILHAS = {t.id: t for t in carregar_trilhas()}
ETICA, DH = TRILHAS["prf-etica"], TRILHAS["prf-direitos-humanos"]


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/index.json").write_text("[]")
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


@pytest.mark.parametrize("trilha,n", [(ETICA, 7), (DH, 4)])
def test_trilhas_bem_formadas(trilha, n):
    assert trilha.atualizado == "2026-11-13" and trilha.plano == "prf" and len(trilha.topicos) == n
    for t in trilha.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 4 and t.palavras and t.faixas(), t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"Lei \d|CF, art\.|STF|Doutrina|Decreto", it["j"]), (t.id, it["t"])


def test_questoes_da_prova_no_topico_certo():
    etica = {int(q.split("item ")[1]): t.id for t in ETICA.topicos for q in t.questoes}
    assert etica == {46: "codigo-etica", 47: "governanca", 48: "gestao-etica", 49: "lai", 50: "conflito-interesses"}
    dh = {int(q.split("item ")[1]): t.id for t in DH.topicos for q in t.questoes}
    assert dh == {116: "dh-cf-tratados", 117: "dh-cf-tratados", 118: "dh-cf-tratados", 119: "dudh",
                  120: "dh-cf-tratados"}


@pytest.mark.parametrize("trilha,topico,marcas", [
    (ETICA, "codigo-etica", ["INJUSTIFICADA", "CENSURA", "honesto e o desonesto"]),
    (ETICA, "gestao-etica", ["sete brasileiros", "três membros titulares e três suplentes", "MESMO QUE AINDA NÃO TENHA SIDO NOTIFICADO", "10 dias"]),
    (ETICA, "lai", ["20 dias", "mais 10", "25 anos", "15 anos", "100 anos", "FACULTADO", "motivos"]),
    (ETICA, "conflito-interesses", ["terceiro grau", "QUARTO grau", "6 meses", "a qualquer tempo"]),
    (ETICA, "governanca", ["liderança, estratégia e controle", "capacidade de resposta", "melhoria regulatória"]),
    (DH, "dh-cf-tratados", ["três quintos", "supralegal", "Súmula Vinculante 25", "ADI 4275", "STJ"]),
    (DH, "pacto-sao-jose", ["7.5", "obrigação alimentar", "art. 61", "1998", "Decreto 678/1992"]),
    (DH, "dudh", ["1948", "resolução", "(14)", "(art. 29)"]),
])
def test_conteudo_conferido(trilha, topico, marcas):
    texto = " ".join(trilha.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


@pytest.mark.parametrize("pergunta,trilha,topico", [
    ("o que é a comissão de ética?", "prf-etica", "gestao-etica"),
    ("qual a pena da comissão de ética?", "prf-etica", "codigo-etica"),
    ("prazo da LAI", "prf-etica", "lai"),
    ("posso contratar a empresa do meu primo?", "prf-etica", "conflito-interesses"),
    ("quarentena depois de sair do cargo", "prf-etica", "conflito-interesses"),
    ("ética e moral diferença", "prf-etica", "etica-moral"),
    ("tratado de direitos humanos tem que status?", "prf-direitos-humanos", "dh-cf-tratados"),
    ("pacto de são josé prisão por dívida", "prf-direitos-humanos", "pacto-sao-jose"),
    ("tribunal penal internacional", "prf-direitos-humanos", "dh-cf-tratados"),
    ("o que diz a declaração universal?", "prf-direitos-humanos", "dudh"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, trilha, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr.id == trilha and top.id == topico, (pergunta, tr and tr.id, top and top.id)


def test_materia_citada(tutor):
    assert tutor.entender("questões de ética").trilha.id == "prf-etica"
    assert tutor.entender("vamos estudar direitos humanos").trilha.id == "prf-direitos-humanos"
