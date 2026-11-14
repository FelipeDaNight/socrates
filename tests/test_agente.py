"""O cérebro que decide: ferramentas de estudo, lei oficial, memória e lições.

Os casos vêm da gravação de 13/11/2026, em que o Sócrates:
  - pôs o art. 7 do CTB só no quadro quando o pedido era "bloco de notas + artigo 7";
  - inventou os "primeiros artigos do Código Penal" (concurso de pessoas é o art. 29);
  - foi estudar "Poder constituinte" quando o pedido era Vidas Secas ("você PODE...").
"""

import asyncio
import json
import random
import shutil
from pathlib import Path

import pytest

from socrates.core.agente import (Agente, LeitorDeLei, faixas_de_artigos, quadro_de_trechos,
                                  sigla_da_lei)
from socrates.core.memoria import Memorias, parecido
from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.leitor_lei import Artigo
from socrates.estudo.plano import achar_topico, carregar_planos
from socrates.llm import ErroCerebro

DADOS = Path(__file__).parent / "dados"


# ---------------------------------------------------------------- lei: nomes e artigos

@pytest.mark.parametrize("fala,sigla", [
    ("CTB", "CTB"), ("Código de Trânsito", "CTB"), ("código penal", "CP"), ("CP", "CP"),
    ("Código de Processo Penal", "CPP"), ("Constituição", "CF"), ("CF/88", "CF"),
    ("Lei de Drogas", "L11343"), ("lei 11.343", "L11343"), ("Lei nº 8.112/1990", "L8112"),
    ("L14133", "L14133"), ("Maria da Penha", "L11340"), ("lei 9.503", "CTB"),
    ("Estatuto do Desarmamento", "L10826"), ("decreto 1.171", "D1171"),
])
def test_sigla_da_lei(fala, sigla):
    registro = json.loads((Path(__file__).parents[1] / "socrates/estudo/planos/leis.json")
                          .read_text(encoding="utf-8"))
    assert sigla_da_lei(fala, registro) == sigla


def test_sigla_desconhecida():
    assert sigla_da_lei("lei do inquilinato", {}) is None


@pytest.mark.parametrize("texto,faixas", [
    ("7", [((7, ""), (7, ""))]),
    ("7º", [((7, ""), (7, ""))]),
    ("artigo 7", [((7, ""), (7, ""))]),
    ("121-A", [((121, "A"), (121, "A"))]),
    ("1-10", [((1, ""), (10, "Z"))]),
    ("1 a 10", [((1, ""), (10, "Z"))]),
    ("do 1 ao 5", [((1, ""), (5, "Z"))]),
    ("5, 7 e 121-A", [((5, ""), (5, "")), ((7, ""), (7, "")), ((121, "A"), (121, "A"))]),
    ("primeiros", [((1, ""), (5, "Z"))]),
    ("primeiros 10", [((1, ""), (10, "Z"))]),
    ("3-A a 3-F", [((3, "A"), (3, "F"))]),
])
def test_faixas_de_artigos(texto, faixas):
    assert faixas_de_artigos(texto) == faixas


# ---------------------------------------------------------------- material de teste

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


class BibliotecaFalsa:
    """A lei inteira "do Planalto", sem internet."""
    registro = {"CF": {"nome": "Constituição Federal"}, "CP": {"nome": "Código Penal"}}

    def __init__(self):
        self.pedidas = []

    def nome(self, sigla):
        return self.registro.get(sigla, {}).get("nome", sigla)

    def artigos(self, sigla):
        self.pedidas.append(sigla)
        if sigla == "CF":
            return {"144": Artigo(144, "", "Art. 144. A segurança pública, dever do Estado, direito "
                                             "e responsabilidade de todos, é exercida para a preservação "
                                             "da ordem pública...\nII - polícia rodoviária federal;")}
        if sigla == "CP":
            return {"29": Artigo(29, "", "Art. 29 - Quem, de qualquer modo, concorre para o crime "
                                           "incide nas penas a este cominadas, na medida de sua "
                                           "culpabilidade.")}
        raise OSError("sem internet")


