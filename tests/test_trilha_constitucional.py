"""Trilha de Direito Constitucional: conteúdo conferido na CF atualizada, questões da prova e roteamento."""

import json
import random
import re

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.estudo.trilha import carregar_trilhas

CF = {t.id: t for t in carregar_trilhas()}["prf-constitucional"]


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
    assert CF.atualizado == "2026-11-13" and CF.plano == "prf" and len(CF.topicos) == 10
    for t in CF.topicos:
        assert len(t.pontos) >= 5 and len(t.itens) >= 5 and t.palavras and t.faixas(), t.id
        assert {it["r"] for it in t.itens} == {"C", "E"}, t.id
        for it in t.itens:
            assert len(it["t"]) > 30 and re.search(r"CF, art\.|STF|Doutrina", it["j"]), (t.id, it["t"])


def test_questoes_da_prova_no_topico_certo():
    ligadas = {int(q.split("item ")[1]): t.id for t in CF.topicos for q in t.questoes}
    assert ligadas == {93: "direitos-individuais", 94: "direitos-individuais", 95: "nacionalidade",
                       96: "direitos-politicos", 97: "remedios"}


@pytest.mark.parametrize("topico,marcas", [
    ("nacionalidade", ["EC 131/2023", "apatridia", "Ministro de Estado da Defesa", "um ano ininterrupto"]),
    ("poder-executivo", ["5 de janeiro", "EC 111/2021", "dois terços", "180 dias", "15 dias"]),
    ("seguranca-publica", ["patrulhamento ostensivo das rodovias federais", "polícias penais", "10 dias", "PRÉVIA"]),
    ("direitos-individuais", ["Tema 280", "Tema 855", "ADPF 187", "Tema 647", "LXXIX"]),
    ("direitos-sociais", ["Tema 541", "EC 90/2015", "EC 114/2021", "120 dias"]),
    ("organizacao-estado", ["trânsito e transporte (XI)", "150 km", "SUSPENDE"]),
])
def test_conteudo_conferido(topico, marcas):
    texto = " ".join(CF.topico(topico).pontos)
    for m in marcas:
        assert m in texto, (topico, m)


def test_pec_da_seguranca_publica_aparece_como_pendente():
    nov = " ".join(CF.topico("seguranca-publica").novidades)
    assert "PEC 18/2025" in nov and "aguarda promulgação" in nov and "ferrovias e hidrovias" in nov


@pytest.mark.parametrize("fala,topico", [
    ("me ensina nacionalidade", "nacionalidade"),
    ("questões de remédios constitucionais", "remedios"),
    ("vamos estudar segurança pública", "seguranca-publica"),
    ("me ensina estado de sítio", "seguranca-publica"),
    ("questões de direitos políticos", "direitos-politicos"),
])
def test_pedidos_vao_ao_topico_certo(tutor, fala, topico):
    p = tutor.entender(fala)
    assert p.trilha.id == "prf-constitucional" and p.topico.id == topico, (fala, p)


@pytest.mark.parametrize("pergunta,topico", [
    ("quem legisla sobre trânsito?", "organizacao-estado"),
    ("o policial pode fazer greve?", "direitos-sociais"),
    ("o que muda com a PEC da segurança pública?", "seguranca-publica"),
    ("qual a idade mínima para senador?", "direitos-politicos"),
    ("quem pode ser extraditado?", "direitos-individuais"),
    ("brasileiro que vira cidadão italiano perde a nacionalidade?", "nacionalidade"),
    ("o que é cláusula pétrea?", "poder-constituinte"),
    ("quando o presidente toma posse?", "poder-executivo"),
    ("redução da maioridade penal", "ordem-social"),
])
def test_pergunta_solta_acha_o_topico(tutor, pergunta, topico):
    tr, top = tutor._trilha_da_fala(pergunta)
    assert tr.id == "prf-constitucional" and top.id == topico, (pergunta, tr and tr.id, top and top.id)
