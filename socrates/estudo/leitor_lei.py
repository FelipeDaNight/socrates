"""Lê a lei no site oficial (Planalto) e separa os artigos, só com o texto em vigor.

No Planalto, o texto antigo fica riscado (<strike>) logo antes do novo, e cada mudança
traz a nota "(Redação dada pela Lei nº 15.397, de 2026)". Aqui:
  - o riscado sai (fica só o que vale hoje);
  - cada artigo vira um bloco ("Art. 155", "Art. 121-A");
  - as notas de mudança viram uma lista (lei e ano), que o autoestudo usa para saber
    o que mudou depois que a trilha foi escrita.

O texto baixado fica guardado em Documentos\\Socrates\\leis por alguns dias.
"""

from __future__ import annotations

import html as html_mod
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

log = logging.getLogger("socrates.lei")

PASTA_CACHE = Path.home() / "Documents" / "Socrates" / "leis"
VALIDADE_DIAS = 7                 # baixa de novo depois disso (a lei pode ter mudado)
TEMPO_LIMITE = 40
NAVEGADOR = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
             "Chrome/124.0 Safari/537.36")

# texto riscado (revogado ou com redação antiga)
_RISCADO = re.compile(r"<(strike|s|del)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_RISCADO_ESTILO = re.compile(
    r"<(span|font|p)\b[^>]*text-decoration\s*:\s*line-through[^>]*>.*?</\1\s*>", re.I | re.S)
