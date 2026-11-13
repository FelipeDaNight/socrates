"""Estudo com o material de verdade: treino por voz, lacunas, revisão, lei seca, planilha."""

import asyncio
import json
import random
from datetime import date

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.planilha import Planilha
from socrates.estudo.respostas import alternativa, certo_ou_errado, comando, lacuna_certa

PRF = {"id": "prf-2021-p1", "titulo": "PRF 2021 · Policial Rodoviário Federal (Cebraspe)",
       "tipo": "ce", "sincroniza_simulado": True, "questoes": [
           {"n": 1, "materia": "Legislação de Trânsito", "topico": "PRF 2021 · item 61", "tipo": "ce",
            "resp": "E", "enunciado": "Julgue.\n\nÉ de seis meses o prazo do registrador.",
            "just": "Gabarito oficial definitivo (Cebraspe): ERRADO."},
           {"n": 2, "materia": "Legislação de Trânsito", "topico": "PRF 2021 · item 62", "tipo": "ce",
            "resp": "C", "enunciado": "Julgue.\n\nO CRLV-e é digital.", "just": "Gabarito: CERTO."},
           {"n": 3, "materia": "Informática", "topico": "PRF 2021 · item 90", "tipo": "ce",
            "resp": "C", "enunciado": "O Linux é um sistema operacional.", "just": ""},
       ]}
CBM = {"id": "cbmgo-2022-soldado", "titulo": "CBMGO 2022 · Soldado (AOCP)", "tipo": "mc", "questoes": [
    {"n": 26, "materia": "Legislação CBM-GO", "topico": "Estatuto: agregação", "tipo": "mc", "resp": "C",
     "just": "Agregação após 1 ano contínuo de licença.", "enunciado": "Moisés será agregado após:",
     "alternativas": {"A": "3 meses", "B": "6 meses", "C": "1 ano", "D": "2 anos", "E": "3 anos"}},
    {"n": 15, "materia": "Raciocínio Lógico", "topico": "x", "tipo": "mc", "resp": "C", "img": "a.png",
     "enunciado": "Veja a figura", "alternativas": {"A": "1", "B": "2", "C": "3", "D": "4", "E": "5"}},
]}
CTB = {"id": "ctb-prf", "tipo": "leiseca", "blocos": [
    {"id": "ctb-1", "dia": "CTB · Dia 1", "lei": "CTB", "rotulo": "Cap. I · Art. 1º a Art. 4º", "artigos": [
        {"art": "Art. 1º", "titulo": "", "itens": [
            {"k": "lei", "t": "Art. 1º O trânsito de qualquer natureza nas vias terrestres rege-se por este Código."}],
         "lacunas": [{"c": "Art. 1º O trânsito nas ____ rege-se por este Código.", "r": "vias terrestres", "i": "h1"},
                     {"c": "§ 3º Os órgãos respondem ____ por danos.", "r": "objetivamente", "i": "h4"}],
         "resumo": "O CTB rege o trânsito nas vias terrestres."}]},
    {"id": "ctb-30", "lei": "CTB", "rotulo": "Infrações", "artigos": [
        {"art": "Art. 165", "titulo": "", "itens": [
            {"k": "lei", "t": "Art. 165. Dirigir sob a influência de álcool:"},
            {"k": "lei", "t": "Infração - gravíssima;"}],
         "lacunas": [], "ficha": {"natureza": "gravíssima", "pontos": 7, "multa_base": "R$ 293,47"},
         "resumo": "Infração gravíssima (7 pontos)."},
        {"art": "Art. 167", "titulo": "", "itens": [
            {"k": "lei", "t": "Art. 167. Deixar o condutor ou passageiro de usar o cinto de segurança:"},
            {"k": "lei", "t": "Infração - grave;"}],
         "lacunas": [], "resumo": "Infração grave (5 pontos)."}]},
]}


