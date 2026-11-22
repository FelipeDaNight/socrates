"""As melhorias que o próprio Sócrates pediu ao Claude (22/11/2026), tiradas do registro dele.

  1. checar capacidades: nunca fingir uma ação que não fez
  2. falha de voz: avisar por escrito
  3. "próxima" / "siga": seguir direto, sem pergunta de confirmação
  4. blocos [QUADRO] íntegros (nada de "[quadro mostrado]" falado nem quadro perdido)
  5. "Cicco" e "Filipe" não eram apelidos: eram o microfone ouvindo "Explique, por favor"

As falas dos testes são as do registro de 14/11, em que ele inventou questões "da PRF 2021"
porque "Pode seguir para a próxima" não era entendido.
"""

import json
from datetime import date

import pytest

from socrates.core.memoria import Memorias
from socrates.core.quadro_fluxo import separar_quadro
from socrates.core.reflexao import Reflexao, eventos_do_log
from socrates.estudo import respostas
from socrates.estudo.treino import Item, Sessao
from socrates.stt.groq_whisper import curta_duvidosa
from socrates.visor import quadro as q

from test_agente import BibliotecaFalsa, CerebroRoteiro


def _itens(n=3):
    return [Item(id=f"t#{i}", tipo="ce", fala=f"Afirmação {i}. Certo ou errado?",
                 quadro=f"# Item {i}\nAfirmação {i}.\n\nCerto ou errado?", resp="C" if i % 2 else "E",
                 completo=f"Afirmação {i}.", materia="Português", topico="Regência", fonte="teste",
                 just=f"Justificativa {i}.")
            for i in range(1, n + 1)]


def _sessao(n=3):
    s = Sessao(_itens(n), "treino", "Teste")
    s.abrir()
    return s


# ---------------------------------------------------------------- 3. próxima / siga

@pytest.mark.parametrize("fala", ["Pode seguir para a próxima.", "Entendi, pode seguir para a próxima.",
                                  "Sim, pode passar.", "pode continuar", "siga", "bora pra próxima"])
def test_seguir_em_qualquer_lugar_da_frase(fala):
    assert respostas.comando(fala) == "pular"


@pytest.mark.parametrize("fala", ["não passa ainda, me explica", "explica por que não passa",
                                  "por que a próxima é errada?"])
def test_nao_e_seguir(fala):
    assert respostas.comando(fala) != "pular"


def test_depois_do_erro_pode_seguir_vai_para_a_proxima_de_verdade():
    s = _sessao()
    s.atender("certo")                       # item 1 é C: acertou e já foi para o 2
    saida = s.atender("certo")               # item 2 é E: errou, fica esperando
    assert s.estado == "corrigida" and "próxima para seguir" in saida.fala
    saida = s.atender("Pode seguir para a próxima.")
    assert saida.contexto is None and saida.fala.startswith("3 de 3.") and "Afirmação 3" in saida.fala


def test_resposta_e_seguir_juntos():
    s = _sessao()
    s.atender("certo")                       # 1: acertou
    saida = s.atender("Certo, passo para a próxima.")   # 2 (E): errou, mas pediu para seguir
    assert s.pos == 2 and "O gabarito é Errado" in saida.fala and "Afirmação 3" in saida.fala
    assert "próxima para seguir" not in saida.fala
    assert [r.ok for r in s.registros] == [True, False]


def test_explicacao_nao_termina_com_pergunta_nem_inventa_questao():
    s = _sessao()
    s.atender("certo")
    s.atender("certo")                       # errou o 2
    saida = s.atender("explica")
    assert "pergunte se ele quer seguir" not in saida.contexto
    assert "NUNCA invente outra questão" in saida.contexto and "é só dizer próxima" in saida.contexto


