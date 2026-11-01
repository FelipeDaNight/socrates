import logging

from ..config import ConfigLLM
from .base import Cerebro, ErroCerebro, ErroPesquisa, Mensagem
from .compativel_openai import CerebroCompativelOpenAI

log = logging.getLogger("socrates.llm")


def pesquisa_disponivel(cfg: ConfigLLM) -> bool:
    """A busca embutida só existe no Groq, nos modelos gpt-oss."""
    return cfg.provedor == "groq" and "gpt-oss" in cfg.modelo


def criar_cerebro(cfg: ConfigLLM, pesquisa: bool = False, acoes: bool = False) -> Cerebro:
    """Fábrica: lê o config e devolve o cérebro certo.

    Camadas: ações no PC  ->  pesquisa na internet  ->  cérebro base
    """
    base = CerebroCompativelOpenAI(
        base_url=cfg.base_url,
        chave=cfg.chave or "",
        modelo=cfg.modelo,
        temperatura=cfg.temperatura,
        nome=cfg.provedor,
    )
    cerebro: Cerebro = base
    if pesquisa:
        if pesquisa_disponivel(cfg):
            from .pesquisa import CerebroComPesquisa
            cerebro = CerebroComPesquisa(base)
        else:
            log.warning("pesquisa pedida, mas %s/%s não tem busca embutida", cfg.provedor, cfg.modelo)
    if acoes:
        from .. import ferramentas
        from ..ferramentas import computador, janelas, tela  # registram as ações
        from .acoes import CerebroComAcoes
        modulos = {computador.__name__, janelas.__name__, tela.__name__}
        nomes = [n for n, f in ferramentas.REGISTRO.items() if f.funcao.__module__ in modulos]
        cerebro = CerebroComAcoes(cerebro, base, nomes)
        log.info("ações no PC: %s", ", ".join(nomes))
    return cerebro


__all__ = ["Cerebro", "ErroCerebro", "ErroPesquisa", "Mensagem", "criar_cerebro",
           "pesquisa_disponivel"]
