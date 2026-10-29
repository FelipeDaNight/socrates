"""Grava a sua fala e para sozinho quando você fica em silêncio.

O DetectorDeFala é só matemática (sem placa de som), por isso dá para testar.
O Microfone liga o detector ao microfone de verdade.
"""

from __future__ import annotations

import io
import logging
import wave
from collections import deque
from dataclasses import dataclass
from enum import Enum

import numpy as np

from . import TAXA_MIC, ErroAudio, importar_sounddevice

log = logging.getLogger("socrates.microfone")

BLOCO_MS = 30


class Status(Enum):
    CONTINUAR = "continuar"
    TERMINOU = "terminou"     # você falou e depois ficou em silêncio
    NADA = "nada"             # ninguém falou dentro do tempo de espera


@dataclass
class AjustesMic:
    silencio_seg: float = 1.2     # quanto silêncio encerra a gravação
    max_seg: float = 30.0         # limite de uma fala
    espera_seg: float = 8.0       # quanto espera você começar a falar
    sensibilidade: float = 3.0    # fala = sinal X vezes acima do ruído ambiente
    limiar_minimo: float = 200.0  # piso, para salas muito silenciosas


def rms(bloco: np.ndarray) -> float:
    if bloco.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(bloco.astype(np.float64) ** 2)))


class DetectorDeFala:
    """Recebe blocos de 30 ms e decide quando a fala começou e terminou."""

    CALIBRAGEM_BLOCOS = 10    # 300 ms iniciais medem o ruído da sala
    INICIO_BLOCOS = 3         # 90 ms seguidos acima do limiar = começou a falar
    PRE_ROLL_BLOCOS = 10      # guarda 300 ms antes, para não cortar a 1ª sílaba

    def __init__(self, ajustes: AjustesMic | None = None, taxa: int = TAXA_MIC):
        self.aj = ajustes or AjustesMic()
        self.bloco_seg = BLOCO_MS / 1000
        self._calibragem: list[float] = []
        self.limiar: float | None = None
        self._antes: deque[np.ndarray] = deque(maxlen=self.PRE_ROLL_BLOCOS)
        self._gravado: list[np.ndarray] = []
        self._seguidos_alto = 0
        self._seguidos_silencio = 0
        self._blocos_total = 0
        self.falando = False

    def alimentar(self, bloco: np.ndarray) -> Status:
        bloco = bloco.reshape(-1)
        self._blocos_total += 1
        nivel = rms(bloco)

        if self.limiar is None:
            self._calibragem.append(nivel)
            self._antes.append(bloco)
            if len(self._calibragem) >= self.CALIBRAGEM_BLOCOS:
                ruido = float(np.median(self._calibragem))
                self.limiar = max(ruido * self.aj.sensibilidade, self.aj.limiar_minimo)
                log.debug("ruído %.0f, limiar %.0f", ruido, self.limiar)
            return Status.CONTINUAR

        alto = nivel > self.limiar
        if not self.falando:
            self._antes.append(bloco)
            self._seguidos_alto = self._seguidos_alto + 1 if alto else 0
            if self._seguidos_alto >= self.INICIO_BLOCOS:
                self.falando = True
                self._gravado = list(self._antes)
            elif self._blocos_total * self.bloco_seg >= self.aj.espera_seg:
                return Status.NADA
            return Status.CONTINUAR

        self._gravado.append(bloco)
        self._seguidos_silencio = 0 if alto else self._seguidos_silencio + 1
        if self._seguidos_silencio * self.bloco_seg >= self.aj.silencio_seg:
            return Status.TERMINOU
        if len(self._gravado) * self.bloco_seg >= self.aj.max_seg:
            return Status.TERMINOU
        return Status.CONTINUAR

    def audio(self) -> np.ndarray:
        if not self._gravado:
            return np.zeros(0, dtype=np.int16)
        return np.concatenate(self._gravado).astype(np.int16)


def para_wav(amostras: np.ndarray, taxa: int = TAXA_MIC) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(amostras.astype(np.int16).tobytes())
    return buf.getvalue()


class Microfone:
    def __init__(self, ajustes: AjustesMic | None = None, dispositivo: int | str | None = None):
        self.ajustes = ajustes or AjustesMic()
        self.dispositivo = dispositivo
        self.ultimo_limiar: float | None = None

    def gravar(self) -> bytes | None:
        """Bloqueia até você terminar de falar. Devolve WAV, ou None se não ouviu nada."""
        sd = importar_sounddevice()
        detector = DetectorDeFala(self.ajustes)
        tamanho = int(TAXA_MIC * BLOCO_MS / 1000)
        try:
            with sd.InputStream(samplerate=TAXA_MIC, channels=1, dtype="int16",
                                blocksize=tamanho, device=self.dispositivo) as fluxo:
                while True:
                    bloco, _ = fluxo.read(tamanho)
                    status = detector.alimentar(bloco)
                    if status is not Status.CONTINUAR:
                        break
        except sd.PortAudioError as e:
            raise ErroAudio(f"Problema com o microfone: {e}") from e
        self.ultimo_limiar = detector.limiar
        if status is Status.NADA:
            return None
        return para_wav(detector.audio())
