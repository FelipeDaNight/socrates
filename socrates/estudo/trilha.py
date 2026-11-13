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

Há dois tipos de tópico:
  conferido   escrito e conferido nas fontes oficiais (as trilhas que vêm com o Sócrates)
  auto        o próprio Sócrates estudou sozinho (autoestudo) a partir da lei e da internet,
              com uma segunda conferência por outro modelo. Fica em Documentos\\Socrates\\trilhas
              e completa as trilhas que vêm com ele (o conferido sempre vale mais).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

from .respostas import norm
from .treino import Item, _quadro_seguro, item_de_questao

log = logging.getLogger("socrates.trilha")

PASTA = Path(__file__).parent / "trilhas"
PASTA_AUTO = Path.home() / "Documents" / "Socrates" / "trilhas"     # o que ele aprendeu sozinho

# "CP 155-183", "CPP 301-310", "L11343 33-40", "CF 5", "D1655 1"
_FAIXA = re.compile(r"^([A-Z][A-Z0-9]*)\s+(\d+)(?:-([A-Z]))?(?:-(\d+)(?:-([A-Z]))?)?$")
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
    origem: str = "conferido"      # conferido | auto (o Sócrates aprendeu sozinho)
    fontes: list[str] = field(default_factory=list)
    gerado: str = ""               # quando o autoestudo escreveu (ou atualizou) o tópico

    @property
    def auto(self) -> bool:
        return self.origem == "auto"

    @classmethod
    def de_json(cls, t: dict, ordem: int = 0) -> "Topico":
        topico = cls(
            id=t["id"], bloco=t.get("bloco", ""), titulo=t["titulo"], edital=t.get("edital", ""),
            peso=int(t.get("peso") or 1), artigos=list(t.get("artigos", [])),
            palavras=list(t.get("palavras", [])), pontos=list(t.get("pontos", [])),
            pegadinhas=list(t.get("pegadinhas", [])), novidades=list(t.get("novidades", [])),
            itens=list(t.get("itens", [])), questoes=list(t.get("questoes", [])), ordem=ordem,
            origem=t.get("origem", "conferido"), fontes=list(t.get("fontes", [])),
            gerado=t.get("gerado", ""))
        topico.indexar()
        return topico

    def indexar(self) -> None:
        self.chaves = sorted({norm(p) for p in self.palavras + [self.titulo] if norm(p)},
                             key=len, reverse=True)

    def para_json(self) -> dict:
        d = {"id": self.id, "bloco": self.bloco, "titulo": self.titulo, "edital": self.edital,
             "peso": self.peso, "artigos": self.artigos, "palavras": self.palavras,
             "pontos": self.pontos, "pegadinhas": self.pegadinhas, "novidades": self.novidades,
             "itens": self.itens, "questoes": self.questoes}
        if self.origem != "conferido":
            d["origem"] = self.origem
        if self.fontes:
            d["fontes"] = self.fontes
        if self.gerado:
            d["gerado"] = self.gerado
        return d

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
    apelidos: list[str] = field(default_factory=list)       # como o aluno chama a matéria
    nao_confundir: list[str] = field(default_factory=list)  # "processo penal" não é "penal"
    plano: str = ""                                          # o edital de onde ela vem (prf, cbmgo)
    auto: bool = False                                       # trilha inteira feita pelo autoestudo

    def __post_init__(self):
        self._rx_materia = _rx_de([norm(a) for a in self.apelidos])
        self._rx_nao = _rx_de([norm(a) for a in self.nao_confundir])

    # ---------- carregar ----------
    @classmethod
    def de_json(cls, d: dict) -> "Trilha":
        topicos = [Topico.de_json(t, i) for i, t in enumerate(d.get("topicos", []))]
        return cls(d["id"], d["materia"], d.get("concurso", ""), d.get("banca", ""),
                   d.get("fonte", ""), d.get("atualizado", ""), topicos,
                   list(d.get("apelidos", [])), list(d.get("nao_confundir", [])),
                   d.get("plano", ""), bool(d.get("auto")))

    @classmethod
    def ler(cls, caminho: Path) -> "Trilha":
        return cls.de_json(json.loads(caminho.read_text(encoding="utf-8")))

    def para_json(self) -> dict:
        d = {"id": self.id, "materia": self.materia, "concurso": self.concurso, "banca": self.banca,
             "fonte": self.fonte, "atualizado": self.atualizado, "apelidos": self.apelidos,
             "nao_confundir": self.nao_confundir, "plano": self.plano}
        if self.auto:
            d["auto"] = True
        d["topicos"] = [t.para_json() for t in self.topicos]
        return d

    def juntar(self, outra: "Trilha") -> None:
        """Completa esta trilha com o que o autoestudo aprendeu: tópicos novos entram;
        num tópico conferido, só entram as atualizações de lei (o conferido vale mais)."""
        for t in outra.topicos:
            meu = self.topico(t.id)
            if meu is None:
                self.topicos.append(t)
                continue
            if meu.auto:                      # o autoestudo refez o tópico: vale o mais novo
                self.topicos[self.topicos.index(meu)] = t
                continue
            for n in t.novidades:
                if n not in meu.novidades:
                    meu.novidades.append(n)
            textos = {i.get("t") for i in meu.itens}
            meu.itens += [i for i in t.itens if i.get("t") not in textos]   # no fim: ids não mudam
            for f in t.fontes:
                if f not in meu.fontes:
                    meu.fontes.append(f)
        for i, t in enumerate(self.topicos):
            t.ordem = i
        for a in outra.apelidos:
            if a not in self.apelidos:
                self.apelidos.append(a)
        self.__post_init__()

    def topico(self, tid: str) -> Topico | None:
        return next((t for t in self.topicos if t.id == tid), None)

    @property
    def tem_auto(self) -> bool:
        return any(t.auto for t in self.topicos)

    # ---------- entender a fala ----------
    def menciona_materia(self, texto: str) -> bool:
        if self._rx_materia is None:
            return False
        t = norm(texto)
        if self._rx_nao is not None:
            t = self._rx_nao.sub(" ", t)
        return bool(self._rx_materia.search(t))

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


