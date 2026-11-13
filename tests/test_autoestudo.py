"""Autoestudo: ler a lei no Planalto, escolher o assunto, escrever, conferir, gravar e usar."""

import asyncio
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from socrates.estudo import Caderno, Tutor
from socrates.estudo import autoestudo as auto
from socrates.estudo import material as mat
from socrates.estudo.leitor_lei import (Biblioteca, ErroLei, decodificar, faixa, mudancas_desde,
                                        separar_artigos, texto_em_vigor)
from socrates.estudo.plano import achar_materia, achar_topico, carregar_leis, carregar_planos
from socrates.estudo.trilha import carregar_trilhas
from socrates.llm.base import ErroLimite

DADOS = Path(__file__).parent / "dados"
PLANOS = carregar_planos(ids=["prf", "cbmgo"])
LEIS = carregar_leis()


def pagina(nome: str) -> str:
    return decodificar((DADOS / f"planalto-{nome}.htm").read_bytes())


# ---------- a lei no Planalto ----------

def test_le_a_lei_sem_o_texto_riscado():
    arts = separar_artigos(texto_em_vigor(pagina("l8072")))
    um = arts["1"].texto
    assert "São considerados hediondos os seguintes crimes" in um
    assert "hediondos os crimes de latrocínio" not in um         # redação original, riscada
    assert ("Lei 8.930", 1994) in arts["1"].mudancas
    assert arts["2"].texto.startswith("Art. 2º Os crimes hediondos")


def test_le_incisos_e_paragrafos_da_tortura():
    arts = separar_artigos(texto_em_vigor(pagina("l9455")))
    assert list(arts)[:4] == ["1", "2", "3", "4"]
    t = arts["1"].texto
    assert "I - constranger alguém com emprego de violência ou grave ameaça" in t
    assert "\nII - submeter alguém, sob sua guarda" in t
    assert "§ 5º A condenação acarretará a perda do cargo" in t


def test_sufixo_do_artigo_e_ordinal():
    t = "Art. 3º - A lei excepcional vale.\nArt. 121-A. Matar mulher.\nArt. 10 - O prazo conta.\nArt. 5o-A Os dados."
    assert list(separar_artigos(t)) == ["3", "121-A", "10", "5-A"]


def test_mudancas_recentes_da_faixa():
    texto = ("Art. 1º Regra antiga. (Redação dada pela Lei nº 9.000, de 1995)\n"
             "Art. 2º Regra nova. (Redação dada pela Lei nº 15.999, de 2026)\n"
             "Art. 3º Incluída. (Incluído pela Lei nº 15.888, de 18 de março de 2026)")
    arts = separar_artigos(texto)
    assert arts["3"].mudancas == [("Lei 15.888", 2026)]
    novas = mudancas_desde(arts, 2026, (2, ""), (3, "Z"))
    assert [(a.chave, lei) for a, lei, _ in novas] == [("2", "Lei 15.999"), ("3", "Lei 15.888")]


def test_faixa_de_artigos():
    assert faixa("CPP 301-310") == ("CPP", (301, ""), (310, "Z"))
    assert faixa("L12850 1-21-B") == ("L12850", (1, ""), (21, "B"))
    assert faixa("CTB 136-139-B") == ("CTB", (136, ""), (139, "B"))
    assert faixa("CF 5") == ("CF", (5, ""), (5, "Z"))
    assert faixa("busca livre") is None


def test_biblioteca_guarda_a_lei_e_usa_sem_internet(tmp_path):
    chamadas = []

    def baixar(url):
        chamadas.append(url)
        return pagina("l9455")

    reg = {"L9455": {"nome": "Lei de Tortura", "url": "https://exemplo/l9455.htm"}}
    b = Biblioteca(reg, tmp_path, baixar)
    assert "Constitui crime de tortura" in b.artigos("L9455")["1"].texto
    b2 = Biblioteca(reg, tmp_path, lambda url: (_ for _ in ()).throw(ErroLei("sem internet")))
    assert "1" in b2.artigos("L9455") and len(chamadas) == 1      # usou a cópia guardada


# ---------- os planos (editais) ----------

