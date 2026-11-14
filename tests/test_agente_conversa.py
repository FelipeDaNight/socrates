"""O cérebro que decide dentro da conversa por voz, a reflexão diária e a voz que não cala."""

import asyncio
import json
import random
import shutil
from datetime import date
from pathlib import Path

import pytest

from socrates.config import Config, ConfigEscuta, ConfigLLM, ConfigVoz
from socrates.core.agente import Agente
from socrates.core.memoria import Memorias
from socrates.core.orquestrador import Orquestrador
from socrates.core.reflexao import Reflexao, aviso_da_reflexao, eventos_do_log
from socrates.estudo import Caderno, Tutor
from socrates.estudo import material as mat
from socrates.estudo.plano import carregar_planos
from socrates.llm import ErroCerebro
from socrates.llm.falso import CerebroFalso
from socrates.maos_livres import Aviso, Conversa
from socrates.tts import ErroVoz
from socrates.visor.painel import Painel

from test_agente import BibliotecaFalsa, CerebroRoteiro
from test_maos_livres import Sentidos, _rodar

DADOS = Path(__file__).parent / "dados"


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


def _montar(tutor, roteiro, tmp_path, conversa_resposta="Resposta da conversa.", saudacao=False):
    cfg = Config(nome="Sócrates", modo_inicial="explicar", historico_max=20,
                 llm=ConfigLLM("groq", "http://x", "modelo", "k"),
                 voz=ConfigVoz(saudacao=saudacao), escuta=ConfigEscuta(True, 30.0, 60.0))
    conversa_cerebro = CerebroFalso(conversa_resposta)
    soc = Orquestrador(conversa_cerebro, modo="explicar")
    feitos = []

    def executar_pc(nome, args):
        feitos.append((nome, args))
        return "Escrevi no Bloco de Notas." if nome == "escrever_no_bloco_de_notas" else "Feito."

    agente = Agente(roteiro, tutor=tutor, memorias=Memorias(tmp_path / "Socrates"),
                    biblioteca=BibliotecaFalsa(), executar_pc=executar_pc,
                    acoes_pc=["escrever_no_bloco_de_notas", "abrir_programa"])
    s = Sentidos()
    painel = Painel()
    tela: list[str] = []
    conversa = Conversa(cfg, soc, s, painel, escrever=tela.append, tutor=tutor, agente=agente)
    return conversa, s, soc, conversa_cerebro, feitos, tela


@pytest.mark.asyncio
async def test_a_fala_da_gravacao_escreve_no_bloco_de_notas(tutor, tmp_path):
    roteiro = CerebroRoteiro([("ler_lei", {"lei": "CTB", "artigos": "7",
                                           "destino": "bloco_de_notas"})],
                             "Pronto, o artigo 7 do CTB está no Bloco de Notas.")
    conversa, s, soc, cerebro_conversa, feitos, _ = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o bloco de notas e coloca o artigo 7 do CTB, por favor.")])
    assert feitos and feitos[0][0] == "escrever_no_bloco_de_notas"
    assert s.voz.faladas[0] == "Pronto, o artigo 7 do CTB está no Bloco de Notas."
    assert cerebro_conversa.recebido == []                   # o caminho antigo nem foi usado
    assert soc.historico[-1]["content"].startswith("Pronto, o artigo 7")


@pytest.mark.asyncio
async def test_quadro_da_lei_aparece(tutor, tmp_path):
    roteiro = CerebroRoteiro([("ler_lei", {"lei": "CP", "artigos": "1-5"})],
                             "Estão no quadro. O primeiro é o princípio da legalidade.")
    conversa, s, *_ , tela = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, e os primeiros artigos do Código Penal?")])
    junto = "".join(tela)
    assert "Não há crime sem lei anterior" in junto and "Concurso de pessoas" not in junto


@pytest.mark.asyncio
async def test_estudar_entrega_ao_tutor_e_o_treino_segue_pelas_regras(tutor, tmp_path):
    roteiro = CerebroRoteiro([("estudar", {"pedido": "lacunas do CTB"})])
    conversa, s, soc, *_ = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    fala = "quero treinar a lei seca de trânsito porque a prova está chegando"
    await _rodar(conversa, [o.fala(f"Sócrates, {fala}")])
    assert "Complete" in " ".join(s.voz.faladas)               # o treino de lacunas começou
    assert soc.historico[0] == {"role": "user", "content": fala}


@pytest.mark.asyncio
async def test_pedido_curto_e_claro_vai_direto_ao_tutor(tutor, tmp_path):
    roteiro = CerebroRoteiro([], "não devia ser chamado")
    conversa, s, *_ = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, lacunas do CTB")])
    assert roteiro.mensagens is None                            # nem gastou o cérebro
    assert "Complete" in " ".join(s.voz.faladas)


