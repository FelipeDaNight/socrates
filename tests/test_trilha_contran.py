"""Resoluções do CONTRAN aprofundadas (17/11/2026): álcool (1.031/2026), tempo de direção (525/2015),
capacete (940/2022), habilitação (1.020/2025) e o mapa das resoluções do edital de 2021 que foram substituídas."""

import random

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

CTB = {t.id: t for t in carregar_trilhas()}["prf-transito"]
NOVOS = ["contran-alcool", "contran-jornada", "contran-capacete", "contran-habilitacao", "contran-mapa"]


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/index.json").write_text("[]")
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


def test_ordem_e_formato():
    ids = [t.id for t in CTB.topicos]
    assert ids[ids.index("contran") + 1: ids.index("contran") + 6] == NOVOS
    for tid in NOVOS:
        t = CTB.topico(tid)
        assert len(t.pontos) >= 5 and len(t.itens) >= 5 and len(t.pegadinhas) >= 2, tid
        assert {it["r"] for it in t.itens} == {"C", "E"} and all("Res. CONTRAN" in it["j"] for it in t.itens), tid


@pytest.mark.parametrize("topico,marcas", [
    ("contran-alcool", ["17/8/2026", "PELO MENOS DOIS", "0,05 mg", "0,34 mg/L", "INDICATIVOS", "NÃO recolhe", "NÃO escolhe"]),
    ("contran-jornada", ["MAIS DE 10", "4.536 kg", "5 horas e meia", "30 minutos a cada 4 horas", "11 horas", "6 horas consecutivas"]),
    ("contran-capacete", ["453/2013", "PARADO", "cristal", "película", "acima de 64"]),
    ("contran-habilitacao", ["9/12/2025", "DUAS HORAS", "instrutor autônomo", "20 acertos", "180 dias", "automaticamente"]),
    ("contran-mapa", ["34 resoluções", "993/2023", "57 t", "19,80 m", "74 t", "53 considerados", "1.027/2026"]),
])
def test_conteudo_conferido(topico, marcas):
    texto = " ".join(CTB.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


@pytest.mark.parametrize("pergunta,topico", [
    ("como funciona o drogômetro?", "contran-alcool"),
    ("quantos sinais de alteração da capacidade psicomotora precisa?", "contran-alcool"),
    ("tempo de descanso do caminhoneiro", "contran-jornada"),
    ("pode andar com a viseira levantada?", "contran-capacete"),
    ("ainda precisa de autoescola?", "contran-habilitacao"),
    ("quanto tempo o estrangeiro pode dirigir com a carteira estrangeira?", "contran-habilitacao"),
    ("quando precisa de autorização especial de trânsito?", "contran-mapa"),
    ("qual a tolerância do radar?", "contran-mapa"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr is not None and tr.id == "prf-transito" and top is not None and top.id == topico, (
        pergunta, tr and tr.id, top and top.id)
