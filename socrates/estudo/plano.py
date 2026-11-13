"""O mapa dos editais (planos/*.json): matérias, tópicos, peso na prova e de onde vem
o conteúdo (artigos da lei ou uma pesquisa). É o que o autoestudo percorre.

  prf.json     Policial Rodoviário Federal (Cebraspe), conteúdo do edital de 2021
  cbmgo.json   Soldado do Corpo de Bombeiros de Goiás (AOCP), edital 004/2022
  leis.json    sigla da lei -> nome e endereço oficial (Planalto)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .respostas import norm

PASTA = Path(__file__).parent / "planos"

_VAZIAS = {"de", "da", "do", "das", "dos", "e", "a", "o", "as", "os", "em", "no", "na", "nos", "nas",
           "para", "por", "com", "sem", "um", "uma", "ao", "aos", "lei", "crimes", "crime", "direito",
           "nocoes", "regras", "gerais", "conceito", "art", "arts", "ctb", "cf", "sua", "seu"}


@dataclass
class TopicoPlano:
    id: str
    titulo: str
    edital: str
    peso: int
    fontes: list[str]
    pesquisa: str
    materia: "MateriaPlano" = field(repr=False, default=None)

    @property
    def chave(self) -> str:
        return f"{self.materia.trilha}:{self.id}"

    def termos(self) -> set[str]:
        """Palavras fortes do título, para achar o tópico na fala do aluno."""
        return {p for p in norm(self.titulo).split() if len(p) >= 4 and p not in _VAZIAS}


@dataclass
class MateriaPlano:
    id: str
    trilha: str
    materia: str
    bloco: str
    peso: int
    apelidos: list[str]
    nao_confundir: list[str]
    topicos: list[TopicoPlano]
    plano: "Plano" = field(repr=False, default=None)


@dataclass
class Plano:
    id: str
    concurso: str
    cargo: str
    banca: str
    edital: str
    materias: list[MateriaPlano]

    @classmethod
    def ler(cls, caminho: Path) -> "Plano":
        d = json.loads(caminho.read_text(encoding="utf-8"))
        plano = cls(d["id"], d.get("concurso", ""), d.get("cargo", ""), d.get("banca", ""),
                    d.get("edital", ""), [])
        for m in d.get("materias", []):
            mat = MateriaPlano(m["id"], m["trilha"], m["materia"], m.get("bloco", ""),
                               int(m.get("peso") or 1), list(m.get("apelidos", [])),
                               list(m.get("nao_confundir", [])), [], plano)
            for t in m.get("topicos", []):
                mat.topicos.append(TopicoPlano(t["id"], t["titulo"], t.get("edital", ""),
                                               int(t.get("peso") or 1), list(t.get("fontes", [])),
                                               t.get("pesquisa", ""), mat))
            plano.materias.append(mat)
        return plano

    def materia(self, mid: str) -> MateriaPlano | None:
        return next((m for m in self.materias if m.id == mid or m.trilha == mid), None)


def carregar_planos(pasta: Path | None = None, ids: list[str] | None = None) -> list[Plano]:
    """Os planos na ordem pedida (o primeiro tem prioridade no autoestudo)."""
    pasta = pasta or PASTA
    todos = {p.stem: p for p in pasta.glob("*.json") if p.stem != "leis"}
    ordem = ids or sorted(todos)
    return [Plano.ler(todos[i]) for i in ordem if i in todos]


def carregar_leis(pasta: Path | None = None) -> dict[str, dict]:
    d = json.loads(((pasta or PASTA) / "leis.json").read_text(encoding="utf-8"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def achar_topico(planos: list[Plano], texto: str) -> TopicoPlano | None:
    """O tópico do edital de que a fala trata ("aprende sobre crimes ambientais")."""
    t = f" {norm(texto)} "
    melhor, nota_melhor = None, 0.0
    for plano in planos:
        for m in plano.materias:
            materia_citada = any(f" {norm(a)} " in t for a in m.apelidos)
            for top in m.topicos:
                termos = top.termos()
                if not termos:
                    continue
                achados = sum(1 for p in termos if f" {p} " in t or f" {p[:-1]} " in t)
                if not achados:
                    continue
                nota = achados / len(termos) + 0.5 * achados + (0.3 if materia_citada else 0)
                if nota > nota_melhor:
                    melhor, nota_melhor = top, nota
    return melhor if nota_melhor >= 0.9 else None


def achar_materia(planos: list[Plano], texto: str) -> MateriaPlano | None:
    t = f" {norm(texto)} "
    for plano in planos:
        for m in plano.materias:
            if any(f" {norm(a)} " in t for a in sorted(m.apelidos, key=len, reverse=True)):
                return m
    return None
