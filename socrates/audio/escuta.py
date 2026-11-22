"""Microfone sempre ligado, numa thread separada.

Cada fala completa vai para uma fila do asyncio. Enquanto o Sócrates fala,
a escuta fica pausada, para ele não ouvir a própria voz pelo alto-falante.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass

import numpy as np

from . import TAXA_MIC, ErroAudio, importar_sounddevice
from .microfone import BLOCO_MS, AjustesMic, Segmentador, rms

log = logging.getLogger("socrates.escuta")


@dataclass
class Fala:
    """Uma fala inteira do microfone e QUANDO ela começou. A conversa decide pelo
    começo se você ainda estava no tempo de falar sem dizer o nome: quem começa a
    falar dentro do tempo não pode ser ignorado só porque a frase foi longa."""
    audio: np.ndarray
    inicio: float      # relógio time.monotonic()


class Escuta:
    def __init__(self, ajustes: AjustesMic | None = None,
                 dispositivo: int | str | None = None, painel=None):
        self.seg = Segmentador(ajustes)
        self.dispositivo = dispositivo
        self.painel = painel
        self.pausada = False
        self._parar = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.fila: asyncio.Queue | None = None
        self._pico, self._pico_desde = 0.0, time.monotonic()

    # ---------- controle (chamado pelo asyncio) ----------
    def iniciar(self, fila: asyncio.Queue) -> None:
        importar_sounddevice()   # falha aqui, cedo, se não houver som
        self._loop = asyncio.get_running_loop()
        self.fila = fila
        self._thread = threading.Thread(target=self._rodar, name="escuta", daemon=True)
        self._thread.start()

    def pausar(self) -> None:
        self.pausada = True
        if self.painel:
            self.painel.ouvindo = False

    def retomar(self) -> None:
        """Volta a ouvir, jogando fora qualquer fala que chegou durante a pausa."""
        self.seg.reiniciar()
        if self.fila is not None:
            pendentes = []
            while not self.fila.empty():
                item = self.fila.get_nowait()
                if not isinstance(item, (np.ndarray, Fala)):
                    pendentes.append(item)   # mantém texto digitado e avisos
            for item in pendentes:
                self.fila.put_nowait(item)
        self.pausada = False

    def parar(self) -> None:
        self._parar.set()

    # ---------- thread do microfone ----------
    def processar(self, bloco: np.ndarray) -> np.ndarray | None:
        """Um bloco de 30 ms. Separado da thread para poder ser testado."""
        if self.pausada:
            if self.painel:
                self.painel.mic(0)
            return None
        nivel = rms(bloco)
        if self.painel:
            self.painel.mic(nivel)
        fala = self.seg.alimentar(bloco)
        self._diagnosticar(nivel, fala)
        if self.painel:
            self.painel.ouvindo = self.seg.falando
            if self.seg.falando:
                self.painel.segurar_janela()   # não "dorme" no meio da sua frase
        return fala

    DIAGNOSTICO_SEG = 60.0

    def _diagnosticar(self, nivel: float, fala, agora: float | None = None) -> None:
        """Som perto do limiar que nunca virou fala (alguém chamou baixo?): vai para o
        registro, no máximo uma vez por minuto, com os números para ajustar o microfone."""
        limiar = self.seg.limiar
        if limiar is None:
            return
        agora = time.monotonic() if agora is None else agora
        if fala is not None or self.seg.falando:
            self._pico, self._pico_desde = 0.0, agora
            return
        self._pico = max(self._pico, nivel)
        if agora - self._pico_desde >= self.DIAGNOSTICO_SEG:
            if self._pico >= 0.5 * limiar:
                log.info("microfone: som perto do limiar sem virar fala (pico %.0f, limiar %.0f, "
                         "ruído %.0f). Se ele não te ouve, diminua microfone.sensibilidade.",
                         self._pico, limiar, self.seg.piso or 0)
            self._pico, self._pico_desde = 0.0, agora

    def _entregar(self, item) -> None:
        if self._loop and self.fila is not None:
            self._loop.call_soon_threadsafe(self.fila.put_nowait, item)

    def _rodar(self) -> None:
        sd = importar_sounddevice()
        tamanho = int(TAXA_MIC * BLOCO_MS / 1000)
        try:
            with sd.InputStream(samplerate=TAXA_MIC, channels=1, dtype="int16",
                                blocksize=tamanho, device=self.dispositivo) as fluxo:
                while not self._parar.is_set():
                    bloco, _ = fluxo.read(tamanho)
                    fala = self.processar(bloco)
                    if fala is not None:
                        duracao = len(fala) / TAXA_MIC
                        log.debug("fala de %.1f s", duracao)
                        self._entregar(Fala(fala, time.monotonic() - duracao))
        except Exception as e:   # microfone desconectado, permissão negada...
            log.exception("escuta caiu")
            self._entregar(ErroAudio(f"O microfone parou: {e}"))