def test_aula_segue_com_pode_seguir_e_para_de_perguntar():
    from socrates.estudo.aula import Aula
    from socrates.estudo.caderno import Caderno
    from socrates.estudo.trilha import carregar_trilhas
    import tempfile, pathlib
    tr = next(t for t in carregar_trilhas() if t.id == "prf-transito")
    top = tr.topicos[0]
    cad = Caderno(pathlib.Path(tempfile.mkdtemp()) / "c.json")
    aula = Aula(tr, top, cad, [])
    aula.abrir()
    assert "UMA pergunta curta" in aula._ctx_explicar(False, False)
    saida = aula.atender("Entendi, pode seguir para o próximo.")       # pulou a pergunta
    assert aula.k == 1 and "Termine SEM pergunta" in saida.contexto
    saida = aula.atender("beleza")                                     # no ritmo direto, "beleza" segue
    assert aula.k == 2


# ---------------------------------------------------------------- questão anterior e quadro

def test_questao_anterior_e_a_de_verdade():
    s = _sessao()
    s.atender("errado")                      # 1 é C: errou
    s.atender("próxima")
    saida = s.atender("Me mostra a questão anterior a essa, por favor.")
    assert "O gabarito é Certo" in saida.fala and "Você respondeu Errado, e errou" in saida.fala
    assert "Afirmação 1" in saida.quadro and s.pos == 1


def test_mostra_a_questao_no_quadro():
    s = _sessao()
    saida = s.atender("Mostra a questão no quadro, por favor.")
    assert saida.quadro and "Afirmação 1" in saida.quadro and saida.contexto is None


def test_errado_certo_e_ambiguo_e_ele_pergunta():
    s = _sessao()
    saida = s.atender("Errado, certo.")
    assert s.registros == [] and "Qual vale" in saida.fala
    assert respostas.certo_ou_errado("Errado, não, certo!") == "C"


# ---------------------------------------------------------------- 5. "Filipe, por favor"

@pytest.mark.parametrize("fala", ["Filipe, por favor.", "Cicco, por favor.", "Felipe por favor"])
def test_nome_solto_e_o_microfone_ouvindo_explique(fala):
    assert respostas.comando(fala) == "explicar"


def test_ruido_curto_e_incerto_e_descartado():
    assert curta_duvidosa("Mie.", -1.03) and curta_duvidosa("Hum...", -1.07)
    assert not curta_duvidosa("Tchau.", -0.97) and not curta_duvidosa("Certo.", -0.38)
    assert not curta_duvidosa("Pode seguir para a próxima.", -1.0)


# ---------------------------------------------------------------- 4. quadro íntegro

