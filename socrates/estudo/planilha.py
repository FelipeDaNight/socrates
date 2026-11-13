"""Manda os registros para a SUA planilha do Google, pelo mesmo Apps Script do app.

Usa o mesmo endereço (/exec) e a mesma chave que você colocou no app do iPhone.
Os registros caem nas mesmas abas: Horas (pomodoro), Questões, Erros e Simulados.
Sem internet, ficam guardados em Documentos\\Socrates\\fila_planilha.json e vão depois.

Configurar (uma vez):
    config.local.yaml:   planilha:
                           url: https://script.google.com/macros/s/.../exec
    .env:                PLANILHA_CHAVE=a mesma chave do app
"""

from __future__ import annotations

import difflib
import json
import logging
import threading
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from .respostas import norm

log = logging.getLogger("socrates.planilha")

ARQUIVO_FILA = Path.home() / "Documents" / "Socrates" / "fila_planilha.json"
LOTE = 40


def _http(url: str, corpo: dict | None = None, timeout: float = 30) -> dict:
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, method="POST" if corpo is not None else "GET",
                                 headers={"Content-Type": "text/plain;charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:   # segue o redirecionamento do Google
        return json.loads(r.read().decode("utf-8"))


class Planilha:
    def __init__(self, url: str | None, chave: str | None, arquivo: Path | None = None,
                 http=_http):
        self.url = (url or "").strip()
        self.chave = (chave or "").strip()
        self.arquivo = arquivo or ARQUIVO_FILA
        self.http = http
        self._trava = threading.Lock()
        self._materias: list[str] | None = None
        self.fila: list[dict] = []
        if self.arquivo.exists():
            try:
                self.fila = json.loads(self.arquivo.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                self.fila = []

    @property
    def ativa(self) -> bool:
        return bool(self.url and self.chave)

    def _salvar(self) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        self.arquivo.write_text(json.dumps(self.fila, ensure_ascii=False), encoding="utf-8")

    def enviar(self, tipo: str, dados: dict, agora: bool = False) -> None:
        """Entra na fila e é enviado em segundo plano (não trava a conversa)."""
        if not self.ativa:
            return
        with self._trava:
            self.fila.append({"id": "s" + uuid.uuid4().hex[:16], "tipo": tipo, "dados": dados})
            self._salvar()
        if agora:
            self.sincronizar()
        else:
            threading.Thread(target=self.sincronizar, name="planilha", daemon=True).start()

    def sincronizar(self) -> str:
        if not self.ativa:
            return "Planilha não configurada."
        with self._trava:
            lote = [i for i in self.fila if not i.get("erro")][:LOTE]
            if not lote:
                return "Nada para enviar."
            try:
                r = self.http(self.url, {"token": self.chave, "itens": [
                    {"id": i["id"], "tipo": i["tipo"], "dados": i["dados"]} for i in lote]})
            except Exception as e:
                log.warning("planilha fora do ar: %s (fica na fila)", e)
                return f"Sem conexão com a planilha; {len(self.fila)} registro(s) guardado(s)."
            if not r.get("ok"):
                log.warning("planilha recusou: %s", r)
                return f"A planilha recusou: {r.get('erro', 'motivo desconhecido')}."
            gravados = set(r.get("gravados", []))
            falhas = {f["id"]: f.get("erro", "") for f in r.get("falhas", [])}
            self.fila = [i for i in self.fila if i["id"] not in gravados]
            for i in self.fila:
                if i["id"] in falhas:
                    i["erro"] = falhas[i["id"]]
            self._salvar()
            log.info("planilha: %d gravado(s), %d falha(s)", len(gravados), len(falhas))
            return f"Enviei {len(gravados)} registro(s) para a planilha."

    # ---------- nomes das matérias iguais aos da planilha ----------
    def materias(self) -> list[str]:
        if self._materias is None:
            self._materias = []
            if self.ativa:
                try:
                    sep = "&" if "?" in self.url else "?"
                    r = self.http(self.url + sep + "token=" + urllib.parse.quote(self.chave))
                    self._materias = (r.get("listas") or {}).get("materias") or []
                except Exception as e:
                    log.warning("não consegui ler as matérias da planilha: %s", e)
        return self._materias

    def nome_da_materia(self, falada: str) -> str:
        """"português" -> "Língua Portuguesa", como está na aba Ajustes (para o SOMASES)."""
        lista = self.materias()
        if not lista or not falada:
            return falada
        alvo = norm(falada)
        for m in lista:
            if alvo and (alvo in norm(m) or norm(m) in alvo):
                return m
        parecidas = difflib.get_close_matches(alvo, [norm(m) for m in lista], n=1, cutoff=0.6)
        if parecidas:
            return lista[[norm(m) for m in lista].index(parecidas[0])]
        return falada
