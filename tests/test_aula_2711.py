"""A aula de Direito Penal de 27/11 (registro das 23h09 às 23h27).

  23h15 "Eu não entendi muito o enunciado... se for fazer perguntas assim, eu recomendo colocar
        no quadro toda vez que você for fazer."
  23h15 "...você tem que ser mais claro no quadro, colocar o enunciado inteiro do que você está
        falando."
  23h17 "anota melhorar a formatação do quadro nas próximas atualizações do Claude e também focar
        em colocar o que está sendo falado de verdade no quadro" -> foi para a aula (sem
        ferramentas) e ele só prometeu
  23h22 "Se atualiza, por favor" -> o cérebro anotou uma lição em vez de atualizar
  23h25 o Spotify tocando: "...é uma luta, uma luta, uma luta [9 vezes]..." -> ele respondeu
"""

import pytest

from socrates import ferramentas
from socrates.estudo.aula import complemento_do_quadro, juntar_ao_quadro
from socrates.stt.groq_whisper import sem_repeticoes

from test_agente_conversa import _montar, tutor  # noqa: F401  (fixture)
from test_maos_livres import _montar as _montar_simples, _rodar
from test_registro_2611 import CerebroSessao

# a explicação das 23h12, como o cérebro falou
LEGALIDADE = ("Hoje vamos dominar os princípios do Direito Penal para a PRF, com oito pontos e itens "
              "de fixação no final. Comecemos pela legalidade, que é a base de tudo. Só uma lei federal "
              "em sentido estrito pode criar crime ou pena. Medida provisória não pode tratar de direito "
              "penal, então fique atento a essa pegadinha. Imagine um policial rodoviário: ele só pode "
              "autuar ou prender se a lei já existir antes do fato. Se não houver lei anterior, não há "
              "crime nem pena. Você consegue me dizer por que a medida provisória não serve para criar "
              "um novo crime?")


# ---------------------------------------------------------------- a pergunta vai para o quadro

def test_pergunta_e_exemplo_da_explicacao_vao_para_o_quadro():
    extra = complemento_do_quadro(LEGALIDADE)
    assert extra == ("# Exemplo\nImagine um policial rodoviário: ele só pode autuar ou prender se a lei "
                     "já existir antes do fato.\n# Pergunta\nVocê consegue me dizer por que a medida "
                     "provisória não serve para criar um novo crime?")


def test_pergunta_de_checagem_nao_vai_para_o_quadro():
    # 23h12m59: o resto da fala já está no quadro; "posso seguir?" não é enunciado
    assert complemento_do_quadro("Exatamente, você acertou. O princípio da legalidade, no art. 1º do "
                                 "Código Penal, exige lei anterior. Posso seguir para o próximo ponto, "
                                 "que trata da taxatividade e da clareza da lei?") == ""
    assert complemento_do_quadro("Entendeu a ideia? Ficou mais claro?") == ""


def test_pergunta_curta_leva_o_caso_junto():
    extra = complemento_do_quadro("Um motorista foge da blitz e atropela o agente. O que o PRF deve fazer?")
    assert extra == "# Pergunta\nUm motorista foge da blitz e atropela o agente. O que o PRF deve fazer?"
    # "art. 5º" não corta a frase no meio
    extra = complemento_do_quadro("A regra está no art. 5º, XXXIX, da Constituição. Por que isso protege "
                                  "o cidadão numa abordagem?")
    assert "# Pergunta\nA regra está no art. 5º, XXXIX, da Constituição. Por que isso" in extra


def test_complemento_novo_troca_o_anterior_e_o_ponto_fica():
    ponto = "# Princípios do Direito Penal · 1/8\nLegalidade: não há crime sem lei anterior que o defina."
    um = juntar_ao_quadro(ponto, "# Pergunta\nPor que a MP não cria crime?")
    dois = juntar_ao_quadro(um, "# Pergunta\nE a lei delegada, pode?")
    assert dois == ponto + "\n\n# Pergunta\nE a lei delegada, pode?"
    assert complemento_do_quadro("Imagine que custou R$ 293,47 na blitz.").endswith(r"custou R\$ 293,47 na blitz.")