def _gravar(pasta, bancos, leis):
    (pasta / "bancos").mkdir(parents=True)
    idx = []
    for b in bancos:
        arq = f"bancos/{b['id']}.json"
        (pasta / arq).write_text(json.dumps(b, ensure_ascii=False), encoding="utf-8")
        idx.append({"id": b["id"], "arquivo": arq, "titulo": b["titulo"]})
    (pasta / "bancos/index.json").write_text(json.dumps(idx), encoding="utf-8")
    li = []
    for lei in leis:
        arq = f"bancos/{lei['id']}.json"
        (pasta / arq).write_text(json.dumps(lei, ensure_ascii=False), encoding="utf-8")
        li.append(arq)
    (pasta / "bancos/lei-index.json").write_text(json.dumps(li), encoding="utf-8")


class Relogio:
    def __init__(self):
        self.dia = date(2026, 11, 12)

    def __call__(self):
        return self.dia


@pytest.fixture
def tutor(tmp_path):
    _gravar(tmp_path / "material", [PRF, CBM], [CTB])
    m = mat.carregar(tmp_path / "material", tmp_path / "privado", baixar_se_faltar=False)
    relogio = Relogio()
    t = Tutor(m, Caderno(tmp_path / "caderno.json", relogio=relogio), sortear=random.Random(0))
    t.relogio = relogio
    return t


# ---------- respostas faladas ----------

@pytest.mark.parametrize("fala,esperado", [("Letra Bê.", "B"), ("Acho que é a letra C", "C"),
                                           ("D", "D"), ("letra B, não, letra C", "C"), ("Bom dia", None)])
def test_entende_a_alternativa(fala, esperado):
    assert alternativa(fala) == esperado


@pytest.mark.parametrize("fala,esperado", [("Certo.", "C"), ("Acho que é errado", "E"),
                                           ("Errado, não, certo!", "C"), ("É", None), ("Falso", "E")])
def test_entende_certo_ou_errado(fala, esperado):
    assert certo_ou_errado(fala) == esperado


@pytest.mark.parametrize("fala,esperado", [("Próxima.", "pular"), ("Pode parar o treino", "parar"),
                                           ("explica por que", "explicar"), ("me dá uma dica", "dica"),
                                           ("mostra o texto completo", "texto"), ("letra b", None)])
def test_comandos_do_treino(fala, esperado):
    assert comando(fala) == esperado


def test_lacuna_aceita_jeitos_de_dizer():
    assert lacuna_certa("as vias terrestres", "vias terrestres")
    assert lacuna_certa("12 meses", "12 (doze) meses") and lacuna_certa("doze meses", "12 (doze) meses")
    assert not lacuna_certa("subjetivamente", "objetivamente")
    assert not lacuna_certa("grave", "gravíssima")


# ---------- pedidos ----------

@pytest.mark.parametrize("fala,tipo", [
    ("questões da PRF", "questoes"), ("5 questões de trânsito da PRF", "questoes"),
    ("simulado de 20 questões do CBMGO", "simulado"), ("lacunas do CTB", "lacunas"),
    ("revisa meus erros", "revisao"), ("lê o artigo 165 do CTB", "artigo"),
    ("como estou indo?", "desempenho"), ("o que eu estudo hoje?", "plano"),
    ("me testa em crase", None), ("o que cai na PRF?", None), ("o que é crase?", None),
])
def test_entende_pedidos_de_estudo(tutor, fala, tipo):
    p = tutor.entender(fala)
    assert (p.tipo if p else None) == tipo


def test_filtra_materia_e_quantidade(tutor):
    p = tutor.entender("2 questões de informática da PRF")
    assert (p.banco, p.materia, p.n) == ("prf-2021-p1", "Informática", 2)


# ---------- treino ----------

def test_treino_corrige_pelo_gabarito_e_explica_com_ele(tutor):
    s = tutor.atender("questões de trânsito da PRF")
    assert "Certo ou errado?" in s.fala and s.quadro.startswith("# PRF 2021 · item")
    atual = tutor.sessao.atual
    errada = "Certo" if atual.resp == "E" else "Errado"
    s = tutor.atender(errada)
    assert s.fala.startswith("Não. O gabarito é")
    s = tutor.atender("explica por quê")
    assert s.contexto and "Gabarito OFICIAL" in s.contexto and f"O aluno respondeu: {errada}" in s.contexto
    s = tutor.atender("próxima")
    assert "2 de 2" in s.fala
    certa = "Certo" if tutor.sessao.atual.resp == "C" else "Errado"
    s = tutor.atender(certa)
    assert s.fim and "1 certa e 1 errada" in s.fala and tutor.sessao is None
    assert tutor.caderno.itens[atual.id]["erros"] == 1
    assert tutor.caderno.dados["sessoes"][-1]["acertos"] == 1


