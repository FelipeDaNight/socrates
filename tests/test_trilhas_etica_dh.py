"""Trilhas de Ética e Cidadania e de Direitos Humanos: decretos de ética, Código de Conduta da
Alta Administração Federal, LAI, conflito de interesses, governança, tratados, DUDH e Pacto
de São José."""

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


@pytest.mark.parametrize("trilha,n,dia", [(ETICA, 8, "2026-11-16"), (DH, 4, "2026-11-13")])
def test_trilhas_bem_formadas(trilha, n, dia):
    assert trilha.atualizado == dia and trilha.plano == "prf" and len(trilha.topicos) == n
    for t in trilha.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 4 and t.palavras and t.faixas(), t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"Lei \d|CF, art\.|STF|Doutrina|Decreto|Código de Conduta", it["j"]), (t.id, it["t"])


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
    (ETICA, "conduta-alta-administracao", ["18/8/2000", "DAS nível 6", "SUPERIOR A 5%", "R$ 100,00", "QUATRO MESES",
                                           "ADVERTÊNCIA", "CENSURA ÉTICA", "SUGESTÃO DE DEMISSÃO", "5 dias", "3 dias",
                                           "Decreto 10.889/2021", "menos de 1% do teto"]),
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
    ("o que diz o código de conduta da alta administração?", "prf-etica", "conduta-alta-administracao"),
    ("ministro pode receber presente?", "prf-etica", "conduta-alta-administracao"),
    ("servidor pode aceitar brinde?", "prf-etica", "conduta-alta-administracao"),
    ("qual o período de interdição depois da exoneração?", "prf-etica", "conduta-alta-administracao"),
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


def test_codigo_de_conduta_da_alta_administracao(tutor):
    """Entra entre o Decreto 6.029 e a LAI, na ordem do edital, e não tira a censura do Decreto 1.171."""
    ids = [t.id for t in ETICA.topicos]
    assert ids.index("conduta-alta-administracao") == ids.index("gestao-etica") + 1
    top = ETICA.topico("conduta-alta-administracao")
    assert top.faixas() == [("CCAAF", (1, ""), (19, "Z"))] and len(top.novidades) == 3
    tr, achado = tutor._trilha_da_fala("qual a pena da comissão de ética?")
    assert achado.id == "codigo-etica"
    tr, achado = tutor._trilha_da_fala("censura ética")
    assert tr.id == "prf-etica" and achado.id == "codigo-etica"
    s = tutor.atender("me ensina código de conduta da alta administração federal")
    assert tutor.aula is not None and tutor.aula.topico.id == "conduta-alta-administracao" and "Alta Administração" in s.quadro
