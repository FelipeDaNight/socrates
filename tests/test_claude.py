"""Confirmação por voz, a caixa do Claude, se atualizar e config.local.yaml."""

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


@pytest.fixture
def atualizar_falso(monkeypatch):
    """A ação que ainda pede confirmação (se atualizar), sem rodar o git de verdade."""
    feitos = []
    monkeypatch.setitem(ferramentas.REGISTRO["atualizar_socrates"].__dict__, "funcao",
                        lambda: feitos.append("atualizou") or "Atualizei (x). Vou reiniciar agora.")
    return feitos


# ---------- confirmação ----------

def test_acao_sensivel_espera_o_sim(atualizar_falso):
    r = ferramentas.executar("atualizar_socrates", {})
    assert "AGUARDANDO CONFIRMAÇÃO" in r and "baixar a versão nova e reiniciar" in r
    assert atualizar_falso == []                            # nada foi feito ainda

    r = ferramentas.resolver_confirmacao("Sim, pode atualizar!")
    assert "Atualizei" in r and atualizar_falso == ["atualizou"]
    assert ferramentas.PENDENTE is None


def test_nao_cancela(atualizar_falso):
    ferramentas.executar("atualizar_socrates", {})
    assert ferramentas.resolver_confirmacao("Não, cancela.") == "Tudo bem, cancelei."
    assert atualizar_falso == []


def test_mudar_de_assunto_descarta(atualizar_falso):
    ferramentas.executar("atualizar_socrates", {})
    assert ferramentas.resolver_confirmacao("O que é crase?") is None
    assert ferramentas.PENDENTE is None
    assert ferramentas.resolver_confirmacao("sim") is None   # o "sim" atrasado não vale mais
    assert atualizar_falso == []


def test_confirmacao_expira(atualizar_falso):
    ferramentas.executar("atualizar_socrates", {})
    ferramentas.PENDENTE.criado -= ferramentas.VALIDADE_SEG + 1
    assert ferramentas.resolver_confirmacao("sim") is None


@pytest.mark.parametrize("fala,esperado", [
    ("Sim.", True), ("Pode mandar.", True), ("Isso mesmo, Sócrates", True), ("Manda!", True),
    ("Não.", False), ("Cancela", False), ("Não manda não", False),
    ("Sim, mas muda o texto", None), ("Por favor", None), ("Qual a capital do Brasil?", None),
])
def test_entende_sim_e_nao(fala, esperado):
    assert ferramentas._concorda(ferramentas._norm(fala)) is esperado


# ---------- a caixa do Claude (22/11: digitar no app dele falhava) ----------

@pytest.fixture
def caixa(tmp_path, monkeypatch):
    import socrates.core.memoria as mem
    monkeypatch.setattr(mem, "PASTA", tmp_path)
    return mem.Memorias(tmp_path)


def test_pedido_vai_para_a_caixa_sem_digitar_nem_confirmar(caixa, monkeypatch):
    import socrates.ferramentas.janelas as jan
    monkeypatch.setattr(jan, "_powershell", lambda *a, **k: pytest.fail("não podia mexer no PC"))
    r = ferramentas.executar("pedir_ao_claude", {"pedido": "Deixe a voz mais grave."})
    assert "AGUARDANDO" not in r and "caixa do Claude" in r and "toda noite" in r
    assert ferramentas.PENDENTE is None
    [item] = caixa.melhorias.itens()
    assert item["t"] == "Deixe a voz mais grave." and item["status"] == "nova"
    assert item["origem"] == "aluno"


def test_pedido_repetido_nao_duplica(caixa):
    claude.pedir_ao_claude("Deixe a voz mais grave")
    r = claude.pedir_ao_claude("deixe a voz mais grave.")
    assert "já está na caixa" in r and len(caixa.melhorias.itens()) == 1


def test_aluno_pede_de_novo_o_que_o_claude_ja_fez_reabre(caixa):
    caixa.melhorias.adicionar("Deixe a voz mais grave", status="feita", origem="aluno",
                              resposta="Tom -8Hz no config.yaml")
    r = claude.pedir_ao_claude("Deixe a voz mais grave")
    assert "deixei de novo na caixa" in r
    [item] = caixa.melhorias.itens()
    assert item["status"] == "nova" and item["antes"] == "feita" and item["de_novo"] is True
    assert caixa.melhorias_pendentes() == [item]


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
async def test_conversa_resolve_o_sim_sem_chamar_o_cerebro(atualizar_falso):
    from test_maos_livres import _montar, _rodar
    conversa, s, painel, cerebro, tela = _montar()
    ferramentas.executar("atualizar_socrates", {})
    painel.abrir_janela(30)
    await _rodar(conversa, [s.ouvido.fala("Sim, pode atualizar.")], espera_entre=0.5)
    assert atualizar_falso == ["atualizou"]
    assert cerebro.recebido == []
    assert "Atualizei (x). Vou reiniciar agora." in s.voz.faladas


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