def test_planos_bem_formados():
    assert [p.id for p in PLANOS] == ["prf", "cbmgo"]
    prf = PLANOS[0]
    assert sum(len(m.topicos) for m in prf.materias) > 100
    for p in PLANOS:
        for m in p.materias:
            for t in m.topicos:
                assert t.fontes or t.pesquisa, t.chave
                for f in t.fontes:
                    fx = faixa(f)
                    assert fx, f"{t.chave}: {f}"
                    assert fx[0] in LEIS, f"{t.chave}: lei {fx[0]} fora de leis.json"


def test_plano_usa_os_mesmos_ids_das_trilhas_conferidas():
    trilhas = {t.id: t for t in carregar_trilhas()}
    for m in PLANOS[0].materias:
        if m.trilha in trilhas:
            assert [t.id for t in m.topicos] == [t.id for t in trilhas[m.trilha].topicos], m.trilha


def test_acha_o_topico_do_edital_na_fala():
    assert achar_topico(PLANOS, "aprende sobre crase").id == "crase"
    assert achar_topico(PLANOS, "me ensina concordância verbal").id == "concordancia"
    assert achar_topico(PLANOS, "estuda teoria do fogo").id == "teoria-fogo"
    assert achar_topico(PLANOS, "bom dia") is None
    assert achar_materia(PLANOS, "vamos estudar física").trilha == "prf-fisica"


# ---------- o motor, com cérebros de mentira ----------

class Escritor:
    nome, modelo = "mistral", "medio"

    def __init__(self, conteudo=None):
        self.pedidos = []
        self.conteudo = conteudo or {
            "palavras": ["tortura", "tortura castigo", "Crime"],
            "pontos": [f"Ponto {i} sobre a tortura, art. 1º da Lei 9.455/1997, com detalhe." for i in range(7)],
            "pegadinhas": ["A banca troca a omissão (detenção) pela tortura comum (reclusão)."],
            "itens": [{"t": f"Item {i}: afirmação sobre a tortura no estilo da banca.", "r": "CE"[i % 2],
                       "j": "Art. 1º."} for i in range(6)],
            "novidades": []}

    async def responder(self, msgs):
        self.pedidos.append(msgs)
        yield "```json\n" + json.dumps(self.conteudo, ensure_ascii=False)[:40]
        yield json.dumps(self.conteudo, ensure_ascii=False)[40:] + "\n```"


class Conferente:
    nome, modelo = "gemini", "flash"

    def __init__(self, contra=(0,), sem_apoio=(1,), erra_itens=(0,)):
        self.contra, self.sem_apoio, self.erra_itens = contra, sem_apoio, erra_itens
        self.pedidos = []

    async def responder(self, msgs):
        self.pedidos.append(msgs)
        pedido = msgs[-1]["content"]
        def conta(titulo, fim):
            bloco = pedido.split(titulo)[1].split(fim)[0]
            return sum(1 for linha in bloco.split("\n") if linha[:1].isdigit())
        n_pontos = conta("PONTOS:", "PEGADINHAS")
        n_novidades = conta("NOVIDADES:", "ITENS (")
        n_itens = conta("ITENS (", "Responda SÓ")
        pontos = ["X" if i in self.contra else "N" if i in self.sem_apoio else "S" for i in range(n_pontos)]
        itens = []
        for i in range(n_itens):
            certo = "CE"[i % 2]
            itens.append(("E" if certo == "C" else "C") if i in self.erra_itens else certo)
        yield json.dumps({"pontos": pontos, "pegadinhas": ["S"], "novidades": ["S"] * n_novidades,
                          "itens": itens})


class Relogio:
    def __init__(self):
        self.agora = datetime(2026, 11, 13, 20, 0)

    def __call__(self):
        return self.agora


def motor(tmp_path, escritor=None, conferente=None, buscar=None, ler=None, **kw):
    reg = dict(LEIS)
    paginas = {"L9455": pagina("l9455"), "L5553": pagina("l5553"), "L8072": pagina("l8072")}

    def baixar(url):
        for sigla, html in paginas.items():
            if reg[sigla]["url"] == url:
                return html
        raise ErroLei("fora do teste")

    m = auto.Autoestudo(PLANOS, escritor or Escritor(), conferente or Conferente(),
                        Biblioteca(reg, tmp_path / "leis", baixar),
                        buscar=buscar or (lambda q: [{"title": "Página", "href": "https://www.gov.br/x"}]),
                        ler=ler or (lambda u: "Texto de estudo sobre o assunto, com regras e exemplos. " * 20),
                        pasta=tmp_path / "Socrates", pasta_trilhas=tmp_path / "Socrates" / "trilhas",
                        relogio=kw.pop("relogio", Relogio()), pausa_seg=0, ocioso_seg=0, **kw)
    return m


