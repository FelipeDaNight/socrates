"""Trilha de Legislação de Trânsito (CTB): conteúdo conferido, questões da prova e roteamento."""

import json
import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.respostas import norm
from socrates.estudo.trilha import carregar_trilhas

TRILHAS = {t.id: t for t in carregar_trilhas()}
CTB = TRILHAS["prf-transito"]
REAIS = (56, 57, 58, 59, 60, 62, 63, 66, 77, 78, 79, 80)                          # CTB e Lei 5.970
CONTRAN = (61, 64, 65, 68, 70, 71, 72, 73, 74, 75, 81, 82, 84, 85)              # resoluções

BANCO = {"id": "prf-2021-p1", "titulo": "PRF 2021", "tipo": "ce", "questoes": [
    {"n": n, "materia": "Legislação de Trânsito", "topico": f"PRF 2021 · item {n}", "tipo": "ce",
     "resp": "C", "enunciado": f"Item {n} de trânsito.", "just": "Gabarito."} for n in range(56, 82)]}


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/prf.json").write_text(json.dumps(BANCO), encoding="utf-8")
    (pasta / "bancos/index.json").write_text(json.dumps([{"id": "prf-2021-p1", "arquivo": "bancos/prf.json"}]))
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


def test_trilha_bem_formada():
    assert CTB.atualizado == "2026-11-13" and CTB.plano == "prf" and "ctb" in CTB.apelidos
    assert len(CTB.topicos) == 15
    for t in CTB.topicos:
        assert len(t.pontos) >= 2 and len(t.itens) >= 2 and t.palavras and t.faixas(), t.id
        respostas = {it["r"] for it in t.itens}
        assert respostas <= {"C", "E"} and (len(t.itens) < 3 or respostas == {"C", "E"}), t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"Art\.|Lei|Res\. CONTRAN", it["j"]), (t.id, it["t"])
        for p in t.palavras:
            assert p == norm(p) and p.strip() == p, (t.id, p)


def test_questoes_da_prova_no_topico_certo():
    ligadas = {int(q.split("item ")[1]): t.id for t in CTB.topicos for q in t.questoes}
    assert sorted(ligadas) == sorted(REAIS + CONTRAN)                 # os 26 itens de trânsito
    assert {ligadas[n] for n in CONTRAN} == {"contran"}
    assert ligadas[56] == ligadas[77] == ligadas[78] == ligadas[79] == "ctb-circulacao"
    assert ligadas[57] == ligadas[62] == "ctb-veiculos"
    assert ligadas[59] == "lei-5970" and ligadas[60] == "ctb-habilitacao"
    assert ligadas[58] == "ctb-infracoes" and ligadas[66] == "ctb-penalidades"