@pytest.mark.asyncio
async def test_sem_internet_volta_ao_caminho_antigo(tutor, tmp_path):
    roteiro = CerebroRoteiro([], falhar=True)
    conversa, s, soc, cerebro_conversa, *_ = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?"),
                            o.fala("lacunas do CTB")])
    assert len(cerebro_conversa.recebido) == 1          # a pergunta livre foi pela conversa
    assert "Complete" in " ".join(s.voz.faladas)         # e o pedido de estudo, pelas regras


@pytest.mark.asyncio
async def test_aviso_entra_no_historico_e_o_vai_seguinte_tem_contexto(tutor, tmp_path):
    roteiro = CerebroRoteiro([], "Certo, continuo.")
    conversa, s, soc, *_ = _montar(tutor, roteiro, tmp_path)
    o = s.ouvido
    await _rodar(conversa, [Aviso("Não consegui estudar Vidas Secas agora."),
                            o.fala("Sócrates, vai, por favor.")])
    conteudos = [m["content"] for m in roteiro.mensagens]
    assert any("Não consegui estudar Vidas Secas" in c for c in conteudos)


@pytest.mark.asyncio
async def test_saudacao_ja_sugere_o_plano(tutor, tmp_path):
    roteiro = CerebroRoteiro([], "ok")
    conversa, s, soc, *_ = _montar(tutor, roteiro, tmp_path, saudacao=True)
    await _rodar(conversa, [])
    assert s.voz.faladas and s.voz.faladas[0].startswith("Olá!")
    assert "Sugestão para hoje" in " ".join(s.voz.faladas)
    assert soc.historico and soc.historico[-1]["role"] == "assistant"


@pytest.mark.asyncio
async def test_acao_no_pc_no_meio_do_treino_vai_ao_agente(tutor, tmp_path):
    roteiro = CerebroRoteiro([("abrir_programa", {"nome": "bloco de notas"})], "Abri.")
    conversa, s, soc, _c, feitos, _t = _montar(tutor, roteiro, tmp_path)
    tutor.atender("lacunas do CTB")
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, abre o bloco de notas")])
    assert feitos == [("abrir_programa", {"nome": "bloco de notas"})]
    assert s.voz.faladas[0] == "Abri." and not any("Não entendi" in f for f in s.voz.faladas)


# ---------------------------------------------------------------- histórico

def test_registrar_junta_avisos_seguidos():
    soc = Orquestrador(CerebroFalso("x"), historico_max=2)
    soc.registrar(None, "aviso 1")
    soc.registrar(None, "aviso 2")
    soc.registrar("pedido", "resposta")
    assert soc.historico == [{"role": "assistant", "content": "aviso 1\naviso 2"},
                             {"role": "user", "content": "pedido"},
                             {"role": "assistant", "content": "resposta"}]
    for i in range(10):
        soc.registrar(f"p{i}", f"r{i}")
    assert len(soc.historico) <= 8


# ---------------------------------------------------------------- reflexão

LOG = """2026-11-13 21:18:07,685 INFO    socrates.ouvido: transcrito: 'Pode ser, me fale sobre os primeiros 10 artigos do CTB.' (certeza -0.06)
2026-11-13 21:18:09,257 INFO    socrates.orquestrador: aluno: 'Pode ser, me fale sobre os primeiros 10 artigos do CTB.' | Sócrates respondeu (94 caracteres): 'Claro, posso resumir os dez primeiros artigos ou detalhar cada um separadamente. Como prefere?'
2026-11-13 21:18:24,488 INFO    socrates.orquestrador: aluno: 'detalhar cada um.' | Sócrates respondeu (78 caracteres): 'Posso dividir a explicação em duas partes, com cinco artigos em cada resposta?'
2026-11-13 21:21:08,175 WARNING socrates.voz: falha na voz: No audio was received. Please verify that your parameters are correct.
2026-11-13 21:21:08,205 WARNING socrates.voz: falha na voz: No audio was received. Please verify that your parameters are correct.
2026-11-13 21:21:12,713 INFO    socrates.orquestrador: aluno: 'Ficou sim, mas o artigo 7, ele não é um...' | Sócrates respondeu (433 caracteres): 'Você tem razão, o artigo sete não trata só da exigência da habilitação.'
2026-11-13 21:25:18,293 INFO    socrates.tutor: pedido de estudo: Pedido(tipo='auto', banco=None)
2026-11-13 21:26:43,775 INFO    socrates.autoestudo: não deu para estudar Poder constituinte: sobrou pouco conteúdo
2026-11-13 21:28:38,668 INFO    socrates.agente: agente: "O bloco de notas e coloca o artigo 7 do CTB, por favor." -> ler_lei | 'Pronto.'
2026-11-13 21:33:52,263 INFO    socrates.conversa: ignorado (sem o nome): 'Tchau.'
"""