def test_leitor_usa_a_lei_seca_e_depois_o_planalto(tutor):
    bib = BibliotecaFalsa()
    leitor = LeitorDeLei(tutor.leis, bib)
    trechos, aviso = leitor.ler("CP", faixas_de_artigos("primeiros"))
    assert [t.rotulo for t in trechos] == ["Art. 1º", "Art. 2º", "Art. 3º", "Art. 4º", "Art. 5º"]
    assert "Não há crime sem lei anterior" in trechos[0].texto and not aviso
    assert "Ninguém pode ser punido" in trechos[1].texto
    assert bib.pedidas == []                       # tudo na lei seca: nada de internet
    trechos, _ = leitor.ler("CP", faixas_de_artigos("29"))
    assert "concorre para o crime" in trechos[0].texto and bib.pedidas == ["CP"]
    trechos, _ = leitor.ler("CF", faixas_de_artigos("144"))
    assert "polícia rodoviária federal" in trechos[0].texto
    trechos, aviso = leitor.ler("L9605", faixas_de_artigos("1"))
    assert trechos == [] and "art. 1" in aviso


def test_lei_guardada_do_planalto_vale_mais_que_a_lei_seca(tutor):
    """A lei seca do app tem anotações de estudo no meio ("(circunstâncias)"); a cópia do
    Planalto já guardada no PC é o texto puro, e sai na hora."""
    class ComCache(BibliotecaFalsa):
        def em_cache(self, sigla):
            if sigla != "CP":
                return None
            return {"3": Artigo(3, "", "Art. 3º - A lei excepcional ou temporária, embora decorrido o "
                                       "período de sua duração ou cessadas as circunstâncias que a "
                                       "determinaram, aplica-se ao fato praticado durante sua vigência. "
                                       "(Redação dada pela Lei nº 7.209, de 1984)",
                                [("Lei 7.209", 1984)])}

    leitor = LeitorDeLei(tutor.leis, ComCache())
    trechos, aviso = leitor.ler("CP", faixas_de_artigos("3"))
    assert "(circunstâncias)" not in trechos[0].texto and "Redação dada" not in trechos[0].texto
    assert not aviso and trechos[0].mudancas == ["Lei 7.209 (1984)"]
    q = quadro_de_trechos("Código Penal", trechos, tutor.leis)
    assert q.startswith("# Código Penal · Art. 3") and "(circunstâncias)" not in q
    trechos, _ = leitor.ler("CP", faixas_de_artigos("1"))      # não está na cópia: lei seca
    assert "Não há crime sem lei anterior" in trechos[0].texto


def test_quadro_de_varios_artigos_tem_o_texto_real(tutor):
    leitor = LeitorDeLei(tutor.leis, BibliotecaFalsa())
    trechos, _ = leitor.ler("CP", faixas_de_artigos("1-5"))
    q = quadro_de_trechos("Código Penal", trechos, tutor.leis)
    assert q.startswith("# Código Penal · arts. 1º a 5º")
    assert "Não há crime sem lei anterior" in q and "Concurso de pessoas" not in q
    assert len(q) < 1500


# ---------------------------------------------------------------- cérebro falso que usa ferramentas

class CerebroRoteiro:
    """Faz as chamadas de ferramenta do roteiro e devolve o texto final."""
    nome = "roteiro"

    def __init__(self, chamadas, final="Pronto.", falhar=False):
        self.chamadas = chamadas
        self.final = final
        self.falhar = falhar
        self.mensagens = None
        self.esquemas = None
        self.resultados = []

    async def com_ferramentas(self, mensagens, esquemas, executar, max_rodadas=4, parar=None):
        if self.falhar:
            raise ErroCerebro("Sem conexão com a internet (ou o serviço caiu).")
        self.mensagens, self.esquemas = mensagens, esquemas
        for nome, args in self.chamadas:
            self.resultados.append(await executar(nome, args))
            if parar is not None and parar():
                return ""
        return self.final

    async def responder(self, mensagens):
        yield self.final


