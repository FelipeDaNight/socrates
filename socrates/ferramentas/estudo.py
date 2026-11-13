"""Pomodoro que conta como estudo: quando acaba, os minutos vão para o caderno
(e para a planilha, se estiver configurada)."""

from __future__ import annotations

import time

from . import ferramenta
from .computador import TIMER

TUTOR = None          # main.py liga ao tutor
_inicio = {"quando": 0.0, "materia": ""}


@ferramenta("Inicia um pomodoro de estudo de uma matéria; no fim, anota os minutos estudados.",
            params={"materia": "Ex.: português, trânsito, direito penal",
                    "minutos": "Minutos (padrão 25)"})
def iniciar_pomodoro(materia: str, minutos: float = 25) -> str:
    minutos = float(minutos or 25)
    if not 1 <= minutos <= 120:
        return "O pomodoro precisa ter entre 1 e 120 minutos."
    materia = (materia or "estudo").strip()

    def terminou() -> str:
        anotado = TUTOR.registrar_estudo(materia, minutos) if TUTOR else ""
        return f"Fim do pomodoro de {materia}! {anotado} Faça uma pausa de 5 minutos."

    _inicio.update(quando=time.monotonic(), materia=materia)
    TIMER.iniciar(minutos, f"estudo de {materia}", ao_terminar=terminou)
    return f"Pomodoro de {round(minutos)} minutos de {materia} começou. Bons estudos!"
