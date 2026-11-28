"""A aparência do próprio Sócrates: a cor e o tamanho do visor, mudados por voz e na hora.

  "Sócrates, muda a cor do visor para azul"
  "Sócrates, coloca o seu visor grande na tela"
"""

from __future__ import annotations

import logging

from ..visor import cores
from ..visor import tamanho as janela_do_visor
from . import ferramenta

log = logging.getLogger("socrates.aparencia")

PAINEL = None     # main.py liga ao visor aberto
TAMANHO_NORMAL = {"largura": 1280, "altura": 760}   # main.py põe o do config


@ferramenta("Muda o tamanho da janela do visor do Sócrates: grande (ocupa a tela toda), normal "
            "(o tamanho de sempre, no centro da tela) ou pequeno. Vale na hora e fica guardado.",
            opcoes={"tamanho": list(janela_do_visor.TAMANHOS)})
def tamanho_do_visor(tamanho: str) -> str:
    nome = janela_do_visor.nome_do_tamanho(tamanho)
    if nome is None:
        return f"Não tenho o tamanho '{tamanho}'. Tenho: grande, normal e pequeno."
    feito = janela_do_visor.ajustar(nome, TAMANHO_NORMAL["largura"], TAMANHO_NORMAL["altura"])
    try:
        from ..config import gravar_local
        gravar_local({"visor": {"tamanho": nome}})
    except Exception as e:   # mudou na tela; só não ficou guardado
        log.warning("não consegui guardar o tamanho do visor: %s", e)
    return feito


@ferramenta("Muda a cor do visor do Sócrates (vale na hora e fica guardada).",
            opcoes={"cor": list(cores.CORES)})
def mudar_cor_do_visor(cor: str) -> str:
    nome = cores.nome_da_cor(cor)
    if nome is None:
        return f"Não tenho a cor '{cor}'. Tenho: {', '.join(cores.CORES)}."
    if PAINEL is not None:
        PAINEL.cor = nome
    try:
        from ..config import gravar_local
        gravar_local({"visor": {"cor": nome}})
    except Exception as e:   # mudou na tela; só não ficou guardado
        log.warning("não consegui guardar a cor: %s", e)
        return f"Mudei o visor para {nome}, mas não consegui guardar a escolha."
    return f"Pronto, o visor agora é {nome}."
