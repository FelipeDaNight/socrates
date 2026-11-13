"""Caderno do aluno: o que ele errou, quando revisar, e o histórico de estudo.

Fica em Documentos\\Socrates\\caderno.json. Revisão espaçada igual à do app
(caixas de Leitner): acertou, sobe de caixa e a próxima revisão fica mais longe;
errou, volta para a caixa 0 e revisa amanhã.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger("socrates.caderno")

INTERVALOS = [1, 3, 7, 15, 30, 60]          # dias até a próxima revisão, por caixa
ARQUIVO = Path.home() / "Documents" / "Socrates" / "caderno.json"


def hoje() -> date:
    from ..core.contexto import agora
    return agora().date()


class Caderno:
    def __init__(self, arquivo: Path | None = None, relogio=hoje):
        self.arquivo = arquivo or ARQUIVO
        self.relogio = relogio
        self._trava = threading.Lock()
        self.dados = {"itens": {}, "sessoes": [], "estudo": []}
        if self.arquivo.exists():
            try:
                lido = json.loads(self.arquivo.read_text(encoding="utf-8"))
                self.dados.update({k: lido.get(k, v) for k, v in self.dados.items()})
            except (OSError, json.JSONDecodeError) as e:
                log.warning("caderno ilegível (%s); começando outro", e)

    def salvar(self) -> None:
        with self._trava:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.arquivo.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.dados, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.arquivo)

    # ---------- itens (questões e lacunas) ----------
    @property
    def itens(self) -> dict:
        return self.dados["itens"]

    def registrar(self, item_id: str, acertou: bool, info: dict | None = None) -> dict:
        """Anota a resposta e calcula a próxima revisão."""
        h = self.relogio()
        it = self.itens.setdefault(item_id, {"caixa": 0, "acertos": 0, "erros": 0})
        if info:
            it.update(info)
        if acertou:
            it["acertos"] += 1
            # quem nunca errou e acertou de primeira não precisa ir para a revisão
            if it["erros"] == 0 and it.get("prox") is None:
                it["caixa"] = len(INTERVALOS)
                it["prox"] = None
            else:
                it["caixa"] = min(it["caixa"] + 1, len(INTERVALOS) - 1)
                it["prox"] = (h + timedelta(days=INTERVALOS[it["caixa"]])).isoformat()
        else:
            it["erros"] += 1
            it["caixa"] = 0
            it["prox"] = (h + timedelta(days=INTERVALOS[0])).isoformat()
        it["ultima"] = h.isoformat()
        it["ok"] = acertou
        return it

    def vencidos(self, prefixo: str = "") -> list[str]:
        h = self.relogio().isoformat()
        venc = [(it["prox"], i) for i, it in self.itens.items()
                if i.startswith(prefixo) and it.get("prox") and it["prox"] <= h]
        return [i for _, i in sorted(venc)]

    def visto(self, item_id: str) -> bool:
        return item_id in self.itens

    # ---------- histórico ----------
    def anotar_sessao(self, sessao: dict) -> None:
        sessao = {"data": self.relogio().isoformat(), **sessao}
        self.dados["sessoes"].append(sessao)
        self.dados["sessoes"] = self.dados["sessoes"][-400:]

    def anotar_estudo(self, materia: str, minutos: float) -> None:
        self.dados["estudo"].append({"data": self.relogio().isoformat(), "materia": materia,
                                     "minutos": round(minutos, 1)})
        self.dados["estudo"] = self.dados["estudo"][-2000:]

    def desde(self, dias: int) -> tuple[list[dict], list[dict]]:
        corte = (self.relogio() - timedelta(days=dias - 1)).isoformat()
        return ([s for s in self.dados["sessoes"] if s["data"] >= corte],
                [e for e in self.dados["estudo"] if e["data"] >= corte])