@pytest.mark.asyncio
async def test_na_aula_o_quadro_ganha_a_pergunta_falada(tutor, tmp_path):  # noqa: F811
    roteiro = CerebroSessao([([("estudar", {"pedido": "me ensina princípios do direito penal"})], "")])
    conversa, s, soc, cerebro_conversa, _, _ = _montar(tutor, roteiro, tmp_path, LEGALIDADE)
    await _rodar(conversa, [s.ouvido.fala("Sócrates, vamos para direito penal, me ensina os princípios.")])
    assert [p[-1]["content"] for p in roteiro.pedidos] == ["vamos para direito penal, me ensina os princípios."]
    quadro = conversa._ultimo_quadro
    assert quadro.startswith("# ") and "· 1/" in quadro.splitlines()[0]          # o ponto continua
    assert quadro.endswith("# Pergunta\nVocê consegue me dizer por que a medida provisória não "
                           "serve para criar um novo crime?")
    assert "# Exemplo\nImagine um policial rodoviário" in quadro
    pedido_da_aula = " ".join(m["content"] for m in cerebro_conversa.recebido[0])
    assert "comece com 'Imagine'" in pedido_da_aula and "NÃO escreva [QUADRO]" in pedido_da_aula


# ---------------------------------------------------------------- pedido ao Claude no meio da aula

@pytest.mark.asyncio
async def test_pedido_ao_claude_no_meio_da_aula_vai_ao_agente(tutor, tmp_path):  # noqa: F811
    roteiro = CerebroSessao([([], "Deixei na caixa do Claude.")])
    conversa, s, soc, cerebro_conversa, _, _ = _montar(tutor, roteiro, tmp_path, LEGALIDADE)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, me ensina os princípios do direito penal."),   # o tutor, direto
                            o.fala("Tá, anota melhorar a formatação do quadro nas próximas atualizações "
                                   "do Cloud, por favor.")])
    assert len(roteiro.pedidos) == 1                           # antes: foi para a aula, sem ferramentas
    assert "atualizações do Claude" in roteiro.pedidos[0][-1]["content"]
    assert "Deixei na caixa do Claude." in s.voz.faladas


# ---------------------------------------------------------------- "se atualiza" sem depender do cérebro

@pytest.fixture
def atualizar_falso(monkeypatch):
    feitos = []
    monkeypatch.setitem(ferramentas.REGISTRO["atualizar_socrates"].__dict__, "funcao",
                        lambda: feitos.append("atualizou") or "Atualizei (x). Vou reiniciar agora.")
    yield feitos
    ferramentas.PENDENTE = None


@pytest.mark.parametrize("fala,sim", [
    ("Se atualiza, por favor Sócrates Dizem.", True), ("Se atualiza. Se atualiza.", True),
    ("Tá, se atualiza aí", True), ("Atualiza o Sócrates", True), ("baixa a versão nova", True),
    ("A tabela do CONTRAN se atualiza quando?", False), ("atualiza o quadro", False),
    ("Você pode se atualizar?", False),          # essa o cérebro decide
])
def test_o_que_e_pedido_de_atualizacao(fala, sim):
    from socrates.maos_livres import pede_atualizacao
    assert pede_atualizacao(fala) is sim


@pytest.mark.asyncio
async def test_se_atualiza_pergunta_e_por_favor_confirma(atualizar_falso):
    conversa, s, painel, cerebro, _ = _montar_simples()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates Sócrates Sócrates Se atualiza, por favor Sócrates Dizem."),
                            o.fala("Por favor.")])
    assert "Posso baixar a versão nova e reiniciar?" in s.voz.faladas
    assert atualizar_falso == ["atualizou"] and cerebro.recebido == []   # nem passou pelo cérebro


# ---------------------------------------------------------------- música tocando no microfone

def test_repeticao_longa_e_musica_e_sai_inteira():
    letra = ("Sons de rio, mais uma luta, mais uma operativa, se você curte as dentes, é uma luta, uma "
             "luta, uma luta, uma luta, uma luta, uma luta, uma luta, uma luta, uma luta, um milho, um "
             "milho e uma luta.")
    assert sem_repeticoes(letra) == ""
    # fala de verdade com 4 ou 5 repetições continua como antes
    assert sem_repeticoes("Sócrates, E aí E aí E aí E aí, me explica crase") == "Sócrates, me explica crase"
    assert sem_repeticoes("Não, não, não, não, não, eu quis dizer crase") == "eu quis dizer crase"