def test_eventos_do_log_legiveis():
    eventos, ultimo = eventos_do_log(LOG.splitlines())
    assert ultimo == "2026-11-13 21:33:52"
    assert "21:18 ALUNO: Pode ser, me fale sobre os primeiros 10 artigos do CTB." in eventos
    assert any("SÓCRATES: Claro, posso resumir" in e for e in eventos)
    assert sum("FALHA (voz)" in e for e in eventos) == 1          # repetidas viram uma
    assert any("SÓCRATES [ler_lei]: Pronto." in e for e in eventos)
    assert any("ignorado por falta do nome" in e for e in eventos)
    assert not any("autoestudo" in e for e in eventos)
    novos, _ = eventos_do_log(LOG.splitlines(), depois_de="2026-11-13 21:25:00")
    assert not any("primeiros 10 artigos" in e for e in novos)


class CerebroJSON:
    def __init__(self, texto):
        self.texto = texto
        self.pedidos = []

    async def responder(self, mensagens):
        self.pedidos.append(mensagens)
        yield self.texto


@pytest.mark.asyncio
async def test_reflexao_grava_licoes_uma_vez_por_dia(tmp_path):
    log = tmp_path / "socrates.log"
    log.write_text(LOG, encoding="utf-8")
    memorias = Memorias(tmp_path / "Socrates")
    resposta = json.dumps({"licoes": ["Não pergunte se deve resumir ou detalhar: escolha e faça",
                                      "Artigo de lei só com ler_lei, nunca de memória"],
                           "melhorias": ["Repetir a síntese de voz quando o Edge falhar"]})
    cerebro = CerebroJSON("Aqui está: " + resposta)
    r = Reflexao(cerebro, memorias, log, hoje=lambda: date(2026, 11, 14))
    licoes, melhorias = await r.refletir()
    assert len(licoes) == 2 and len(melhorias) == 1
    assert "primeiros 10 artigos" in cerebro.pedidos[0][-1]["content"]
    assert len(memorias.licoes.textos()) == 2 and memorias.melhorias_pendentes()
    assert await r.refletir() is None                       # já refletiu hoje
    fala = aviso_da_reflexao(licoes, melhorias)
    assert "2 lições" in fala and "manda suas ideias para o Claude" in fala


@pytest.mark.asyncio
async def test_reflexao_sem_conversa_nova_espera(tmp_path):
    log = tmp_path / "socrates.log"
    log.write_text(LOG.splitlines()[0] + "\n", encoding="utf-8")
    r = Reflexao(CerebroJSON("{}"), Memorias(tmp_path / "S"), log, hoje=lambda: date(2026, 11, 14))
    assert await r.refletir() is None


# ---------------------------------------------------------------- voz que não cala

@pytest.mark.asyncio
async def test_edge_tenta_de_novo_antes_de_desistir(monkeypatch):
    import edge_tts

    from socrates.tts import edge

    tentativas = {"n": 0}

    class Falso:
        def __init__(self, *a, **k):
            pass

        async def stream(self):
            tentativas["n"] += 1
            if tentativas["n"] < 3:
                raise RuntimeError("No audio was received. Please verify that your parameters are correct.")
            yield {"type": "audio", "data": b"mp3"}

    monkeypatch.setattr(edge_tts, "Communicate", Falso)
    monkeypatch.setattr(edge, "ESPERAS", (0.0, 0.0))
    assert await edge.VozEdge().sintetizar("Olá") == b"mp3" and tentativas["n"] == 3
    tentativas["n"] = -10
    with pytest.raises(ErroVoz):
        await edge.VozEdge().sintetizar("Olá")


def test_velocidade_do_windows():
    from socrates.tts.windows import velocidade_sapi
    assert velocidade_sapi("+5%") == 0 or velocidade_sapi("+5%") == 1
    assert velocidade_sapi("+20%") == 2 and velocidade_sapi("-10%") == -1 and velocidade_sapi("x") == 0


def test_cidade_nao_some_com_a_secao_do_cerebro_local(tmp_path, monkeypatch):
    """Antes "local: Morrinhos" e a seção "local:" do Ollama tinham o mesmo nome: o prompt
    dizia "O aluno mora em {'modelo': 'qwen3.5:4b', ...}"."""
    from socrates import config
    (tmp_path / "config.yaml").write_text((config.RAIZ / "config.yaml").read_text(encoding="utf-8"),
                                          encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("cerebro: nuvem\nlocal:\n  modelo: qwen3.5:2b\n",
                                                encoding="utf-8")
    monkeypatch.setenv("GROQ_API_KEY", "x")
    cfg = config.carregar(tmp_path / "config.yaml")
    assert cfg.local == "Morrinhos, Goiás" and cfg.local_cfg.modelo == "qwen3.5:2b"
    assert cfg.agente.ativo and cfg.agente.reflexao
