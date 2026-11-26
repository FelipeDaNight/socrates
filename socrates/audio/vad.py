"""Detector de voz: confere se o trecho gravado tem voz humana ANTES de gastar o Whisper.

O microfone separa as falas pelo volume. Sopro, clique, TV baixa, jogo ao fundo e
silêncio com chiado também passam do volume, e o Whisper "inventa" frases para eles:
"Legenda Adriana Zanotto" (9 vezes em 22/11), "A CIDADE NO BRASIL", "FFFF!", "Aplausos"...
Cada um gastava uma transcrição do limite grátis e, com a janela aberta, virava conversa.

Usa o Silero VAD (github.com/snakers4/silero-vad, licença MIT, cópia em
SILERO_VAD_LICENSE.txt): um modelo de 2 MB que roda no onnxruntime, sem PyTorch,
em uns milissegundos por segundo de áudio. Sem o onnxruntime, nada muda (tudo passa).
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("socrates.vad")

MODELO = Path(__file__).with_name("silero_vad.onnx")
TAXA = 16_000
BLOCO = 512                # amostras por pedaço (32 ms a 16 kHz), o que o modelo pede
CONTEXTO = 64              # o modelo vê também o fim do pedaço anterior
LIMIAR = 0.5               # probabilidade de voz a partir da qual o pedaço conta como fala
MIN_VOZ_SEG = 0.2          # um "sim" curto tem uns 0,3 s de voz


class DetectorDeVoz:
    def __init__(self, modelo: Path = MODELO):
        import onnxruntime as ort

        opcoes = ort.SessionOptions()
        opcoes.inter_op_num_threads = 1
        opcoes.intra_op_num_threads = 1
        self._sessao = ort.InferenceSession(str(modelo), sess_options=opcoes,
                                            providers=["CPUExecutionProvider"])

    def probabilidades(self, audio: np.ndarray) -> list[float]:
        """Probabilidade de voz em cada pedaço de 32 ms (áudio int16 ou float, 16 kHz)."""
        x = np.asarray(audio).reshape(-1)
        if x.dtype == np.int16:
            x = x.astype(np.float32) / 32768.0
        else:
            x = x.astype(np.float32)
        estado = np.zeros((2, 1, 128), dtype=np.float32)
        contexto = np.zeros((1, CONTEXTO), dtype=np.float32)
        taxa = np.array(TAXA, dtype=np.int64)
        probs = []
        for i in range(0, len(x) - BLOCO + 1, BLOCO):
            entrada = np.concatenate([contexto, x[i:i + BLOCO][None, :]], axis=1)
            saida, estado = self._sessao.run(None, {"input": entrada, "state": estado, "sr": taxa})
            contexto = entrada[:, -CONTEXTO:]
            probs.append(float(saida.reshape(-1)[0]))
        return probs

    def segundos_de_voz(self, audio: np.ndarray) -> float:
        return sum(p >= LIMIAR for p in self.probabilidades(audio)) * BLOCO / TAXA

    def tem_voz(self, audio: np.ndarray) -> bool:
        return self.segundos_de_voz(audio) >= MIN_VOZ_SEG


def carregar() -> DetectorDeVoz | None:
    """O detector, ou None se o onnxruntime não estiver instalado (aí nada é filtrado)."""
    try:
        detector = DetectorDeVoz()
    except Exception as e:                 # sem onnxruntime, DLL faltando, modelo corrompido
        log.info("sem o detector de voz (%s): as falas vão direto para o Whisper", e)
        return None
    log.info("detector de voz ligado (Silero VAD)")
    return detector
