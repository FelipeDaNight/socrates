"""Conversa mãos livres de ponta a ponta, com tudo simulado."""

import asyncio

import numpy as np
import pytest

from socrates.config import Config, ConfigEscuta, ConfigLLM, ConfigVoz
from socrates.core.orquestrador import Orquestrador
from socrates.llm import ErroCerebro
from socrates.llm.falso import CerebroFalso
from socrates.maos_livres import Conversa
from socrates.tts import Voz
from socrates.visor.painel import Painel

RESPOSTA = "Crase é a fusão de duas letras a. Entendeu?"


class EscutaFalsa:
    def __init__(self):
        self.pausada = False
        self.pausas = 0

    def pausar(self):
        self.pausada = True
        self.pausas += 1

    def retomar(self):
        self.pausada = False


class OuvidoFalso:
    """Cada 'fala' do microfone é um array; o texto vem de um dicionário."""
    def __init__(self):
        self.textos: dict[int, str] = {}
        self.chamadas = 0

    def fala(self, texto: str) -> np.ndarray:
        i = len(self.textos) + 1
        self.textos[i] = texto
        return np.full(1600, i, dtype=np.int16)

    async def transcrever(self, wav: bytes, dica: str | None = None) -> str:
        self.chamadas += 1
        i = int(np.frombuffer(wav[44:46], dtype=np.int16)[0])
        return self.textos[i]


class VozFalsa(Voz):
    def __init__(self, escuta):
        self.escuta = escuta
        self.faladas: list[str] = []
        self.sinteses = 0

    async def sintetizar(self, texto):
        self.sinteses += 1
        return texto.encode()

    async def tocar(self, audio):
        assert self.escuta.pausada, "o microfone deveria estar pausado enquanto ele fala"
        self.faladas.append(audio.decode())

    def parar(self):
        pass


class Sentidos:
    def __init__(self):
        self.escuta = EscutaFalsa()
        self.ouvido = OuvidoFalso()
        self.voz = VozFalsa(self.escuta)


def _montar(cerebro=None, palavra=True, janela=30.0, janela_prova=60.0):
    cfg = Config(nome="Sócrates", modo_inicial="explicar", historico_max=20,
                 llm=ConfigLLM("groq", "http://x", "modelo", "k"),
                 voz=ConfigVoz(saudacao=False),
                 escuta=ConfigEscuta(palavra, janela, janela_prova))
    cerebro = cerebro or CerebroFalso(RESPOSTA)
    soc = Orquestrador(cerebro, modo="explicar")
    s = Sentidos()
    painel = Painel()
    tela: list[str] = []
    conversa = Conversa(cfg, soc, s, painel, escrever=tela.append)
    return conversa, s, painel, cerebro, tela


async def _rodar(conversa, itens, espera_entre=0.0):
    fila = asyncio.Queue()
    tarefa = asyncio.create_task(conversa.rodar(fila))
    for item in itens:
        if isinstance(item, float):        # pausa no roteiro
            await asyncio.sleep(item)
            continue
        fila.put_nowait(item)
        await asyncio.sleep(espera_entre or 0.05)
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)


@pytest.mark.asyncio
async def test_ignora_quem_nao_chamou_e_responde_quem_chamou():
    conversa, s, painel, cerebro, _ = _montar()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Vou almoçar agora."),
                            o.fala("Sócrates, o que é crase?")])
    assert len(cerebro.recebido) == 1
    assert cerebro.recebido[0][-1]["content"] == "o que é crase?"
    assert s.voz.faladas[:2] == ["Crase é a fusão de duas letras a.", "Entendeu?"]


@pytest.mark.asyncio
async def test_depois_da_resposta_continua_sem_dizer_o_nome():
    conversa, s, painel, cerebro, _ = _montar()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?"), o.fala("Entendi, e antes de casa?")])
    assert [m[-1]["content"] for m in cerebro.recebido] == ["o que é crase?",
                                                            "Entendi, e antes de casa?"]


@pytest.mark.asyncio
async def test_janela_fecha_com_o_tempo():
    conversa, s, painel, cerebro, _ = _montar(janela=0.1)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?"), 0.5, o.fala("E antes de casa?")])
    assert len(cerebro.recebido) == 1


