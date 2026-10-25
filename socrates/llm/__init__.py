from ..config import ConfigLLM
from .base import Cerebro, ErroCerebro, Mensagem
from .compativel_openai import CerebroCompativelOpenAI


def criar_cerebro(cfg: ConfigLLM) -> Cerebro:
    """Fábrica: lê o config e devolve o cérebro certo."""
    return CerebroCompativelOpenAI(
        base_url=cfg.base_url,
        chave=cfg.chave or "",
        modelo=cfg.modelo,
        temperatura=cfg.temperatura,
        nome=cfg.provedor,
    )


__all__ = ["Cerebro", "ErroCerebro", "Mensagem", "criar_cerebro"]
