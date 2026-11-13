"""Trilha de Direito Penal da PRF: conteúdo, aula guiada, domínio, direção, diário e mapa."""

import asyncio
import json
import random
import re
from datetime import date

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.progresso import Progresso, diario
from socrates.estudo.respostas import norm
from socrates.estudo.trilha import PASTA, carregar_trilhas

TRILHA = next(t for t in carregar_trilhas() if t.id == "prf-penal")

PRF = {"id": "prf-2021-p1", "titulo": "PRF 2021 · Policial Rodoviário Federal (Cebraspe)", "tipo": "ce",
       "questoes": [
           {"n": 83 + i, "materia": "Direito Penal, Processo Penal e Legislação Especial",
            "topico": f"PRF 2021 · item {100 + i}", "tipo": "ce", "resp": r,
            "enunciado": f"Texto de apoio.\n\nItem {100 + i} sobre a blitz.", "just": "Gabarito: X."}
           for i, r in enumerate("EECEC")] + [
           {"n": 1, "materia": "Informática", "topico": "PRF 2021 · item 33", "tipo": "ce", "resp": "C",
            "enunciado": "O Linux é um sistema operacional."}]}
LEI = {"id": "leiseca-sem01", "tipo": "leiseca", "blocos": [
    {"id": "s1-1", "lei": "CP", "rotulo": "CP · Arts. 1º a 3º", "artigos": [
        {"art": "Art. 1º", "itens": [{"k": "lei", "t": "Art. 1º Não há crime sem lei anterior que o defina."}],
         "lacunas": [{"c": "Não há crime sem lei ____ que o defina.", "r": "anterior", "i": "a"}]},
        {"art": "Art. 2º", "itens": [{"k": "lei", "t": "Art. 2º Ninguém pode ser punido por fato que lei posterior deixa de considerar crime."}],
         "lacunas": []}]}]}


class Relogio:
    def __init__(self):
        self.dia = date(2026, 11, 13)

    def __call__(self):
        return self.dia


@pytest.fixture
def tutor(tmp_path):
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/prf.json").write_text(json.dumps(PRF, ensure_ascii=False), encoding="utf-8")
    (pasta / "bancos/lei.json").write_text(json.dumps(LEI, ensure_ascii=False), encoding="utf-8")
    (pasta / "bancos/index.json").write_text(json.dumps([{"id": "prf-2021-p1", "arquivo": "bancos/prf.json"}]))
    (pasta / "bancos/lei-index.json").write_text(json.dumps(["bancos/lei.json"]))
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    relogio = Relogio()
    t = Tutor(m, Caderno(tmp_path / "caderno.json", relogio=relogio), sortear=random.Random(0))
    t.relogio = relogio
    return t


def _responder_fixacao(t, acertar=True):
    while t.aula is not None and t.aula.sessao is not None:
        it = t.aula.sessao.atual
        certa = "certo" if it.resp == "C" else "errado"
        errada = "errado" if it.resp == "C" else "certo"
        s = t.atender(certa if acertar else errada)
        if not acertar and not s.fim and t.aula and t.aula.sessao and t.aula.sessao.estado == "corrigida":
            s = t.atender("próxima")
    return s


# ---------- o conteúdo ----------

def test_conteudo_da_trilha_bem_formado():
    d = json.loads((PASTA / "prf-direito-penal.json").read_text(encoding="utf-8"))
    ids = [t["id"] for t in d["topicos"]]
    assert len(ids) == len(set(ids)) >= 15
    for t in d["topicos"]:
        assert len(t["pontos"]) >= 4, t["id"]
        assert len(t["itens"]) >= 3, t["id"]
        assert t["peso"] in (1, 2, 3)
        for it in t["itens"]:
            assert it["r"] in ("C", "E") and it["j"].strip() and it["t"].strip()
        for a in t["artigos"]:
            assert re.match(r"^(CP|CPP|CTB|L14133) \d", a), a
    # o edital da PRF 2021 inteiro está coberto
    editais = " ".join(t["edital"] for t in d["topicos"])
    for parte in ("Princípios", "Lei penal no tempo", "Lei penal no espaço", "Erro de tipo",
                  "Crime impossível", "Punibilidade", "Ilicitude", "Culpabilidade",
                  "contra a pessoa", "patrimônio", "dignidade sexual", "incolumidade pública",
                  "fé pública", "Administração Pública"):
        assert parte in editais, parte