def test_questao_desatualizada_treina_pela_lei_de_hoje():
    """Item de prova com gabarito que a lei mudou depois ("atual"): treina-se a regra de hoje,
    contando que a prova antiga cobrava a anterior."""
    from socrates.estudo.treino import Sessao, item_de_questao
    banco = {"id": "prf-2021-p1", "titulo": "PRF 2021", "tipo": "ce"}
    q = {"n": 74, "materia": "Legislação de Trânsito", "topico": "PRF 2021 · item 82", "tipo": "ce",
         "resp": "E", "atual": "C", "enunciado": "É admitida a tolerância de 12,5% sobre o peso por eixo.",
         "just": "Gabarito oficial definitivo (Cebraspe): ERRADO.",
         "atualizacao": "Lei 14.229/2021: a tolerância por eixo subiu de 10% para 12,5%."}
    it = item_de_questao(banco, q)
    assert (it.resp, it.oficial, it.mudou) == ("C", "E", True)
    assert "hoje o gabarito é Certo" in it.comentario() and "14.229/2021" in it.comentario()
    ctx = it.contexto(revelar=True, resposta_aluno="Errado")
    assert "Gabarito pela lei ATUAL: Certo" in ctx and "foi Errado" in ctx and "Gabarito OFICIAL" not in ctx
    s = Sessao([it], "treino", "Teste")
    s.abrir()
    saida = s.atender("Errado")
    assert saida.fala.startswith("Não. O gabarito é Certo.") and "lei mudou" in saida.fala
    # sem "atual" (ou igual ao oficial), nada muda
    sem = item_de_questao(banco, {**q, "atual": "E"})
    assert (sem.resp, sem.mudou) == ("E", False) and "Gabarito OFICIAL: Errado" in sem.contexto(True)


def test_dica_nao_revela_a_resposta(tutor):
    tutor.atender("questões do CBMGO")
    s = tutor.atender("me dá uma dica")
    assert "AINDA NÃO respondeu" in s.contexto and "Gabarito OFICIAL" not in s.contexto


def test_questao_com_figura_fica_de_fora(tutor):
    s = tutor.atender("questões do CBMGO")
    assert "1 questões" in s.fala or "1 de 1" in s.fala
    assert "Moisés" in s.fala and "- C) 1 ano" in s.quadro
    assert tutor.atender("letra C").fala.startswith("Certo! Agregação")


def test_simulado_so_corrige_no_fim_com_nota_cebraspe(tutor):
    s = tutor.atender("simulado da PRF")
    assert "Não vou corrigir até o fim" in s.fala
    respostas = []
    while tutor.sessao:
        r = "Errado" if len(respostas) == 0 else "Certo"
        respostas.append(r)
        s = tutor.atender(r)
        if not s.fim:
            assert s.fala.startswith("Anotado.")
    assert "nota é" in s.fala and "Nota Cebraspe" in s.quadro


def test_trocar_de_treino_no_meio(tutor):
    tutor.atender("questões da PRF")
    s = tutor.atender("lacunas do CTB")
    assert tutor.sessao.modo == "lacunas" and "Complete" in s.fala


def test_consultar_artigo_no_meio_do_treino_nao_perde_a_questao(tutor):
    tutor.atender("questões da PRF")
    antes = tutor.sessao.atual
    s = tutor.atender("lê o artigo 165 do CTB")
    assert "gravíssima" in s.fala and "repete" in s.fala and tutor.sessao.atual is antes


# ---------- lacunas e revisão ----------

