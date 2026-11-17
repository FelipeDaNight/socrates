"""Trilhas do Bloco I da PRF que não dependem de lei: Raciocínio Lógico-Matemático,
Informática, Física, Geopolítica e Língua Inglesa, com as questões 27 a 55 da PRF 2021."""

import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

TRILHAS = {t.id: t for t in carregar_trilhas()}
RLM, INFO, FIS = TRILHAS["prf-rlm"], TRILHAS["prf-informatica"], TRILHAS["prf-fisica"]
GEO, ING = TRILHAS["prf-geopolitica"], TRILHAS["prf-ingles"]


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/index.json").write_text("[]")
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


@pytest.mark.parametrize("trilha,n,justificativa", [
    (RLM, 11, r"Cálculo|Definição|Regra|Propriedade|Fórmula"),
    (INFO, 6, r"Conceito|Regra|Windows"),
    (FIS, 5, r"Cálculo|Conceito|Fórmula|Lei|Definição"),
    (GEO, 10, r"IBGE|CF, art\.|Lei \d|Geografia|Tratado|PNL"),
    (ING, 2, r"Vocabulário|Estratégia|Interpretação|Gramática"),
])
def test_trilhas_bem_formadas(trilha, n, justificativa):
    assert trilha.atualizado == "2026-11-16" and trilha.plano == "prf" and len(trilha.topicos) == n
    for t in trilha.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 5 and len(t.pegadinhas) >= 2 and t.palavras, t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 25 and re.search(justificativa, it["j"]), (t.id, it["t"], it["j"])
        for p in t.palavras:
            assert re.fullmatch(r"[a-z0-9 ]+", p), (t.id, p)


def test_questoes_da_prova_no_topico_certo():
    def ligadas(trilha):
        return {int(q.split("item ")[1]): t.id for t in trilha.topicos for q in t.questoes}
    assert ligadas(RLM) == {27: "funcoes", 28: "funcoes", 29: "funcoes", 30: "funcoes", 31: "sequencias", 32: "sequencias"}
    assert ligadas(INFO) == {33: "internet-intranet", 35: "internet-intranet", 34: "windows",
                             36: "transformacao-digital", 37: "malwares", 38: "backup-nuvem"}
    assert ligadas(FIS) == {40: "cinematica", 42: "cinematica", 41: "newton", 43: "impulso", 44: "impulso"}
    assert ligadas(GEO) == {51: "transportes", 52: "transportes", 53: "transportes", 54: "urbanizacao", 55: "urbanizacao"}


