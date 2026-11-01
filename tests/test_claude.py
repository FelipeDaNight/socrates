"""Confirmação por voz, pedir ao Claude, se atualizar e config.local.yaml."""

import asyncio
import subprocess

import pytest

from socrates import ferramentas
from socrates.config import carregar, mesclar
from socrates.ferramentas import claude
from socrates.ferramentas import janelas as jn
from socrates.llm.acoes import pede_acao


@pytest.fixture(autouse=True)
def limpo():
    ferramentas.PENDENTE = None
    claude.REINICIAR.clear()
    yield
    ferramentas.PENDENTE = None
    claude.REINICIAR.clear()


JANELAS = [{"processo": "notepad", "titulo": "Sem título - Bloco de notas", "id": 1},
           {"processo": "claude", "titulo": "Claude", "id": 77}]


# ---------- confirmação ----------

def test_acao_sensivel_espera_o_sim(monkeypatch):
    chamadas = []
    monkeypatch.setattr(claude, "WINDOWS", True)
    monkeypatch.setattr(claude, "listar_janelas", lambda: JANELAS)
    monkeypatch.setattr(claude, "_powershell", lambda s, timeout=15: chamadas.append(s) or "OK")

    r = ferramentas.executar("pedir_ao_claude", {"pedido": "Deixe a voz mais grave."})
    assert "AGUARDANDO CONFIRMAÇÃO" in r and 'Claude: "Deixe a voz mais grave."' in r
    assert chamadas == []                                   # nada foi digitado ainda

    r = ferramentas.resolver_confirmacao("Sim, pode mandar!")
    assert "Mandei para o Claude" in r
    script = chamadas[0]
    assert "AppActivate(77)" in script and "^v" in script and "{ENTER}" in script
    assert "[Pedido do Sócrates, por voz] Deixe a voz mais grave." in script
    assert ferramentas.PENDENTE is None


def test_nao_cancela(monkeypatch):
    monkeypatch.setattr(claude, "_powershell", lambda *a, **k: pytest.fail("não podia digitar"))
    ferramentas.executar("pedir_ao_claude", {"pedido": "x"})
    assert ferramentas.resolver_confirmacao("Não, cancela.") == "Tudo bem, cancelei."


def test_mudar_de_assunto_descarta(monkeypatch):
    monkeypatch.setattr(claude, "_powershell", lambda *a, **k: pytest.fail("não podia digitar"))
    ferramentas.executar("pedir_ao_claude", {"pedido": "x"})
    assert ferramentas.resolver_confirmacao("O que é crase?") is None
    assert ferramentas.PENDENTE is None
    assert ferramentas.resolver_confirmacao("sim") is None   # o "sim" atrasado não vale mais


def test_confirmacao_expira(monkeypatch):
    ferramentas.executar("pedir_ao_claude", {"pedido": "x"})
    ferramentas.PENDENTE.criado -= ferramentas.VALIDADE_SEG + 1
    assert ferramentas.resolver_confirmacao("sim") is None


@pytest.mark.parametrize("fala,esperado", [
    ("Sim.", True), ("Pode mandar.", True), ("Isso mesmo, Sócrates", True), ("Manda!", True),
    ("Não.", False), ("Cancela", False), ("Não manda não", False),
    ("Sim, mas muda o texto", None), ("Por favor", None), ("Qual a capital do Brasil?", None),
])
def test_entende_sim_e_nao(fala, esperado):
    assert ferramentas._concorda(ferramentas._norm(fala)) is esperado


# ---------- digitar no Claude ----------

def test_acha_o_app_do_claude():
    assert claude.janela_do_claude(JANELAS)["id"] == 77
    web = [{"processo": "chrome", "titulo": "Sócrates - Claude - Google Chrome", "id": 9}]
    assert claude.janela_do_claude(web)["id"] == 9
    assert claude.janela_do_claude(JANELAS[:1]) is None


def test_texto_do_pedido_nunca_vira_comando():
    script = claude.script_colar(77, "'; Remove-Item C:\\ -Recurse; '", True)
    linha = next(l for l in script.splitlines() if l.startswith("Set-Clipboard -Value '"))
    miolo = linha.removeprefix("Set-Clipboard -Value ")[1:-1]
    assert miolo.replace("''", "").count("'") == 0


def test_sem_enter_so_cola():
    assert "{ENTER}" not in claude.script_colar(77, "oi", False)


def test_devolve_o_que_estava_copiado():
    script = claude.script_colar(77, "oi", True)
    assert script.index("$antes = Get-Clipboard") < script.index("Set-Clipboard -Value 'oi'")
    assert "Set-Clipboard -Value $antes" in script


def test_sem_claude_aberto_explica(monkeypatch):
    monkeypatch.setattr(claude, "WINDOWS", True)
    monkeypatch.setattr(claude, "listar_janelas", lambda: JANELAS[:1])
    assert "Não encontrei o app do Claude" in ferramentas.executar(
        "pedir_ao_claude", {"pedido": "x"}, confirmado=True)