@pytest.mark.asyncio
async def test_modo_prova_da_mais_tempo_para_responder():
    conversa, s, painel, cerebro, _ = _montar(janela=0.1, janela_prova=5)
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, modo prova."), o.fala("Me testa em crase"),
                            0.4, o.fala("É a letra b")])
    assert [m[-1]["content"] for m in cerebro.recebido] == ["Me testa em crase", "É a letra b"]
    assert "TESTAR" in cerebro.recebido[0][0]["content"]


@pytest.mark.asyncio
async def test_so_o_nome_responde_sim_na_hora():
    conversa, s, painel, cerebro, _ = _montar()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates?"), o.fala("O que é próclise?"),
                            o.fala("Obrigado, Sócrates."), o.fala("Sócrates!")])
    assert s.voz.faladas.count("Sim?") == 2
    assert cerebro.recebido[0][-1]["content"] == "O que é próclise?"
    sinteses_sim = s.voz.sinteses - len([f for f in s.voz.faladas if f != "Sim?"])
    assert sinteses_sim == 1   # o "Sim?" foi guardado, não gerado de novo


@pytest.mark.asyncio
async def test_obrigado_encerra_o_assunto():
    conversa, s, painel, cerebro, _ = _montar()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?"), o.fala("Valeu, Sócrates!"),
                            o.fala("Agora vou jantar.")])
    assert len(cerebro.recebido) == 1
    assert "Por nada. É só me chamar." in s.voz.faladas
    assert not painel.em_janela()


@pytest.mark.asyncio
async def test_texto_digitado_nao_precisa_do_nome():
    conversa, s, painel, cerebro, _ = _montar()
    await _rodar(conversa, ["o que é crase?"])
    assert cerebro.recebido[0][-1]["content"] == "o que é crase?"
    assert s.ouvido.chamadas == 0


@pytest.mark.asyncio
async def test_encerrar_por_voz_se_despede():
    conversa, s, painel, cerebro, tela = _montar()
    o = s.ouvido
    fila = asyncio.Queue()
    fila.put_nowait(o.fala("Sócrates, encerrar."))
    fila.put_nowait(o.fala("Sócrates, o que é crase?"))   # não deve chegar a ser atendido
    await asyncio.wait_for(conversa.rodar(fila), 5)
    assert cerebro.recebido == []
    assert s.voz.faladas[-1] == "Até a próxima. Bons estudos!"


@pytest.mark.asyncio
async def test_sem_palavra_de_ativacao_responde_tudo():
    conversa, s, painel, cerebro, _ = _montar(palavra=False)
    o = s.ouvido
    await _rodar(conversa, [o.fala("O que é crase?")])
    assert len(cerebro.recebido) == 1


@pytest.mark.asyncio
async def test_erro_no_cerebro_avisa_por_voz_e_continua():
    class Quebrado(CerebroFalso):
        async def responder(self, mensagens):
            self.recebido.append(mensagens)
            if len(self.recebido) == 1:
                raise ErroCerebro("Limite do plano grátis atingido.")
            yield "Agora funcionou."

    conversa, s, painel, cerebro, tela = _montar(Quebrado())
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?"), o.fala("Sócrates, tenta de novo")])
    assert "Limite do plano grátis atingido." in s.voz.faladas   # fala o motivo de verdade
    assert "Agora funcionou." in s.voz.faladas
    assert any("Limite do plano grátis" in t for t in tela)
    assert painel.estado == "ocioso"


@pytest.mark.asyncio
async def test_microfone_volta_depois_de_cada_fala():
    conversa, s, painel, cerebro, _ = _montar()
    o = s.ouvido
    await _rodar(conversa, [o.fala("Sócrates, o que é crase?")])
    assert s.escuta.pausas >= 2 and not s.escuta.pausada


# ---------- quadro e avisos ----------

QUADRO = ("Veja no quadro. [QUADRO]# Bhaskara\n$$ x = \\frac{-b}{2a} $$[/QUADRO] Entendeu?")


