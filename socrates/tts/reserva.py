"""Voz principal com reserva: se a principal falhar, a frase sai na reserva.

Assim, se o Gemini bater o limite grátis no meio da explicação, o Sócrates
continua falando (com a voz do Edge) em vez de ficar mudo.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

from . import ErroVoz, Voz

log = logging.getLogger("socrates.voz")

FALHAS_PARA_DESCANSAR = 3
DESCANSO_SEG = 600   # depois de 3 falhas seguidas, usa só a reserva por 10 minutos


class VozComReserva(Voz):
    def __init__(self, principal: Voz, reserva: Voz,
                 avisar: Callable[[str], None] | None = None):
        self.principal = principal
        self.reserva = reserva
        self.avisar = avisar or (lambda t: None)
        self.falhas = 0
        self.descansar_ate = 0.0

    async def sintetizar(self, texto: str):
        if time.monotonic() >= self.descansar_ate:
            try:
                audio = await self.principal.sintetizar(texto)
                self.falhas = 0
                return (self.principal, audio)
            except ErroVoz as e:
                self.falhas += 1
                log.warning("voz principal falhou (%d): %s", self.falhas, e)
                if self.falhas >= FALHAS_PARA_DESCANSAR:
                    self.descansar_ate = time.monotonic() + DESCANSO_SEG
                    self.falhas = 0
                    self.avisar(f"{e} Usando a voz reserva por 10 minutos.")
        return (self.reserva, await self.reserva.sintetizar(texto))

    async def tocar(self, audio) -> None:
        voz, dados = audio
        await voz.tocar(dados)

    def parar(self) -> None:
        self.principal.parar()
        self.reserva.parar()