def test_lacunas_e_revisao_no_dia_seguinte(tutor):
    s = tutor.atender("lacunas do CTB")
    assert "Complete: Art. 1º O trânsito nas, branco, rege-se" in s.fala
    assert tutor.atender("vias terrestres").fala.startswith("Isso!")
    s = tutor.atender("subjetivamente")
    assert "A resposta é: objetivamente" in s.fala and s.fim
    assert tutor.atender("revisa meus erros").fala.startswith("Nada para revisar")
    tutor.relogio.dia = date(2026, 11, 13)
    s = tutor.atender("revisa meus erros")
    assert "Revisão de 1" in s.fala and "Os órgãos respondem" in s.fala
    s = tutor.atender("objetivamente")
    assert s.fim
    assert tutor.caderno.itens[next(iter(k for k in tutor.caderno.itens if k.endswith("h4")))]["caixa"] == 1


# ---------- lei seca ----------

def test_le_o_artigo_com_ficha(tutor):
    s = tutor.atender("Sócrates, lê o artigo 165 do CTB")
    assert s.fala.startswith("Art. 165 do CTB. Infração gravíssima")
    assert "7 pontos" in s.quadro and r"R\$ 293,47" in s.quadro   # $ escapado para o quadro
    assert "Não tenho o artigo 999" in tutor.atender("artigo 999 do CTB").fala


def test_trechos_da_lei_para_o_cerebro(tutor):
    t = tutor.contexto_da_lei("quantos pontos tem dirigir sem cinto?")
    assert "Art. 167" in t and "Trechos OFICIAIS" in t
    assert tutor.contexto_da_lei("o que é crase?") == ""


# ---------- desempenho, plano e pomodoro ----------

def test_desempenho_e_plano(tutor):
    assert "Ainda não tenho registros" in tutor.desempenho().fala
    tutor.atender("questões de trânsito da PRF")
    tutor.atender("Certo")
    tutor.atender("próxima")
    tutor.atender("Certo")
    s = tutor.atender("como estou indo?")
    assert "respondeu 2 questões" in s.fala and "Legislação de Trânsito" in s.quadro
    p = tutor.atender("o que eu estudo hoje?")
    assert "# Plano de hoje" in p.quadro and "CTB" in p.quadro


def test_pomodoro_anota_os_minutos(tutor, monkeypatch):
    from socrates.ferramentas import computador, estudo
    avisos = []
    monkeypatch.setattr(computador, "avisar", avisos.append)
    estudo.TUTOR = tutor
    assert "começou" in estudo.iniciar_pomodoro("português", 1)
    computador.TIMER.timer.cancel()
    computador.TIMER._tocar()                     # o tempo acabou
    assert "Fim do pomodoro de português" in avisos[0] and "Anotei 1 minutos" in avisos[0]
    assert tutor.caderno.dados["estudo"][-1]["materia"] == "português"
    estudo.TUTOR = None


# ---------- planilha ----------

def test_planilha_envia_no_formato_do_app_e_guarda_sem_internet(tutor, tmp_path):
    pedidos, fora_do_ar = [], [True]

    def http(url, corpo=None):
        if corpo is None:
            return {"ok": True, "listas": {"materias": ["Língua Portuguesa", "Legislação de Trânsito"]}}
        if fora_do_ar[0]:
            raise OSError("sem internet")
        pedidos.append(corpo)
        return {"ok": True, "gravados": [i["id"] for i in corpo["itens"]], "falhas": []}

    pl = Planilha("https://script.google.com/macros/s/X/exec", "segredo", tmp_path / "fila.json", http)
    tutor.planilha = pl
    assert tutor.registrar_estudo("português", 25) == "Anotei 25 minutos de Língua Portuguesa na planilha."
    pl.sincronizar()
    assert len(pl.fila) == 1 and (tmp_path / "fila.json").exists()      # ficou guardado
    fora_do_ar[0] = False
    pl.sincronizar()
    item = pedidos[0]["itens"][0]
    assert pedidos[0]["token"] == "segredo" and item["tipo"] == "estudo"
    assert item["dados"] == {"data": "2026-11-12", "materia": "Língua Portuguesa", "minutos": 25}
    assert pl.fila == []


