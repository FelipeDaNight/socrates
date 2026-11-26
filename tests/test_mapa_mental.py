"""Desenho no quadro: mapa mental, cenários e passo a passo (26/11/2026).

O Felipe pediu: "quando eu pedir, ele fazer um desenho explicativo explicando cenários no
quadro, como um mapa mental". O cérebro escreve "mapa:", "cenarios:" ou "fluxo:" e os ramos
com "-"; o quadro desenha caixas ligadas (visor/diagrama.py).
"""

import io
import json
import random
import shutil

import pytest

from socrates.core import persona
from socrates.core.agente import INSTRUCAO, Agente
from socrates.core.memoria import Memorias
from socrates.estudo import material as mat
from socrates.estudo.caderno import Caderno
from socrates.estudo.plano import carregar_planos
from socrates.estudo.tutor import Tutor
from socrates.llm.acoes import pede_acao
from socrates.maos_livres import PEDIDO_QUADRO, pede_quadro
from socrates.visor import diagrama as dg
from socrates.visor.quadro import interpretar, renderizar

from test_agente import DADOS

MAPA = """# Espécies de flagrante
mapa: Prisão em flagrante
- Próprio (art. 302, I e II)
  - está cometendo a infração
  - acabou de cometê-la
- Impróprio (art. 302, III)
  - perseguido logo após
- Presumido (art. 302, IV)
  - encontrado logo depois com armas ou objetos"""

CENARIOS = """# Entrar na casa sem o morador deixar
cenarios: Casa é asilo inviolável (CF, art. 5º, XI)
- Flagrante delito -> pode entrar, a qualquer hora
- Desastre -> pode entrar, a qualquer hora
- Para prestar socorro -> pode entrar, a qualquer hora
- Ordem judicial
  - só durante o dia
Pegadinha: a banca troca dia por noite."""

FLUXO = """# Como uma emenda constitucional passa
fluxo: Emenda à Constituição (CF, art. 60)
1. Proposta
   - 1/3 da Câmara ou do Senado, o Presidente ou mais da metade das Assembleias
2. Votação em cada Casa, em dois turnos
3. Aprovação com 3/5 dos votos
4. Promulgação pelas Mesas da Câmara e do Senado"""


# ---------------------------------------------------------------- leitura

def test_mapa_com_ramos_e_detalhes_recuados():
    d = dg.ler(MAPA)
    assert d.tipo == "mapa" and d.centro == "Prisão em flagrante"
    assert d.titulo == "Espécies de flagrante"
    assert [r.texto for r in d.ramos] == ["Próprio (art. 302, I e II)", "Impróprio (art. 302, III)",
                                          "Presumido (art. 302, IV)"]
    assert [f.texto for f in d.ramos[0].filhos] == ["está cometendo a infração", "acabou de cometê-la"]


def test_cenarios_com_seta_numa_linha_e_nota_embaixo():
    d = dg.ler(CENARIOS)
    assert d.tipo == "cenarios" and d.centro.startswith("Casa é asilo")
    assert d.ramos[0].texto == "Flagrante delito"
    assert d.ramos[0].filhos[0].texto == "pode entrar, a qualquer hora"
    assert d.ramos[3].filhos[0].texto == "só durante o dia"
    assert d.nota == "Pegadinha: a banca troca dia por noite."


def test_fluxo_numerado_sem_os_numeros():
    d = dg.ler(FLUXO)
    assert d.tipo == "fluxo" and len(d.ramos) == 4
    assert d.ramos[0].texto == "Proposta" and d.ramos[0].filhos
    assert d.ramos[1].texto == "Votação em cada Casa, em dois turnos"


@pytest.mark.parametrize("linha,tipo", [
    ("mapa mental: Crimes", "mapa"), ("**Mapa mental:** Crimes", "mapa"), ("# Mapa mental: Crimes", "mapa"),
    ("Cenários: Blitz", "cenarios"), ("cenario: Blitz", "cenarios"), ("Árvore de cenários: Blitz", "cenarios"),
    ("fluxograma: Inquérito", "fluxo"), ("Passo a passo: Inquérito", "fluxo"),
])
def test_jeitos_de_escrever_o_tipo(linha, tipo):
    d = dg.ler(f"{linha}\n- um\n- dois")
    assert d.tipo == tipo and d.ramos[0].texto == "um"