_LIXO = re.compile(r"<(script|style|head)\b[^>]*>.*?</\1\s*>", re.I | re.S)
_QUEBRA = re.compile(r"<\s*(br|/p|/div|/h\d|/tr|/li|/blockquote|p|div|tr|li|blockquote)\b[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_ESPACOS = re.compile(r"[ \t\r\f\v ]+")

# "Art. 1º", "Art. 1o", "Art. 121-A.", "Art. 1.001.", "Art. 5o-A" (no começo da linha, sem aspas)
# (o sufixo vem colado: "Art. 3º-A." é o 3-A; "Art. 3º - A lei..." é o 3º)
_ARTIGO = re.compile(r"^\s*Art\.\s*(\d{1,2}\.\d{3}|\d+)\s*(?:º|°|o(?![a-z])|ª)?"
                     r"(?:-([A-Z])(?![A-Za-zÀ-ú])(?!\s+[a-zà-ú]))?\s*[.\-–—]?\s*", re.M)
_NOTA = re.compile(r"\(\s*(?:Reda[cç][aã]o dada|Inclu[ií]d[oa]|Acrescid[oa]|Acrescentad[oa]|"
                   r"Revogad[oa]|Renumerad[oa]|Vig[eê]ncia|Vide)[^()]*\)", re.I)
_LEI_DA_NOTA = re.compile(r"(Lei Complementar|Lei|Decreto-Lei|Decreto|Medida Provis[oó]ria|"
                          r"Emenda Constitucional)\s*(?:n[º°o.]?\s*)?([\d.]+)\s*,\s*de\s*(?:\d{1,2}\s*"
                          r"(?:º|o)?\s*(?:de\s*)?\w+\s*de\s*)?(\d{4})", re.I)


class ErroLei(Exception):
    """Não deu para baixar ou ler a lei (o autoestudo tenta outra fonte)."""


@dataclass
class Artigo:
    numero: int
    sufixo: str                       # "" ou "A", "B"...
    texto: str                        # só o que está em vigor, com as notas de mudança
    mudancas: list[tuple[str, int]] = field(default_factory=list)   # [("Lei 15.397", 2026)]

    @property
    def chave(self) -> str:
        return f"{self.numero}-{self.sufixo}" if self.sufixo else str(self.numero)

    @property
    def rotulo(self) -> str:
        return f"Art. {self.numero}" + (f"-{self.sufixo}" if self.sufixo else "")

    @property
    def ultima_mudanca(self) -> int:
        return max((ano for _, ano in self.mudancas), default=0)

    def sem_notas(self) -> str:
        return _ESPACOS.sub(" ", _NOTA.sub("", self.texto)).strip()


# ---------- HTML -> texto ----------

def decodificar(dados: bytes, tipo: str = "") -> str:
    """O Planalto mistura UTF-8 e Windows-1252."""
    m = re.search(r"charset=([\w-]+)", tipo or "", re.I) or \
        re.search(rb"charset=[\"']?([\w-]+)", dados[:3000], re.I)
    declarado = (m.group(1).decode() if isinstance(m.group(1), bytes) else m.group(1)).lower() if m else ""
    try:
        return dados.decode("utf-8")
    except UnicodeDecodeError:
        pass
    for cod in (declarado, "cp1252", "latin-1"):
        if not cod or cod in ("utf-8", "utf8"):
            continue
        try:
            return dados.decode(cod)
        except (UnicodeDecodeError, LookupError):
            continue
    return dados.decode("latin-1", errors="replace")


def texto_em_vigor(pagina: str) -> str:
    """O texto da página sem o que está riscado, um parágrafo por linha."""
    t = _LIXO.sub(" ", pagina)
    t = _RISCADO.sub(" ", t)
    t = _RISCADO_ESTILO.sub(" ", t)
    t = re.sub(r"<sup>\s*(?:<u>)?\s*o\s*(?:</u>)?\s*</sup>", "º", t, flags=re.I)  # 1<sup>o</sup>
    t = re.sub(r"<sup>\s*(?:<u>)?\s*a\s*(?:</u>)?\s*</sup>", "ª", t, flags=re.I)
    t = _QUEBRA.sub("\n", t)
    t = _TAG.sub("", t)
    t = html_mod.unescape(t)
    linhas = []
    for linha in t.split("\n"):
        linha = _ESPACOS.sub(" ", linha).strip()
        if linha:
            linhas.append(linha)
    return "\n".join(linhas)


def separar_artigos(texto: str) -> dict[str, Artigo]:
    """{"155": Artigo, "121-A": Artigo}. Se o mesmo artigo aparece duas vezes (texto
    antigo sem risco), vale o último, que é o mais novo."""
    marcas = list(_ARTIGO.finditer(texto))
    artigos: dict[str, Artigo] = {}
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        corpo = texto[m.start():fim].strip()
        corpo = re.split(r"\n(?:Brasília|Rio de Janeiro),\s*\d", corpo)[0]   # assinatura da lei
        numero = int(m.group(1).replace(".", ""))
        art = Artigo(numero, m.group(2) or "", _juntar_linhas(corpo))
        art.mudancas = mudancas_do_texto(art.texto)
        if len(art.sem_notas()) < 8 and art.chave in artigos:
            continue
        artigos[art.chave] = art
    return artigos


def _juntar_linhas(corpo: str) -> str:
    """Junta as linhas quebradas no meio da frase, mantendo incisos e parágrafos."""
    saida = []
    for linha in corpo.split("\n"):
        nova = bool(re.match(r"^(?:[IVXLC]+\s*[-–—]|§|Parágrafo|Pena|[a-z]\)|Art\.)", linha))
        if saida and not nova and not saida[-1].endswith((":", ";", ".")):
            saida[-1] += " " + linha
        else:
            saida.append(linha)
    return "\n".join(saida)


def mudancas_do_texto(texto: str) -> list[tuple[str, int]]:
    vistos, saida = set(), []
    for nota in _NOTA.findall(texto):
        for tipo, numero, ano in _LEI_DA_NOTA.findall(_ESPACOS.sub(" ", nota)):
            chave = (f"{_tipo_curto(tipo)} {numero}", int(ano))
            if chave not in vistos:
                vistos.add(chave)
                saida.append(chave)
    return saida


def _tipo_curto(tipo: str) -> str:
    t = tipo.lower()
    if "complementar" in t:
        return "LC"
    if "emenda" in t:
        return "EC"
    if "medida" in t:
        return "MP"
    if "decreto-lei" in t:
        return "Decreto-Lei"
    return "Decreto" if t.startswith("decreto") else "Lei"


# ---------- faixas de artigos ----------

def no_intervalo(art: Artigo, inicio: tuple[int, str], fim: tuple[int, str]) -> bool:
    return inicio <= (art.numero, art.sufixo) <= fim


def trecho(artigos: dict[str, Artigo], inicio: tuple[int, str], fim: tuple[int, str],
           limite: int = 6000) -> str:
    """Os artigos da faixa, em ordem, cortados no limite de caracteres."""
    escolhidos = sorted((a for a in artigos.values() if no_intervalo(a, inicio, fim)),
                        key=lambda a: (a.numero, a.sufixo))
    partes, total = [], 0
    for a in escolhidos:
        bloco = a.texto
        if total + len(bloco) > limite:
            sobra = limite - total
            if sobra > 300:
                partes.append(bloco[:sobra].rsplit(" ", 1)[0] + " [...]")
            break
        partes.append(bloco)
        total += len(bloco) + 2
    return "\n\n".join(partes)


def mudancas_desde(artigos: dict[str, Artigo], ano: int, inicio=(0, ""), fim=(99999, "Z")
                   ) -> list[tuple[Artigo, str, int]]:
    """Artigos da faixa mudados por lei de `ano` em diante: [(artigo, "Lei 15.397", 2026)]."""
    saida = []
    for a in sorted(artigos.values(), key=lambda a: (a.numero, a.sufixo)):
        if not no_intervalo(a, inicio, fim):
            continue
        for lei, a_ano in a.mudancas:
            if a_ano >= ano:
                saida.append((a, lei, a_ano))
    return saida


# ---------- baixar (com cache) ----------

def baixar(url: str, tempo_limite: float = TEMPO_LIMITE) -> str:
    pedido = urllib.request.Request(url, headers={"User-Agent": NAVEGADOR,
                                                  "Accept-Language": "pt-BR,pt;q=0.9"})
    try:
        with urllib.request.urlopen(pedido, timeout=tempo_limite) as r:
            return decodificar(r.read(), r.headers.get("Content-Type", ""))
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise ErroLei(f"não consegui baixar {url}: {e}") from e


class Biblioteca:
    """As leis do registro (planos/leis.json), baixadas e guardadas por alguns dias."""

    def __init__(self, registro: dict[str, dict], pasta: Path | None = None, baixar_pagina=None,
                 hoje=date.today):
        self.registro = registro
        self.pasta = pasta or PASTA_CACHE
        self.baixar_pagina = baixar_pagina or baixar
        self.hoje = hoje
        self._memoria: dict[str, dict[str, Artigo]] = {}

    def nome(self, sigla: str) -> str:
        return (self.registro.get(sigla) or {}).get("nome", sigla)

    def url(self, sigla: str) -> str:
        return (self.registro.get(sigla) or {}).get("url", "")

    def _arquivo(self, sigla: str) -> Path:
        return self.pasta / f"{re.sub(r'[^A-Za-z0-9_-]', '_', sigla)}.json"

    def em_cache(self, sigla: str) -> dict[str, Artigo] | None:
        """A cópia já guardada (de qualquer idade), sem internet: para ler na hora."""
        if sigla in self._memoria:
            return self._memoria[sigla]
        try:
            guardado = json.loads(self._arquivo(sigla).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not guardado.get("artigos") or guardado.get("url") != self.url(sigla):
            return None
        return {k: Artigo(v["n"], v["s"], v["t"], [tuple(x) for x in v.get("m", [])])
                for k, v in guardado["artigos"].items()}

    def artigos(self, sigla: str) -> dict[str, Artigo]:
        if sigla in self._memoria:
            return self._memoria[sigla]
        url = self.url(sigla)
        if not url:
            raise ErroLei(f"sem endereço oficial para {sigla}")
        arq = self._arquivo(sigla)
        guardado = None
        try:
            guardado = json.loads(arq.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if guardado and guardado.get("url") == url and _dias(guardado.get("data"), self.hoje()) < VALIDADE_DIAS:
            arts = {k: Artigo(v["n"], v["s"], v["t"], [tuple(x) for x in v.get("m", [])])
                    for k, v in guardado["artigos"].items()}
        else:
            try:
                arts = separar_artigos(texto_em_vigor(self.baixar_pagina(url)))
            except ErroLei:
                if guardado:                    # sem internet: usa o que já tinha
                    log.warning("usando a cópia guardada de %s", sigla)
                    arts = {k: Artigo(v["n"], v["s"], v["t"], [tuple(x) for x in v.get("m", [])])
                            for k, v in guardado["artigos"].items()}
                    self._memoria[sigla] = arts
                    return arts
                raise
            if not arts:
                raise ErroLei(f"a página de {sigla} veio sem artigos")
            try:
                self.pasta.mkdir(parents=True, exist_ok=True)
                arq.write_text(json.dumps({
                    "url": url, "data": self.hoje().isoformat(),
                    "artigos": {k: {"n": a.numero, "s": a.sufixo, "t": a.texto, "m": a.mudancas}
                                for k, a in arts.items()}}, ensure_ascii=False), encoding="utf-8")
            except OSError as e:
                log.warning("não guardei a lei %s: %s", sigla, e)
        self._memoria[sigla] = arts
        return arts


def _dias(iso: str | None, hoje: date) -> int:
    try:
        return (hoje - date.fromisoformat(iso)).days
    except (TypeError, ValueError):
        return 10 ** 6


def faixa(texto: str) -> tuple[str, tuple[int, str], tuple[int, str]] | None:
    """"CPP 301-310" -> ("CPP", (301, ""), (310, "Z")); "L12850 1-21-B" -> fim (21, "B")."""
    m = re.match(r"^([A-Z][A-Z0-9]*)\s+(\d+)(?:-([A-Z]))?(?:-(\d+)(?:-([A-Z]))?)?$", texto.strip())
    if not m:
        return None
    sigla, ini, s_ini, fim, s_fim = m.groups()
    inicio = (int(ini), s_ini or "")
    final = (int(fim), s_fim or "Z") if fim else (int(ini), s_ini or "Z")
    return sigla, inicio, final


def agora() -> float:
    return time.monotonic()
