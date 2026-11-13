"""As trilhas de Processo Penal e Legislação Especial e o tutor com várias trilhas."""

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
PP, LE, PENAL = TRILHAS["prf-processo-penal"], TRILHAS["prf-legislacao-especial"], TRILHAS["prf-penal"]

BANCO = {"id": "prf-2021-p1", "titulo": "PRF 2021", "tipo": "ce", "questoes": [
    {"n": 83 + i, "materia": "Direito Penal, Processo Penal e Legislação Especial",
     "topico": f"PRF 2021 · item {100 + i}", "tipo": "ce", "resp": "C",
     "enunciado": f"Item {100 + i}.", "just": "Gabarito."} for i in range(16)]}


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


@pytest.mark.parametrize("trilha", [PP, LE])
def test_trilhas_bem_formadas(trilha):
    assert trilha.atualizado == "2026-11-13" and trilha.apelidos
    for t in trilha.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 3 and t.palavras, t.id
        assert t.faixas(), t.id
        for it in t.itens:
            assert it["r"] in ("C", "E") and len(it["t"]) > 30 and it["j"], (t.id, it["t"])
        for q in t.questoes:
            assert re.fullmatch(r"prf-2021-p1\|item 1(0[5-9]|1[0-5])", q), q


def test_questoes_reais_da_prova_no_topico_certo():
    ligadas = {q.split("item ")[1]: (tr.id, t.id) for tr in (PP, LE) for t in tr.topicos for q in t.questoes}
    assert ligadas["105"] == ("prf-processo-penal", "busca-apreensao")
    assert ligadas["106"] == ligadas["109"] == ("prf-processo-penal", "prisao-flagrante")
    assert ligadas["107"] == ligadas["112"] == ("prf-processo-penal", "identificacao-criminal")
    assert ligadas["110"] == ("prf-legislacao-especial", "hediondos")
    assert ligadas["115"] == ("prf-legislacao-especial", "tortura")
    assert len(ligadas) == 11


def test_novidades_de_2026_conferidas():
    texto = json.dumps([t.novidades + t.pontos for t in LE.topicos + PP.topicos], ensure_ascii=False)
    for marca in ("15.358/2026", "15.487/2026", "15.245/2025", "videoconferência", "ADIs 6245 e 6264",
                  "art. 58", "PEC 18/2025", "ferrovias e hidrovias"):
        assert marca in texto, marca
    assert "15.358/2026" in " ".join(PENAL.topico("crimes-pessoa").novidades)


@pytest.mark.parametrize("fala,trilha,topico", [
    ("me ensina prisão em flagrante", "prf-processo-penal", "prisao-flagrante"),
    ("questões de drogas", "prf-legislacao-especial", "drogas"),
    ("me ensina busca pessoal", "prf-processo-penal", "busca-apreensao"),
    ("questões de abuso de autoridade", "prf-legislacao-especial", "abuso-autoridade"),
    ("me ensina o estatuto do desarmamento", "prf-legislacao-especial", "armas"),
    ("vamos estudar furto", "prf-penal", "crimes-patrimonio"),
    ("questões de tco", "prf-processo-penal", "tco"),
])
def test_cada_pedido_vai_para_a_trilha_certa(tutor, fala, trilha, topico):
    p = tutor.entender(fala)
    assert p.trilha.id == trilha and p.topico.id == topico


def test_materia_citada_escolhe_a_trilha(tutor):
    assert tutor.entender("vamos estudar processo penal").trilha.id == "prf-processo-penal"
    assert tutor.entender("questões de legislação especial").trilha.id == "prf-legislacao-especial"
    assert tutor.entender("questões de penal").trilha.id == "prf-penal"
    assert not PENAL.menciona_materia("aula de processo penal")


def test_aula_de_processo_penal_e_fixacao_com_questao_real(tutor):
    s = tutor.atender("me ensina prisão em flagrante")
    assert "Prisão em flagrante e audiência de custódia · 1/7" in s.quadro
    assert "videoconferência" in s.contexto                  # a novidade vai junto
    for _ in PP.topico("prisao-flagrante").pontos:
        tutor.atender("próximo")
    ids = [i.id for i in tutor.aula.sessao.itens]
    assert ids and any(i.startswith("prf-2021-p1#") for i in ids)


def test_plano_do_dia_junta_as_materias(tutor):
    s = tutor.atender("o que eu estudo hoje?")
    materias = [tr.materia for tr in tutor.trilhas]
    assert sum(f"- {m}:" in s.quadro for m in materias) == 2       # duas matérias por dia
    assert "- Legislação de Trânsito:" in s.quadro                    # a que mais cai vem
    assert tutor.entender("qual o próximo passo?").tipo == "plano"


def test_pergunta_solta_leva_as_notas_da_trilha_certa(tutor):
    ctx = tutor.contexto_da_lei("qual a pena do tráfico de drogas?")
    assert "Legislação Especial" in ctx and "5 a 15 anos" in ctx
    ctx = tutor.contexto_da_lei("o policial pode revistar o carro sem mandado na blitz?")
    assert "Processual Penal" in ctx and "fundada suspeita" in ctx


def test_o_que_aprendi_em_varias_materias(tutor):
    tutor.atender("questões de drogas")
    for _ in range(3):
        tutor.atender("certo")
        if tutor.sessao and tutor.sessao.estado == "corrigida":
            tutor.atender("próxima")
    tutor.atender("parar")
    tutor.atender("me ensina prisão em flagrante")
    tutor.atender("parar")
    s = tutor.atender("o que eu já aprendi?")
    assert "Legislação Especial" in s.fala and "Direito Processual Penal" in s.fala
    assert "domina 0 tópicos" not in s.fala