def test_penas_atualizadas_ate_2026():
    """O que os modelos de IA erram: as penas mudaram em 2024, 2025 e 2026."""
    tudo = json.dumps(json.loads((PASTA / "prf-direito-penal.json").read_text(encoding="utf-8")),
                      ensure_ascii=False)
    for trecho in ("Pena de 1 a 6 anos e multa desde a Lei 15.397/2026",       # furto
                   "Pena de 6 a 10 anos desde a Lei 15.397/2026",              # roubo
                   "24 a 30 anos",                                              # latrocínio
                   "art. 121-A, Lei 14.994/2024",                               # feminicídio autônomo
                   "Pena de 10 a 18 anos desde a Lei 15.280/2025",              # estupro de vulnerável
                   "revogou o § 5º",                                            # estelionato incondicionado
                   "art. 338-A"):                                               # medida protetiva
        assert trecho in tudo, trecho


@pytest.mark.parametrize("fala,topico", [
    ("me ensina legítima defesa", "ilicitude"), ("o que é legítima defesa putativa?", "erro-de-tipo"),
    ("questões de corrupção", "adm-publica"), ("qual a pena do roubo?", "crimes-patrimonio"),
    ("questões de furto", "crimes-patrimonio"), ("o que é abolitio criminis?", "lei-penal-tempo"),
    ("CNH falsa apresentada ao PRF", "fe-publica"), ("feminicídio", "crimes-pessoa"),
    ("crime impossível", "iter-criminis"), ("embriaguez exclui a imputabilidade?", "culpabilidade"),
    ("corrupção de menores", "dignidade-sexual"), ("o que é crase?", None),
])
def test_acha_o_topico_na_fala(fala, topico):
    t = TRILHA.topico_citado(fala)
    assert (t.id if t else None) == topico


def test_processo_penal_nao_e_direito_penal():
    assert TRILHA.menciona_materia("questões de penal") and TRILHA.menciona_materia("direito penal")
    assert not TRILHA.menciona_materia("questões de processo penal")


# ---------- pedidos ----------

@pytest.mark.parametrize("fala,tipo", [
    ("vamos estudar penal", "aula"), ("me ensina legítima defesa", "aula"),
    ("o que eu estudo de penal?", "direcao"), ("qual o próximo passo em direito penal?", "direcao"),
    ("o que eu estudei hoje?", "estudado"), ("o que eu já aprendi?", "aprendido"),
    ("como estou em penal?", "aprendido"), ("mapa de penal", "mapa"), ("mostra meu mapa", "mapa"),
    ("questões de penal", "questoes"), ("simulado de penal", "simulado"),
    ("revisa meus erros de penal", "revisao"), ("me explica legítima defesa", None),
    ("o que eu estudo hoje?", "plano"), ("questões da PRF", "questoes"),
])
def test_entende_pedidos_da_trilha(tutor, fala, tipo):
    p = tutor.entender(fala)
    assert (p.tipo if p else None) == tipo
    if fala == "questões da PRF":
        assert p.trilha is None and p.banco == "prf-2021-p1"


# ---------- aula guiada ----------

def test_aula_ponto_a_ponto_ate_a_fixacao(tutor):
    s = tutor.atender("Sócrates, me ensina legítima defesa")
    top = TRILHA.topico("ilicitude")
    assert s.quadro.startswith(f"# {top.titulo} · 1/{len(top.pontos)}")
    assert top.pontos[0][:40] in s.quadro
    assert "PONTO 1 de" in s.contexto and "NÃO use o quadro" in s.contexto
    assert "Pegadinhas que a banca usa" in s.contexto
    s = tutor.atender("acho que é quando a lei permite o fato")       # resposta à pergunta
    assert "acabou de responder" in s.contexto and s.quadro is None
    s = tutor.atender("sim")                                          # "posso seguir?" -> sim
    assert "· 2/" in s.quadro
    s = tutor.atender("sim")                                          # agora "sim" é resposta
    assert "acabou de responder" in s.contexto
    s = tutor.atender("repete")
    assert "· 2/" in s.quadro and "OUTRO jeito" in s.contexto
    for _ in range(len(top.pontos) - 2):
        s = tutor.atender("próximo")
    s = tutor.atender("próximo")                                      # acabou a teoria
    assert s.fala.startswith("Fim da parte teórica") and "Certo ou errado?" in s.fala
    s = _responder_fixacao(tutor)
    assert s.fim and "concluída" in s.fala and "Próximo passo" in s.fala
    assert tutor.aula is None
    reg = tutor.caderno.dados["aulas"]["prf-penal:ilicitude"]
    assert reg["concluida"] and reg["vistos"] == len(top.pontos)
    assert any(e["k"] == "aula" and e.get("fim") for e in tutor.caderno.eventos)


