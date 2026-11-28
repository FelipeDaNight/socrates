"""Visor novo (estilo HUD do Jarvis): servidor local + página no Edge (visor/hud.py).

Pedido do Felipe (26/11/2026): "pode implementar já, quero estudar nele hoje".
"""

import asyncio
import io
import json
import time
import urllib.request
from types import SimpleNamespace

import numpy as np
import pytest

from socrates import config
from socrates.maos_livres import Conversa
from socrates.visor import hud
from socrates.visor.painel import Painel
from socrates.visor.quadro import HUD, renderizar

LEI = "# CF · Art. 5º, XI\nXI - a casa é asilo inviolável do indivíduo;\n- multa de R\\$ 293,47\nCerto ou errado?"
MAPA = "# Espécies\nmapa: Flagrante\n- Próprio\n  - está cometendo\n- Impróprio\n  - perseguido logo após"


# ---------------------------------------------------------------- o que a página recebe

def test_quadro_de_texto_vai_como_itens_para_a_pagina_desenhar():
    q = hud.descrever_quadro(LEI)
    assert q["tipo"] == "texto"
    assert [i["tipo"] for i in q["itens"]] == ["titulo", "texto", "item", "texto"]
    assert q["itens"][2]["texto"] == "multa de R$ 293,47"         # o \$ do treino volta a ser $


@pytest.mark.parametrize("fonte", [MAPA, "# Bhaskara\n$$ x = \\frac{-b}{2a} $$",
                                   "# Função\ngrafico: x^2 | -2 | 2", "# Conta\nResolva $x^2 = 4$"])
def test_desenho_formula_e_grafico_vao_como_imagem(fonte):
    assert hud.descrever_quadro(fonte)["tipo"] == "imagem"


def test_quadro_vazio_texto_e_png_antigo():
    p = Painel()
    assert hud.quadro(p)["tipo"] == "vazio"
    p.mostrar_fonte(LEI)
    assert hud.quadro(p)["tipo"] == "texto" and hud.quadro(p)["versao"] == 1
    p.limpar_quadro()
    assert hud.quadro(p)["tipo"] == "vazio" and p.quadro_versao == 2
    p.mostrar_quadro(b"\x89PNG...")
    assert hud.quadro(p)["tipo"] == "imagem"


def test_estado_tem_tudo_e_vira_json():
    p = Painel()
    p.qual_cerebro = lambda: "GROQ · GPT-OSS-120B"
    p.info_estudo = lambda: {"modo": "aula", "titulo": "Flagrante", "progresso": "2/6"}
    p.info_timer = lambda: 1 / 0                       # dado que quebra não derruba o visor
    p.iniciar_fala(np.ones(200) * 0.8)
    e = json.loads(json.dumps(hud.estado(p)))
    assert e["visual"] == "falando" and e["nivel"] == pytest.approx(0.8)
    assert e["cerebro"] == "GROQ · GPT-OSS-120B" and e["estudo"]["modo"] == "aula"
    assert e["timer"] is None and e["encerrado"] is False
    assert e["cor"].startswith("#") and e["brilho"].startswith("#")


def test_log_de_voz_e_tempo_de_resposta():
    p = Painel()
    p.registrar("voce", "  me ensina\n flagrante ")
    p.registrar("socrates", "")                         # fala vazia não entra
    assert [r[1:] for r in p.registro] == [("voce", "me ensina flagrante")]
    assert p.falas == 1 and p.registro_versao == 1
    time.sleep(0.05)
    p.iniciar_fala(np.zeros(10))
    assert p.resposta_seg is not None and 0 <= p.resposta_seg < 5
    p.iniciar_fala(np.zeros(10))                        # a 2ª frase não mexe no tempo
    assert p.resposta_seg is not None


def test_rotulo_do_cerebro():
    m = SimpleNamespace(nome="groq_qwen", modelo="qwen/qwen3.8-27b")
    assert hud.rotulo_cerebro(m) == "GROQ · QWEN3.8-27B"
    assert hud.rotulo_cerebro(SimpleNamespace(nome="gemini", modelo="gemini-flash-latest")) == "GEMINI · GEMINI-FLASH"
    assert hud.rotulo_cerebro(None) == ""


def test_estudo_em_andamento_e_revisoes():
    hud._revisoes.update(quando=0.0, n=None)
    caderno = SimpleNamespace(vencidos=lambda: ["a", "b", "c"])
    aula = SimpleNamespace(topico=SimpleNamespace(titulo="Prisão em flagrante"), k=2, n=7)
    d = hud.info_estudo(SimpleNamespace(aula=aula, sessao=None, caderno=caderno))
    assert (d["modo"], d["progresso"], d["revisoes"]) == ("aula", "3/7", 3)
    sessao = SimpleNamespace(modo="treino", titulo="Questões da PRF", pos=3, itens=[1] * 10,
                             registros=[SimpleNamespace(ok=True)] * 2 + [SimpleNamespace(ok=False)])
    d = hud.info_estudo(SimpleNamespace(aula=None, sessao=sessao, caderno=caderno))
    assert (d["modo"], d["progresso"], d["acertos"]) == ("treino", "4/10", "2/3")


def test_timer_do_pomodoro():
    from socrates.ferramentas import computador
    computador.TIMER.cancelar()
    assert hud.info_timer() is None
    computador.TIMER.iniciar(25, "estudo")
    try:
        t = hud.info_timer()
        assert t["total"] == 1500 and 1490 <= t["resta"] <= 1500 and t["motivo"] == "estudo"
    finally:
        computador.TIMER.cancelar()


