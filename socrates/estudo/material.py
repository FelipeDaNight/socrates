"""O material de estudo: os mesmos bancos do app estudo-prf (questões e lei seca).

Os arquivos são baixados uma vez do GitHub para a pasta `material/` (e atualizados
com `main.py --material`). Funciona sem internet depois disso.

Questões suas (por exemplo, as que você errou no Gran Questões) ficam em
Documentos\\Socrates\\questoes\\*.json, no mesmo formato do app:
    {"questoes": [{"materia", "topico", "tipo": "ce"|"mc", "resp", "enunciado",
                   "alternativas"?, "just"?}]}
"""

from __future__ import annotations

import json
import logging
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from ..config import RAIZ

log = logging.getLogger("socrates.material")

FONTE = "https://raw.githubusercontent.com/FelipeDaNight/estudo-prf/main/"
PASTA = RAIZ / "material"
PASTA_PRIVADA = Path.home() / "Documents" / "Socrates" / "questoes"

ID_PRIVADO = "meus-erros"


class ErroMaterial(Exception):
    pass


def _baixar(url: str, timeout: float = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "socrates"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def baixar(fonte: str = FONTE, pasta: Path | None = None, escrever=print,
           buscar=_baixar) -> int:
    """Baixa os índices e todos os bancos. Devolve quantos arquivos baixou."""
    pasta = pasta or PASTA
    (pasta / "bancos").mkdir(parents=True, exist_ok=True)
    arquivos = []
    for indice in ("bancos/index.json", "bancos/lei-index.json"):
        dados = buscar(fonte + indice)
        (pasta / indice).write_bytes(dados)
        conteudo = json.loads(dados)
        arquivos += [i["arquivo"] if isinstance(i, dict) else i for i in conteudo]
    for arq in arquivos:
        escrever(f"     {arq}")
        (pasta / arq).parent.mkdir(parents=True, exist_ok=True)
        (pasta / arq).write_bytes(buscar(fonte + arq))
    return len(arquivos) + 2


@dataclass
class Material:
    bancos: dict[str, dict] = field(default_factory=dict)    # id -> banco de questões
    leis: list[dict] = field(default_factory=list)           # cadernos de lei seca

    @property
    def vazio(self) -> bool:
        return not self.bancos and not self.leis

    def blocos(self):
        for caderno in self.leis:
            for bloco in caderno.get("blocos", []):
                yield caderno, bloco


def _ler(caminho: Path):
    return json.loads(caminho.read_text(encoding="utf-8"))


def carregar_privadas(pasta: Path | None = None) -> dict | None:
    pasta = pasta or PASTA_PRIVADA
    if not pasta.exists():
        return None
    questoes = []
    for arq in sorted(pasta.glob("*.json")):
        try:
            dados = _ler(arq)
        except (OSError, json.JSONDecodeError) as e:
            log.warning("não consegui ler %s: %s", arq, e)
            continue
        lista = dados.get("questoes", []) if isinstance(dados, dict) else dados
        questoes += [q for q in lista if isinstance(q, dict) and q.get("enunciado") and q.get("resp")]
    if not questoes:
        return None
    for i, q in enumerate(questoes, 1):
        q.setdefault("n", i)
        q.setdefault("materia", "Meus erros")
        q.setdefault("topico", q["materia"])
        q.setdefault("tipo", "mc" if q.get("alternativas") else "ce")
    return {"id": ID_PRIVADO, "titulo": "Meus erros", "banca": "", "tipo": "mix",
            "questoes": questoes}


def carregar(pasta: Path | None = None, pasta_privada: Path | None = None,
             baixar_se_faltar: bool = True) -> Material:
    pasta = pasta or PASTA
    if baixar_se_faltar and not (pasta / "bancos" / "index.json").exists():
        try:
            log.info("baixando o material de estudo pela primeira vez")
            baixar(pasta=pasta, escrever=lambda *a, **k: None)
        except Exception as e:   # sem internet: segue só com o que tiver
            log.warning("não consegui baixar o material: %s", e)
    m = Material()
    try:
        for info in _ler(pasta / "bancos" / "index.json"):
            banco = _ler(pasta / info["arquivo"])
            for i, q in enumerate(banco.get("questoes", []), 1):
                q.setdefault("n", i)
            m.bancos[banco["id"]] = banco
        for arq in _ler(pasta / "bancos" / "lei-index.json"):
            m.leis.append(_ler(pasta / arq))
    except (OSError, json.JSONDecodeError, KeyError) as e:
        log.warning("material incompleto: %s", e)
    privado = carregar_privadas(pasta_privada)
    if privado:
        m.bancos[ID_PRIVADO] = privado
    return m