_CURTAS = ("artigos", "palavras", "questoes", "apelidos", "nao_confundir", "fontes")


def formatar_json(d: dict, topicos_em_linha: bool = False) -> str:
    """JSON da trilha no formato de sempre: listas curtas numa linha, textos longos um
    por linha, cada item de fixação numa linha (fácil de ler e de comparar no git).
    Nos planos (editais), cada tópico fica numa linha só."""
    def valor(chave: str, v, recuo: str) -> str:
        if isinstance(v, list):
            if not v:
                return "[]"
            if chave in _CURTAS:
                return json.dumps(v, ensure_ascii=False)
            dentro = recuo + "  "
            if chave == "materias" or (chave == "topicos" and not topicos_em_linha):
                partes = [dentro + objeto(x, dentro) for x in v]
            else:
                partes = [dentro + json.dumps(x, ensure_ascii=False) for x in v]
            return "[\n" + ",\n".join(partes) + "\n" + recuo + "]"
        return json.dumps(v, ensure_ascii=False)

    def objeto(o: dict, recuo: str) -> str:
        dentro = recuo + "  "
        linhas = [f"{dentro}{json.dumps(k, ensure_ascii=False)}: {valor(k, v, dentro)}"
                  for k, v in o.items()]
        return "{\n" + ",\n".join(linhas) + "\n" + recuo + "}"

    return objeto(d, "") + "\n"


def _rx_de(expressoes: list[str]) -> re.Pattern | None:
    expressoes = sorted({e for e in expressoes if e}, key=len, reverse=True)
    if not expressoes:
        return None
    return re.compile(r"\b(?:" + "|".join(re.escape(e) for e in expressoes) + r")\b")


def carregar_trilhas(pasta: Path | None = None, extra: Path | None = None) -> list[Trilha]:
    """As trilhas conferidas (que vêm com o Sócrates) completadas pelo que ele aprendeu
    sozinho (autoestudo). `extra=None` usa Documentos\\Socrates\\trilhas."""
    pasta = pasta or PASTA
    trilhas: dict[str, Trilha] = {}
    for p in sorted(pasta.glob("*.json")):
        tr = Trilha.ler(p)
        trilhas[tr.id] = tr
    extra = PASTA_AUTO if extra is None else extra
    if extra and extra.is_dir():
        for p in sorted(extra.glob("*.json")):
            try:
                tr = Trilha.ler(p)
            except (OSError, ValueError, KeyError) as e:
                log.warning("trilha do autoestudo com defeito (%s): %s", p.name, e)
                continue
            if not tr.topicos:
                continue
            if tr.id in trilhas:
                trilhas[tr.id].juntar(tr)
            else:
                trilhas[tr.id] = tr
    return list(trilhas.values())