@pytest.mark.asyncio
async def test_quadro_vai_para_o_visor_e_nao_e_falado():
    conversa, s, painel, cerebro, tela = _montar(CerebroFalso(QUADRO))
    painel.tem_visor = True
    painel.quadro_tamanho = (400, 300)
    await _rodar(conversa, [s.ouvido.fala("Sócrates, me explica Bhaskara")], espera_entre=0.5)
    await asyncio.gather(*conversa._desenhos)
    assert painel.quadro_png and painel.quadro_png[:4] == b"\x89PNG"
    faladas = " ".join(s.voz.faladas)
    assert "frac" not in faladas and "Bhaskara" not in faladas and "Entendeu?" in faladas
    assert any("[quadro: Bhaskara]" in t for t in tela)


@pytest.mark.asyncio
async def test_sem_visor_o_quadro_aparece_no_terminal():
    conversa, s, painel, cerebro, tela = _montar(CerebroFalso(QUADRO))
    await _rodar(conversa, ["me explica Bhaskara"])
    assert any("┌─ quadro" in t and "\\frac{-b}{2a}" in t for t in tela)
    assert painel.quadro_png is None


@pytest.mark.asyncio
async def test_apagar_quadro():
    conversa, s, painel, cerebro, tela = _montar()
    painel.mostrar_quadro(b"png")
    await _rodar(conversa, [s.ouvido.fala("Sócrates, apaga o quadro.")])
    assert painel.quadro_png is None and "Quadro apagado." in s.voz.faladas


@pytest.mark.asyncio
async def test_aviso_do_timer_e_falado():
    from socrates.maos_livres import Aviso
    conversa, s, painel, cerebro, tela = _montar()
    fila = asyncio.Queue()
    tarefa = asyncio.create_task(conversa.rodar(fila))
    fila.put_nowait(Aviso("Seu tempo de estudo acabou! Hora de fazer uma pausa."))
    await asyncio.sleep(0.5)
    assert "Seu tempo de estudo acabou! Hora de fazer uma pausa." in s.voz.faladas
    assert painel.em_janela()   # pode responder ao aviso sem dizer o nome
    fila.put_nowait(None)
    await asyncio.wait_for(tarefa, 5)


class CerebroEmSequencia(CerebroFalso):
    """Responde cada chamada com o próximo texto da lista."""
    def __init__(self, *respostas):
        super().__init__("")
        self.respostas = list(respostas)

    async def responder(self, mensagens):
        self.recebido.append(list(mensagens))
        for palavra in self.respostas.pop(0).split(" "):
            yield palavra + " "


@pytest.mark.asyncio
async def test_pede_o_quadro_quando_o_modelo_esquece():
    cerebro = CerebroEmSequencia(
        "A fórmula de Bhaskara serve para equações do segundo grau. Entendeu?",
        "[QUADRO]\n# Bhaskara\n$$ x = \\frac{-b \\pm \\sqrt{\\Delta}}{2a} $$\n[/QUADRO]")
    conversa, s, painel, _, tela = _montar(cerebro)
    painel.tem_visor = True
    painel.quadro_tamanho = (400, 300)
    await _rodar(conversa, [s.ouvido.fala("Sócrates, me mostre a fórmula de básquet")],
                 espera_entre=0.6)
    await asyncio.gather(*conversa._desenhos)
    assert painel.quadro_png is not None
    assert "somente o quadro" in cerebro.recebido[1][-1]["content"]
    assert len([m for m in conversa.soc.historico if m["role"] == "user"]) == 1
    assert "[QUADRO]" in conversa.soc.historico[-1]["content"]
    assert "frac" not in " ".join(s.voz.faladas)


@pytest.mark.asyncio
async def test_conversa_comum_nao_pede_quadro():
    cerebro = CerebroEmSequencia("Tudo ótimo, e com você?")
    conversa, s, painel, _, _ = _montar(cerebro)
    painel.tem_visor = True
    await _rodar(conversa, [s.ouvido.fala("Sócrates, tudo bem?")])
    assert len(cerebro.recebido) == 1 and painel.quadro_png is None


@pytest.mark.parametrize("pedido,esperado", [
    ("me mostre a fórmula de básquet", True),
    ("desenha o gráfico de seno", True),
    ("resolve essa equação passo a passo", True),
    ("o que é crase?", False),
    ("tudo bem?", False),
])
def test_pede_quadro(pedido, esperado):
    from socrates.maos_livres import pede_quadro
    assert pede_quadro(pedido) is esperado