@pytest.mark.parametrize("trilha,topico,marcas", [
    (RLM, "funcoes", ["0,25 (25%)", "0,21 (21%)", "xv = −b/2a", "log₂ 8 = 3"]),
    (RLM, "sequencias", ["an = a1 + (n − 1)·r", "560 > 550", "10·n·(n + 1)"]),
    (RLM, "porcentagem", ["1,21", "0,96", "250 ÷ 1,25 = 200"]),
    (RLM, "contagem", ["C(5,2) = 10", "5.040", "ARARA"]),
    (INFO, "malwares", ["hospedeiro", "resgate", "engenharia social", "item 37"]),
    (INFO, "backup-nuvem", ["PaaS, não SaaS", "Incremental", "Diferencial", "3-2-1"]),
    (INFO, "internet-intranet", ["SMTP ENVIA", "Cco", "@twitter"]),
    (FIS, "cinematica", ["v² = v0² + 2·a·Δs", "40 m", "QUADRADO", "item 42"]),
    (FIS, "impulso", ["I = ΔQ", "100.000 J", "item 44, Errado", "item 43, Certo"]),
    (FIS, "movimento-circular", ["v = √(μ·g·R)", "4.000 N", "NÃO depende da massa"]),
    (GEO, "urbanizacao", ["87,4%", "Grande Metrópole Nacional", "Campinas", "art. 25, § 3º", "item 55"]),
    (GEO, "transportes", ["66,2%", "item 52", "longitudinais", "Lei 14.273/2021", "BR-153"]),
    (GEO, "biomas", ["49,5%", "23,3%", "1,8%", "EXCLUSIVAMENTE brasileiro", "Ab'Sáber"]),
    (GEO, "economia-global", ["17/1/2026", "1º/5/2026", "agosto de 2024", "Xangai"]),
    (GEO, "gestao-ambiental", ["Lei 15.190/2025", "4/2/2026", "80%", "35%", "ADIs 7913"]),
    (GEO, "populacao", ["203,1 milhões", "213,4 milhões", "35 anos", "51,5%"]),
    (GEO, "estado-brasileiro", ["5.569", "133", "510", "772 municípios"]),
    (ING, "ingles-texto", ["actually = na verdade", "skimming", "scanning", "policy"]),
])
def test_conteudo_conferido(trilha, topico, marcas):
    texto = " ".join(trilha.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


@pytest.mark.parametrize("pergunta,trilha,topico", [
    ("como calcular aumentos sucessivos?", "prf-rlm", "porcentagem"),
    ("regra de três composta", "prf-rlm", "razao-proporcao"),
    ("o que é progressão aritmética?", "prf-rlm", "sequencias"),
    ("questões de probabilidade", "prf-rlm", "probabilidade"),
    ("qual a negação de proposição com se então?", "prf-rlm", "logica"),
    ("o que é ransomware?", "prf-informatica", "malwares"),
    ("diferença entre iaas paas e saas", "prf-informatica", "backup-nuvem"),
    ("atalhos de teclado do windows", "prf-informatica", "windows"),
    ("o que é big data?", "prf-informatica", "transformacao-digital"),
    ("pra que serve o firewall?", "prf-informatica", "ferramentas-seguranca"),
    ("me explica a equação de torricelli", "prf-fisica", "cinematica"),
    ("o que é força centrípeta?", "prf-fisica", "movimento-circular"),
    ("colisão inelástica conserva o quê?", "prf-fisica", "impulso"),
    ("leis de newton", "prf-fisica", "newton"),
    ("quais são os biomas do brasil?", "prf-geopolitica", "biomas"),
    ("o que é a amazônia legal?", "prf-geopolitica", "estado-brasileiro"),
    ("matriz de transportes do brasil", "prf-geopolitica", "transportes"),
    ("o que é conurbação?", "prf-geopolitica", "urbanizacao"),
    ("o brics é bloco econômico?", "prf-geopolitica", "economia-global"),
    ("falsos cognatos", "prf-ingles", "ingles-texto"),
    ("verbos modais", "prf-ingles", "ingles-gramatica"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, trilha, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr is not None and tr.id == trilha and top is not None and top.id == topico, (
        pergunta, tr and tr.id, top and top.id)


@pytest.mark.parametrize("fala", ["coação física irresistível", "lesão à integridade física",
                                  "pessoa física pode ser sócia?", "princípio da reserva legal"])
def test_nao_rouba_assunto_de_outra_materia(tutor, fala):
    tr, _ = tutor._trilha_da_fala(fala)
    assert tr is None or tr.id not in ("prf-fisica", "prf-geopolitica"), (fala, tr and tr.id)


def test_materia_citada_abre_a_trilha(tutor):
    for fala, tid in [("questões de física", "prf-fisica"), ("vamos estudar geopolítica", "prf-geopolitica"),
                      ("questões de informática", "prf-informatica"), ("questões de matemática", "prf-rlm"),
                      ("questões de inglês", "prf-ingles")]:
        tr, _ = tutor._trilha_da_fala(fala)
        assert tr is not None and tr.id == tid, (fala, tr and tr.id)


def test_aulas(tutor):
    s = tutor.atender("me ensina porcentagem")
    assert tutor.aula is not None and tutor.aula.topico.id == "porcentagem" and "Porcentagem" in s.quadro
    tutor.encerrar()
    s = tutor.atender("me ensina biomas")
    assert tutor.aula is not None and tutor.aula.topico.id == "biomas"
