"""Trilha de estudo: o mapa do edital de uma matéria, com conteúdo conferido.

Uma trilha (socrates/estudo/trilhas/*.json) tem os tópicos do edital, e cada tópico tem:
  pontos       o que é preciso saber, com os artigos (base das aulas e das respostas)
  pegadinhas   como a banca costuma cobrar
  novidades    leis recentes que os modelos de IA ainda não conhecem
  itens        itens de fixação estilo banca, com gabarito e justificativa
  questoes     questões de prova reais do banco ligadas ao tópico ("prf-2021-p1|item 103")
  artigos      faixas de artigos ("CP 155-183"), para ligar as lacunas da lei seca ao tópico

É esse conteúdo que faz o Sócrates "saber" a matéria: o cérebro recebe as notas do
tópico junto com a pergunta e é instruído a não contradizê-las.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .respostas import norm
from .treino import Item, _quadro_seguro, item_de_questao

PASTA = Path(__file__).parent / "trilhas"

# "direito penal", "código penal", "penal" (mas não "processo penal")
_MATERIA = {
    "prf-penal": re.compile(r"\b(direito penal|codigo penal|penal)\b"),
}
_NAO_E = re.compile(r"\b(processo penal|processual penal|lei de execucao penal|execucao penal)\b")
_FAIXA = re.compile(r"^(CP|CPP|CTB|L14133)\s+(\d+)(?:-([A-Z]))?(?:-(\d+)(?:-([A-Z]))?)?$")
_ROTULO = re.compile(r"Art\.\s*(\d+)\s*º?(?:-([A-Z]))?")


@dataclass
class Topico:
    id: str
    bloco: str
    titulo: str
    edital: str
    peso: int
    artigos: list[str]
    palavras: list[str]
    pontos: list[str]
    pegadinhas: list[str]
    novidades: list[str]
    itens: list[dict]
    questoes: list[str]
    ordem: int = 0
    chaves: list[str] = field(default_factory=list)   # palavras normalizadas

    def faixas(self) -> list[tuple[str, tuple[int, str], tuple[int, str]]]:
        saida = []
        for a in self.artigos:
            m = _FAIXA.match(a.strip())
            if not m:
                continue
            lei, ini, s_ini, fim, s_fim = m.groups()
            inicio = (int(ini), s_ini or "")
            if fim:
                final = (int(fim), s_fim or "Z")
            else:
                final = (int(ini), s_ini or "Z")
            saida.append((lei, inicio, final))
        return saida

    def tem_artigo(self, lei: str, numero: tuple[int, str]) -> bool:
        return any(lei == l and ini <= numero <= fim for l, ini, fim in self.faixas())


@dataclass
class Trilha:
    id: str
    materia: str
    concurso: str
    banca: str
    fonte: str
    atualizado: str
    topicos: list[Topico]

    # ---------- carregar ----------
    @classmethod
    def ler(cls, caminho: Path) -> "Trilha":
        d = json.loads(caminho.read_text(encoding="utf-8"))
        topicos = []
        for i, t in enumerate(d["topicos"]):
            topico = Topico(
                id=t["id"], bloco=t.get("bloco", ""), titulo=t["titulo"], edital=t.get("edital", ""),
                peso=int(t.get("peso") or 1), artigos=t.get("artigos", []),
                palavras=t.get("palavras", []), pontos=t.get("pontos", []),
                pegadinhas=t.get("pegadinhas", []), novidades=t.get("novidades", []),
                itens=t.get("itens", []), questoes=t.get("questoes", []), ordem=i)
            topico.chaves = sorted({norm(p) for p in topico.palavras + [topico.titulo] if norm(p)},
                                   key=len, reverse=True)
            topicos.append(topico)
        return cls(d["id"], d["materia"], d.get("concurso", ""), d.get("banca", ""),
                   d.get("fonte", ""), d.get("atualizado", ""), topicos)

    def topico(self, tid: str) -> Topico | None:
        return next((t for t in self.topicos if t.id == tid), None)

    # ---------- entender a fala ----------
    def menciona_materia(self, texto: str) -> bool:
        t = norm(texto)
        rx = _MATERIA.get(self.id)
        return bool(rx and rx.search(_NAO_E.sub(" ", t)))

    def achar(self, texto: str) -> list[tuple[int, Topico]]:
        """Tópicos citados na fala, do mais provável para o menos. Expressão mais
        longa vale mais ("legítima defesa putativa" é erro de tipo, não ilicitude)."""
        t = f" {norm(texto)} "
        notas = []
        for top in self.topicos:
            usado, nota = t, 0
            for chave in top.chaves:
                if f" {chave} " in usado:
                    nota += len(chave.split())
                    usado = usado.replace(f" {chave} ", " ")
            if nota:
                notas.append((nota, top))
        notas.sort(key=lambda x: (-x[0], x[1].ordem))
        return notas

    def topico_citado(self, texto: str) -> Topico | None:
        achados = self.achar(texto)
        return achados[0][1] if achados else None

    # ---------- itens ----------
    def id_item(self, topico: Topico, n: int) -> str:
        return f"trilha:{self.id}:{topico.id}:{n}"

    def itens_de_fixacao(self, topico: Topico) -> list[Item]:
        saida = []
        for n, it in enumerate(topico.itens, 1):
            frase = it["t"].strip()
            saida.append(Item(
                id=self.id_item(topico, n), tipo="ce", materia=self.materia, topico=topico.titulo,
                fonte=f"Trilha {self.concurso} · {topico.titulo}", resp=it["r"].strip().upper()[:1],
                fala=f"{frase} Certo ou errado?",
                quadro=_quadro_seguro(f"# {topico.titulo} · item {n}\n{frase}\n\nCerto ou errado?"),
                completo=frase, just=it.get("j", ""), letras="CE", real=False))
        return saida

    def questoes_reais(self, topico: Topico, bancos: dict) -> list[Item]:
        saida = []
        for ref in topico.questoes:
            banco_id, _, rotulo = ref.partition("|")
            banco = bancos.get(banco_id)
            if not banco:
                continue
            alvo = norm(rotulo)
            for q in banco.get("questoes", []):
                if norm(str(q.get("topico", ""))).endswith(alvo) or norm(f"q{q.get('n')}") == alvo:
                    item = item_de_questao(banco, q)
                    if item:
                        saida.append(item)
                    break
        return saida

    def itens_do_topico(self, topico: Topico, bancos: dict) -> list[Item]:
        return self.questoes_reais(topico, bancos) + self.itens_de_fixacao(topico)

    def ids_do_topico(self, topico: Topico, bancos: dict, lacunas: list[Item] = ()) -> set[str]:
        """Tudo que mede o domínio do tópico: itens da trilha, questões reais ligadas
        a ele e as lacunas dos artigos dele."""
        ids = {i.id for i in self.itens_do_topico(topico, bancos)}
        for lac in lacunas:
            partes = lac.id.split(":")       # lei:<bloco>:<Art. 1º>:<i>
            if len(partes) < 4:
                continue
            m = _ROTULO.match(partes[2])
            lei = getattr(lac, "lei", "") or ""
            if m and lei and topico.tem_artigo(lei, (int(m.group(1)), m.group(2) or "")):
                ids.add(lac.id)
        return ids

    # ---------- notas para o cérebro ----------
    def notas(self, pergunta: str, limite: int = 1600) -> tuple[str, list[Topico]]:
        """As notas conferidas dos tópicos ligados à pergunta. É o que impede o
        modelo de responder com pena antiga ou de inventar artigo."""
        achados = self.achar(pergunta)
        if not achados:
            return "", []
        topicos = [t for _, t in achados[:2]]
        palavras = {p for p in norm(pergunta).split() if len(p) >= 4}
        partes = []
        for top in topicos:
            def relevantes(lista: list[str]) -> list[str]:
                """Palavra rara no tópico vale mais ("roubo" > "pena")."""
                conjuntos = [set(norm(x).split()) for x in lista]
                df = {p: sum(1 for c in conjuntos if p in c) for p in palavras}
                notas = [(sum(1 / df[p] for p in palavras if df[p] and p in c), i)
                         for i, c in enumerate(conjuntos)]
                notas.sort(key=lambda n: (-n[0], n[1]))
                return [lista[i] for _, i in notas]
            escolhidos = relevantes(top.pontos)[:4]
            bloco = [f"[{top.titulo}]"] + [f"- {p}" for p in escolhidos]
            bloco += [f"- Atualização: {n}" for n in top.novidades[:2]]
            bloco += [f"- Pegadinha da banca: {p}" for p in relevantes(top.pegadinhas)[:1]]
            partes.append("\n".join(bloco))
        texto = "\n".join(partes)
        if len(texto) > limite:
            texto = texto[:limite].rsplit("\n", 1)[0]
        cabeca = (f"Notas CONFERIDAS da trilha de {self.materia} ({self.concurso}, banca {self.banca}; "
                  f"leis atualizadas até {self.atualizado[:4]}). Baseie a resposta nelas, cite os artigos "
                  "e NÃO contradiga as penas e as regras daqui, mesmo que você se lembre de outra "
                  "versão (a lei mudou). Se a pergunta for além das notas, responda o que tiver certeza "
                  "e avise quando não tiver:")
        return f"{cabeca}\n{texto}", topicos


def carregar_trilhas(pasta: Path | None = None) -> list[Trilha]:
    pasta = pasta or PASTA
    return [Trilha.ler(p) for p in sorted(pasta.glob("*.json"))]
