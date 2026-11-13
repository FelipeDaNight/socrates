"""Autoestudo: enquanto o Sócrates está aberto, ele estuda sozinho o edital.

A cada volta:
  1. escolhe o próximo assunto: o que pediram por voz; o tópico do edital que ainda
     não tem conteúdo (pelo peso na prova, alternando as matérias); a lei que mudou
     depois da trilha; ou o tópico do autoestudo que ficou velho
  2. pesquisa: o texto em vigor da lei, no Planalto, e páginas da internet
  3. escreve o tópico (pontos, pegadinhas, itens certo/errado) com um cérebro grátis
  4. confere com OUTRO cérebro: ponto que a fonte contradiz sai; item cujo gabarito
     não bate com a resposta do conferente sai
  5. grava em Documentos\\Socrates\\trilhas\\auto-<trilha>.json (as aulas, as questões
     e as respostas já usam na hora) e anota em Documentos\\Socrates\\aprendizado.json
  6. descansa um pouco e segue para o próximo

Ele só estuda quando você está quieto (a conversa tem prioridade), respeita um
limite por dia e, se o serviço grátis bater no limite, espera e tenta depois.

Fale com ele: "o que você está aprendendo?", "o que você aprendeu hoje?",
"pausa o aprendizado", "volta a aprender", "aprende sobre crimes ambientais".
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from ..llm.base import ErroCerebro, ErroLimite
from .leitor_lei import Artigo, Biblioteca, ErroLei, baixar, faixa, mudancas_desde, no_intervalo, \
    texto_em_vigor
from .plano import MateriaPlano, Plano, TopicoPlano, achar_materia, achar_topico
from .respostas import norm
from .trilha import Trilha, carregar_trilhas, formatar_json

log = logging.getLogger("socrates.autoestudo")

PASTA = Path.home() / "Documents" / "Socrates"
REVER_AUTO_DIAS = 60        # o tópico feito pelo autoestudo é refeito depois disso
CONFERIR_LEI_DIAS = 7       # de quanto em quanto tempo confere se cada lei mudou
LIMITE_FONTES = 11000       # caracteres de fonte por assunto (cabe no limite grátis)
LIMITE_LEI = 7000           # do total, quanto pode ser texto de lei
MIN_PONTOS, MIN_ITENS = 4, 3
ESPERA_FALHA_H = 6          # assunto que falhou só volta depois disso
FATOR_PLANO = (1.0, 0.5, 0.35)   # prioridade do 1º, 2º e 3º edital da lista
MAX_LOG = 3000

_PALAVRAS_FRACAS = {"crime", "crimes", "pena", "penas", "lei", "leis", "artigo", "artigos", "direito",
                    "regra", "regras", "conceito", "codigo", "concurso", "banca", "prova", "questao",
                    "questoes", "estudo", "materia", "topico", "geral", "gerais", "nocoes"}
_SITES_RUINS = ("youtube.", "facebook.", "instagram.", "tiktok.", "twitter.", "x.com", "jusbrasil.",
                "scribd.", "passeidireto.", "brainly.", "pinterest.", "linkedin.")
_SITES_BONS = (".gov.br", ".leg.br", ".jus.br", ".mp.br", ".edu.br")


class ErroAutoestudo(Exception):
    """O assunto não deu certo agora (fonte, modelo ou conferência); tenta outro."""


@dataclass
class Tarefa:
    topico: TopicoPlano
    tipo: str                       # novo | pedido | atualizar | rever
    motivo: str = ""
    mudancas: list = field(default_factory=list)    # [(Artigo, "Lei 15.397", 2026, sigla)]

    @property
    def materia(self) -> MateriaPlano:
        return self.topico.materia

    @property
    def chave(self) -> str:
        return self.topico.chave


@dataclass
class Fonte:
    titulo: str
    url: str
    texto: str
    oficial: bool = False


@dataclass
class Resultado:
    ok: bool
    tarefa: Tarefa
    pontos: int = 0
    itens: int = 0
    descartados: int = 0
    motivo: str = ""
    fontes: list[str] = field(default_factory=list)
    modelo: str = ""
    conferente: str = ""


# ---------------------------------------------------------------- utilidades

def extrair_json(texto: str) -> dict | None:
    """O primeiro objeto JSON da resposta (o modelo às vezes põe ``` ou texto em volta)."""
    if not texto:
        return None
    t = re.sub(r"```(?:json)?", "", texto).strip()
    try:
        d = json.loads(t)
        return d if isinstance(d, dict) else None
    except ValueError:
        pass
    inicio = t.find("{")
    while inicio != -1:
        nivel, dentro_str, escape = 0, False, False
        for i in range(inicio, len(t)):
            c = t[i]
            if dentro_str:
                if escape:
                    escape = False
                elif c == "\\":
                    escape = True
                elif c == '"':
                    dentro_str = False
                continue
            if c == '"':
                dentro_str = True
            elif c == "{":
                nivel += 1
            elif c == "}":
                nivel -= 1
                if nivel == 0:
                    try:
                        d = json.loads(t[inicio:i + 1])
                        if isinstance(d, dict):
                            return d
                    except ValueError:
                        break
        inicio = t.find("{", inicio + 1)
    return None


def _textos(valor, minimo: int = 12, maximo: int = 700) -> list[str]:
    saida = []
    for v in valor if isinstance(valor, list) else []:
        if isinstance(v, str):
            v = re.sub(r"\s+", " ", v).strip()
            if minimo <= len(v) <= maximo and v not in saida:
                saida.append(v)
    return saida


def _itens(valor) -> list[dict]:
    saida, vistos = [], set()
    for v in valor if isinstance(valor, list) else []:
        if not isinstance(v, dict):
            continue
        t = re.sub(r"\s+", " ", str(v.get("t", ""))).strip()
        r = str(v.get("r", "")).strip().upper()[:1]
        j = re.sub(r"\s+", " ", str(v.get("j", ""))).strip()
        if 20 <= len(t) <= 600 and r in ("C", "E") and t not in vistos:
            vistos.add(t)
            saida.append({"t": t, "r": r, "j": j})
    return saida


def _palavras(valor, titulo: str) -> list[str]:
    saida = []
    for v in (valor if isinstance(valor, list) else []) + [titulo]:
        p = norm(str(v))
        if len(p) >= 4 and p not in _PALAVRAS_FRACAS and p not in saida:
            saida.append(p)
    return saida[:18]


def _slug(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")[:50] or "assunto"


def _dominio(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def buscar_web(consulta: str, quantos: int = 6) -> list[dict]:
    from ddgs import DDGS
    return list(DDGS().text(consulta, region="br-pt", safesearch="moderate", max_results=quantos) or [])


def ler_pagina(url: str) -> str:
    """O texto corrido da página (só os parágrafos de verdade)."""
    t = texto_em_vigor(baixar(url, 25))
    return "\n".join(linha for linha in t.split("\n") if len(linha) >= 60)


def trecho_amplo(artigos: dict[str, Artigo], inicio, fim, limite: int) -> str:
    """Os artigos da faixa. Se não cabem inteiros, vai o começo de cada um (cobre a
    faixa toda em vez de só os primeiros artigos)."""
    escolhidos = sorted((a for a in artigos.values() if no_intervalo(a, inicio, fim)),
                        key=lambda a: (a.numero, a.sufixo))
    if not escolhidos:
        return ""
    inteiro = "\n\n".join(a.texto for a in escolhidos)
    if len(inteiro) <= limite:
        return inteiro
    cada = max(220, limite // len(escolhidos))
    partes, total = [], 0
    for a in escolhidos:
        bloco = a.texto if len(a.texto) <= cada else a.texto[:cada].rsplit(" ", 1)[0] + " [...]"
        if total + len(bloco) > limite:
            break
        partes.append(bloco)
        total += len(bloco) + 2
    return "\n\n".join(partes)


def _quem(cerebro) -> str:
    usado = getattr(cerebro, "ultimo_usado", None) or cerebro
    return f"{getattr(usado, 'nome', '?')}:{getattr(usado, 'modelo', '?')}"


def _sem(cerebro, quem: str):
    """O mesmo rodízio sem o modelo que escreveu (quem confere precisa ser outro)."""
    membros = getattr(cerebro, "membros", None)
    if not membros:
        return cerebro
    outros = [m for m in membros if f"{m.nome}:{m.modelo}" != quem]
    if not outros or len(outros) == len(membros):
        return cerebro
    from ..llm.rodizio import CerebroRodizio
    return CerebroRodizio(outros)


# ---------------------------------------------------------------- prompts

SISTEMA_ESCRITOR = (
    "Você prepara material de estudo para concursos públicos no Brasil. Escreve em português do "
    "Brasil, com frases curtas e corretas. Usa SÓ o que está nas FONTES. Quando a fonte é texto de "
    "lei, ele é a versão em vigor e vale mais do que a sua memória: a lei pode ter mudado. Nunca "
    "inventa número de artigo, pena, prazo, súmula, julgado ou lei. Responde só com JSON.")

SISTEMA_CONFERENTE = (
    "Você é um conferente rigoroso de material de concurso. Julga cada afirmação SÓ pelas FONTES "
    "dadas, sem usar a memória. Responde só com JSON.")


def _bloco_fontes(fontes: list[Fonte]) -> str:
    partes = []
    for i, f in enumerate(fontes, 1):
        tipo = "TEXTO OFICIAL DA LEI, EM VIGOR" if f.oficial else "página da internet"
        partes.append(f"[{i}] {f.titulo} ({tipo}) {f.url}\n{f.texto}")
    return "\n\n".join(partes)


def pedido_escrever(t: Tarefa, fontes: list[Fonte]) -> str:
    m, p = t.materia, t.materia.plano
    return (
        f"Concurso: {p.concurso} ({p.cargo}), banca {p.banca}. Matéria: {m.materia}.\n"
        f"Tópico do edital: {t.topico.titulo}." + (f" ({t.topico.edital})" if t.topico.edital else "") +
        "\n\nFONTES:\n" + _bloco_fontes(fontes) + "\n\n"
        "Monte o tópico neste JSON (e nada fora dele):\n"
        '{"palavras": ["6 a 15 palavras ou expressões curtas que o aluno usaria para pedir este '
        'assunto, minúsculas e sem acento"],\n'
        ' "pontos": ["6 a 10 pontos; cada um é uma regra ou um fato completo, que se entende sozinho, '
        'com o artigo e a lei quando houver"],\n'
        f' "pegadinhas": ["2 a 4 frases: como a banca {p.banca} costuma tentar confundir neste tópico"],\n'
        ' "itens": [{"t": "afirmação no estilo da banca, para julgar certo ou errado", "r": "C ou E", '
        '"j": "por que, citando o artigo ou a fonte"}],\n'
        ' "novidades": ["mudanças recentes de lei que as FONTES mostram, com o número da lei e o ano; '
        '[] se não houver"]}\n'
        "Faça de 6 a 8 itens, misturando certos e errados. O item errado tem que ser errado por um "
        "detalhe que dá para conferir na fonte (prazo, pena, quem, quando, exceção).")


def pedido_atualizar(t: Tarefa, fontes: list[Fonte], nome_lei: Callable[[str], str]) -> str:
    linhas = [f"- {a.rotulo} ({nome_lei(sigla)}): mudado pela {lei}, de {ano}"
              for a, lei, ano, sigla in t.mudancas]
    return (
        f"O tópico \"{t.topico.titulo}\" ({t.materia.materia}, concurso {t.materia.plano.concurso}) já "
        "tem material, mas a lei mudou depois dele:\n" + "\n".join(linhas) +
        "\n\nFONTES:\n" + _bloco_fontes(fontes) + "\n\n"
        "Escreva SÓ este JSON:\n"
        '{"novidades": ["1 a 3 frases: o que mudou, por qual lei e de que ano, e como ficou a regra"],\n'
        ' "itens": [{"t": "afirmação sobre a mudança, para julgar certo ou errado", "r": "C ou E", '
        '"j": "por que, citando o artigo"}]}\n'
        "Faça 2 a 4 itens. Use só o texto em vigor das fontes.")


def pedido_conferir(fontes: list[Fonte], c: dict) -> str:
    def lista(nome, xs, fmt=lambda x: x):
        return f"{nome}:\n" + "\n".join(f"{i}. {fmt(x)}" for i, x in enumerate(xs, 1)) if xs else f"{nome}: (nenhum)"
    return (
        "FONTES:\n" + _bloco_fontes(fontes) + "\n\n"
        "Confira o material abaixo SÓ pelas FONTES.\n\n" +
        lista("PONTOS", c.get("pontos", [])) + "\n\n" +
        lista("PEGADINHAS", c.get("pegadinhas", [])) + "\n\n" +
        lista("NOVIDADES", c.get("novidades", [])) + "\n\n" +
        lista("ITENS (responda você mesmo, C ou E, sem gabarito)", c.get("itens", []),
              lambda x: x["t"]) + "\n\n"
        "Responda SÓ com este JSON, uma letra por afirmação, na mesma ordem:\n"
        '{"pontos": ["S"], "pegadinhas": ["S"], "novidades": ["S"], "itens": ["C"]}\n'
        "Pontos, pegadinhas e novidades: S = a fonte confirma; X = a fonte contradiz; N = a fonte "
        "não trata disso. Itens: C = certo, E = errado, ? = a fonte não permite saber.")


# ---------------------------------------------------------------- o motor

class Autoestudo:
    def __init__(self, planos: list[Plano], escritor, conferente=None,
                 biblioteca: Biblioteca | None = None,
                 buscar: Callable[[str], list[dict]] | None = buscar_web,
                 ler: Callable[[str], str] | None = ler_pagina,
                 pasta: Path | None = None, pasta_trilhas: Path | None = None,
                 ativo: bool = True, por_dia: int = 40, pausa_seg: float = 90, ocioso_seg: float = 30,
                 relogio: Callable[[], datetime] = datetime.now,
                 avisar: Callable[[str], None] | None = None,
                 ao_aprender: Callable[[str], None] | None = None,
                 ao_mudar: Callable[[str], None] | None = None,
                 ocupado: Callable[[], bool] | None = None):
        self.planos = planos
        self.escritor = escritor
        self.conferente = conferente or escritor
        self.biblioteca = biblioteca or Biblioteca({})
        self.buscar = buscar
        self.ler = ler
        self.pasta = pasta or PASTA
        self.pasta_trilhas = pasta_trilhas or (self.pasta / "trilhas")
        self.por_dia = por_dia
        self.pausa_seg = pausa_seg
        self.ocioso_seg = ocioso_seg
        self.relogio = relogio
        self.avisar = avisar
        self.ao_aprender = ao_aprender
        self.ao_mudar = ao_mudar
        self.ocupado = ocupado
        self.pausado = not ativo
        self.estado = "parado"
        self.atual: Tarefa | None = None
        self.fila: list[Tarefa] = []
        self._lock = threading.RLock()
        self._parar = threading.Event()
        self._acordar = threading.Event()
        self._thread: threading.Thread | None = None
        self._livre_desde = time.monotonic()
        self.dados = self._ler_estado()

    # ---------- estado guardado ----------
    @property
    def _arq_estado(self) -> Path:
        return self.pasta / "autoestudo.json"

    @property
    def _arq_log(self) -> Path:
        return self.pasta / "aprendizado.json"

    def _ler_estado(self) -> dict:
        try:
            d = json.loads(self._arq_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            d = {}
        d.setdefault("leis", {})        # sigla -> última conferência (data)
        d.setdefault("falhas", {})      # chave do tópico -> {"n": 1, "ate": iso}
        d.setdefault("dias", {})        # data -> assuntos estudados
        d.setdefault("pausado", None)
        if d["pausado"] is not None:
            self.pausado = bool(d["pausado"])
        return d

    def _salvar_estado(self) -> None:
        try:
            with self._lock:                 # a conversa (outra thread) também mexe aqui
                texto = json.dumps(self.dados, ensure_ascii=False, indent=1)
            self.pasta.mkdir(parents=True, exist_ok=True)
            _gravar(self._arq_estado, texto)
        except OSError as e:
            log.warning("estado do autoestudo não salvo: %s", e)

    def registro(self) -> list[dict]:
        try:
            d = json.loads(self._arq_log.read_text(encoding="utf-8"))
            return d if isinstance(d, list) else []
        except (OSError, ValueError):
            return []

    def _anotar(self, r: Resultado) -> None:
        t = r.tarefa
        entrada = {"data": self.relogio().isoformat(timespec="seconds"), "ok": r.ok, "tipo": t.tipo,
                   "plano": t.materia.plano.id, "trilha": t.materia.trilha, "materia": t.materia.materia,
                   "topico": t.topico.id, "titulo": t.topico.titulo, "pontos": r.pontos, "itens": r.itens,
                   "descartados": r.descartados, "motivo": r.motivo, "fontes": r.fontes[:6],
                   "modelo": r.modelo, "conferente": r.conferente}
        lista = self.registro()
        lista.append(entrada)
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            _gravar(self._arq_log, json.dumps(lista[-MAX_LOG:], ensure_ascii=False, indent=1))
        except OSError as e:
            log.warning("aprendizado.json não salvo: %s", e)

    def feitos_hoje(self) -> int:
        return int(self.dados["dias"].get(self.relogio().date().isoformat(), 0))

    # ---------- o que já existe ----------
    def trilhas(self) -> dict[str, Trilha]:
        return {t.id: t for t in carregar_trilhas(extra=self.pasta_trilhas)}

    def _esperando(self, chave: str) -> bool:
        f = self.dados["falhas"].get(chave)
        if not f:
            return False
        try:
            return self.relogio() < datetime.fromisoformat(f["ate"])
        except (KeyError, ValueError):
            return False

    # ---------- escolher o próximo assunto ----------
    def proxima(self, trilhas: dict[str, Trilha] | None = None) -> Tarefa | None:
        with self._lock:
            if self.fila:
                return self.fila.pop(0)
        trilhas = trilhas if trilhas is not None else self.trilhas()
        hoje = self.relogio().date()
        melhor: tuple[float, Tarefa] | None = None

        def considerar(nota: float, tarefa: Tarefa):
            nonlocal melhor
            if melhor is None or nota > melhor[0]:
                melhor = (nota, tarefa)

        for i, plano in enumerate(self.planos):
            fator = FATOR_PLANO[min(i, len(FATOR_PLANO) - 1)]
            for m in plano.materias:
                tr = trilhas.get(m.trilha)
                feitos = sum(1 for t in m.topicos if tr is not None and tr.topico(t.id) is not None)
                faltam = [t for t in m.topicos
                          if (tr is None or tr.topico(t.id) is None) and not self._esperando(t.chave)]
                if faltam:
                    t = max(faltam, key=lambda x: (x.peso, -m.topicos.index(x)))
                    considerar(fator * m.peso * (1 + t.peso) / (1 + feitos),
                               Tarefa(t, "novo", f"falta na trilha de {m.materia}"))
                if tr is None:
                    continue
                for t in m.topicos:              # o que o autoestudo fez há muito tempo
                    top = tr.topico(t.id)
                    if top is None or not top.auto or self._esperando(t.chave):
                        continue
                    try:
                        idade = (hoje - date.fromisoformat(top.gerado[:10])).days
                    except ValueError:
                        idade = REVER_AUTO_DIAS + 1
                    if idade > REVER_AUTO_DIAS:
                        considerar(0.05 * fator * m.peso * t.peso,
                                   Tarefa(t, "rever", f"o conteúdo tem {idade} dias"))
        return melhor[1] if melhor else None

    def todos_os_topicos(self) -> list[TopicoPlano]:
        return [t for p in self.planos for m in p.materias for t in m.topicos]

    # ---------- a lei mudou? ----------
    def conferir_uma_lei(self, trilhas: dict[str, Trilha] | None = None) -> list[Tarefa]:
        """Confere UMA lei por vez (a que faz mais tempo): se um artigo usado pela trilha
        mudou por uma lei que a trilha não cita, agenda a atualização do tópico."""
        trilhas = trilhas if trilhas is not None else self.trilhas()
        hoje = self.relogio().date()
        usos: dict[str, list[tuple[TopicoPlano, object]]] = {}
        for t in self.todos_os_topicos():
            tr = trilhas.get(t.materia.trilha)
            top = tr.topico(t.id) if tr else None
            if top is None:
                continue
            for f in t.fontes:
                fx = faixa(f)
                if fx and self.biblioteca.url(fx[0]):
                    usos.setdefault(fx[0], []).append((t, top))
        if not usos:
            return []
        def ultima(sigla):
            try:
                return date.fromisoformat(self.dados["leis"].get(sigla, "")[:10])
            except ValueError:
                return date.min
        sigla = min(usos, key=ultima)
        if (hoje - ultima(sigla)).days < CONFERIR_LEI_DIAS:
            return []
        self._mudar(f"conferindo se a lei mudou: {self.biblioteca.nome(sigla)}")
        try:
            artigos = self.biblioteca.artigos(sigla)
        except ErroLei as e:
            log.info("não conferi %s: %s", sigla, e)
            self.dados["leis"][sigla] = hoje.isoformat()     # tenta de novo na semana que vem
            self._salvar_estado()
            return []
        self.dados["leis"][sigla] = hoje.isoformat()
        self._salvar_estado()
        novas: list[Tarefa] = []
        for t, top in usos[sigla]:
            tr = trilhas[t.materia.trilha]
            base = (top.gerado or tr.atualizado or "2000")[:4]
            # um ano de folga: lei do fim do ano anterior pode ter escapado da conferência
            ano_base = (int(base) if base.isdigit() else 2000) - (0 if top.auto else 1)
            conhecido = " ".join(top.pontos + top.novidades + top.pegadinhas +
                                 [i.get("t", "") + " " + i.get("j", "") for i in top.itens])
            mudancas = []
            for f in t.fontes:
                fx = faixa(f)
                if not fx or fx[0] != sigla:
                    continue
                for art, lei, ano in mudancas_desde(artigos, ano_base, fx[1], fx[2]):
                    numero = lei.split(" ", 1)[-1]
                    if numero not in conhecido and (art, lei, ano, sigla) not in mudancas:
                        mudancas.append((art, lei, ano, sigla))
            if not mudancas:
                continue
            leis = sorted({f"{lei}/{ano}" for _, lei, ano, _ in mudancas})
            tipo = "rever" if top.auto else "atualizar"
            novas.append(Tarefa(t, tipo, "a lei mudou: " + ", ".join(leis), mudancas[:8]))
        with self._lock:
            chaves = {x.chave for x in self.fila}
            for n in novas:
                if n.chave not in chaves:
                    self.fila.append(n)
        return novas

    # ---------- pesquisar ----------
    def pesquisar(self, t: Tarefa) -> list[Fonte]:
        fontes: list[Fonte] = []
        usado_lei = 0
        consultas: list[str] = []
        faixas = [fx for f in t.topico.fontes if (fx := faixa(f))]
        if t.tipo == "atualizar" and t.mudancas:     # só os artigos que mudaram
            por_sigla: dict[str, list[Artigo]] = {}
            for art, _lei, _ano, sigla in t.mudancas:
                por_sigla.setdefault(sigla, []).append(art)
            for sigla, arts in por_sigla.items():
                texto = "\n\n".join(a.texto for a in arts)[:LIMITE_LEI]
                fontes.append(Fonte(f"{self.biblioteca.nome(sigla)} ({', '.join(a.rotulo for a in arts[:6])})",
                                    self.biblioteca.url(sigla), texto, True))
            return fontes
        for sigla, ini, fim in faixas:
            reg = self.biblioteca.registro.get(sigla) or {}
            if reg.get("url"):
                try:
                    artigos = self.biblioteca.artigos(sigla)
                    sobra = max(0, LIMITE_LEI - usado_lei) // max(1, len(faixas))
                    texto = trecho_amplo(artigos, ini, fim, max(sobra, 1500))
                    if texto:
                        rot = f"arts. {ini[0]}" + (f" a {fim[0]}" if fim[0] != ini[0] else "")
                        fontes.append(Fonte(f"{self.biblioteca.nome(sigla)}, {rot}", reg["url"], texto, True))
                        usado_lei += len(texto)
                        continue
                except ErroLei as e:
                    log.info("lei %s indisponível (%s); vou pela internet", sigla, e)
                consultas.append(f"{self.biblioteca.nome(sigla)} art. {ini[0]} texto")
            elif reg.get("busca"):
                consultas.append(f"{reg['busca']} {t.topico.titulo}")
        if t.topico.pesquisa:
            consultas.append(t.topico.pesquisa)
        if not fontes and not consultas:
            consultas.append(f"{t.topico.titulo} {t.materia.materia} concurso {t.materia.plano.concurso}")
        if self.buscar is not None and self.ler is not None:
            sobra = LIMITE_FONTES - sum(len(f.texto) for f in fontes)
            for consulta in consultas[:3]:
                if sobra < 800:
                    break
                for pagina in self._paginas(consulta, 2 if fontes else 3):
                    texto = pagina.texto[:min(4000, sobra)]
                    fontes.append(Fonte(pagina.titulo, pagina.url, texto))
                    sobra -= len(texto)
                    if sobra < 800:
                        break
        return fontes

    def _paginas(self, consulta: str, quantas: int) -> list[Fonte]:
        try:
            resultados = self.buscar(consulta) or []
        except Exception as e:                   # a busca é um extra: segue sem ela
            log.info("busca falhou (%s): %s", consulta, e)
            return []
        resultados = [r for r in resultados if r.get("href", "").startswith("http")
                      and not any(s in _dominio(r["href"]) for s in _SITES_RUINS)
                      and not r["href"].lower().endswith(".pdf")]
        resultados.sort(key=lambda r: not ("." + _dominio(r["href"])).endswith(_SITES_BONS))
        saida = []
        for r in resultados:
            if len(saida) >= quantas:
                break
            try:
                texto = self.ler(r["href"])
            except Exception as e:
                log.info("não li %s: %s", r["href"], e)
                continue
            if len(texto) >= 400:
                saida.append(Fonte(r.get("title", "") or _dominio(r["href"]), r["href"], texto))
        return saida

    # ---------- escrever e conferir ----------
    async def _pedir_json(self, cerebro, sistema: str, pedido: str) -> tuple[dict, str]:
        msgs = [{"role": "system", "content": sistema}, {"role": "user", "content": pedido}]
        for _ in range(2):
            texto = ""
            async for pedaco in cerebro.responder(msgs):
                texto += pedaco
            dados = extrair_json(texto)
            if dados is not None:
                return dados, _quem(cerebro)
            msgs += [{"role": "assistant", "content": texto[:1500]},
                     {"role": "user", "content": "Responda de novo SÓ com o JSON válido, nada fora dele."}]
        raise ErroAutoestudo("o modelo não devolveu um JSON válido")

    async def escrever(self, t: Tarefa, fontes: list[Fonte]) -> tuple[dict, str]:
        if t.tipo == "atualizar":
            bruto, quem = await self._pedir_json(self.escritor, SISTEMA_ESCRITOR,
                                                 pedido_atualizar(t, fontes, self.biblioteca.nome))
            return {"novidades": _textos(bruto.get("novidades"), 20), "itens": _itens(bruto.get("itens")),
                    "pontos": [], "pegadinhas": [], "palavras": []}, quem
        bruto, quem = await self._pedir_json(self.escritor, SISTEMA_ESCRITOR, pedido_escrever(t, fontes))
        return {"palavras": _palavras(bruto.get("palavras"), t.topico.titulo),
                "pontos": _textos(bruto.get("pontos"), 25)[:12],
                "pegadinhas": _textos(bruto.get("pegadinhas"), 20)[:5],
                "itens": _itens(bruto.get("itens"))[:10],
                "novidades": _textos(bruto.get("novidades"), 20)[:4]}, quem

    async def conferir(self, t: Tarefa, fontes: list[Fonte], c: dict, quem_escreveu: str
                       ) -> tuple[dict, int, str]:
        """Fica só o que o conferente confirma. Devolve (conteúdo, descartados, conferente)."""
        cerebro = _sem(self.conferente, quem_escreveu)
        veredito, quem = await self._pedir_json(cerebro, SISTEMA_CONFERENTE, pedido_conferir(fontes, c))
        oficial = any(f.oficial for f in fontes)

        def marcas(nome: str, n: int) -> list[str]:
            v = veredito.get(nome)
            v = [str(x).strip().upper()[:1] for x in v] if isinstance(v, list) else []
            return v + ["N"] * (n - len(v))

        descartados = 0
        saida = dict(c)
        for nome in ("pontos", "pegadinhas", "novidades"):
            xs = c.get(nome, [])
            ms = marcas(nome, len(xs))
            # contra a fonte, sai sempre; sem apoio na lei (quando há lei), sai também
            manter = [x for x, m in zip(xs, ms) if m == "S" or (m == "N" and not oficial and nome != "novidades")]
            descartados += len(xs) - len(manter)
            saida[nome] = manter
        itens = c.get("itens", [])
        respostas = marcas("itens", len(itens))
        bons = [i for i, r in zip(itens, respostas) if r == i["r"]]
        descartados += len(itens) - len(bons)
        saida["itens"] = bons
        return saida, descartados, quem

    # ---------- gravar ----------
    def gravar(self, t: Tarefa, c: dict, fontes: list[Fonte]) -> Path:
        m = t.materia
        hoje = self.relogio().date().isoformat()
        arq = self.pasta_trilhas / f"auto-{m.trilha}.json"
        try:
            dados = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            dados = None
        if not isinstance(dados, dict) or dados.get("id") != m.trilha:
            dados = {"id": m.trilha, "materia": m.materia, "concurso": m.plano.concurso,
                     "banca": m.plano.banca,
                     "fonte": "Aprendido pelo Sócrates sozinho (autoestudo): texto em vigor da lei e páginas "
                              "da internet, conferido por um segundo modelo. Confira na fonte antes de "
                              "confiar 100%.",
                     "atualizado": hoje, "apelidos": m.apelidos, "nao_confundir": m.nao_confundir,
                     "plano": m.plano.id, "auto": True, "topicos": []}
        urls = list(dict.fromkeys(f.url for f in fontes if f.url))
        anterior = next((x for x in dados["topicos"] if x.get("id") == t.topico.id), None)
        if t.tipo == "atualizar":
            entrada = anterior or {"id": t.topico.id, "bloco": m.bloco or m.materia,
                                   "titulo": t.topico.titulo, "edital": t.topico.edital,
                                   "peso": t.topico.peso, "artigos": [], "palavras": [], "pontos": [],
                                   "pegadinhas": [], "novidades": [], "itens": [], "questoes": []}
            for n in c.get("novidades", []):
                if n not in entrada.setdefault("novidades", []):
                    entrada["novidades"].append(n)
            textos = {i.get("t") for i in entrada.setdefault("itens", [])}
            entrada["itens"] += [i for i in c.get("itens", []) if i["t"] not in textos]
            entrada["fontes"] = list(dict.fromkeys(entrada.get("fontes", []) + urls))
        else:
            entrada = {"id": t.topico.id, "bloco": m.bloco or m.materia, "titulo": t.topico.titulo,
                       "edital": t.topico.edital, "peso": t.topico.peso,
                       "artigos": [f for f in t.topico.fontes if faixa(f)],
                       "palavras": c.get("palavras", []), "pontos": c.get("pontos", []),
                       "pegadinhas": c.get("pegadinhas", []), "novidades": c.get("novidades", []),
                       "itens": c.get("itens", []), "questoes": [], "fontes": urls}
        entrada["origem"] = "auto"
        entrada["gerado"] = hoje
        if anterior is not None:
            dados["topicos"][dados["topicos"].index(anterior)] = entrada
        else:
            dados["topicos"].append(entrada)
        ordem = {tp.id: i for i, tp in enumerate(m.topicos)}
        dados["topicos"].sort(key=lambda x: ordem.get(x.get("id"), len(ordem)))
        dados["atualizado"] = hoje
        self.pasta_trilhas.mkdir(parents=True, exist_ok=True)
        _gravar(arq, formatar_json(dados))
        return arq

    # ---------- um assunto inteiro ----------
    async def estudar(self, t: Tarefa) -> Resultado:
        self.atual = t
        nome = f"{t.topico.titulo} ({t.materia.materia})"
        try:
            self._mudar(f"pesquisando: {nome}")
            fontes = await asyncio.to_thread(self.pesquisar, t)
            if not fontes:
                raise ErroAutoestudo("não achei fontes (sem internet?)")
            self._mudar(f"escrevendo: {nome}")
            conteudo, quem = await self.escrever(t, fontes)
            self._mudar(f"conferindo: {nome}")
            conteudo, descartados, conferente = await self.conferir(t, fontes, conteudo, quem)
            if t.tipo == "atualizar":
                if not conteudo["novidades"]:
                    raise ErroAutoestudo("a atualização não passou na conferência")
            elif len(conteudo["pontos"]) < MIN_PONTOS or len(conteudo["itens"]) < MIN_ITENS:
                raise ErroAutoestudo(f"sobrou pouco conteúdo confiável ({len(conteudo['pontos'])} pontos, "
                                     f"{len(conteudo['itens'])} itens)")
            self.gravar(t, conteudo, fontes)
            r = Resultado(True, t, len(conteudo["pontos"]) + len(conteudo["novidades"]),
                          len(conteudo["itens"]), descartados, "", [f.url for f in fontes], quem, conferente)
            dia = self.relogio().date().isoformat()
            with self._lock:
                self.dados["falhas"].pop(t.chave, None)
                self.dados["dias"][dia] = self.dados["dias"].get(dia, 0) + 1
                self.dados["dias"] = dict(sorted(self.dados["dias"].items())[-60:])
            self._salvar_estado()
            self._anotar(r)
            log.info("aprendi %s: %d pontos, %d itens (%d descartados)", nome, r.pontos, r.itens, descartados)
            if self.ao_aprender:
                self.ao_aprender(t.materia.trilha)
            if t.tipo == "pedido" and self.avisar:
                self.avisar(f"Terminei de estudar {t.topico.titulo}. Quando quiser, diga: "
                            f"me ensina {t.topico.titulo.lower()}.")
            self._mudar(f"aprendi: {nome}")
            return r
        except ErroAutoestudo as e:
            self._mudar(f"não deu para estudar {nome} agora")
            return self._falhou(t, str(e))
        finally:
            self.atual = None

    def _falhou(self, t: Tarefa, motivo: str) -> Resultado:
        log.info("não deu para estudar %s: %s", t.topico.titulo, motivo)
        f = self.dados["falhas"].get(t.chave, {"n": 0})
        n = int(f.get("n", 0)) + 1
        ate = self.relogio() + timedelta(hours=ESPERA_FALHA_H * min(n, 8))
        with self._lock:
            self.dados["falhas"][t.chave] = {"n": n, "ate": ate.isoformat(timespec="seconds"),
                                             "motivo": motivo}
        self._salvar_estado()
        r = Resultado(False, t, motivo=motivo)
        self._anotar(r)
        if t.tipo == "pedido" and self.avisar:
            self.avisar(f"Não consegui estudar {t.topico.titulo} agora: {motivo}. Tento de novo mais tarde.")
        return r

    # ---------- o laço ----------
    def _mudar(self, texto: str) -> None:
        self.estado = texto
        if self.ao_mudar:
            try:
                self.ao_mudar(texto)
            except Exception:
                pass

    def _livre(self) -> bool:
        if self.ocupado is not None and self.ocupado():
            self._livre_desde = time.monotonic()
            return False
        return time.monotonic() - self._livre_desde >= self.ocioso_seg

    async def _dormir(self, segundos: float) -> None:
        fim = time.monotonic() + segundos
        while time.monotonic() < fim and not self._parar.is_set():
            if self._acordar.is_set():
                self._acordar.clear()
                return
            await asyncio.sleep(min(1.0, max(0.05, fim - time.monotonic())))

    async def rodar(self, max_assuntos: int | None = None, esperar_livre: bool = True,
                    max_tentativas: int | None = None) -> int:
        """Estuda até mandarem parar (ou até `max_assuntos` aprendidos, ou `max_tentativas`
        assuntos tentados). Devolve quantos aprendeu."""
        feitos = tentativas = 0
        while not self._parar.is_set():
            if self.pausado:
                self._mudar("aprendizado pausado")
                await self._dormir(30)
                continue
            if self.feitos_hoje() >= self.por_dia:
                self._mudar(f"estudei {self.por_dia} assuntos hoje; volto amanhã")
                await self._dormir(900)
                continue
            if esperar_livre and not self._livre():
                self._mudar("esperando você terminar")
                await self._dormir(3)
                continue
            trilhas = await asyncio.to_thread(self.trilhas)
            with self._lock:
                tem_pedido = bool(self.fila)
            if not tem_pedido:                   # o que pediram por voz vem antes
                try:
                    await asyncio.to_thread(self.conferir_uma_lei, trilhas)
                except Exception:
                    log.exception("conferência da lei falhou")
            tarefa = self.proxima(trilhas)
            if tarefa is None:
                self._mudar("terminei o edital; confiro as leis de tempos em tempos")
                await self._dormir(1800)
                continue
            tentativas += 1
            try:
                r = await self.estudar(tarefa)
            except ErroLimite as e:
                with self._lock:
                    self.fila.insert(0, tarefa)
                espera = 3 * 3600 if e.do_dia else max(60, e.espera or 120)
                self._mudar(f"limite grátis dos cérebros; volto em {round(espera / 60)} min")
                await self._dormir(espera)
                continue
            except ErroCerebro as e:
                self._mudar(f"os cérebros falharam: {e}")
                self._falhou(tarefa, str(e))
                if max_tentativas and tentativas >= max_tentativas:
                    break
                await self._dormir(120)
                continue
            except Exception as e:      # nunca derrubar o Sócrates por causa do autoestudo
                log.exception("autoestudo falhou em %s", tarefa.topico.titulo)
                self._falhou(tarefa, f"erro inesperado: {e}")
                if max_tentativas and tentativas >= max_tentativas:
                    break
                await self._dormir(120)
                continue
            if r.ok:
                feitos += 1
                self._mudar(f"aprendi: {tarefa.topico.titulo} ({tarefa.materia.materia})")
            if (max_assuntos and feitos >= max_assuntos) or (max_tentativas and tentativas >= max_tentativas):
                break
            await self._dormir(self.pausa_seg)
        self._mudar("parado")
        return feitos

    def iniciar(self) -> None:
        """Roda numa thread própria (com o seu próprio laço), sem atrapalhar a conversa."""
        if self._thread is not None and self._thread.is_alive():
            return

        def corpo():
            try:
                asyncio.run(self.rodar())
            except Exception:
                log.exception("o autoestudo parou")

        self._thread = threading.Thread(target=corpo, name="autoestudo", daemon=True)
        self._thread.start()

    def parar(self) -> None:
        self._parar.set()
        self._acordar.set()

    # ---------- comandos falados ----------
    def pausar(self) -> str:
        self.pausado = True
        with self._lock:
            self.dados["pausado"] = True
        self._salvar_estado()
        self._mudar("aprendizado pausado")
        return "Pausei o meu autoestudo. Para eu voltar a estudar sozinho, diga: volta a aprender."

    def retomar(self) -> str:
        self.pausado = False
        with self._lock:
            self.dados["pausado"] = False
        self._salvar_estado()
        self._acordar.set()
        return "Voltei a estudar sozinho. Eu só estudo quando você estiver quieto."

    def pedir(self, texto: str) -> tuple[str, TopicoPlano | None]:
        """"aprende sobre X": põe X na frente da fila. Fora do edital, vira um assunto extra."""
        topico = achar_topico(self.planos, texto)
        if topico is None:
            materia = achar_materia(self.planos, texto)
            assunto = _assunto_da_fala(texto)
            if not assunto:
                return "Sobre o que você quer que eu estude?", None
            if materia is not None and norm(assunto) in [norm(a) for a in materia.apelidos]:
                t = self.proxima_da_materia(materia)
                if t is None:
                    return f"Já estudei todo o edital de {materia.materia}.", None
                topico = t
            else:
                topico = self._extra(assunto)
        with self._lock:
            self.fila = [x for x in self.fila if x.chave != topico.chave]
            self.fila.insert(0, Tarefa(topico, "pedido", "você pediu"))
            self.dados["falhas"].pop(topico.chave, None)
        self._acordar.set()
        if self.pausado:
            return (f"Anotei {topico.titulo}, mas o meu autoestudo está pausado. Diga volta a aprender "
                    "e eu começo por ele."), topico
        return (f"Certo, vou estudar {topico.titulo} agora, pela lei e pela internet, e confiro com "
                "outro modelo. Te aviso quando terminar."), topico

    def proxima_da_materia(self, materia: MateriaPlano) -> TopicoPlano | None:
        tr = self.trilhas().get(materia.trilha)
        faltam = [t for t in materia.topicos if tr is None or tr.topico(t.id) is None]
        return max(faltam, key=lambda x: (x.peso, -materia.topicos.index(x))) if faltam else None

    def _extra(self, assunto: str) -> TopicoPlano:
        plano = self.planos[0] if self.planos else Plano("extra", "", "", "", "", [])
        m = next((x for x in plano.materias if x.id == "extras"), None)
        if m is None:
            m = MateriaPlano("extras", f"{plano.id}-extras", "Assuntos extras", "Extras", 1,
                             ["assuntos extras"], [], [], plano)
            plano.materias.append(m)
        tid = _slug(assunto)
        t = next((x for x in m.topicos if x.id == tid), None)
        if t is None:
            t = TopicoPlano(tid, assunto[:1].upper() + assunto[1:], "pedido por voz", 1, [],
                            f"{assunto} concurso {plano.concurso}".strip(), m)
            m.topicos.append(t)
        return t

    def status(self) -> str:
        if self.pausado:
            return "Meu autoestudo está pausado. Diga volta a aprender para eu continuar."
        hoje = self.feitos_hoje()
        partes = []
        if self.atual is not None:
            partes.append(f"Agora estou estudando {self.atual.topico.titulo}, de {self.atual.materia.materia}.")
        else:
            partes.append(f"Neste momento: {self.estado}.")
        partes.append(f"Hoje já estudei {hoje} de no máximo {self.por_dia} assuntos.")
        with self._lock:
            if self.fila:
                partes.append(f"Na fila: {', '.join(t.topico.titulo for t in self.fila[:3])}.")
        return " ".join(partes)

    def aprendidos(self, dias: int = 0) -> list[dict]:
        inicio = (self.relogio().date() - timedelta(days=dias)).isoformat()
        return [e for e in self.registro() if e.get("ok") and e.get("data", "")[:10] >= inicio]

    def resumo(self, dias: int = 0) -> tuple[str, str]:
        """(fala, quadro) do que ele aprendeu sozinho no período."""
        lista = self.aprendidos(dias)
        quando = "hoje" if dias == 0 else ("ontem e hoje" if dias == 1 else f"nos últimos {dias + 1} dias")
        if not lista:
            return (f"Ainda não aprendi nenhum assunto novo {quando}. " +
                    ("Meu autoestudo está pausado." if self.pausado else "Eu estudo quando você fica quieto."),
                    f"# Autoestudo\nNada novo {quando}.")
        novos = [e for e in lista if e.get("tipo") != "atualizar"]
        atual = [e for e in lista if e.get("tipo") == "atualizar"]
        titulos = list(dict.fromkeys(f"{e['titulo']} ({e['materia']})" for e in novos))
        fala = f"{quando.capitalize()} eu aprendi {len(titulos)} assunto{'s' if len(titulos) != 1 else ''}"
        if titulos:
            fala += ", como " + ", ".join(t.split(' (')[0] for t in titulos[:3])
        fala += "."
        if atual:
            fala += f" E atualizei {len(atual)} tópico{'s' if len(atual) != 1 else ''} por mudança na lei."
        fala += " Para ter a aula, diga: me ensina e o nome do assunto."
        linhas = [f"# O que eu aprendi {quando}"]
        linhas += [f"- {t}" for t in titulos[:12]]
        if atual:
            linhas.append("Atualizados (lei nova): " + ", ".join(e["titulo"] for e in atual[:6]))
        linhas.append(f"Itens de fixação novos: {sum(e.get('itens', 0) for e in lista)}")
        return fala, "\n".join(linhas)


def _gravar(arq: Path, texto: str) -> None:
    """Grava sem deixar o arquivo pela metade se o PC desligar no meio."""
    tmp = arq.with_suffix(arq.suffix + ".tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(arq)


# ---------------------------------------------------------------- entender a fala

_STATUS = re.compile(r"\b(o que (?:voce|vc) (?:esta|ta|anda) (?:aprendendo|estudando|pesquisando)|"
                     r"(?:como|como que) (?:esta|ta|vai) (?:o |seu |o seu )?(?:autoestudo|aprendizado)|"
                     r"(?:voce|vc) (?:esta|ta) (?:aprendendo|estudando) (?:sozinho|alguma coisa|algo)|"
                     r"status do (?:autoestudo|aprendizado))\b")
_HOJE = re.compile(r"\b(o que (?:voce|vc) (?:ja )?(?:aprendeu|estudou|pesquisou)|"
                   r"(?:voce|vc) aprendeu (?:o que|alguma coisa|algo))\b")
_PAUSA = re.compile(r"\b(?:pausa|pause|para|pare|desliga|desligue|interrompe|chega de)\s+(?:o |de |seu |o seu )?"
                    r"(?:autoestudo|aprendizado|aprender|estudar sozinho)\b")
_VOLTA = re.compile(r"\b(?:volta|volte|continua|continue|retoma|retome|liga|ligue|pode)\s+(?:a |o |seu |o seu )?"
                    r"(?:aprender|aprendizado|autoestudo|estudar sozinho)\b")
_PEDIDO = re.compile(r"\b(?:aprende|aprenda|vai aprender|pesquisa e aprende|estuda sozinho|estude sozinho|"
                     r"estuda pra mim|estuda para mim|completa (?:a trilha|o conteudo)|atualiza (?:a trilha|o conteudo))"
                     r"\s+(?:sobre |de |do |da |a |o |as |os )?(.+)$")


def _assunto_da_fala(texto: str) -> str:
    """O assunto pedido, com os acentos de como foi dito ("a história do xadrez")."""
    t = norm(texto)
    m = _PEDIDO.search(t)
    assunto = m.group(1) if m else t
    assunto = re.sub(r"\b(pra mim|para mim|por favor|agora|ai|sozinho|tudo)\b", " ", assunto)
    assunto = re.sub(r"\s+", " ", assunto).strip(" ,.?!")
    palavras = re.findall(r"[^\W_]+", texto)
    normais = [norm(p) for p in palavras]
    alvo = assunto.split()
    for i in range(len(normais) - len(alvo) + 1):
        if alvo and normais[i:i + len(alvo)] == alvo:
            return " ".join(palavras[i:i + len(alvo)])
    return assunto


def entender(texto: str) -> tuple[str, str] | None:
    """("status"|"hoje"|"semana"|"pausar"|"retomar"|"pedir", texto) ou None."""
    t = norm(texto)
    t = re.sub(r"^(?:socrates|ei socrates|ok)\s+", "", t)
    if _PAUSA.search(t):
        return "pausar", texto
    if _VOLTA.search(t):
        return "retomar", texto
    if _STATUS.search(t):
        return "status", texto
    if _HOJE.search(t):
        return ("semana" if re.search(r"\b(semana|ultimos dias)\b", t) else "hoje"), texto
    if _PEDIDO.search(t):
        return "pedir", texto
    return None
