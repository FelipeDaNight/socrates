"""Estado compartilhado entre o Sócrates (que pensa e fala) e o visor (que desenha).

O Sócrates escreve aqui; o visor só lê, 30 vezes por segundo.
Funciona sem o visor também: aí ninguém lê, e tudo segue igual.
"""

from __future__ import annotations

import time

import numpy as np

PASSO_ENVELOPE = 0.03   # 30 ms por ponto do envelope da voz
SOBRA_FALA = 0.45       # entre uma frase e outra o visor continua "falando"


def envelope(amostras: np.ndarray, taxa: int, passo: float = PASSO_ENVELOPE) -> np.ndarray:
    """Volume da voz a cada 30 ms, de 0 a 1. É o que faz o visor pulsar."""
    n = max(1, int(taxa * passo))
    if amostras.size == 0:
        return np.zeros(1)
    usar = amostras[: len(amostras) // n * n].astype(np.float64)
    if usar.size == 0:
        return np.zeros(1)
    rms = np.sqrt(np.mean(usar.reshape(-1, n) ** 2, axis=1))
    topo = np.percentile(rms, 95)
    return np.clip(rms / topo, 0, 1) if topo > 0 else np.zeros_like(rms)


class Painel:
    def __init__(self) -> None:
        self.estado = "ocioso"        # ocioso | pensando
        self.legenda = ""             # última coisa que você disse
        self.ouvindo = False          # o microfone detectou alguém falando agora
        self.nivel_mic = 0.0          # 0..1
        self.janela_ate = 0.0         # até quando ele aceita fala sem o nome
        self.fechou = False           # você fechou a janela do visor
        self.encerrado = False        # o Sócrates terminou; o visor deve fechar
        self.ao_fechar = None         # chamado quando você fecha a janela
        self._env: np.ndarray | None = None
        self._env_inicio = 0.0
        self._env_fim = 0.0
        # quadro branco
        self.tem_visor = False                    # o visor está aberto para mostrar o quadro
        self.quadro_tamanho = (760, 640)          # o visor informa o tamanho real
        self.quadro_png: bytes | None = None
        self.quadro_versao = 0

    def mostrar_quadro(self, png: bytes) -> None:
        self.quadro_png = png
        self.quadro_versao += 1

    def limpar_quadro(self) -> None:
        self.quadro_png = None
        self.quadro_versao += 1

    # ---------- escrito pelo Sócrates ----------
    def mic(self, rms: float) -> None:
        self.nivel_mic = min(1.0, rms / 2500)

    def iniciar_fala(self, env: np.ndarray) -> None:
        self._env = env
        self._env_inicio = time.monotonic()

    def fim_fala(self) -> None:
        self._env = None
        self._env_fim = time.monotonic()

    def abrir_janela(self, segundos: float) -> None:
        self.janela_ate = time.monotonic() + segundos

    def fechar_janela(self) -> None:
        self.janela_ate = 0.0

    # ---------- lido pelo visor ----------
    def nivel_voz(self, agora: float | None = None) -> float:
        env = self._env
        if env is None:
            return 0.0
        agora = time.monotonic() if agora is None else agora
        i = int((agora - self._env_inicio) / PASSO_ENVELOPE)
        return float(env[i]) if 0 <= i < len(env) else 0.0

    def falando(self, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        return self._env is not None or agora - self._env_fim < SOBRA_FALA

    def em_janela(self, agora: float | None = None) -> bool:
        agora = time.monotonic() if agora is None else agora
        return agora < self.janela_ate

    def visual(self, agora: float | None = None) -> str:
        """dormindo | atento | ouvindo | pensando | falando"""
        agora = time.monotonic() if agora is None else agora
        if self.falando(agora):
            return "falando"
        if self.estado == "pensando":
            return "pensando"
        if self.em_janela(agora):
            return "ouvindo" if self.ouvindo else "atento"
        return "dormindo"