@pytest.fixture
def memorias(tmp_path):
    return Memorias(tmp_path / "Socrates")


def _agente(cerebro, tutor, memorias, pc=None):
    feitos = []

    def executar_pc(nome, args):
        feitos.append((nome, args))
        return "Escrevi no Bloco de Notas." if nome == "escrever_no_bloco_de_notas" else "ok"

    ag = Agente(cerebro, tutor=tutor, memorias=memorias, biblioteca=BibliotecaFalsa(),
                acoes_pc=pc or ["escrever_no_bloco_de_notas", "abrir_programa", "ver_tela"],
                executar_pc=executar_pc)
    return ag, feitos


@pytest.mark.asyncio
async def test_bloco_de_notas_com_o_artigo_7_do_ctb(tutor, memorias):
    """A fala da gravação: antes virava só 'mostrar o artigo'."""
    c = CerebroRoteiro([("ler_lei", {"lei": "CTB", "artigos": "7", "destino": "bloco_de_notas"})],
                       "Pronto, escrevi o artigo 7 do CTB no Bloco de Notas.")
    ag, feitos = _agente(c, tutor, memorias)
    r = await ag.atender("O bloco de notas e coloca o artigo 7 do CTB, por favor.")
    assert feitos and feitos[0][0] == "escrever_no_bloco_de_notas"
    texto = feitos[0][1]["texto"]
    assert "Compõem o Sistema Nacional de Trânsito" in texto and "V - a Polícia Rodoviária Federal" in texto
    assert r.quadro is None and r.texto.startswith("Pronto")
    assert "Compõem o Sistema Nacional" in c.resultados[0]          # o cérebro viu o texto oficial


@pytest.mark.asyncio
async def test_primeiros_artigos_do_codigo_penal_vem_da_lei(tutor, memorias):
    c = CerebroRoteiro([("ler_lei", {"lei": "Código Penal", "artigos": "primeiros"})],
                       "Estão no quadro: o 1º é a legalidade e o 2º trata da lei penal no tempo.")
    ag, _ = _agente(c, tutor, memorias)
    r = await ag.atender("E os primeiros artigos do Código Penal.")
    assert r.quadro and "Não há crime sem lei anterior" in r.quadro
    assert "Ninguém pode ser punido por fato que lei posterior" in r.quadro
    assert "concurso de pessoas" not in r.quadro.lower()
    assert "Texto oficial em vigor" in c.resultados[0]


@pytest.mark.asyncio
async def test_lei_que_nao_tem_avisa_para_nao_inventar(tutor, memorias):
    c = CerebroRoteiro([("ler_lei", {"lei": "Lei de Crimes Ambientais", "artigos": "1"})])
    ag, _ = _agente(c, tutor, memorias)
    await ag.atender("lê o artigo 1 da lei de crimes ambientais")
    assert "não cite o texto de memória" in c.resultados[0]


@pytest.mark.asyncio
async def test_estudar_passa_ao_tutor_e_para_o_laco(tutor, memorias):
    c = CerebroRoteiro([("estudar", {"pedido": "lacunas do CTB"}),
                        ("abrir_programa", {"nome": "spotify"})])
    ag, feitos = _agente(c, tutor, memorias)
    r = await ag.atender("bora treinar a lei seca de trânsito")
    assert r.saida is not None and r.texto == ""
    assert feitos == []                                   # parou depois que o tutor assumiu
    assert tutor.em_treino


@pytest.mark.asyncio
async def test_estudar_nao_reconhecido_volta_ao_cerebro(tutor, memorias):
    c = CerebroRoteiro([("estudar", {"pedido": "faz um poema"})], "Aqui vai um poema.")
    ag, _ = _agente(c, tutor, memorias)
    r = await ag.atender("faz um poema sobre o CTB")
    assert r.saida is None and "não reconheceu" in c.resultados[0] and r.texto