def tarefa(chave):
    trilha, tid = chave.split(":")
    t = next(t for p in PLANOS for m in p.materias if m.trilha == trilha for t in m.topicos if t.id == tid)
    return auto.Tarefa(t, "novo")


def test_primeiro_assunto_e_o_que_mais_cai_e_depois_alterna(tmp_path):
    m = motor(tmp_path)
    t1 = m.proxima()
    assert t1.materia.trilha == "prf-transito" and t1.topico.peso == 3
    asyncio.run(_gravar_falso(m, t1))
    t2 = m.proxima()
    assert t2.materia.trilha == "prf-portugues"        # não fica só em trânsito


async def _gravar_falso(m, t):
    m.gravar(t, {"palavras": ["x"], "pontos": ["p" * 30] * 5, "pegadinhas": [], "novidades": [],
                 "itens": [{"t": "i" * 30, "r": "C", "j": ""}] * 3}, [])


def test_estuda_pela_lei_confere_e_grava(tmp_path):
    esc, conf = Escritor(), Conferente()
    m = motor(tmp_path, esc, conf)
    r = asyncio.run(m.estudar(tarefa("prf-legislacao-especial:tortura")))
    assert r.ok, r.motivo
    # o escritor recebeu o texto oficial em vigor
    pedido = esc.pedidos[0][-1]["content"]
    assert "TEXTO OFICIAL DA LEI, EM VIGOR" in pedido and "Constitui crime de tortura" in pedido
    # quem confere é outro modelo e não vê o gabarito
    assert "sem gabarito" in conf.pedidos[0][-1]["content"]
    assert '"r": "C"' not in conf.pedidos[0][-1]["content"]
    arq = tmp_path / "Socrates" / "trilhas" / "auto-prf-legislacao-especial.json"
    dados = json.loads(arq.read_text(encoding="utf-8"))
    top = next(t for t in dados["topicos"] if t["id"] == "tortura")
    assert top["origem"] == "auto" and top["gerado"] == "2026-11-13"
    assert "Ponto 0" not in json.dumps(top)            # a fonte contradiz: saiu
    assert "Ponto 1" not in json.dumps(top)            # sem apoio na lei: saiu
    assert len(top["pontos"]) == 5 and len(top["itens"]) == 5     # o item 0 não bateu
    assert "crime" not in top["palavras"] and "tortura" in top["palavras"]
    assert r.descartados == 3
    registro = json.loads((tmp_path / "Socrates" / "aprendizado.json").read_text(encoding="utf-8"))
    assert registro[-1]["ok"] and registro[-1]["titulo"] == "Tortura"
    assert m.feitos_hoje() == 1


def test_sem_lei_pesquisa_na_internet(tmp_path):
    buscas = []

    def buscar(q):
        buscas.append(q)
        return [{"title": "Vídeo", "href": "https://youtube.com/x"},
                {"title": "Blog", "href": "https://blog.exemplo.com/crase"},
                {"title": "Gov", "href": "https://www.gov.br/crase"}]

    lidas = []

    def ler(url):
        lidas.append(url)
        return "Crase é a fusão da preposição a com o artigo a. " * 30

    esc = Escritor()
    m = motor(tmp_path, esc, Conferente(contra=(), sem_apoio=(1,), erra_itens=()), buscar, ler)
    r = asyncio.run(m.estudar(tarefa("prf-portugues:crase")))
    assert r.ok
    assert "crase" in buscas[0]
    assert lidas[0] == "https://www.gov.br/crase"      # site oficial primeiro; vídeo fica de fora
    assert "youtube" not in " ".join(lidas)
    top = carregar_trilhas(extra=tmp_path / "Socrates" / "trilhas")
    crase = next(t for t in top if t.id == "prf-portugues").topico("crase")
    assert len(crase.pontos) == 7                      # sem lei, o "não trata" fica


