"""Correções da sessão de 25/11/2026 (Direito Constitucional, 22h38 às 23h39).

No registro:
- "Artigo 5º" mostrou no quadro o art. 5º do ADCT (eleições de 1988), não o da CF: na
  página da Constituição o ADCT vem depois e repete os números 1 a 140.
- O título do quadro saía cortado na borda ("Poder constituinte e emendas à Cons").
- "Coloca um cenário no quadro" abriu o Bloco de Notas com "[QUADRO]..." escrito dentro.
- Uma lição tirada do próprio registro fez ele FALAR "[usou a ferramenta pedir_ao_claude]".
- "Me ensina o artigo 5º da CF" caía em Português (classes de palavras: "artigo").
- "Estudo do artigo 5º da CF, focar nos incisos..." o tutor não entendia, e o modelo falou
  ao aluno o exemplo da mensagem de erro.
- ler_lei do mesmo artigo duas vezes na mesma resposta (estourou o limite grátis).
- "FFFF!" (sopro no microfone) virou fala do aluno.
"""

import json
import random
import shutil
from datetime import date

import pytest

from socrates.core.agente import Agente, _limpar
from socrates.core.memoria import Memorias, licao_ruim
from socrates.core.reflexao import Reflexao
from socrates.estudo import material as mat
from socrates.estudo.caderno import Caderno
from socrates.estudo.leitor_lei import Biblioteca, ErroLei, VERSAO, separar_artigos
from socrates.estudo.plano import carregar_planos
from socrates.estudo.tutor import Tutor
from socrates.llm.acoes import pede_acao
from socrates.stt.groq_whisper import filtrar_alucinacao
from socrates.visor import quadro as q

from test_agente import DADOS

# ---------------------------------------------------------------- CF sem o ADCT

CF_COM_ADCT = """CONSTITUIÇÃO DA REPÚBLICA FEDERATIVA DO BRASIL DE 1988
Art. 5º Todos são iguais perante a lei, sem distinção de qualquer natureza.
XI - a casa é asilo inviolável do indivíduo.
Art. 60. A Constituição poderá ser emendada mediante proposta:
I - de um terço, no mínimo, dos membros da Câmara dos Deputados ou do Senado Federal;
Art. 250. Com o objetivo de assegurar recursos para o pagamento dos benefícios.
Brasília, 5 de outubro de 1988.
ATO DAS DISPOSIÇÕES CONSTITUCIONAIS TRANSITÓRIAS
Art. 5º. Não se aplicam às eleições previstas para 15 de novembro de 1988 o disposto no art. 16.
Art. 60. A complementação da União referida no inciso IV do caput do art. 212-A.
Brasília, 5 de outubro de 1988."""


def test_cf_para_antes_do_adct():
    arts = separar_artigos(CF_COM_ADCT)
    assert "Todos são iguais" in arts["5"].texto
    assert "emendada mediante proposta" in arts["60"].texto
    assert "250" in arts and "eleições" not in arts["5"].texto


def test_sem_o_titulo_numeracao_que_recomeca_depois_do_200_tambem_para():
    sem_titulo = CF_COM_ADCT.replace(
        "ATO DAS DISPOSIÇÕES CONSTITUCIONAIS TRANSITÓRIAS\n",
        "Art. 1º O Presidente da República e os membros do Congresso prestarão o compromisso.\n")
    arts = separar_artigos(sem_titulo)
    assert "Todos são iguais" in arts["5"].texto and "Brasília" not in arts["250"].texto


def test_decreto_com_regulamento_anexo_continua_como_antes():
    """Decreto de poucos artigos + regulamento anexo que recomeça no art. 1º: vale o anexo."""
    texto = ("Art. 1º Fica aprovado o Regulamento anexo.\nArt. 2º Este Decreto entra em vigor.\n"
             "ANEXO\nArt. 1º A PRF tem por finalidade patrulhar as rodovias federais.")
    assert "patrulhar" in separar_artigos(texto)["1"].texto


def test_referencia_ao_adct_no_meio_do_texto_nao_corta():
    texto = ("Art. 1º O texto cita o Ato das Disposições Constitucionais Transitórias no meio.\n"
             "Art. 2º Continua valendo.")
    assert set(separar_artigos(texto)) == {"1", "2"}


def _guardar(pasta, sigla, url, artigos, v=None):
    pasta.mkdir(parents=True, exist_ok=True)
    dados = {"url": url, "data": "2026-11-22",
             "artigos": {k: {"n": int(k), "s": "", "t": t, "m": []} for k, t in artigos.items()}}
    if v is not None:
        dados["v"] = v
    (pasta / f"{sigla}.json").write_text(json.dumps(dados, ensure_ascii=False), encoding="utf-8")


