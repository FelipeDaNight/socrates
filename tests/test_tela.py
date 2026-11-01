"""Janelas, área de transferência, bloco de notas e visão da tela (Windows simulado)."""

import base64
import io
import json

import pytest

from socrates.ferramentas import janelas as jn
from socrates.ferramentas import tela
from socrates.llm.acoes import pede_acao

JANELAS = [
    {"processo": "notepad", "titulo": "Sem título - Bloco de notas", "id": 101},
    {"processo": "chrome", "titulo": "QConcursos - Questões - Google Chrome", "id": 202},
    {"processo": "WindowsTerminal", "titulo": "Windows PowerShell", "id": 303},
    {"processo": "python", "titulo": "Sócrates", "id": 404},
    {"processo": "WINWORD", "titulo": "Resumo crase - Word", "id": 505},
]


@pytest.fixture
def ps(monkeypatch):
    """PowerShell falso: guarda os scripts e responde como o Windows."""
    scripts = []

    def falso(script, timeout=15):
        scripts.append(script)
        if "Get-Process | Where-Object" in script:
            return json.dumps(JANELAS)
        if "Get-Clipboard" in script:
            return "Questão 1: Assinale a alternativa correta sobre crase."
        return ""

    monkeypatch.setattr(jn, "_powershell", falso)
    return scripts


# ---------- janelas ----------

def test_janelas_abertas_esconde_terminal_e_socrates(ps):
    r = jn.janelas_abertas()
    assert "Bloco de notas" in r and "QConcursos" in r and "Word" in r
    assert "PowerShell" not in r and "Sócrates" not in r


@pytest.mark.parametrize("nome,ids", [
    ("bloco de notas", [101]), ("o Chrome", [202]), ("navegador", [202]),
    ("word", [505]), ("resumo crase", [505]), ("powershell", []), ("sócrates", []),
])
def test_acha_janelas_pelo_nome(nome, ids):
    assert [j["id"] for j in jn.achar_janelas(nome, JANELAS)] == ids


def test_fechar_programa_fecha_so_o_certo(ps):
    assert "Bloco de notas" in jn.fechar_programa("bloco de notas")
    assert "@(101)" in ps[-1] and "CloseMainWindow" in ps[-1]


def test_nunca_fecha_o_terminal_do_socrates(ps):
    assert "Não encontrei" in jn.fechar_programa("PowerShell")
    assert not any("CloseMainWindow" in s for s in ps)


def test_mostrar_janela(ps):
    assert "QConcursos" in jn.mostrar_janela("chrome")
    assert "AppActivate(202)" in ps[-1]


# ---------- área de transferência ----------

def test_le_o_que_foi_copiado(ps):
    assert "Assinale a alternativa correta" in jn.ler_area_de_transferencia()


@pytest.mark.parametrize("texto", [
    "D'Alembert",
    "'; Remove-Item C:\\ -Recurse; '",
    "$(calc.exe) `whoami` \"aspas\"",
])
def test_copiar_texto_nunca_vira_comando(ps, texto):
    jn.copiar_texto(texto)
    script = ps[-1]
    literal = script.removeprefix("Set-Clipboard -Value ")
    assert literal.startswith("'") and literal.endswith("'")
    miolo = literal[1:-1]
    assert miolo.replace("''", "") .count("'") == 0     # toda aspa simples foi dobrada
    assert miolo.replace("''", "'") == texto


def test_powershell_codifica_o_script(monkeypatch):
    chamado = {}

    class R:
        returncode, stdout, stderr = 0, "olá".encode(), b""

    def falso_run(cmd, **kw):
        chamado["cmd"] = cmd
        return R()

    monkeypatch.setattr(jn, "WINDOWS", True)
    monkeypatch.setattr(jn.subprocess, "run", falso_run)
    assert jn._powershell("Get-Clipboard -Raw") == "olá"
    cmd = chamado["cmd"]
    assert cmd[:4] == ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand"]
    script = base64.b64decode(cmd[4]).decode("utf-16-le")
    assert "UTF8" in script and script.endswith("Get-Clipboard -Raw")


def test_fora_do_windows_avisa():
    with pytest.raises(OSError, match="Windows"):
        jn._powershell("Get-Process")


# ---------- bloco de notas ----------

def test_escreve_e_abre_no_bloco_de_notas(tmp_path, monkeypatch):
    abertos = []
    monkeypatch.setattr(jn, "PASTA_NOTAS", tmp_path)
    monkeypatch.setattr(jn, "abrir_no_bloco_de_notas", abertos.append)
    r = jn.escrever_no_bloco_de_notas("Crase = a + a.\nAntes de feminino.", "resumo: crase/../x")
    assert "Bloco de Notas" in r
    arquivo = abertos[0]
    assert arquivo.parent == tmp_path and "/" not in arquivo.name.replace(str(tmp_path), "")
    assert arquivo.read_text(encoding="utf-8").startswith("Crase = a + a.")


# ---------- visão ----------

class ClienteVisao:
    def __init__(self, resposta):
        self.pedidos = []
        self.resposta = resposta
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.pedidos.append(kw)
        msg = type("M", (), {"content": self.resposta})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


def test_descreve_a_tela_com_a_imagem():
    from PIL import Image
    jpeg = tela.preparar(Image.new("RGB", (3000, 1500), "white"))
    cliente = ClienteVisao("<think>vendo...</think>Uma questão de crase com 4 alternativas.")
    texto = tela.descrever(jpeg, "transcreva a questão", cliente)
    assert texto == "Uma questão de crase com 4 alternativas."
    conteudo = cliente.pedidos[0]["messages"][0]["content"]
    assert "transcreva a questão" in conteudo[0]["text"]
    url = conteudo[1]["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    img = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert img.width == tela.LARGURA_MAX           # print grande foi reduzido


def test_ver_tela_sem_chave_explica(monkeypatch):
    from PIL import Image
    monkeypatch.setitem(tela.VISAO, "captura", lambda: tela.preparar(Image.new("RGB", (10, 10))))
    monkeypatch.setitem(tela.VISAO, "chave", None)
    assert "falta a chave" in tela.ver_tela("o que tem aqui?")


# ---------- roteador com as frases reais do log ----------

@pytest.mark.parametrize("frase", [
    "O teste não deu certo, mas vamos fazer o seguinte, fecha o bloco de notas e tenta de novo",
    "Crie uma nota aleatória no bloco de notas.",
    "Escreve um resumo de crase no bloco de notas",
    "O que tem na minha tela?",
    "Resolve a questão que está na tela",
    "Explica o que eu copiei",
    "Quais programas estão abertos?",
    "Fecha o Chrome",
])
def test_frases_do_log_viram_acao(frase):
    assert pede_acao(frase)


@pytest.mark.parametrize("frase", [
    "Escreve a fórmula de Bhaskara no quadro",
    "O que é crase?",
    "Me explica regência verbal",
])
def test_estudo_continua_estudo(frase):
    assert not pede_acao(frase)


def test_legenda_alucinada_e_ignorada():
    from socrates.stt.groq_whisper import filtrar_alucinacao
    assert filtrar_alucinacao("Legenda por Sônia Ruberti") == ""
    assert filtrar_alucinacao("Legendas pela comunidade Amara.org") == ""


def test_caracteres_invisiveis_somem_da_fala():
    from socrates.tts.limpeza import limpar_para_fala
    assert limpar_para_fala("Pronto,\u200b\xa0\xa0 anotei… … …\u202f no caderno.") == \
        "Pronto, anotei... no caderno."
