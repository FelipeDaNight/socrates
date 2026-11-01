"""Pesquisa na internet sem chave nem conta: busca no DuckDuckGo e quem lê e
resume os resultados é o modelo LOCAL. Usada no modo `cerebro: local`."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from . import ferramenta

log = logging.getLogger("socrates.busca")

MAX_RESULTADOS = 5


def buscar(consulta: str, quantos: int = MAX_RESULTADOS) -> list[dict]:
    from ddgs import DDGS
    return list(DDGS().text(consulta, region="br-pt", safesearch="moderate",
                            max_results=quantos) or [])


@ferramenta("Pesquisa na internet (notícias, preços, clima, editais, fatos recentes). "
            "Depois responda citando o site pelo nome.",
            params={"consulta": "O que pesquisar, em poucas palavras"})
def pesquisar_na_internet(consulta: str) -> str:
    try:
        resultados = buscar(consulta)
    except ImportError:
        return "Erro: falta instalar o pacote ddgs (rode pip install -r requirements.txt)."
    except Exception as e:
        log.warning("busca falhou: %s", e)
        return f"Erro: a busca não respondeu ({str(e)[:100]}). Pode ser falta de internet."
    if not resultados:
        return "A busca não encontrou nada. Tente com outras palavras."
    linhas = []
    for r in resultados:
        site = urlparse(r.get("href", "")).netloc.removeprefix("www.")
        linhas.append(f"- {r.get('title', '').strip()} ({site}): {r.get('body', '').strip()[:300]}")
    return "Resultados da busca:\n" + "\n".join(linhas)