def test_pausar_e_continuar_de_onde_parou(tutor):
    tutor.atender("me ensina erro de tipo")
    tutor.atender("próximo")
    s = tutor.atender("parar")
    assert s.fim and "ponto 2 de" in s.fala and tutor.aula is None
    s = tutor.atender("me ensina erro de tipo")
    assert "· 2/" in s.quadro and "continuar a aula" in s.contexto


def test_consulta_no_meio_da_aula_e_volta(tutor):
    tutor.atender("me ensina princípios do direito penal")
    tutor.atender("próximo")
    s = tutor.atender("o que eu estudei hoje?")
    assert "Diga continua para voltar à aula" in s.fala and tutor.aula is not None
    s = tutor.atender("continua")
    assert "· 2/" in s.quadro                                        # o mesmo ponto, não pulou


def test_pedido_claro_troca_a_aula_por_questoes(tutor):
    tutor.atender("me ensina princípios do direito penal")
    s = tutor.atender("questões da PRF")
    assert tutor.aula is None and tutor.sessao is not None
    assert "Aula pausada" in s.fala


def test_vamos_estudar_penal_abre_o_topico_recomendado(tutor):
    s = tutor.atender("vamos estudar penal")
    assert "Princípios" in s.quadro                                   # o primeiro do edital


# ---------- domínio e direção ----------

def _registrar(tutor, tid, oks):
    top = TRILHA.topico(tid)
    itens = TRILHA.itens_do_topico(top, tutor.material.bancos)
    for it, ok in zip(itens * 4, oks):
        tutor.caderno.registrar(it.id, ok)


def test_direcao_segue_o_aluno(tutor):
    prog = tutor.progresso(TRILHA)
    passo = prog.proximo_passo()
    assert passo.acao == "aula" and passo.topico.id == "principios"
    _registrar(tutor, "principios", [True] * 6)
    assert prog.situacao(TRILHA.topico("principios")).estado == "dominado"
    assert prog.proximo_passo().topico.id == "lei-penal-tempo"
    _registrar(tutor, "iter-criminis", [False, False, True, False])
    passo = prog.proximo_passo()
    assert passo.acao == "reforco" and passo.topico.id == "iter-criminis"
    assert "me ensina" in passo.comando
    tutor.relogio.dia = date(2026, 11, 14)                             # erros vencem no dia seguinte
    _registrar(tutor, "fe-publica", [False] * 3)
    tutor.relogio.dia = date(2026, 11, 15)
    assert prog.proximo_passo().acao == "revisao"


def test_aula_pela_metade_e_prioridade(tutor):
    tutor.atender("me ensina furto")
    tutor.atender("parar")
    passo = tutor.progresso(TRILHA).proximo_passo()
    assert passo.acao == "continuar" and passo.topico.id == "crimes-patrimonio"


def test_questoes_reais_da_prova_entram_no_topico(tutor):
    itens = TRILHA.itens_do_topico(TRILHA.topico("adm-publica"), tutor.material.bancos)
    reais = [i for i in itens if i.real]
    assert [i.id for i in reais] == ["prf-2021-p1#85", "prf-2021-p1#86"]
    s = tutor.atender("questões de corrupção")
    assert tutor.sessao is not None and "Administração Pública" in s.fala


def test_lacuna_do_artigo_conta_para_o_topico(tutor):
    prog = tutor.progresso(TRILHA)
    lacuna = next(i for i in prog.lacunas if i.lei == "CP")
    assert lacuna.id in prog.ids["principios"]


def test_revisao_de_penal_so_traz_penal(tutor):
    _registrar(tutor, "ilicitude", [False, False])
    tutor.caderno.registrar("prf-2021-p1#1", False)          # informática
    tutor.relogio.dia = date(2026, 11, 14)
    s = tutor.atender("revisa meus erros de penal")
    assert tutor.sessao is not None and len(tutor.sessao.itens) == 2
    assert all(i.materia == "Direito Penal" for i in tutor.sessao.itens)


# ---------- diário e aprendizado ----------