@pytest.mark.parametrize("topico,marcas", [
    ("ctb-circulacao", ["110 km/h", "100 e 90", "5 horas e meia", "1,45 m", "metade da máxima"]),
    ("ctb-veiculos", ["4.536 kg", "mais de 10 lugares", "mudar de MUNICÍPIO", "luzes de rodagem diurna"]),
    ("ctb-habilitacao", ["penalmente imputável", "validade de 1 ano", "2 anos e 6 meses", "a cada 3 anos"]),
    ("ctb-infracoes", ["R$ 293,47", "multa (10 vezes)", "SEGURANDO", "mais de 50%"]),
    ("ctb-penalidades", ["20 pontos", "30 pontos", "40 pontos", "zera os pontos", "2 anos"]),
    ("ctb-medidas", ["até 30 dias", "qualquer concentração"]),
    ("ctb-processo", ["30 DIAS", "80%", "60%"]),
    ("ctb-crimes", ["reclusão de 5 a 8 anos", "0,3 mg", "perigo de dano", "2 meses a 5 anos"]),
    ("ctb-snt", ["OBJETIVAMENTE", "perícia administrativa", "condomínios"]),
    ("contran", ["2,60 m", "19,30 m", "57 t", "12,5%", "até 50 t", "1 ano", "devidamente sinalizada",
                 "2 vezes o peso", "menos de 10 anos", "2,5 cm", "70%", "882/2021", "938/2022"]),
])
def test_numeros_conferidos_na_lei(topico, marcas):
    texto = " ".join(CTB.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


@pytest.mark.parametrize("fala,topico", [
    ("me ensina habilitação", "ctb-habilitacao"),
    ("questões de crimes de trânsito", "ctb-crimes"),
    ("vamos estudar medidas administrativas", "ctb-medidas"),
    ("me ensina a lei 5970", "lei-5970"),
    ("questões de velocidade máxima", "ctb-circulacao"),
    ("me ensina o sistema nacional de trânsito", "ctb-snt"),
    ("questões de bafômetro", "ctb-infracoes"),
    ("me ensina suspensão do direito de dirigir", "ctb-penalidades"),
    ("questões de transporte escolar", "ctb-escolares"),
    ("questões de resoluções do contran", "contran"),
    ("me ensina pesos e dimensões", "contran"),
    ("questões de tacógrafo", "contran"),
])
def test_cada_pedido_vai_para_o_topico_certo(tutor, fala, topico):
    p = tutor.entender(fala)
    assert p.trilha.id == "prf-transito" and p.topico.id == topico, (fala, p)


@pytest.mark.parametrize("pergunta,topico", [
    ("qual a tolerância de peso por eixo?", "contran"),
    ("o que o tacógrafo registra?", "contran"),
    ("posso usar película no vidro?", "contran"),
    ("quantos pontos suspendem a carteira?", "ctb-penalidades"),
    ("o que acontece se eu recusar o bafômetro?", "ctb-infracoes"),
    ("quem tem preferência na rotatória?", "ctb-circulacao"),
    ("quanto tempo o motorista de caminhão pode dirigir sem parar?", "ctb-circulacao"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr.id == "prf-transito" and top.id == topico, (pergunta, tr and tr.id, top and top.id)


def test_questoes_da_prf_vao_ao_banco_e_sem_prf_vao_a_trilha(tutor):
    p = tutor.entender("questões de trânsito da PRF")
    assert p.trilha is None and (p.banco, p.materia) == ("prf-2021-p1", "Legislação de Trânsito")
    p = tutor.entender("questões de trânsito")
    assert p.trilha.id == "prf-transito" and p.topico is None
    p = tutor.entender("questões de habilitação da PRF")            # com tópico, fica na trilha
    assert p.trilha.id == "prf-transito" and p.topico.id == "ctb-habilitacao"


def test_aula_de_circulacao_termina_com_questao_real(tutor):
    s = tutor.atender("me ensina normas de circulação")
    assert "normas gerais de circulação" in s.quadro
    for _ in CTB.topico("ctb-circulacao").pontos:
        tutor.atender("próximo")
    ids = [i.id for i in tutor.aula.sessao.itens]
    assert any(i.startswith("prf-2021-p1#") for i in ids)


def test_pergunta_solta_leva_as_notas_do_ctb(tutor):
    ctx = tutor.contexto_da_lei("qual a velocidade máxima numa rodovia de pista dupla?")
    assert "Legislação de Trânsito" in ctx and "110 km/h" in ctx
    ctx = tutor.contexto_da_lei("dirigir sem habilitação é crime?")
    assert "perigo de dano" in ctx


def test_palavras_nao_colidem_entre_trilhas(tutor):
    """Cada palavra-chave leva à trilha dona dela (nada de "depósito" do CTB roubar drogas)."""
    erradas = []
    for tr in TRILHAS.values():
        for t in tr.topicos:
            for p in t.palavras:
                achada, _ = tutor._trilha_da_fala(p)
                if achada is None or achada.id != tr.id:
                    erradas.append((tr.id, t.id, p, achada.id if achada else None))
    assert not erradas, erradas


def test_novidade_do_peso_por_eixo_esta_na_trilha():
    contran = CTB.topico("contran")
    assert any("14.229/2021" in n and "12,5%" in n for n in contran.novidades)
    assert any("item 82" in p and "CERTO" in p for p in contran.pegadinhas)
