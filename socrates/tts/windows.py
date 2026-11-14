"""Voz do próprio Windows (SAPI), sem internet e sem instalar nada.

É a reserva da reserva: se o Edge falhar três vezes seguidas, a frase sai nesta voz
(a "Maria" que vem no Windows em português), em vez de o Sócrates ficar mudo.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
import uuid
from pathlib import Path

from ..audio.alto_falante import AltoFalante
from . import ErroVoz, Voz

log = logging.getLogger("socrates.voz")

SCRIPT = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$v = $s.GetInstalledVoices() | Where-Object { $_.Enabled -and $_.VoiceInfo.Culture.Name -like 'pt*' } |
     Select-Object -First 1
if (-not $v) { Write-Output 'SEM_PT'; exit }
$s.SelectVoice($v.VoiceInfo.Name)
$s.Rate = {velocidade}
$texto = Get-Content -Raw -Encoding UTF8 -LiteralPath '{entrada}'
$s.SetOutputToWaveFile('{saida}')
$s.Speak($texto)
$s.Dispose()
Write-Output 'OK'
"""


def velocidade_sapi(velocidade: str) -> int:
    """"+10%" do Edge -> 1 na escala do Windows (-10 a 10)."""
    try:
        pct = int(str(velocidade).strip().rstrip("%") or 0)
    except ValueError:
        return 0
    return max(-10, min(10, round(pct / 10)))


class VozWindows(Voz):
    def __init__(self, alto_falante: AltoFalante | None = None, velocidade: str = "+0%"):
        self.alto_falante = alto_falante or AltoFalante()
        self.rate = velocidade_sapi(velocidade)
        self.sem_portugues = False

    @staticmethod
    def disponivel() -> bool:
        return sys.platform == "win32"

    def _gerar(self, texto: str) -> bytes:
        from ..ferramentas.janelas import _powershell
        pasta = Path(tempfile.gettempdir())
        nome = f"socrates_fala_{os.getpid()}_{uuid.uuid4().hex[:8]}"   # frases em paralelo
        entrada, saida = pasta / f"{nome}.txt", pasta / f"{nome}.wav"
        entrada.write_text(texto, encoding="utf-8")
        try:
            r = _powershell(SCRIPT.replace("{velocidade}", str(self.rate))
                            .replace("{entrada}", str(entrada).replace("'", "''"))
                            .replace("{saida}", str(saida).replace("'", "''")), timeout=40)
            if "SEM_PT" in r:
                self.sem_portugues = True
                raise ErroVoz("O Windows não tem voz em português instalada.")
            return saida.read_bytes()
        except OSError as e:
            raise ErroVoz(f"A voz do Windows falhou: {e}") from e
        finally:
            for arq in (entrada, saida):
                try:
                    arq.unlink()
                except OSError:
                    pass

    async def sintetizar(self, texto: str) -> bytes:
        if self.sem_portugues:
            raise ErroVoz("O Windows não tem voz em português instalada.")
        return await asyncio.to_thread(self._gerar, texto)

    async def tocar(self, audio: bytes) -> None:
        from .gemini import wav_para_amostras
        amostras, taxa = wav_para_amostras(audio)
        await self.alto_falante.tocar_wav(amostras, taxa)

    def parar(self) -> None:
        self.alto_falante.parar()