def test_treino_vai_para_as_abas_questoes_e_erros(tutor, tmp_path):
    enviados = []
    pl = Planilha("u", "k", tmp_path / "f.json", lambda u, c=None: {"ok": True, "gravados": []})
    pl.enviar = lambda tipo, dados, agora=False: enviados.append((tipo, dados))
    tutor.planilha = pl
    tutor.atender("questões de trânsito da PRF")
    tutor.atender("Certo" if tutor.sessao.atual.resp == "E" else "Errado")    # erra
    tutor.atender("parar")
    tipos = [t for t, _ in enviados]
    assert tipos == ["questoes", "erro"]
    assert enviados[0][1]["feitas"] == 1 and enviados[0][1]["erros"] == 1
    assert enviados[0][1]["fonte"] == "PRF 2021 (Sócrates)"


# ---------- material ----------

def test_baixa_o_material_do_app(tmp_path):
    arquivos = {"bancos/index.json": json.dumps([{"id": "x", "arquivo": "bancos/x.json"}]),
                "bancos/lei-index.json": json.dumps(["bancos/l.json"]),
                "bancos/x.json": json.dumps({"id": "x", "questoes": []}),
                "bancos/l.json": json.dumps({"id": "l", "blocos": []})}
    n = mat.baixar("https://raw/", tmp_path, lambda *a, **k: None,
                   lambda url: arquivos[url.removeprefix("https://raw/")].encode())
    assert n == 4 and (tmp_path / "bancos/l.json").exists()


def test_questoes_privadas(tmp_path):
    (tmp_path / "q").mkdir()
    (tmp_path / "q" / "gran.json").write_text(json.dumps({"questoes": [
        {"materia": "Penal", "topico": "Drogas", "tipo": "ce", "resp": "C", "enunciado": "Item."}]}),
        encoding="utf-8")
    m = mat.carregar(tmp_path / "nada", tmp_path / "q", baixar_se_faltar=False)
    assert m.bancos["meus-erros"]["questoes"][0]["n"] == 1


# ---------- na conversa por voz ----------

@pytest.mark.asyncio
async def test_treino_por_voz_com_janela_longa_e_ouvido_de_respostas(tutor):
    from socrates.stt.groq_whisper import DICA_TREINO
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
    fila.put_nowait(s.ouvido.fala("Sócrates, questões de informática da PRF"))
    await asyncio.sleep(0.5)
    fila.put_nowait(s.ouvido.fala("Certo"))          # sem o nome: a janela do treino é longa
    await asyncio.sleep(0.5)
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)
    falado = " ".join(s.voz.faladas)
    assert "O Linux é um sistema operacional" in falado and "Certo!" in falado
    assert dicas[1] == DICA_TREINO and cerebro.recebido == []     # nada gastou o cérebro
    assert any("┌─ quadro" in t for t in tela)


@pytest.mark.asyncio
async def test_pergunta_de_lei_vai_ao_cerebro_com_o_texto_oficial(tutor):
    from test_maos_livres import _montar, _rodar
    conversa, s, painel, cerebro, _ = _montar()
    conversa.tutor = tutor
    await _rodar(conversa, [s.ouvido.fala("Sócrates, quantos pontos tem dirigir sem cinto?")])
    msgs = cerebro.recebido[0]
    assert msgs[-1]["content"] == "quantos pontos tem dirigir sem cinto?"
    assert msgs[-2]["role"] == "system" and "Art. 167" in msgs[-2]["content"]
    assert "Art. 167" not in str(conversa.soc.historico)     # não fica no histórico


@pytest.mark.asyncio
async def test_obrigado_e_desligar_valem_no_meio_do_treino(tutor):
    from test_maos_livres import _montar, _rodar
    conversa, s, painel, cerebro, _ = _montar()
    conversa.tutor = tutor
    painel.tem_visor = False
    await _rodar(conversa, [s.ouvido.fala("Sócrates, questões da PRF"), s.ouvido.fala("desligar"),
                            s.ouvido.fala("Sócrates, o que é crase?")])
    assert cerebro.recebido == []                  # desligou antes da última pergunta
    assert tutor.sessao is None                    # e guardou o treino