@pytest.mark.asyncio
async def test_memoria_e_licao_ficam_para_sempre(tutor, memorias):
    c = CerebroRoteiro([("lembrar", {"fato": "A prova da PRF dele é em março de 2027"}),
                        ("anotar_licao", {"licao": "Quando ele pedir artigos, ler o texto oficial"}),
                        ("sugerir_melhoria", {"ideia": "Ler a lei em voz alta mais devagar"})],
                       "Anotado.")
    ag, _ = _agente(c, tutor, memorias)
    await ag.atender("minha prova é em março de 2027; e para de inventar artigo")
    assert memorias.aluno.textos() == ["A prova da PRF dele é em março de 2027."]
    assert len(memorias.licoes.textos()) == 1 and len(memorias.melhorias_pendentes()) == 1
    sistema = ag.sistema()
    assert "março de 2027" in sistema and "ler o texto oficial" in sistema
    assert "Ler a lei em voz alta mais devagar" in sistema
    c2 = CerebroRoteiro([("esquecer", {"assunto": "prova da PRF"})])
    ag2, _ = _agente(c2, tutor, memorias)
    await ag2.atender("esquece a data da prova")
    assert memorias.aluno.textos() == []


@pytest.mark.asyncio
async def test_aprender_vidas_secas_nao_vira_poder_constituinte(tutor, memorias):
    class Auto:
        def __init__(self):
            self.pedidos = []

        def pedir_assunto(self, assunto):
            self.pedidos.append(assunto)
            return f"Certo, vou estudar {assunto}.", None

    tutor.autoestudo = Auto()
    c = CerebroRoteiro([("aprender_assunto", {"assunto": "Vidas Secas, de Graciliano Ramos"})])
    ag, _ = _agente(c, tutor, memorias)
    await ag.atender("Você pode me resumir o primeiro capítulo do livro Vidas Secas, se você não "
                     "tiver nos seus dados, aprenda por favor.")
    assert tutor.autoestudo.pedidos == ["Vidas Secas, de Graciliano Ramos"]


def test_achar_topico_nao_confunde_pode_com_poder():
    planos = carregar_planos(ids=["prf", "cbmgo"])
    fala = ("Você pode me resumir o primeiro capítulo do livro Vidas Secas, se você não tiver nos "
            "seus dados, aprenda por favor.")
    t = achar_topico(planos, fala)
    assert t is None or "poder" not in t.titulo.lower()
    t = achar_topico(planos, "aprende sobre crimes ambientais")
    assert t is not None and "ambient" in t.titulo.lower()


@pytest.mark.asyncio
async def test_pc_e_notas_vao_juntos_e_falha_vira_excecao(tutor, memorias):
    from socrates import ferramentas
    ferramentas.nomes_das_acoes()                       # registra as ações do PC
    c = CerebroRoteiro([("abrir_programa", {"nome": "spotify"})], "Abri o Spotify.")
    ag, feitos = _agente(c, tutor, memorias)
    r = await ag.atender("abre o spotify")
    assert feitos == [("abrir_programa", {"nome": "spotify"})] and r.ferramentas == ["abrir_programa"]
    nomes = {e["function"]["name"] for e in c.esquemas}
    assert {"ler_lei", "estudar", "lembrar", "pesquisar_internet", "abrir_programa"} <= nomes
    with pytest.raises(ErroCerebro):
        await _agente(CerebroRoteiro([], falhar=True), tutor, memorias)[0].atender("oi")


@pytest.mark.asyncio
async def test_notas_do_material_vao_junto_com_a_pergunta(tutor, memorias):
    c = CerebroRoteiro([], "O art. 7 lista os órgãos do SNT.")
    ag, _ = _agente(c, tutor, memorias)
    await ag.atender("o que diz o artigo 7 do CTB?")
    sistemas = [m["content"] for m in c.mensagens if m["role"] == "system"]
    assert any("Compõem o Sistema Nacional de Trânsito" in s for s in sistemas[1:])
    assert c.mensagens[-1] == {"role": "user", "content": "o que diz o artigo 7 do CTB?"}


