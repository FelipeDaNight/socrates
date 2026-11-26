"""Vigia de notícias do edital da PRF e do CBMGO (estudo/noticias.py), de graça (26/11/2026).

"Um agente agendado que vigia notícias sobre o edital da PRF e do CBMGO todo dia: esse
seria uma boa se não fosse custar nada ao Sócrates." Usa a busca de notícias do ddgs (sem
chave) e não chama o cérebro.
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from socrates.estudo import noticias as nt

AGORA = datetime(2026, 11, 26, 18, 0, tzinfo=timezone.utc)


def _r(titulo, dias=1, fonte="Estratégia Concursos", url=None, corpo=""):
    return {"title": titulo, "date": (AGORA - timedelta(days=dias)).isoformat(), "source": fonte,
            "url": url or f"https://exemplo.com/{abs(hash(titulo))}", "body": corpo}


class Busca:
    """Finge a busca de notícias: devolve o que estiver em `respostas` para cada consulta."""

    def __init__(self, respostas):
        self.respostas = respostas
        self.feitas = []

    def __call__(self, consulta):
        self.feitas.append(consulta)
        if isinstance(self.respostas, Exception):
            raise self.respostas
        return self.respostas.get(consulta, [])


PRF = [_r("Concurso PRF: corporação confirma pedido para novo edital", 1),
       _r("PRF apreende 2 toneladas de maconha na BR-153", 1),                 # não é concurso
       _r("Concurso PRF 2021: relembre o último edital", 40),                   # velha
       _r("Concurso PRF tem validade prorrogada até dezembro", 3, "Folha Dirigida")]
CBMGO = [_r("Concurso Bombeiros GO: comissão formada, edital em breve", 2, "Gran Cursos"),
         _r("Bombeiros de Goiás resgatam família em enchente", 1)]              # não é concurso


def _vigia(tmp_path, respostas):
    busca = Busca(respostas)
    return nt.Vigia(tmp_path / "noticias.json", buscar=busca, relogio=lambda: AGORA), busca


@pytest.mark.parametrize("concurso,titulo,sim", [
    ("prf", "Concurso PRF: corporação confirma pedido para novo edital", True),
    ("prf", "Polícia Rodoviária Federal publica edital com 1.500 vagas", True),
    ("prf", "PRF apreende drogas na BR-060", False),
    ("prf", "Concurso PF: edital publicado", False),
    ("cbmgo", "Concurso CBMGO: banca definida", True),
    ("cbmgo", "Concurso CBM-GO tem inscrições abertas", True),
    ("cbmgo", "Concurso Bombeiros GO: edital em breve", True),
    ("cbmgo", "Corpo de Bombeiros de Goiás convoca aprovados", True),
    ("cbmgo", "Concurso Bombeiros DF: edital publicado", False),
    ("cbmgo", "Bombeiros de Goiás resgatam família", False),
])
def test_so_noticia_do_concurso_certo_e_de_edital(concurso, titulo, sim):
    assert nt.relevante(concurso, titulo) is sim


def test_primeira_vez_avisa_so_a_mais_recente_de_cada_concurso(tmp_path):
    v, busca = _vigia(tmp_path, {"concurso PRF edital": PRF, "concurso CBMGO edital": CBMGO})
    novas = v.verificar()
    assert [n.titulo for n in novas] == ["Concurso PRF: corporação confirma pedido para novo edital",
                                         "Concurso Bombeiros GO: comissão formada, edital em breve"]
    assert len(busca.feitas) == 4                       # 2 buscas por concurso
    dados = json.loads((tmp_path / "noticias.json").read_text(encoding="utf-8"))
    assert len(dados["vistas"]) == 3                    # a da validade também ficou como vista
    assert len(v.recentes()) == 3


def test_depois_so_avisa_o_que_e_novo_e_uma_vez(tmp_path):
    v, _ = _vigia(tmp_path, {"concurso PRF edital": PRF, "concurso CBMGO edital": CBMGO})
    v.verificar()
    assert v.verificar() == []                          # nada novo
    nova = _r("Concurso PRF: edital publicado com 2.000 vagas", 0, "G1")
    v2, _ = _vigia(tmp_path, {"concurso PRF edital": [nova] + PRF,
                              "concurso Polícia Rodoviária Federal": [dict(nova, url="https://outro.com/x")]})
    novas = v2.verificar()
    assert [n.titulo for n in novas] == ["Concurso PRF: edital publicado com 2.000 vagas"]  # uma vez só
    assert "Novidade do concurso da PRF: Concurso PRF: edital publicado com 2.000 vagas, no G1." == nt.aviso(novas)
    assert v2.verificar() == []


def test_busca_fora_do_ar_nao_quebra_e_tenta_depois(tmp_path):
    v, _ = _vigia(tmp_path, RuntimeError("sem internet"))
    assert v.verificar() == []
    assert not v.precisa_buscar(6)                      # espera o intervalo para tentar de novo
    v.relogio = lambda: AGORA + timedelta(hours=7)
    assert v.precisa_buscar(6)


def test_sem_o_pacote_ddgs_avisa_no_registro(tmp_path):
    v, _ = _vigia(tmp_path, ImportError("ddgs"))
    assert v.verificar() == []


def test_aviso_de_varias_e_formato_do_visor(tmp_path):
    ns = [nt.Noticia("prf", f"Concurso PRF: notícia {i}", "Site", "https://a.com", AGORA.isoformat())
          for i in range(3)]
    texto = nt.aviso(ns)
    assert texto.count("Novidade do concurso") == 2 and texto.endswith("E mais 1 no visor.")
    assert nt.aviso([nt.Noticia("cbmgo", "Concurso CBMGO: banca", "Gran", "")]).startswith(
        "Novidade do concurso dos Bombeiros de Goiás")
    visor = nt.para_o_visor(ns[:1])
    assert visor[0]["concurso"] == "PRF" and visor[0]["data"] and visor[0]["url"] == "https://a.com"


def test_resumo_para_o_cerebro_marca_as_novas_e_nao_inventa():
    assert "não invente" in nt.resumo_para_o_cerebro([], [])
    n = nt.Noticia("prf", "Concurso PRF: pedido de edital", "Estratégia", "", AGORA.isoformat())
    texto = nt.resumo_para_o_cerebro([n], [n])
    assert "[PRF] Concurso PRF: pedido de edital (Estratégia" in texto and "(NOVA)" in texto


def test_arquivo_estragado_comeca_do_zero(tmp_path):
    (tmp_path / "noticias.json").write_text("{quebrado", encoding="utf-8")
    v, _ = _vigia(tmp_path, {"concurso PRF edital": PRF})
    assert v.verificar()


# ---------------------------------------------------------------- ligado ao Sócrates

def test_ferramenta_saiu_o_edital_filtra_por_concurso(tmp_path):
    from socrates.core.agente import Agente
    from socrates.core.memoria import Memorias

    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    ag = Agente(C(), memorias=Memorias(tmp_path / "S"))
    ag.vigia, _ = _vigia(tmp_path, {"concurso PRF edital": PRF, "concurso CBMGO edital": CBMGO})
    assert "noticias_do_concurso" in {e["function"]["name"] for e in ag.esquemas(False)}
    texto = asyncio.run(ag.noticias_do_concurso("cbmgo"))
    assert "Bombeiros GO" in texto and "PRF" not in texto.split(":", 1)[1]


def test_vigia_em_segundo_plano_espera_voce_parar_de_falar(tmp_path):
    import main
    from socrates import config
    from socrates.visor.painel import Painel

    cfg = config.Config.__new__(config.Config)
    cfg.noticias = config.ConfigNoticias()
    v, _ = _vigia(tmp_path, {"concurso PRF edital": PRF})
    painel, falas, ocupado = Painel(), [], {"sim": True}

    async def rodar():
        tarefa = asyncio.create_task(main.vigiar_noticias(cfg, v, painel, falas.append,
                                                          lambda: ocupado["sim"], espera=0, passo=0.05))
        await asyncio.sleep(0.2)
        assert falas == [] and painel.noticias           # achou, mas você estava falando
        ocupado["sim"] = False
        await asyncio.sleep(0.2)
        tarefa.cancel()

    asyncio.run(rodar())
    assert len(falas) == 1 and falas[0].startswith("Novidade do concurso da PRF")


def test_configuracao_padrao():
    from socrates import config
    c = config.ConfigNoticias()
    assert c.ativo and c.concursos == ["prf", "cbmgo"] and c.intervalo_horas == 6