def test_copia_antiga_da_cf_nao_vale_mas_as_outras_leis_sim(tmp_path):
    reg = {"CF": {"url": "https://exemplo/cf.htm"}, "CTB": {"url": "https://exemplo/ctb.htm"}}
    _guardar(tmp_path, "CF", reg["CF"]["url"], {"5": "Art. 5º. Não se aplicam às eleições de 1988"})
    _guardar(tmp_path, "CTB", reg["CTB"]["url"], {"1": "Art. 1º O trânsito de qualquer natureza"})
    sem_internet = Biblioteca(reg, tmp_path, lambda url: (_ for _ in ()).throw(ErroLei("offline")),
                              hoje=lambda: date(2026, 11, 25))
    assert sem_internet.em_cache("CF") is None                  # a errada, nem para ler na hora
    assert "trânsito" in sem_internet.em_cache("CTB")["1"].texto
    with pytest.raises(ErroLei):
        sem_internet.artigos("CF")                              # nem sem internet
    assert "trânsito" in sem_internet.artigos("CTB")["1"].texto


def test_cf_baixada_de_novo_fica_certa_e_guardada_na_versao_nova(tmp_path):
    reg = {"CF": {"url": "https://exemplo/cf.htm"}}
    _guardar(tmp_path, "CF", reg["CF"]["url"], {"5": "Art. 5º. Não se aplicam às eleições de 1988"})
    pagina = "<p>" + CF_COM_ADCT.replace("\n", "</p><p>") + "</p>"
    b = Biblioteca(reg, tmp_path, lambda url: pagina, hoje=lambda: date(2026, 11, 25))
    assert "Todos são iguais" in b.artigos("CF")["5"].texto
    guardado = json.loads((tmp_path / "CF.json").read_text(encoding="utf-8"))
    assert guardado["v"] == VERSAO
    assert "Todos são iguais" in Biblioteca(reg, tmp_path).em_cache("CF")["5"].texto


# ---------------------------------------------------------------- título do quadro

def test_titulo_longo_diminui_ou_quebra_e_cabe_na_largura():
    titulo = "Poder constituinte e emendas à Constituição · 1/7"
    fs, linhas = q._titulo(titulo, 760, 1.0)
    util = 760 - 2 * q.MARGEM
    assert all(q._medir_negrito(l, fs) <= util for l in linhas)
    assert " ".join(linhas) == titulo
    assert linhas[-1].endswith("Constituição · 1/7")          # o "· 1/7" não fica sozinho


def test_titulo_curto_fica_numa_linha_grande():
    fs, linhas = q._titulo("Habeas Corpus", 760, 1.0)
    assert linhas == ["Habeas Corpus"] and fs == q.TITULO_PT[0]


def test_quadro_com_titulo_de_duas_linhas_tem_altura_para_elas():
    item = q.Item("titulo", "Direitos e deveres individuais e coletivos: inviolabilidade de "
                            "domicílio e sigilo das comunicações · item 3")
    fs, linhas = q._titulo(item.conteudo, 760, 1.0)
    assert len(linhas) >= 2
    assert q._altura(item, 760, 1.0) > q._altura(q.Item("titulo", "Curto"), 760, 1.0)
    png = q.renderizar(f"# {item.conteudo}\n- Item curto")
    assert png[:8] == b"\x89PNG\r\n\x1a\n"


# ---------------------------------------------------------------- "no quadro" não é o PC

@pytest.mark.parametrize("fala,acao", [
    ("Coloca um cenário no quadro, por favor.", False),
    ("Consegue colocar um resumo no quadro do que é o habeas corpus?", False),
    ("Coloca no bloco de notas o resumo do quadro", True),
    ("Coloca uma música", True),
    ("Anota pra arrumar o quadro", True),
])
def test_pedido_no_quadro_nao_vai_para_o_bloco_de_notas(fala, acao):
    assert pede_acao(fala) is acao


def test_agente_nao_oferece_ferramentas_do_pc_para_o_quadro(tmp_path):
    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    ag = Agente(C(), memorias=Memorias(tmp_path / "S"), acoes_pc=["escrever_no_bloco_de_notas"])
    assert ag.quer_pc("Coloca um cenário no quadro, por favor.", []) is False
    assert ag.quer_pc("Escreve no bloco de notas o cenário", []) is True


# ---------------------------------------------------------------- a marca do registro

def test_marca_do_registro_nunca_vai_para_a_voz():
    texto = "Vou enviar ao Claude um resumo. [usou a ferramenta pedir_ao_claude]  \nPronto."
    assert "usou a ferramenta" not in _limpar(texto)


