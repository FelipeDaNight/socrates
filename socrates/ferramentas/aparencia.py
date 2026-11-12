"""A aparência do próprio Sócrates: a cor do visor, mudada por voz e na hora.

  "Sócrates, muda a cor do visor para azul"
"""

from __future__ import annotations

import logging

from ..visor import cores
from . import ferramenta

log = logging.getLogger("socrates.aparencia")

PAINEL = None     # main.py liga ao visor aberto


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
