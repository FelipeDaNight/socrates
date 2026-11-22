"""Falar com o Claude e se atualizar: o Sócrates pede mudanças no próprio código.

  "Sócrates, pede pro Claude deixar a voz mais grave"
     -> vai para a CAIXA DO CLAUDE (melhorias.json, na pasta do Sócrates)
     -> toda noite uma tarefa agendada do Claude lê a caixa, faz o que tiver sentido,
        sobe para o GitHub e deixa um recado, que o Sócrates lê na saudação
  "Sócrates, se atualiza"
     -> confirma por voz -> git pull -> instala o que mudou -> reinicia

Antes ele digitava o pedido no app do Claude. Não dava certo sempre: o app tinha de estar
aberto, na conversa certa, e o texto caía no meio do que o Claude estava fazendo.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading

from ..config import RAIZ
from ..core import memoria
from . import ferramenta

log = logging.getLogger("socrates.claude")

REINICIAR = threading.Event()   # a conversa vê isso e reinicia o Sócrates


@ferramenta("Manda ao Claude (quem programa o Sócrates) um pedido de mudança no Sócrates: o "
            "pedido vai para a caixa do Claude, que ele lê toda noite. Ele faz o que tiver "
            "sentido e deixa um recado, que você lê na saudação. É o único jeito de falar com ele.",
            params={"pedido": "O pedido, claro e completo, com o que o aluno quer"})
def pedir_ao_claude(pedido: str) -> str:
    como, item = memoria.Memorias().para_o_claude(pedido, origem="aluno")
    if como == "vazia":
        return "Qual é o pedido para o Claude?"
    if como == "ja_estava":
        return "Esse pedido já está na caixa do Claude. Ele lê hoje à noite e me deixa um recado."
    if como == "reaberta":
        antes = "tinha feito" if item.get("antes") == "feita" else "tinha analisado"
        return (f"O Claude já {antes} esse pedido; deixei de novo na caixa dele, avisando que "
                "ainda não está bom. Ele vê hoje à noite.")
    return ("Deixei na caixa do Claude. Ele lê toda noite, faz o que tiver sentido e me deixa "
            "um recado; eu te conto quando você me abrir de novo.")


# ---------------- atualizar ----------------

def _git(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=RAIZ, capture_output=True, text=True,
                          timeout=timeout, encoding="utf-8", errors="ignore")


@ferramenta("Baixa a versão nova do Sócrates e reinicia.",
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
