"""A caixa do Claude (22/11/2026).

"Ele não está conseguindo acesso ao chat de novo": o Sócrates digitava os pedidos no app do
Claude, o que dependia do app aberto na conversa certa, e ainda entendia "Cloud" como serviço
de nuvem. Agora os pedidos e as ideias dele vão para melhorias.json (a caixa do Claude), que
uma tarefa agendada lê toda noite; cada item volta "feita" ou "descartada", com a resposta.
"""

import json

import pytest

from socrates.core.agente import Agente
from socrates.core.memoria import Memorias
from socrates.core.reflexao import CAPACIDADES, aviso_da_reflexao
from socrates.stt.groq_whisper import filtrar_alucinacao


class CerebroMudo:
    async def com_ferramentas(self, *a, **k):
        return ""


@pytest.fixture
def agente(tmp_path):
    return Agente(CerebroMudo(), memorias=Memorias(tmp_path / "S"))


def test_ideia_do_socrates_entra_uma_vez(agente):
    assert "caixa do Claude" in agente.sugerir_melhoria("Reconectar o microfone quando cair")
    assert "já está na caixa" in agente.sugerir_melhoria("reconectar o microfone quando cair.")
    [item] = agente.memorias.melhorias.itens()
    assert item["status"] == "nova" and item["origem"] == "conversa"


def test_ideia_que_o_claude_descartou_nao_volta(agente):
    """A da "integração com o Cloud" (era o microfone trocando Claude por Cloud) não pode
    voltar para a caixa toda vez que ele pensar nela de novo."""
    agente.memorias.melhorias.adicionar(
        "Integração direta com o serviço Cloud para sincronizar anotações", status="descartada",
        origem="conversa", resposta="era o microfone trocando Claude por Cloud")
    r = agente.sugerir_melhoria("Integração direta com o serviço Cloud para sincronizar anotações")
    assert "não fez" in r and "trocando Claude por Cloud" in r
    assert agente.memorias.melhorias_pendentes() == []


def test_ideia_que_o_claude_ja_fez_nao_volta(agente):
    agente.memorias.melhorias.adicionar("Reconectar o microfone quando cair", status="feita",
                                        origem="reflexao", resposta="commit df2cea3")
    r = agente.sugerir_melhoria("Reconectar o microfone quando cair")
    assert "já fez" in r and "pedir_ao_claude" in r
    assert agente.memorias.melhorias_pendentes() == []


def test_minhas_melhorias_mostra_a_resposta_do_claude(agente):
    m = agente.memorias.melhorias
    m.adicionar("Pedir confirmação antes de abrir programas", status="descartada",
                origem="conversa", resposta="o Felipe prefere que você aja direto")
    m.adicionar("Reconectar o microfone quando cair", status="feita", origem="reflexao")
    m.adicionar("Ler o quadro mais devagar", status="nova", origem="aluno")
    texto = agente.minhas_melhorias()
    assert "o Claude analisou e não fez; resposta do Claude: o Felipe prefere" in texto
    assert "Reconectar o microfone quando cair. (o Claude já fez)" in texto
    assert "Ler o quadro mais devagar. (na caixa, o Claude lê hoje à noite)" in texto


def test_prompt_diz_que_a_caixa_ja_esta_com_o_claude(agente):
    agente.sugerir_melhoria("Reconectar o microfone quando cair")
    sistema = agente.sistema()
    assert "Na caixa do Claude" in sistema and "não precisa mandar de novo" in sistema
    assert "não digita no app dele" in sistema


def test_aviso_da_reflexao_nao_pede_para_mandar(tmp_path):
    fala = aviso_da_reflexao(["Releia o artigo com ler_lei"], ["Reconectar o microfone"])
    assert "caixa do Claude" in fala and "hoje à noite" in fala and "manda" not in fala
    assert "caixa do Claude" in CAPACIDADES


def test_caixa_continua_json_simples_de_editar(tmp_path):
    m = Memorias(tmp_path)
    m.para_o_claude("Deixe a voz mais grave", origem="aluno")
    dados = json.loads((tmp_path / "melhorias.json").read_text(encoding="utf-8"))
    assert dados == [{"t": "Deixe a voz mais grave.", "d": dados[0]["d"], "status": "nova",
                      "origem": "aluno"}]


# ---------------------------------------------------------------- frases inventadas no silêncio

@pytest.mark.parametrize("fala", ["Legenda Adriana Zanotto", "Sous-titrage Société Radio-Canada",
                                  "Aplausos", "Amém.", "Música", "Sous-titres réalisés par la "
                                  "communauté d'Amara.org", "Thanks for watching!"])
def test_frases_que_o_whisper_inventa_sao_descartadas(fala):
    assert filtrar_alucinacao(fala) == ""


@pytest.mark.parametrize("fala", ["Sócrates, aplausos para você", "Legenda do mapa da prova",
                                  "Música no Spotify", "Tchau.", "Certo."])
def test_fala_de_verdade_passa(fala):
    assert filtrar_alucinacao(fala) == fala