def test_janela_sem_foco_explica(monkeypatch):
    monkeypatch.setattr(claude, "WINDOWS", True)
    monkeypatch.setattr(claude, "listar_janelas", lambda: JANELAS)
    monkeypatch.setattr(claude, "_powershell", lambda s, timeout=15: "SEM_FOCO")
    assert "Clique uma vez" in claude.pedir_ao_claude("x")


def test_claude_nunca_e_fechado():
    assert jn.achar_janelas("claude", JANELAS) == []


# ---------- se atualizar (com um repositório git de verdade) ----------

def _git(pasta, *args):
    subprocess.run(["git", *args], cwd=pasta, check=True, capture_output=True)


@pytest.fixture
def repos(tmp_path, monkeypatch):
    origem, local = tmp_path / "origem", tmp_path / "local"
    origem.mkdir()
    _git(origem, "init", "-q", "-b", "main")
    _git(origem, "config", "user.email", "t@t")
    _git(origem, "config", "user.name", "t")
    (origem / "a.txt").write_text("v1")
    _git(origem, "add", ".")
    _git(origem, "commit", "-q", "-m", "v1")
    _git(tmp_path, "clone", "-q", str(origem), str(local))
    monkeypatch.setattr(claude, "RAIZ", local)
    return origem, local


def test_ja_atualizado(repos):
    assert "Já estou na versão mais nova" in claude.atualizar_socrates()
    assert not claude.REINICIAR.is_set()


def test_atualiza_e_pede_reinicio(repos):
    origem, local = repos
    (origem / "a.txt").write_text("v2")
    _git(origem, "commit", "-qam", "Voz mais grave")
    r = claude.atualizar_socrates()
    assert "Atualizei (Voz mais grave)" in r and claude.REINICIAR.is_set()
    assert (local / "a.txt").read_text() == "v2"


def test_atualizacao_com_arquivo_editado_explica(repos):
    origem, local = repos
    (origem / "a.txt").write_text("v2")
    _git(origem, "commit", "-qam", "v2")
    (local / "a.txt").write_text("mexi à mão")
    r = claude.atualizar_socrates()
    assert "git recusou" in r and not claude.REINICIAR.is_set()


@pytest.mark.parametrize("frase", [
    "Pede pro Claude deixar a voz mais grave",
    "Manda pro Cláudio melhorar o quadro",
    "Sócrates, se atualiza",
    "Atualiza o Sócrates",
])
def test_frases_do_claude_sao_acao(frase):
    assert pede_acao(frase)


# ---------- conversa: "sim" resolve antes do cérebro ----------

@pytest.mark.asyncio
async def test_conversa_resolve_o_sim_sem_chamar_o_cerebro(monkeypatch):
    from test_maos_livres import _montar, _rodar
    conversa, s, painel, cerebro, tela = _montar()
    feitos = []
    monkeypatch.setitem(ferramentas.REGISTRO["pedir_ao_claude"].__dict__, "funcao",
                        lambda pedido: feitos.append(pedido) or "Mandei para o Claude.")
    ferramentas.executar("pedir_ao_claude", {"pedido": "Quadro maior"})
    painel.abrir_janela(30)
    await _rodar(conversa, [s.ouvido.fala("Sim, pode mandar.")], espera_entre=0.5)
    assert feitos == ["Quadro maior"]
    assert cerebro.recebido == []
    assert "Mandei para o Claude." in s.voz.faladas


@pytest.mark.asyncio
async def test_conversa_encerra_para_reiniciar(monkeypatch):
    from test_maos_livres import _montar
    conversa, s, painel, cerebro, tela = _montar()
    monkeypatch.setitem(ferramentas.REGISTRO["atualizar_socrates"].__dict__, "funcao",
                        lambda: claude.REINICIAR.set() or "Atualizei. Vou reiniciar agora.")
    ferramentas.executar("atualizar_socrates", {})
    painel.abrir_janela(30)
    fila = asyncio.Queue()
    fila.put_nowait(s.ouvido.fala("Pode atualizar"))
    await asyncio.wait_for(conversa.rodar(fila), 5)    # sai sozinho, sem precisar de /sair
    assert s.voz.faladas[-2:] == ["Atualizei. Vou reiniciar agora.", "Até já, volto atualizado."]


# ---------- config.local.yaml ----------

def test_mesclar_por_secao():
    base = {"voz": {"nome": "Antonio", "velocidade": "+5%"}, "local": "Morrinhos"}
    assert mesclar(base, {"voz": {"velocidade": "-8%"}}) == \
        {"voz": {"nome": "Antonio", "velocidade": "-8%"}, "local": "Morrinhos"}


def test_config_local_vale_por_cima(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "k")
    (tmp_path / "config.yaml").write_text(
        "llm: {provedor: groq}\nprovedores: {groq: {base_url: x, chave_env: GROQ_API_KEY, modelo: m}}\n"
        "voz: {nome: pt-BR-AntonioNeural, tom: '+0Hz'}\n", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text("voz: {tom: '-8Hz'}\n", encoding="utf-8")
    cfg = carregar(tmp_path / "config.yaml")
    assert cfg.voz.tom == "-8Hz" and cfg.voz.nome == "pt-BR-AntonioNeural"