@pytest.mark.parametrize("frase,ruim", [
    ('Registre sempre o uso de ferramentas com "[usou a ferramenta X]" para evidenciar a ação.', True),
    ("Ao não reconhecer o nome do usuário, peça clarificação ao invés de ignorar a mensagem.", True),
    ("Implementar um módulo que detecta ausência de nome e gera prompt de confirmação.", True),
    ("Não faça perguntas de verificação se o aluno já pediu para avançar.", False),
    ("Quando ocorrer falha de voz, avise o usuário e ofereça a resposta por texto.", False),
])
def test_licao_tirada_do_registro_e_ruim(frase, ruim):
    assert licao_ruim(frase) is ruim


class CerebroJSON:
    def __init__(self, texto):
        self.texto = texto

    async def responder(self, mensagens):
        yield self.texto


@pytest.mark.asyncio
async def test_reflexao_nao_guarda_e_ainda_tira_lição_do_registro(tmp_path):
    log = tmp_path / "socrates.log"
    linhas = [f"2026-11-25 22:{m:02d}:00,000 INFO    socrates.orquestrador: aluno: 'pergunta {m}' | "
              f"Sócrates respondeu (10 caracteres): 'resposta {m}'" for m in range(5)]
    log.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    memorias = Memorias(tmp_path / "S")
    memorias.licoes.adicionar("Ao não reconhecer o nome do usuário, peça clarificação", origem="reflexao")
    resposta = json.dumps({"licoes": ['Registre sempre o uso de ferramentas com "[usou a ferramenta X]"',
                                      "Artigo de lei só com ler_lei, nunca de memória"],
                           "melhorias": ['Criar log com a tag "[usou a ferramenta X]" após execução']})
    r = Reflexao(CerebroJSON(resposta), memorias, log, hoje=lambda: date(2026, 11, 25))
    licoes, melhorias = await r.refletir()
    assert licoes == ["Artigo de lei só com ler_lei, nunca de memória"] and melhorias == []
    assert memorias.licoes.textos() == ["Artigo de lei só com ler_lei, nunca de memória."]


def test_anotar_licao_recusa_a_marca_do_registro(tmp_path):
    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    ag = Agente(C(), memorias=Memorias(tmp_path / "S"))
    assert "recusada" in ag.anotar_licao('Sempre escreva "[usou a ferramenta X]" na resposta')
    assert ag.memorias.licoes.textos() == []


# ---------------------------------------------------------------- "artigo 5º da CF"

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


@pytest.mark.parametrize("fala", ["me ensina o artigo 5º da CF", "me ensina direitos e deveres individuais",
                                  "questões de inviolabilidade de domicílio"])
def test_artigo_5_da_cf_vai_para_direitos_individuais(tutor, fala):
    p = tutor.entender(fala)
    assert p.trilha.id == "prf-constitucional" and p.topico.id == "direitos-individuais"


def test_artigo_definido_ainda_e_portugues(tutor):
    p = tutor.entender("me ensina artigo definido")
    assert p.trilha.id == "prf-portugues" and p.topico.id == "classes-palavras"


def test_estudar_sem_o_verbo_tenta_de_novo_com_me_ensina(tutor, tmp_path):
    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    ag = Agente(C(), tutor=tutor, memorias=Memorias(tmp_path / "S"))
    r = ag.estudar("estudo do artigo 5º da CF, focar nos incisos mais cobrados na PRF e Bombeiros")
    assert r.startswith("FEITO") and ag._turno.saida is not None


def test_pedido_que_o_tutor_nao_entende_manda_nao_repetir(tutor, tmp_path):
    class C:
        async def com_ferramentas(self, *a, **k):
            return ""
    ag = Agente(C(), tutor=tutor, memorias=Memorias(tmp_path / "S"))
    assert "NÃO repita" in ag.estudar("blá blá blá")


# ---------------------------------------------------------------- ferramenta repetida

@pytest.mark.asyncio
async def test_mesma_ferramenta_com_os_mesmos_argumentos_roda_uma_vez(tmp_path):
    feitos = []

    class C:
        async def com_ferramentas(self, msgs, esquemas, executar, **k):
            a = await executar("abrir_programa", {"nome": "spotify"})
            b = await executar("abrir_programa", {"nome": "spotify"})
            c = await executar("abrir_programa", {"nome": "calculadora"})
            return f"{a}|{b}|{c}"

    ag = Agente(C(), memorias=Memorias(tmp_path / "S"), acoes_pc=["abrir_programa"],
                executar_pc=lambda nome, args: feitos.append(args["nome"]) or "Abri.")
    r = await ag.atender("abre o spotify")
    assert feitos == ["spotify", "calculadora"]
    assert "Já feito nesta resposta" in r.texto.split("|")[1]


# ---------------------------------------------------------------- "FFFF!"

@pytest.mark.parametrize("fala,fica", [("FFFF!", ""), ("Aaaa", ""), ("sss sss", ""),
                                       ("Hmmm", "Hmmm"), ("PRF", "PRF"), ("Certo.", "Certo.")])
def test_uma_letra_repetida_e_ruido(fala, fica):
    assert filtrar_alucinacao(fala) == fica