@pytest.mark.asyncio
async def test_historico_com_avisos_seguidos_vira_uma_mensagem(tutor, memorias):
    c = CerebroRoteiro([], "Vou continuar.")
    ag, _ = _agente(c, tutor, memorias)
    historico = [{"role": "assistant", "content": "Olá! Sugestão para hoje: revisar."},
                 {"role": "assistant", "content": "Aprendi CTB: habilitação."},
                 {"role": "user", "content": "me ensina habilitação"},
                 {"role": "assistant", "content": "Certo, vou estudar."}]
    await ag.atender("Vai, por favor.", historico)
    papeis = [m["role"] for m in c.mensagens if m["role"] != "system"]
    assert papeis == ["user", "assistant", "user", "assistant", "user"]
    assert "Sugestão para hoje" in c.mensagens[2]["content"] and "Aprendi" in c.mensagens[2]["content"]


@pytest.mark.asyncio
async def test_situacao_do_treino_vai_no_prompt(tutor, memorias):
    tutor.atender("lacunas do CTB")
    ag, _ = _agente(CerebroRoteiro([]), tutor, memorias)
    assert "Treino em andamento" in ag.sistema()


# ---------------------------------------------------------------- memória

def test_parecido_e_lista_sem_repetidos(memorias):
    assert parecido("A prova é em março", "a prova é em março.")
    assert not parecido("A prova é em março", "Ele erra crase")
    assert memorias.aluno.adicionar("Ele erra muito crase")
    assert not memorias.aluno.adicionar("ele erra muito crase.")
    assert memorias.aluno.adicionar("Prefere respostas curtas")
    assert memorias.aluno.remover("crase") == ["Ele erra muito crase."]
    assert memorias.aluno.textos() == ["Prefere respostas curtas."]


class CerebroQueBateNoLimite(CerebroRoteiro):
    """Age e, no meio, bate no limite: devolve o resultado cru da ferramenta (como o
    compativel_openai faz) — o agente pede só a resposta final a outro cérebro."""

    async def com_ferramentas(self, mensagens, esquemas, executar, max_rodadas=4, parar=None):
        self.mensagens = mensagens
        for nome, args in self.chamadas:
            self.resultados.append(await executar(nome, args))
        return self.resultados[-1]

    async def responder(self, mensagens):
        self.final_pedido = mensagens
        yield "Está no quadro: o artigo 7 lista os órgãos do Sistema Nacional de Trânsito."


@pytest.mark.asyncio
async def test_limite_no_meio_nao_fala_o_resultado_cru(tutor, memorias):
    c = CerebroQueBateNoLimite([("ler_lei", {"lei": "CTB", "artigos": "7"})])
    ag, _ = _agente(c, tutor, memorias)
    r = await ag.atender("lê o artigo 7 do CTB")
    assert r.texto.startswith("Está no quadro") and r.quadro
    ultimo = c.final_pedido[-1]
    assert ultimo["role"] == "user" and "Compõem o Sistema" in ultimo["content"]


@pytest.mark.asyncio
async def test_ferramentas_do_pc_so_quando_a_fala_pede(tutor, memorias):
    from socrates import ferramentas
    from socrates.llm.compativel_openai import ESPERA_LIMITE, ESPERA_MAX_SEG
    nomes = ferramentas.nomes_das_acoes()
    c = CerebroRoteiro([], "O furto é subtrair coisa alheia móvel.")
    ag = Agente(c, tutor=tutor, memorias=memorias, biblioteca=BibliotecaFalsa(), acoes_pc=nomes)
    await ag.atender("qual a pena do furto?")
    assert "abrir_programa" not in {e["function"]["name"] for e in c.esquemas}   # ~2 mil tokens a menos
    await ag.atender("O bloco de notas e coloca o artigo 7 do CTB, por favor.")
    assert "escrever_no_bloco_de_notas" in {e["function"]["name"] for e in c.esquemas}
    assert ag.quer_pc("e agora fecha", [{"role": "user", "content": "abre o spotify"}])
    assert ESPERA_LIMITE.get() == ESPERA_MAX_SEG          # a pressa do agente não vaza
