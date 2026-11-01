import logging

from ..config import ConfigLLM
from .base import Cerebro, ErroCerebro, ErroPesquisa, Mensagem
from .compativel_openai import CerebroCompativelOpenAI

log = logging.getLogger("socrates.llm")


def pesquisa_disponivel(cfg: ConfigLLM) -> bool:
    """A busca embutida só existe no Groq, nos modelos gpt-oss."""
    return cfg.provedor == "groq" and "gpt-oss" in cfg.modelo


def criar_cerebro(cfg: ConfigLLM, pesquisa: bool = False) -> Cerebro:
    """Fábrica: lê o config e devolve o cérebro certo."""
    base = CerebroCompativelOpenAI(
        base_url=cfg.base_url,
        chave=cfg.chave or "",
        modelo=cfg.modelo,
        temperatura=cfg.temperatura,
        nome=cfg.provedor,
    )
    if not pesquisa:
        return base
    if not pesquisa_disponivel(cfg):
        log.warning("pesquisa pedida, mas %s/%s não tem busca embutida", cfg.provedor, cfg.modelo)
        return base
    from .pesquisa import CerebroComPesquisa
    return CerebroComPesquisa(base)


__all__ = ["Cerebro", "ErroCerebro", "ErroPesquisa", "Mensagem", "criar_cerebro",
           "pesquisa_disponivel"]
