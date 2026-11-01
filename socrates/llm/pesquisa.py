"""Cérebro que pesquisa na internet quando a pergunta pede algo atual.

Decide em dois níveis:
  1. Palavras óbvias ("cotação do dólar", "edital", "vai chover") vão direto
     para a pesquisa, sem perder tempo.
  2. No resto, o modelo responde normal. Se ele não souber por ser algo
     atual, responde só "PESQUISAR" (instrução em core/contexto.py), e aí a
     pesquisa é feita. Essa palavra nunca chega à tela nem à voz.

Enquanto pesquisa, ele diz "Vou pesquisar isso." para você não ficar no silêncio.
"""

from __future__ import annotations

import logging
import re
import unicodedata
from typing import AsyncIterator

from .base import Cerebro, ErroPesquisa, Mensagem

log = logging.getLogger("socrates.pesquisa")

MARCADOR = "pesquisar"
AVISO = "Vou pesquisar isso. "
ESPIAR = 12   # quantos caracteres olhar antes de decidir se é o marcador

INSTRUCAO = """AGORA você está no modo de pesquisa: use a ferramenta de busca na internet
(browser_search) para encontrar a resposta. Não responda "PESQUISAR".
Depois de pesquisar, responda em no máximo 4 frases curtas, para serem FALADAS em voz alta.
Diga a fonte pelo nome (por exemplo: "segundo o g1"), nunca leia links.
Se a pesquisa não trouxer a resposta, diga isso com franqueza."""

# Pedidos diretos: "pesquisa...", "procura na internet..."
_PEDIDO = re.compile(r"^(pesquis|procur|busc)\w*\b|\b(na internet|no google|na web)\b")

# Assuntos que quase sempre dependem de informação atual
_ATUAL = re.compile(
    r"\b(hoje|agora|atualmente|neste momento|esta semana|essa semana|este mes|esse mes|ontem|amanha"
    r"|noticia|noticias|aconteceu|acontecendo|ultimas"
    r"|previsao do tempo|como esta o tempo|como ta o tempo|vai chover|chovendo|temperatura"
    r"|cotacao|dolar|euro|bitcoin|preco|quanto custa|quanto ta custando"
    r"|placar|quem ganhou|resultado do jogo|jogo do|jogo de hoje|tabela do"
    r"|edital|inscricoes|inscricao|data da prova|concurso da|concurso do|vagas"
    r"|lancamento|lancou|lancaram|eleicao|eleito|presidente atual"
    r"|horario de funcionamento|esta aberto|ta aberto)\b"
)

# "hoje"/"agora" sozinhos não bastam quando é pedido de estudo
_ESTUDO = re.compile(r"\b(me testa|me explica|explica|exercicio|questao|questoes|revisar|estudar)\b")


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


# Data e hora ele já sabe (vêm do relógio do PC): não gasta pesquisa com isso
_DATA = re.compile(r"\b(que dia|que horas|qual a data|qual e a data|dia da semana|que mes|que ano)\b")
_TEMPO_RELATIVO = re.compile(r"\b(hoje|agora|amanha|ontem)\b")


def precisa_pesquisar(pergunta: str) -> bool:
    t = _norm(pergunta)
    if _PEDIDO.search(t):
        return True
    if _ESTUDO.search(t):
        return False
    if _DATA.search(t):
        t = _TEMPO_RELATIVO.sub(" ", t)   # "que dia é hoje" não; "que dia sai o edital" sim
    return bool(_ATUAL.search(t))


_CITACAO = re.compile(r"【[^】]*】|\[\d+(?:[,†][^\]]*)?\]")
_LINK = re.compile(r"\(?https?://[^\s)\]]+\)?")


def limpar_resposta(texto: str) -> str:
    texto = _CITACAO.sub("", texto)
    texto = _LINK.sub("", texto)
    texto = re.sub(r"[ \t]+([.,;:!?])", r"\1", texto)
    return re.sub(r"[ \t]{2,}", " ", texto).strip()


def _com_instrucao(mensagens: list[Mensagem]) -> list[Mensagem]:
    """Prepara as mensagens para a pesquisa: tira a regra "responda PESQUISAR"
    (senão o modelo obedece a ela em vez de usar a busca) e põe a de pesquisar."""
    from ..core.contexto import INSTRUCAO_PESQUISA

    copia = [dict(m) for m in mensagens]
    # respostas antigas "PESQUISAR" no histórico também confundem o modelo
    copia = [m for m in copia if not (m["role"] == "assistant"
                                      and _norm(m["content"]).startswith(MARCADOR)
                                      and len(m["content"]) < 20)]
    if copia and copia[0]["role"] == "system":
        copia[0]["content"] = copia[0]["content"].replace(INSTRUCAO_PESQUISA, "").rstrip()
        copia[0]["content"] += "\n\n" + INSTRUCAO
    else:
        copia.insert(0, {"role": "system", "content": INSTRUCAO})
    return copia


class CerebroComPesquisa(Cerebro):
    def __init__(self, base: Cerebro):
        if not hasattr(base, "pesquisar"):
            raise TypeError("o cérebro base precisa ter o método pesquisar()")
        self.base = base
        self.nome = f"{base.nome}+pesquisa"
        self.pesquisas = 0

    async def _pesquisar(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        yield AVISO
        self.pesquisas += 1
        try:
            texto = limpar_resposta(await self.base.pesquisar(_com_instrucao(mensagens)))
        except ErroPesquisa as e:
            log.warning("pesquisa falhou: %s", e)
            yield f"Não consegui pesquisar agora. {e}"
            return
        if not texto or _norm(texto).startswith(MARCADOR):
            texto = "A pesquisa não trouxe nada útil. Tente perguntar de outro jeito."
        yield texto

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        pergunta = next((m["content"] for m in reversed(mensagens) if m["role"] == "user"), "")
        if precisa_pesquisar(pergunta):
            log.info("pesquisa direta: %r", pergunta[:60])
            async for p in self._pesquisar(mensagens):
                yield p
            return

        # Espia o começo da resposta: se for o marcador, troca para a pesquisa
        inicio = ""
        fluxo = self.base.responder(mensagens).__aiter__()
        async for pedaco in fluxo:
            inicio += pedaco
            if len(inicio.strip()) >= ESPIAR:
                break
        if _norm(inicio).startswith(MARCADOR):
            log.info("o modelo pediu pesquisa: %r", pergunta[:60])
            async for _ in fluxo:   # descarta o resto da resposta sem pesquisa
                pass
            async for p in self._pesquisar(mensagens):
                yield p
            return

        if inicio:
            yield inicio
        async for pedaco in fluxo:
            yield pedaco
