import logging

from ..config import ConfigLLM
from .base import Cerebro, ErroCerebro, ErroLimite, ErroPesquisa, Mensagem
from .compativel_openai import CerebroCompativelOpenAI

log = logging.getLogger("socrates.llm")


def pesquisa_disponivel(cfg: ConfigLLM | list[ConfigLLM]) -> bool:
    """A busca embutida só existe no Groq, nos modelos gpt-oss."""
    lista = cfg if isinstance(cfg, list) else [cfg]
    return any(c.provedor.startswith("groq") and "gpt-oss" in c.modelo for c in lista)


def membro(cfg: ConfigLLM, reserva: str | None = None) -> CerebroCompativelOpenAI:
    return CerebroCompativelOpenAI(base_url=cfg.base_url, chave=cfg.chave or "", modelo=cfg.modelo,
                                   temperatura=cfg.temperatura, nome=cfg.provedor,
                                   modelo_reserva=reserva)


def _juntar(cfgs: list[ConfigLLM]):
    """Um só cérebro, ou o rodízio de vários."""
    from .rodizio import CerebroRodizio
    membros = [membro(c) for c in cfgs]
    return membros[0] if len(membros) == 1 else CerebroRodizio(membros)


def criar_cerebro(cfg: ConfigLLM, pesquisa: bool = False, acoes: bool = False,
                  rodizio: list[ConfigLLM] | None = None,
                  rodizio_acoes: list[ConfigLLM] | None = None) -> Cerebro:
    """Fábrica. Camadas: ações no PC -> pesquisa na internet -> cérebro (ou rodízio).

    Sem `rodizio`, usa só `cfg` (com o modelo_acoes como reserva, se houver).
    """
    if rodizio:
        base = _juntar(rodizio)
    else:
        base = membro(cfg, reserva=cfg.modelo_acoes)

    cerebro: Cerebro = base
    if pesquisa:
        if getattr(base, "pesquisa_ok", False):
            from .pesquisa import CerebroComPesquisa
            cerebro = CerebroComPesquisa(base)
        else:
            log.warning("pesquisa pedida, mas nenhum cérebro tem busca embutida")
    if acoes:
        from .. import ferramentas
        from .acoes import CerebroComAcoes
        nomes = ferramentas.nomes_das_acoes()
        if rodizio_acoes:
            maos = _juntar(rodizio_acoes)
        elif not rodizio and cfg.modelo_acoes and cfg.modelo_acoes != cfg.modelo:
            maos = CerebroCompativelOpenAI(base_url=cfg.base_url, chave=cfg.chave or "",
                                           modelo=cfg.modelo_acoes, nome=f"{cfg.provedor}-acoes",
                                           modelo_reserva=cfg.modelo)
        else:
            maos = base
        cerebro = CerebroComAcoes(cerebro, maos, nomes)
        log.info("ações no PC: %s", ", ".join(nomes))
    return cerebro


__all__ = ["Cerebro", "ErroCerebro", "ErroLimite", "ErroPesquisa", "Mensagem", "criar_cerebro",
           "pesquisa_disponivel", "membro"]