async def _separar(texto, pedacos=1):
    quadros = []
    tam = max(1, len(texto) // pedacos)

    async def fonte():
        for i in range(0, len(texto), tam):
            yield texto[i:i + tam]

    fala = "".join([p async for p in separar_quadro(fonte(), quadros.append)])
    return fala, quadros


@pytest.mark.asyncio
@pytest.mark.parametrize("pedacos", [1, 7, 40])
async def test_quadro_mostrado_imitado_vira_quadro_de_verdade(pedacos):
    """A resposta do registro de 14/11: o modelo escreveu "[quadro mostrado]" e o quadro sumiu."""
    texto = ("[quadro mostrado]  \nVerbo “assistir” no sentido de “ver”  \n– É transitivo direto  \n"
             "– Não pede preposição antes do complemento  \n\nCerto ou errado?")
    fala, quadros = await _separar(texto, pedacos)
    assert quadros and "É transitivo direto" in quadros[0] and "Certo ou errado" not in quadros[0]
    assert "quadro mostrado" not in fala.lower() and fala.strip() == "Certo ou errado?"


@pytest.mark.asyncio
@pytest.mark.parametrize("texto", ["Veja. **[QUADRO]**\n# Crase\n- a + a\n**[/QUADRO]** Entendeu?",
                                   "Veja. [quadro]\n# Crase\n- a + a\n[/quadro] Entendeu?",
                                   "Veja. [ QUADRO ]\n# Crase\n- a + a\n[ /QUADRO ] Entendeu?"])
async def test_marcas_tortas_valem(texto):
    fala, quadros = await _separar(texto, 5)
    assert quadros == ["# Crase\n- a + a"] and "Veja." in fala and "Entendeu?" in fala
    assert "[" not in fala and "*" not in fala


@pytest.mark.asyncio
async def test_quadro_cortado_fecha_sozinho():
    fala, quadros = await _separar("Olha. [QUADRO]\n# Regência\n- assistir (ver): VTI\n- obedecer: VTI", 3)
    assert quadros == ["# Regência\n- assistir (ver): VTI\n- obedecer: VTI"] and fala.strip() == "Olha."


@pytest.mark.asyncio
async def test_colchete_comum_nao_trava():
    fala, quadros = await _separar("O intervalo [0, 1] é fechado. [QUADRO]\n$$ [a, b] $$\n[/QUADRO] Ok?", 4)
    assert "[0, 1]" in fala and quadros == ["$$ [a, b] $$"]


def test_historico_nao_ensina_a_marca_falsa():
    from socrates.core.orquestrador import compactar
    hist = [{"role": "assistant", "content": "Veja. [QUADRO]\n# Crase\n- a + a = à\n- fim\n[/QUADRO]"},
            {"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    c = compactar(hist)[0]["content"]
    assert "quadro mostrado" not in c and c.count("[QUADRO]") == 1 and "[/QUADRO]" in c


def test_item_longo_nao_passa_por_cima_do_seguinte():
    """A foto do plano de hoje: "e nominal)" por cima de "Legislação de Trânsito"."""
    item = q.Item("item", "Língua Portuguesa: Reforçar Regência verbal e nominal: você está "
                          "acertando 50 por cento. (diga: me ensina regência verbal e nominal)")
    desenho = q._quebrar(item.conteudo, q._max_chars(item, 760, 1.0))
    altura = q._altura(item, 760, 1.0)
    assert altura >= len(desenho) * 19 * 1.55


# ---------------------------------------------------------------- 1. não fingir ação

@pytest.fixture
def agente(tmp_path):
    from socrates.core.agente import Agente

    def novo(cerebro):
        return Agente(cerebro, memorias=Memorias(tmp_path / "S"), biblioteca=BibliotecaFalsa(),
                      acoes_pc=["abrir_programa"], executar_pc=lambda n, a: "Abri spotify.")
    return novo


class CerebroQueFinge(CerebroRoteiro):
    """Primeiro diz que mandou a mensagem sem usar ferramenta; corrigido, admite."""

    def __init__(self, segunda):
        super().__init__([])
        self.vezes = 0
        self.segunda = segunda

    async def com_ferramentas(self, mensagens, esquemas, executar, max_rodadas=4, parar=None):
        self.vezes += 1
        self.mensagens = mensagens
        if self.vezes == 1:
            return "Pronto, mandei a mensagem no WhatsApp para a sua mãe."
        return self.segunda


@pytest.mark.asyncio
async def test_acao_fingida_e_corrigida(agente):
    c = CerebroQueFinge("Não consigo mandar mensagem no WhatsApp: não tenho essa ferramenta.")
    r = await agente(c).atender("manda um zap pra minha mãe")
    assert r.texto.startswith("Não consigo") and c.vezes == 2
    assert "NÃO aconteceu" in c.mensagens[-1]["content"]


@pytest.mark.asyncio
async def test_acao_fingida_duas_vezes_vira_resposta_honesta(agente):
    c = CerebroQueFinge("Pronto, enviei.")
    r = await agente(c).atender("manda um zap pra minha mãe")
    assert r.texto.startswith("Não consegui fazer isso daqui")


@pytest.mark.asyncio
async def test_acao_de_verdade_e_quadro_nao_sao_fingimento(agente):
    c = CerebroRoteiro([("abrir_programa", {"nome": "spotify"})], "Pronto, abri o Spotify.")
    r = await agente(c).atender("abre o spotify")
    assert r.texto == "Pronto, abri o Spotify."
    c = CerebroRoteiro([], "Coloquei no quadro. [QUADRO]\n# Crase\n[/QUADRO]")
    r = await agente(c).atender("põe a regra da crase no quadro")
    assert r.texto.startswith("Coloquei no quadro")


def test_o_prompt_diz_o_que_ele_nao_consegue(agente):
    s = agente(CerebroRoteiro([])).sistema()
    assert "NÃO consegue" in s and "WhatsApp" in s and "Filipe, por favor" in s
    assert "NUNCA invente questão" in s and "[quadro mostrado]" in s


# ---------------------------------------------------------------- reflexão mais esperta

LOG = """2026-11-14 18:25:00,000 INFO    socrates.ferramentas: ferramenta abrir_programa({'nome': 'spotify'})
2026-11-14 18:25:01,000 INFO    socrates.orquestrador: aluno: 'Abra o Spotify.' | Sócrates respondeu (22 caracteres): 'Pronto, abri o Spotify.'
2026-11-14 18:38:28,191 INFO    socrates.orquestrador: aluno: 'Cicco, por favor.' | Sócrates respondeu (20 caracteres): 'Certo. Um verbo ...'
2026-11-14 18:39:00,318 INFO    socrates.orquestrador: aluno: 'Entendi, pode seguir.' | Sócrates respondeu (20 caracteres): 'Próxima afirmação.'
2026-11-14 18:42:47,504 INFO    socrates.orquestrador: aluno: 'Filipe, por favor.' | Sócrates respondeu (20 caracteres): 'O verbo preferir.'
"""


def test_reflexao_ve_a_ferramenta_usada():
    eventos, _ = eventos_do_log(LOG.splitlines())
    assert eventos[0] == "18:25 [usou a ferramenta abrir_programa]"


class CerebroJSON:
    def __init__(self, dados):
        self.texto = json.dumps(dados)
        self.pedido = ""

    async def responder(self, mensagens):
        self.pedido = mensagens[-1]["content"]
        yield self.texto


@pytest.mark.asyncio
async def test_reflexao_tira_licao_errada(tmp_path):
    log = tmp_path / "socrates.log"
    log.write_text(LOG, encoding="utf-8")
    m = Memorias(tmp_path / "S")
    m.licoes.adicionar("Ao receber pedidos de controle de aplicativos (ex.: abrir Spotify), informe "
                       "a limitação em vez de fingir que a ação foi executada")
    m.licoes.adicionar("Não faça perguntas de verificação se o aluno já pediu para avançar")
    c = CerebroJSON({"licoes": [], "melhorias": [], "remover": [1]})
    await Reflexao(c, m, log, hoje=lambda: date(2026, 11, 23)).refletir()
    assert "abrir e fechar programas" in c.pedido and "erro de transcrição" in c.pedido
    assert "1. Ao receber pedidos" in c.pedido
    assert m.licoes.textos() == ["Não faça perguntas de verificação se o aluno já pediu para avançar."]


@pytest.mark.asyncio
async def test_no_treino_por_no_quadro_e_do_tutor_nao_do_agente(tmp_path):
    """No registro, "Coloque a questão no quadro" foi ao agente, que pôs uma questão inventada."""
    from test_agente_conversa import _montar
    from test_maos_livres import _rodar
    import random, shutil
    from pathlib import Path
    from socrates.estudo import Caderno, Tutor
    from socrates.estudo import material as mat
    from socrates.estudo.plano import carregar_planos

    pasta = tmp_path / "material"
    (pasta / "bancos").mkdir(parents=True)
    shutil.copy(Path(__file__).parent / "dados/leiseca-agente.json", pasta / "bancos/leiseca.json")
    (pasta / "bancos/lei-index.json").write_text(json.dumps(["bancos/leiseca.json"]))
    (pasta / "bancos/index.json").write_text("[]")
    m = mat.carregar(pasta, tmp_path / "privado", baixar_se_faltar=False)
    tutor = Tutor(m, Caderno(tmp_path / "caderno.json"), sortear=random.Random(0),
                  planos=carregar_planos(ids=["prf", "cbmgo"]))
    roteiro = CerebroRoteiro([("abrir_programa", {"nome": "x"})], "não devia")
    conversa, s, *_ = _montar(tutor, roteiro, tmp_path)
    tutor.atender("lacunas do CTB")
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, coloque a questão no quadro, por favor.")])
    assert roteiro.mensagens is None and s.voz.faladas[0] == "Está no quadro."