def test_recuo_de_quatro_espacos_negrito_e_netos():
    d = dg.ler("mapa: Controle\n1. **Preventivo**\n    - Legislativo (CCJ)\n2. **Repressivo**\n"
               "    - Concentrado: STF\n        - ADI, ADC, ADPF e ADO")
    assert [r.texto for r in d.ramos] == ["Preventivo", "Repressivo"]
    assert dg._detalhes(d.ramos[1]) == ["Concentrado: STF", "– ADI, ADC, ADPF e ADO"]


def test_ramo_numa_linha_com_dois_pontos_vira_nome_e_detalhe():
    d = dg.ler("mapa: Crime\n- Doloso: quis o resultado ou assumiu o risco\n- Culposo")
    assert d.ramos[0].texto == "Doloso" and d.ramos[0].filhos[0].texto.startswith("quis")
    assert d.ramos[1].texto == "Culposo" and not d.ramos[1].filhos


def test_sem_hifen_o_modelo_esqueceu_os_tracos():
    d = dg.ler("cenarios: Blitz\nSe aceita o teste -> segue\nSe recusa -> infração")
    assert [r.texto for r in d.ramos] == ["Se aceita o teste", "Se recusa"]


def test_ramos_demais_ficam_de_fora_com_aviso():
    texto = "mapa: Tema\n" + "\n".join(f"- ramo {i}" for i in range(9))
    d = dg.ler(texto)
    assert len(d.ramos) == dg.MAXIMO["mapa"] and "mais 3 ramos" in d.nota


def test_detalhes_demais_terminam_em_reticencias():
    no = dg.No("Ramo", [dg.No(f"d{i}") for i in range(7)])
    assert dg._detalhes(no) == ["d0", "d1", "d2", "d3", "…"]


def test_quadro_comum_continua_igual():
    texto = "# Bhaskara\n$$ x = \\frac{-b}{2a} $$\n- onde a é diferente de 0"
    assert dg.ler(texto) is None
    assert [i.tipo for i in interpretar(texto)] == ["titulo", "formula", "item"]
    assert dg.ler("# Mapa da mina\nmapa: sem ramos") is None


def test_markdown_e_dinheiro_viram_texto_simples():
    d = dg.ler("mapa: Multas\n- **Gravíssima**\n  - R\\$ 293,47")
    assert d.ramos[0].texto == "Gravíssima" and d.ramos[0].filhos[0].texto == "R$ 293,47"


# ---------------------------------------------------------------- desenho

def _medidor():
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    fig = Figure(figsize=(7.6, 6.1), dpi=100)
    return dg._medidor(FigureCanvasAgg(fig).get_renderer())


def _sobrepoe(a, b) -> bool:
    return a.x < b.x + b.w and b.x < a.x + a.w and a.y < b.y + b.h and b.y < a.y + a.h


LONGO = ("mapa: Controle de constitucionalidade no Brasil\n" + "\n".join(
    f"- Ramo {i} com um nome comprido de propósito\n  - detalhe grande número um do ramo {i}\n"
    f"  - detalhe grande número dois do ramo {i}\n  - detalhe três\n  - detalhe quatro\n  - cinco"
    for i in range(6)))


@pytest.mark.parametrize("texto", [MAPA, CENARIOS, FLUXO, LONGO])
@pytest.mark.parametrize("tamanho", [(764, 609), (744, 609), (520, 480)])
def test_caixas_cabem_no_quadro_e_nao_se_encostam(texto, tamanho):
    largura, altura = tamanho
    titulo, nota, m = dg.montar(dg.ler(texto), largura, altura, _medidor())
    assert m.cabe
    for c in m.caixas:
        assert 0 <= c.x and c.x + c.w <= largura + 0.5
        assert 0 <= c.y and c.y + c.h <= altura + 0.5
    for i, a in enumerate(m.caixas):
        for b in m.caixas[i + 1:]:
            assert not _sobrepoe(a, b)


def test_texto_demais_diminui_a_letra_e_depois_corta_com_reticencias():
    _, _, m = dg.montar(dg.ler(LONGO), 520, 480, _medidor())
    assert min(c.pt for c in m.caixas) == dg.TAMANHOS[-1]
    assert any(["…"] in c.corpo for c in m.caixas)


def test_palavra_comprida_nao_e_cortada_no_meio_do_centro():
    w = _medidor()
    _, _, m = dg.montar(dg.ler("cenarios: Casa é asilo inviolável (CF, art. 5º, XI)\n- a -> b"),
                        764, 609, w)
    raiz = next(c for c in m.caixas if c.raiz)
    assert not any(l.endswith("-") for l in raiz.cabeca)


