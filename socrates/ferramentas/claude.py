"""Falar com o Claude e se atualizar: o Sócrates pede mudanças no próprio código.

  "Sócrates, pede pro Claude deixar a voz mais grave"
     -> confirma por voz -> traz o app do Claude para a frente -> cola -> Enter
  "Sócrates, se atualiza"
     -> confirma por voz -> git pull -> instala o que mudou -> reinicia

As duas ações só rodam depois de você dizer "sim".
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

from ..config import RAIZ
from . import ferramenta
from .janelas import WINDOWS, _literal, _powershell, listar_janelas

log = logging.getLogger("socrates.claude")

PREFIXO = "[Pedido do Sócrates, por voz] "
ENVIAR_COM_ENTER = True     # main.py ajusta a partir do config.yaml
REINICIAR = threading.Event()   # a conversa vê isso e reinicia o Sócrates


def janela_do_claude(janelas: list[dict]) -> dict | None:
    """O app do Claude para desktop: processo 'claude' com janela de título."""
    candidatas = [j for j in janelas if j.get("processo", "").lower() == "claude"]
    candidatas += [j for j in janelas if j not in candidatas
                   and "claude" in j.get("titulo", "").lower()
                   and j.get("processo", "").lower() in {"chrome", "msedge", "firefox", "brave"}]
    return candidatas[0] if candidatas else None


def script_colar(pid: int, texto: str, enter: bool) -> str:
    """Põe o texto na área de transferência, ativa a janela, cola e (opcional) envia.
    Depois devolve o que o aluno tinha copiado antes."""
    return "\n".join([
        "$antes = Get-Clipboard -Raw -ErrorAction SilentlyContinue",
        f"Set-Clipboard -Value {_literal(texto)}",
        "$ws = New-Object -ComObject WScript.Shell",
        f"if (-not $ws.AppActivate({int(pid)})) {{ Write-Output 'SEM_FOCO'; exit }}",
        "Start-Sleep -Milliseconds 800",
        "$ws.SendKeys('^v')",
        "Start-Sleep -Milliseconds 500",
        "$ws.SendKeys('{ENTER}')" if enter else "",
        "Start-Sleep -Milliseconds 400",
        "if ($antes) { Set-Clipboard -Value $antes }",
        "Write-Output 'OK'",
    ])


def _resumo_pedido(args: dict) -> str:
    return f'mandar para o Claude: "{args.get("pedido", "")}"'


@ferramenta("Manda uma mensagem para o Claude (o assistente que programa o Sócrates), "
            "digitando no app do Claude aberto no computador. Use quando o aluno pedir para "
            "mudar, melhorar ou consertar o próprio Sócrates ('pede pro Claude...', "
            "'manda pro Claude...'). Precisa de confirmação.",
            params={"pedido": "A mensagem para o Claude, clara e completa, em português, "
                              "descrevendo a mudança que o aluno quer no Sócrates"},
            confirmar=True, resumo=_resumo_pedido)
def pedir_ao_claude(pedido: str) -> str:
    if not WINDOWS:
        return "Mandar mensagem para o Claude só funciona no Windows."
    janela = janela_do_claude(listar_janelas())
    if janela is None:
        return ("Não encontrei o app do Claude aberto. Abra o Claude na conversa do "
                "Sócrates e peça de novo.")
    resultado = _powershell(script_colar(janela["id"], PREFIXO + pedido.strip(), ENVIAR_COM_ENTER),
                            timeout=20)
    if "SEM_FOCO" in resultado:
        return ("O Windows não deixou eu trazer o Claude para a frente. Clique uma vez na "
                "janela do Claude e peça de novo.")
    if ENVIAR_COM_ENTER:
        return "Mandei para o Claude. Quando ele terminar, é só dizer: Sócrates, se atualiza."
    return "Colei a mensagem no Claude. Confira e aperte Enter para enviar."


# ---------------- atualizar ----------------

def _git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="ignore")


@ferramenta("Atualiza o Sócrates com a versão mais nova do GitHub (o que o Claude fez) e "
            "reinicia. Use para 'se atualiza', 'atualiza o Sócrates', 'baixa a versão nova'. "
            "Precisa de confirmação.",
            confirmar=True, resumo=lambda a: "baixar a versão nova e reiniciar")
def atualizar_socrates() -> str:
    antes = _git("rev-parse", "HEAD")
    if antes.returncode != 0:
        return "Não consegui ver a versão atual (a pasta do Sócrates não é um repositório git)."
    puxar = _git("pull", "--ff-only")
    if puxar.returncode != 0:
        log.warning("git pull falhou: %s", puxar.stderr)
        detalhe = (puxar.stderr or puxar.stdout).strip().splitlines()
        return ("Não consegui atualizar: o git recusou. Provavelmente algum arquivo do Sócrates "
                "foi editado à mão. Detalhe: " + (detalhe[-1] if detalhe else "desconhecido"))
    depois = _git("rev-parse", "HEAD")
    if depois.stdout.strip() == antes.stdout.strip():
        return "Já estou na versão mais nova. Se o Claude acabou de mexer, espere ele terminar."
    mudou = _git("diff", "--name-only", antes.stdout.strip(), depois.stdout.strip()).stdout
    if "requirements.txt" in mudou:
        pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r",
                              str(RAIZ / "requirements.txt")],
                             capture_output=True, text=True, timeout=900)
        if pip.returncode != 0:
            return "Baixei a versão nova, mas a instalação dos pacotes falhou. Rode o pip à mão."
    log_novo = _git("log", "--format=%s", f"{antes.stdout.strip()}..{depois.stdout.strip()}")
    novidades = "; ".join(log_novo.stdout.strip().splitlines()[:3])
    REINICIAR.set()
    return f"Atualizei ({novidades}). Vou reiniciar agora."