def test_pouco_conteudo_confiavel_nao_grava_e_espera(tmp_path):
    rel = Relogio()
    m = motor(tmp_path, Escritor(), Conferente(contra=range(10)), relogio=rel)
    t = tarefa("prf-legislacao-especial:tortura")
    r = asyncio.run(m.estudar(t))
    assert not r.ok and "pouco conteúdo" in r.motivo
    assert not (tmp_path / "Socrates" / "trilhas" / "auto-prf-legislacao-especial.json").exists()
    assert m._esperando(t.chave)
    rel.agora += timedelta(hours=7)
    assert not m._esperando(t.chave)


def test_lei_mudou_agenda_atualizacao_do_topico_conferido(tmp_path):
    m = motor(tmp_path)
    # a cópia de 8.072 do teste mostra mudanças antigas; uma "nova", de 2026, entra assim:
    import re
    html = re.sub(r"\(Redação dada pela Lei nº 8\.930, de\s*1994\)",
                  "(Redação dada pela Lei nº 15.999, de 2026)", pagina("l8072"), count=1)
    assert "15.999" in html
    m.biblioteca.baixar_pagina = lambda url: html
    m.dados["leis"] = {sigla: "2026-11-13" for sigla in LEIS if sigla != "L8072"}   # só falta a 8.072
    tarefas = m.conferir_uma_lei()
    assert any(t.topico.id == "hediondos" and t.tipo == "atualizar" for t in tarefas), \
        [(t.topico.id, t.motivo) for t in tarefas]
    t = next(t for t in tarefas if t.topico.id == "hediondos")
    assert "Lei 15.999/2026" in t.motivo
    assert m.proxima().topico.id in {x.topico.id for x in tarefas}       # vem antes do resto


def test_atualizacao_entra_nas_novidades_do_conferido(tmp_path):
    esc = Escritor({"novidades": ["A Lei 15.999/2026 incluiu um crime no rol dos hediondos."],
                    "itens": [{"t": "A Lei 15.999/2026 incluiu crime no rol dos hediondos.", "r": "C",
                               "j": "Art. 1º."}]})
    conf = Conferente(contra=(), sem_apoio=(), erra_itens=())
    m = motor(tmp_path, esc, conf)
    html = pagina("l8072")
    arts = separar_artigos(texto_em_vigor(html))
    t = tarefa("prf-legislacao-especial:hediondos")
    t.tipo, t.mudancas = "atualizar", [(arts["1"], "Lei 15.999", 2026, "L8072")]
    r = asyncio.run(m.estudar(t))
    assert r.ok
    tr = next(x for x in carregar_trilhas(extra=tmp_path / "Socrates" / "trilhas")
              if x.id == "prf-legislacao-especial")
    top = tr.topico("hediondos")
    assert top.origem == "conferido"                   # continua o conferido...
    assert "A Lei 15.999/2026 incluiu um crime no rol dos hediondos." in top.novidades   # ...com a novidade
    assert top.itens[-1]["t"].startswith("A Lei 15.999/2026")


def test_laco_espera_no_limite_gratis_e_tenta_de_novo(tmp_path):
    class Limite(Escritor):
        def __init__(self):
            super().__init__()
            self.vezes = 0

        async def responder(self, msgs):
            self.vezes += 1
            if self.vezes == 1:
                raise ErroLimite("limite", espera=1)
            async for x in super().responder(msgs):
                yield x

    esc = Limite()
    m = motor(tmp_path, esc, Conferente(contra=(), sem_apoio=(), erra_itens=()))
    esperas = []

    async def dormir(seg):
        esperas.append(seg)

    m._dormir = dormir
    m.pedir("aprende sobre tortura")
    n = asyncio.run(m.rodar(max_assuntos=1, esperar_livre=False))
    assert n == 1 and esc.vezes >= 2 and esperas and esperas[0] >= 60
    assert (tmp_path / "Socrates" / "trilhas" / "auto-prf-legislacao-especial.json").exists()


def test_respeita_o_limite_do_dia_e_a_pausa(tmp_path):
    m = motor(tmp_path, por_dia=1)
    m.dados["dias"]["2026-11-13"] = 1
    estados = []
    m.ao_mudar = estados.append

    async def dormir(seg):
        m.parar()

    m._dormir = dormir
    asyncio.run(m.rodar(esperar_livre=False))
    assert any("volto amanhã" in e for e in estados)
    m2 = motor(tmp_path / "b")
    m2.pausar()
    assert motor(tmp_path / "b").pausado                 # a pausa vale na próxima vez também