@pytest.mark.parametrize("texto", [MAPA, CENARIOS, FLUXO])
def test_renderizar_devolve_a_imagem_do_tamanho_do_quadro(texto):
    from PIL import Image
    img = Image.open(io.BytesIO(renderizar(texto, 764, 609)))
    assert img.size == (764, 609)


# ---------------------------------------------------------------- pedido certo, lugar certo

@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    shutil.copy(DADOS / "leiseca-agente.json", pasta / "bancos/leiseca.json")
    (pasta / "bancos/lei-index.json").write_text(json.dumps(["bancos/leiseca.json"]))
    (pasta / "bancos/index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    return Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                 planos=carregar_planos(ids=["prf", "cbmgo"]))


@pytest.mark.parametrize("fala", ["mapa mental de prisão em flagrante", "faz um mapa mental de flagrante",
                                  "meu mapa mental de penal", "mapas mentais de processo penal"])
def test_mapa_mental_nao_e_o_mapa_de_estudo(tutor, fala):
    p = tutor.entender(fala)
    assert p is None or p.tipo != "mapa"


def test_meu_mapa_continua_sendo_o_mapa_de_estudo(tutor):
    assert tutor.entender("mostra meu mapa").tipo == "mapa"
    assert tutor.entender("meu mapa de penal").tipo == "mapa"


@pytest.mark.parametrize("fala", ["coloca um mapa mental de flagrante", "faz um esquema do inquérito",
                                  "mostra os cenários da blitz", "desenha o passo a passo da emenda",
                                  "coloca no quadro os cenários"])
def test_desenho_e_no_quadro_nao_no_pc(fala, tmp_path):
    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    assert not pede_acao(fala)
    ag = Agente(C(), memorias=Memorias(tmp_path / "S"), acoes_pc=["abrir_programa", "anotar"],
                executar_pc=lambda n, a: "ok")
    assert not ag.quer_pc(fala, [])
    assert pede_quadro(fala)


def test_pc_continua_valendo_com_destino_ou_sem_verbo_de_desenho():
    assert pede_acao("abre o bloco de notas e escreve um esquema de flagrante")
    assert pede_acao("anota esse esquema")


def test_os_prompts_ensinam_o_formato():
    for texto in (INSTRUCAO, persona.QUADRO, PEDIDO_QUADRO):
        assert "mapa:" in texto and "cenarios:" in texto and "fluxo:" in texto


# ---------------------------------------------------------------- lei + desenho

DESENHO_DA_LEI = ("Veja o mapa no quadro. [QUADRO]\n# Primeiros artigos do CP\nmapa: Código Penal\n"
                  "- Art. 1º\n  - não há crime sem lei anterior\n- Art. 2º\n  - lei posterior que "
                  "deixa de considerar crime\n[/QUADRO]")


@pytest.mark.asyncio
async def test_mapa_mental_da_lei_le_o_texto_mas_o_quadro_e_o_desenho(tutor, tmp_path):
    from test_agente import CerebroRoteiro, _agente
    c = CerebroRoteiro([("ler_lei", {"lei": "Código Penal", "artigos": "primeiros"})], DESENHO_DA_LEI)
    ag, _ = _agente(c, tutor, Memorias(tmp_path / "S"))
    r = await ag.atender("faz um mapa mental dos primeiros artigos do Código Penal")
    assert "Texto oficial em vigor" in c.resultados[0] and "DESENHO" in c.resultados[0]
    assert r.quadro is None                              # a lei crua não ocupa o quadro
    assert "mapa: Código Penal" in r.texto               # o desenho do modelo fica


@pytest.mark.asyncio
async def test_pedido_de_lei_comum_continua_com_a_lei_no_quadro(tutor, tmp_path):
    from test_agente import CerebroRoteiro, _agente
    c = CerebroRoteiro([("ler_lei", {"lei": "Código Penal", "artigos": "primeiros"})],
                       "Estão no quadro. [QUADRO]\n# CP\n- **Caput**: resumo\n[/QUADRO]")
    ag, _ = _agente(c, tutor, Memorias(tmp_path / "S"))
    r = await ag.atender("lê os primeiros artigos do Código Penal")
    assert r.quadro and "Não há crime sem lei anterior" in r.quadro
    assert "[QUADRO]" not in r.texto