def test_o_que_estudei_e_o_que_aprendi(tutor):
    assert "Não encontrei estudo" in tutor.atender("o que eu estudei hoje?").fala
    tutor.atender("me ensina princípios do direito penal")
    for _ in TRILHA.topico("principios").pontos:
        tutor.atender("próximo")
    _responder_fixacao(tutor)
    tutor.atender("lê o artigo 1 do código penal")
    tutor.contexto_da_lei("qual a pena do roubo?")
    s = tutor.atender("o que eu estudei hoje?")
    assert "Teve aula de Princípios do Direito Penal" in s.fala
    assert "Respondeu 4 questões, com 100 por cento" in s.fala
    assert "Leu o art. 1º do Código Penal" in s.fala
    assert "Tirou dúvidas sobre Crimes contra o patrimônio" in s.fala
    tutor.relogio.dia = date(2026, 11, 14)
    assert "Não encontrei estudo registrado hoje" in tutor.atender("o que eu estudei hoje?").fala
    assert "Teve aula" in tutor.atender("o que eu estudei ontem?").fala
    a = tutor.atender("o que eu já aprendi?")
    assert "Princípios do Direito Penal" in a.fala and "faltam 15" in a.quadro


def test_o_que_aprendi_mostra_o_que_ainda_erra(tutor):
    top = TRILHA.topico("ilicitude")
    item = TRILHA.itens_de_fixacao(top)[1]
    for _ in range(3):
        tutor.caderno.registrar(item.id, False)
    fala, quadro = tutor.progresso(TRILHA).resumo_aprendizado()
    assert "Precisa reforçar Ilicitude" in fala
    assert "atual ou iminente" in fala and "Rever:" in quadro


# ---------- o cérebro recebe as notas conferidas ----------

def test_pergunta_livre_leva_as_notas_atualizadas(tutor):
    ctx = tutor.contexto_da_lei("qual a pena do roubo?")
    assert "Notas CONFERIDAS" in ctx and "6 a 10 anos" in ctx and "NÃO contradiga" in ctx
    assert tutor.caderno.eventos[-1]["k"] == "duvida"
    assert tutor.contexto_da_lei("o que é crase?") == ""


def test_artigo_do_cp_sem_texto_vira_explicacao_pelas_notas(tutor):
    s = tutor.atender("lê o artigo 155 do código penal")
    assert s.contexto and "NÃO tem o texto literal" in s.contexto and "1 a 6 anos" in s.contexto
    s = tutor.atender("lê o artigo 1 do código penal")                # este está na lei seca
    assert s.fala and "Não há crime sem lei anterior" in s.fala


def test_pomodoro_de_penal_vira_direito_penal(tutor):
    assert "Direito Penal" in tutor.registrar_estudo("penal", 25)


# ---------- mapa ----------

def test_mapa_em_html(tutor, tmp_path, monkeypatch):
    from socrates.estudo import mapa
    monkeypatch.setattr(mapa, "PASTA", tmp_path / "Socrates")
    _registrar(tutor, "principios", [True] * 6)
    s = tutor.atender("mostra meu mapa de penal")
    html = (tmp_path / "Socrates" / "mapa-prf-penal.html").read_text(encoding="utf-8")
    assert s.abrir_pagina.endswith("mapa-prf-penal.html")
    assert "Próximo passo" in html and "Lei penal no tempo" in html
    assert "domina · " in html and "Lei 15.397/2026" in html
    assert "<script" not in html                                       # página estática


# ---------- na conversa por voz ----------

@pytest.mark.asyncio
async def test_aula_por_voz_mostra_o_ponto_e_o_cerebro_explica(tutor):
    from socrates.stt.groq_whisper import DICA_PENAL
    from test_maos_livres import _montar

    conversa, s, painel, cerebro, tela = _montar(janela=0.05, janela_prova=5)
    conversa.tutor = tutor
    painel.tem_visor = False
    dicas = []
    original = s.ouvido.transcrever

    async def transcrever(wav, dica=None):
        dicas.append(dica)
        return await original(wav)
    s.ouvido.transcrever = transcrever

    fila = asyncio.Queue()
    tarefa = asyncio.create_task(conversa.rodar(fila))
    fila.put_nowait(s.ouvido.fala("Sócrates, me ensina legítima defesa"))
    await asyncio.sleep(0.5)
    fila.put_nowait(s.ouvido.fala("próximo"))          # sem dizer o nome: está na aula
    await asyncio.sleep(0.5)
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)

    assert len(cerebro.recebido) == 2
    primeiro = cerebro.recebido[0]
    assert primeiro[-1]["content"] == "me ensina legítima defesa"
    assert primeiro[-2]["role"] == "system" and "PONTO 1 de" in primeiro[-2]["content"]
    assert "PONTO 2 de" in cerebro.recebido[1][-2]["content"]
    quadros = [x for x in tela if "┌─ quadro" in x]
    assert len(quadros) >= 2 and "1/" in quadros[0]
    assert dicas[1] == DICA_PENAL