# ---------- falar com o autoestudo ----------

@pytest.mark.parametrize("fala,cmd", [
    ("Sócrates, o que você está aprendendo?", "status"), ("o que você aprendeu hoje?", "hoje"),
    ("o que você aprendeu essa semana?", "semana"), ("pausa o aprendizado", "pausar"),
    ("para de aprender", "pausar"), ("volta a aprender", "retomar"), ("aprende sobre crase", "pedir"),
    ("estuda pra mim o ECA", "pedir"), ("o que eu aprendi?", None), ("me ensina crase", None),
])
def test_entende_os_comandos(fala, cmd):
    r = auto.entender(fala)
    assert (r[0] if r else None) == cmd


def test_pedido_vai_para_a_frente_da_fila(tmp_path):
    m = motor(tmp_path)
    fala, t = m.pedir("aprende sobre crase")
    assert "vou estudar Crase" in fala
    assert m.proxima().topico.id == "crase"
    fala, t = m.pedir("aprende sobre a história do xadrez")
    assert t.materia.id == "extras" and "A história do xadrez" in fala
    assert m.proxima().tipo == "pedido"


def test_resumo_do_que_aprendeu(tmp_path):
    m = motor(tmp_path, Escritor(), Conferente(contra=(), sem_apoio=(), erra_itens=()))
    asyncio.run(m.estudar(tarefa("prf-legislacao-especial:tortura")))
    fala, quadro = m.resumo(0)
    assert "Hoje eu aprendi 1 assunto, como Tortura" in fala
    assert "Tortura (Legislação Especial)" in quadro
    assert "Hoje já estudei 1" in m.status()


def test_extrair_json_tolerante():
    assert auto.extrair_json('Claro! {"a": [1, {"b": "}"}]} fim') == {"a": [1, {"b": "}"}]}
    assert auto.extrair_json("```json\n{\"x\": 1}\n```") == {"x": 1}
    assert auto.extrair_json("sem json") is None


# ---------- o tutor usa o que ele aprendeu ----------

@pytest.fixture
def tutor_com_motor(tmp_path, monkeypatch):
    from socrates.estudo import trilha
    pasta_auto = tmp_path / "Socrates" / "trilhas"
    monkeypatch.setattr(trilha, "PASTA_AUTO", pasta_auto)
    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    (pasta / "bancos/index.json").write_text("[]")
    (pasta / "bancos/lei-index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    t = Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0), planos=PLANOS)
    motor_ = motor(tmp_path, Escritor(), Conferente(contra=(), sem_apoio=(), erra_itens=()))
    motor_.ao_aprender = t.marcar_recarga
    t.autoestudo = motor_
    return t, motor_


def test_aula_de_assunto_que_falta_pede_ao_autoestudo(tutor_com_motor):
    t, m = tutor_com_motor
    s = t.atender("me ensina crase")
    assert s.contexto and "ainda não tem a aula completa" in s.contexto
    assert m.fila and m.fila[0].topico.id == "crase"
    assert "o que você está aprendendo" and "Na fila: Crase" in t.atender("o que você está aprendendo?").fala


def test_depois_de_aprender_a_aula_existe(tutor_com_motor):
    t, m = tutor_com_motor
    asyncio.run(m.estudar(tarefa("prf-portugues:crase")))
    s = t.atender("me ensina crase")
    assert t.aula is not None and t.aula.topico.auto
    assert "Crase · 1/7" in s.quadro
    assert "autoestudo" in s.contexto
    t.encerrar()
    q = t.atender("questões de crase")
    assert t.sessao is not None and q.fala


def test_mapa_geral_com_o_autoestudo(tutor_com_motor, tmp_path, monkeypatch):
    from socrates.estudo import mapa
    t, m = tutor_com_motor
    monkeypatch.setattr(mapa, "PASTA", tmp_path / "Socrates")
    asyncio.run(m.estudar(tarefa("prf-portugues:crase")))
    s = t.atender("mostra meu mapa")
    html = Path(s.abrir_pagina).read_text(encoding="utf-8")
    assert "Meu mapa de estudo" in html and "Língua Portuguesa" in html and "autoestudo" in html
    assert "Direito Penal" in html and "Crase" in html
