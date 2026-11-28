"""Vigia de notícias dos concursos (PRF e CBMGO), de graça.

Com o Sócrates aberto, a cada poucas horas ele procura notícias recentes na busca de notícias
do DuckDuckGo (o mesmo pacote `ddgs` da pesquisa: sem chave, sem conta e sem gastar o cérebro),
fica só com as que falam do concurso E de edital, banca, inscrição, vagas, prova..., e avisa
cada novidade uma vez só, quando você não está no meio de uma conversa:

    "Novidade do concurso da PRF: Concurso PRF tem novo pedido de edital, no Estratégia."

As já avisadas ficam em Documentos\\Socrates\\noticias.json. Na primeira vez ele não despeja
tudo o que já saiu: avisa só a mais recente de cada concurso e guarda o resto como visto.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

log = logging.getLogger("socrates.noticias")

CONCURSOS = {
    "prf": {
        "nome": "PRF",
        "buscas": ["concurso PRF edital", "concurso Polícia Rodoviária Federal"],
        "precisa": re.compile(r"\bprf\b|policia rodoviaria federal"),
    },
    "cbmgo": {
        "nome": "Bombeiros de Goiás",
        "buscas": ["concurso CBMGO edital", "concurso Corpo de Bombeiros Goiás"],
        "precisa": re.compile(r"\bcbm[ -]?go\b|bombeiros?\b.{0,40}\b(?:goias|go)\b|\bgoias\b.{0,40}\bbombeiros?\b"),
    },
}
# Tem que ser sobre o concurso, não qualquer notícia da PRF (acidente, apreensão...)
ASSUNTO = re.compile(r"\b(concursos?|edital|editais|inscric\w*|banca|vagas?|autoriza\w*|provas?|gabarito|"
                     r"resultado|cronograma|nomea\w*|convoca\w*|homologa\w*|selecao|aprovados?|posse)\b")
MAX_DIAS = 10                  # notícia mais velha que isso não é novidade
MAX_POR_VEZ = 3                # avisos de uma vez (o resto fica no visor)
GUARDA_VISTAS = 400
MAX_RESUMO = 400


@dataclass
class Noticia:
    concurso: str              # prf | cbmgo
    titulo: str
    fonte: str
    url: str
    data: str = ""             # ISO, quando a busca informa
    resumo: str = ""           # o trecho que a busca mostra: é o que ele conta quando você pergunta

    @property
    def chave(self) -> str:
        return _chave(self.titulo)

    def falada(self) -> str:
        nome = CONCURSOS.get(self.concurso, {}).get("nome", self.concurso.upper())
        fonte = f", no {self.fonte}" if self.fonte else ""
        return f"Novidade do concurso {('da ' + nome) if nome == 'PRF' else ('dos ' + nome)}: {self.titulo}{fonte}."


def _sem_acento(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _chave(titulo: str) -> str:
    """O mesmo título em sites diferentes conta uma vez só."""
    return re.sub(r"[^a-z0-9]+", " ", _sem_acento(titulo)).strip()[:120]


def _data(texto: str) -> datetime | None:
    if not texto:
        return None
    try:
        d = datetime.fromisoformat(str(texto).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def relevante(concurso: str, titulo: str, resumo: str = "") -> bool:
    """Fala do concurso certo E de edital/inscrição/prova... (o título pesa mais)."""
    t = _sem_acento(titulo)
    tudo = f"{t} {_sem_acento(resumo)}"
    regra = CONCURSOS[concurso]["precisa"]
    return bool(regra.search(t) or regra.search(tudo)) and bool(ASSUNTO.search(t))


def buscar_ddgs(consulta: str) -> list[dict]:
    """Busca de notícias do DuckDuckGo (pacote ddgs, já instalado com o Sócrates)."""
    from ddgs import DDGS
    return list(DDGS().news(consulta, region="br-pt", safesearch="moderate", timelimit="w",
                            max_results=15) or [])


class Vigia:
    def __init__(self, arquivo: Path, concursos: list[str] | None = None,
                 buscar: Callable[[str], list[dict]] | None = None,
                 relogio: Callable[[], datetime] | None = None):
        self.arquivo = Path(arquivo)
        self.concursos = [c for c in (concursos or list(CONCURSOS)) if c in CONCURSOS]
        self.buscar = buscar or buscar_ddgs
        self.relogio = relogio or (lambda: datetime.now(timezone.utc))
        self.estado = self._ler()

    # ---------- arquivo ----------
    def _ler(self) -> dict:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
            if isinstance(dados, dict):
                dados.setdefault("vistas", {})
                dados.setdefault("recentes", [])
                return dados
        except (OSError, ValueError):
            pass
        return {"vistas": {}, "recentes": [], "ultima_busca": ""}

    def _salvar(self) -> None:
        vistas = self.estado["vistas"]
        if len(vistas) > GUARDA_VISTAS:          # esquece as mais antigas
            for k, _ in sorted(vistas.items(), key=lambda kv: kv[1])[:len(vistas) - GUARDA_VISTAS]:
                vistas.pop(k, None)
        try:
            self.arquivo.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        except OSError as e:
            log.warning("não consegui guardar as notícias: %s", e)

    # ---------- busca ----------
    def precisa_buscar(self, horas: float) -> bool:
        ultima = _data(self.estado.get("ultima_busca", ""))
        return ultima is None or self.relogio() - ultima >= timedelta(hours=horas)

    def _coletar(self) -> list[Noticia]:
        achadas: dict[str, Noticia] = {}
        limite = self.relogio() - timedelta(days=MAX_DIAS)
        for concurso in self.concursos:
            for consulta in CONCURSOS[concurso]["buscas"]:
                try:
                    resultados = self.buscar(consulta)
                except ImportError:
                    log.warning("notícias: falta o pacote ddgs (pip install -r requirements.txt)")
                    return []
                except Exception as e:           # sem internet, busca fora do ar: tenta depois
                    log.warning("notícias: a busca falhou (%s)", str(e)[:120])
                    continue
                for r in resultados or []:
                    titulo = re.sub(r"\s+", " ", str(r.get("title") or "")).strip()
                    url = str(r.get("url") or r.get("href") or "")
                    if not titulo or not relevante(concurso, titulo, str(r.get("body") or "")):
                        continue
                    quando = _data(str(r.get("date") or ""))
                    if quando is not None and quando < limite:
                        continue
                    fonte = str(r.get("source") or "").strip() or urlparse(url).netloc.removeprefix("www.")
                    resumo = re.sub(r"\s+", " ", str(r.get("body") or "")).strip()[:MAX_RESUMO]
                    n = Noticia(concurso, titulo, fonte, url, quando.isoformat() if quando else "",
                                resumo)
                    achadas.setdefault(n.chave, n)
        return sorted(achadas.values(), key=lambda n: n.data, reverse=True)

    def verificar(self) -> list[Noticia]:
        """Busca agora. Devolve só as novidades (ainda não avisadas), da mais nova à mais velha."""
        primeira = not self.estado["vistas"] and not self.estado.get("ultima_busca")
        achadas = self._coletar()
        agora = self.relogio().isoformat()
        self.estado["ultima_busca"] = agora
        novas = [n for n in achadas if n.chave not in self.estado["vistas"]]
        for n in novas:
            self.estado["vistas"][n.chave] = agora
        if primeira:                             # não despeja o que já tinha saído
            avisar, vistos = [], set()
            for n in novas:
                if n.concurso not in vistos:
                    vistos.add(n.concurso)
                    avisar.append(n)
            novas = avisar
        recentes = [n for n in map(_noticia, self.estado["recentes"]) if n is not None]
        juntas = {n.chave: n for n in [*recentes, *achadas]}   # a busca nova traz o resumo
        self.estado["recentes"] = [asdict(n) for n in
                                   sorted(juntas.values(), key=lambda n: n.data, reverse=True)[:10]]
        self._salvar()
        return novas[:MAX_POR_VEZ]

    def recentes(self, quantas: int = 5) -> list[Noticia]:
        return [n for n in map(_noticia, self.estado["recentes"][:quantas]) if n is not None]


def _noticia(dados) -> Noticia | None:
    """Uma notícia guardada no noticias.json (campo a mais ou a menos não derruba)."""
    if not isinstance(dados, dict):
        return None
    campos = {k: str(v or "") for k, v in dados.items() if k in Noticia.__dataclass_fields__}
    if not campos.get("titulo"):
        return None
    campos.setdefault("concurso", "prf")
    campos.setdefault("fonte", "")
    campos.setdefault("url", "")
    return Noticia(**campos)


def aviso(novas: list[Noticia]) -> str:
    """O que ele fala quando acha novidade."""
    if not novas:
        return ""
    if len(novas) == 1:
        return novas[0].falada()
    partes = " ".join(n.falada() for n in novas[:2])
    resto = len(novas) - 2
    return partes + (f" E mais {resto} no visor." if resto > 0 else "")


def para_o_visor(noticias: list[Noticia]) -> list[dict]:
    saida = []
    for n in noticias:
        d = _data(n.data)
        saida.append({"concurso": CONCURSOS.get(n.concurso, {}).get("nome", n.concurso),
                      "titulo": n.titulo, "fonte": n.fonte, "url": n.url,
                      "data": d.astimezone().strftime("%d/%m") if d else ""})
    return saida


def resumo_para_o_cerebro(novas: list[Noticia], recentes: list[Noticia]) -> str:
    """O que a ferramenta noticias_do_concurso devolve ao cérebro."""
    if not recentes and not novas:
        return ("Não achei notícia recente (últimos 10 dias) sobre edital, inscrição ou prova da PRF "
                "nem do CBMGO. Diga isso ao aluno; não invente.")
    linhas = []
    for n in recentes:
        d = _data(n.data)
        quando = d.astimezone().strftime("%d/%m") if d else "sem data"
        marca = " (NOVA)" if any(x.chave == n.chave for x in novas) else ""
        nome = CONCURSOS.get(n.concurso, {}).get("nome", n.concurso)
        linhas.append(f"- [{nome}] {n.titulo} ({n.fonte}, {quando}){marca}")
        if n.resumo:
            linhas.append(f"  Trecho: {n.resumo}")
    return ("Notícias recentes dos concursos (busca de notícias, títulos e trechos como saíram; a que "
            "você avisou está aqui. Conte ao aluno o essencial, só o que está escrito, e cite o "
            "site):\n" + "\n".join(linhas))