# ---------------------------------------------------------------- o quadro em imagem

def test_imagem_do_quadro_no_tema_hud_tem_fundo_transparente_e_dobra_os_pixels():
    from PIL import Image
    img = Image.open(io.BytesIO(renderizar(MAPA, 600, 480, HUD, 2)))
    assert img.size == (1200, 960) and img.mode == "RGBA"
    assert img.getpixel((2, 2))[3] == 0                 # canto sem nada: transparente


def test_quadro_grande_usa_letra_maior():
    from socrates.visor import diagrama as dg
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    w = dg._medidor(FigureCanvasAgg(Figure(figsize=(7.6, 6.1), dpi=100)).get_renderer())
    _, _, pequeno = dg.montar(dg.ler(MAPA), 760, 610, w)
    _, _, grande = dg.montar(dg.ler(MAPA), 1240, 820, w)
    assert max(c.pt for c in grande.caixas) > max(c.pt for c in pequeno.caixas)


# ---------------------------------------------------------------- o servidor de verdade

@pytest.fixture
def servidor():
    p = Painel()
    h = hud.Hud(p, porta=0)
    h.iniciar()
    yield p, h
    p.encerrado = True
    h.parar()


def _get(h, caminho):
    with urllib.request.urlopen(h.url.rstrip("/") + caminho, timeout=5) as r:
        return r.status, r.headers.get("Content-Type"), r.read()


def _post(h, caminho):
    req = urllib.request.Request(h.url.rstrip("/") + caminho, data=b"", method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status


def test_pagina_estado_quadro_e_imagem(servidor):
    p, h = servidor
    status, tipo, corpo = _get(h, "/")
    assert status == 200 and "text/html" in tipo and "SÓCRATES".encode() in corpo
    assert not h._contatou.is_set()
    status, _, corpo = _get(h, "/estado")
    assert json.loads(corpo)["visual"] == "dormindo" and h._contatou.is_set()
    p.mostrar_fonte(MAPA)
    assert json.loads(_get(h, "/quadro")[2])["tipo"] == "imagem"
    status, tipo, png = _get(h, "/quadro.png?w=700&h=500&s=2")
    assert tipo == "image/png" and png[:4] == b"\x89PNG"
    assert _get(h, "/quadro.png?w=700&h=500&s=2")[2] == png           # guardada: não desenha de novo


def test_espaco_cala_a_voz_so_quando_ele_fala(servidor):
    p, h = servidor
    calou = []
    p.interromper = lambda: calou.append(1)
    assert _post(h, "/interromper") == 204 and calou == []
    p.iniciar_fala(np.ones(100))
    _post(h, "/interromper")
    assert calou == [1]


def test_fechar_a_janela_encerra_mas_f5_nao(servidor, monkeypatch):
    p, h = servidor
    monkeypatch.setattr(hud, "ESPERA_FECHAR", 0.3)
    fechou = []
    p.ao_fechar = lambda: fechou.append(1)
    _get(h, "/estado")
    _post(h, "/fechou")                 # F5: avisa que fechou e volta logo
    time.sleep(0.1)
    _get(h, "/estado")
    time.sleep(1.2)
    assert fechou == [] and not p.fechou
    _post(h, "/fechou")                 # fechou de verdade
    time.sleep(1.5)
    assert fechou == [1] and p.fechou


def test_sem_edge_volta_para_o_visor_classico(monkeypatch):
    monkeypatch.setattr(hud, "achar_navegador", lambda: None)
    p = Painel()
    assert hud.abrir(p, porta=0, espera=0.5) is None
    assert not p.quadro_por_fonte and not p.tem_visor


def test_pagina_que_nao_carrega_tambem_volta(monkeypatch):
    class NavegadorMudo:
        def poll(self):
            return None

        def terminate(self):
            pass
    monkeypatch.setattr(hud.Hud, "abrir_janela",
                        lambda self, largura, altura, tamanho="normal":
                        setattr(self, "navegador", NavegadorMudo()) or True)
    p = Painel()
    assert hud.abrir(p, porta=0, espera=0.3) is None


def test_perfil_do_edge_fica_fora_da_pasta_do_socrates(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert hud.pasta_do_perfil() == tmp_path / "Socrates" / "visor-edge"


# ---------------------------------------------------------------- ligado ao resto

def test_com_o_visor_novo_o_quadro_vai_como_texto_sem_desenhar_png():
    p = Painel()
    p.quadro_por_fonte = True
    conversa = SimpleNamespace(painel=p)
    asyncio.run(Conversa._desenhar(conversa, LEI))
    assert p.quadro_fonte == LEI and p.quadro_png is None and p.quadro_versao == 1


def test_configuracao_padrao_e_o_visor_novo():
    v = config.ConfigVisor()
    assert v.estilo == "hud" and (v.largura, v.altura) == (1280, 760)


def test_pagina_tem_os_pedacos_do_visor():
    html = hud.PAGINA.read_text(encoding="utf-8")
    for pedaco in ('id="reator-grande"', 'id="reator-pequeno"', 'id="quadro"', 'id="log-lista"',
                   "/estado", "/quadro.png", "/interromper", "/fechou"):
        assert pedaco in html
