"""Monta a voz a partir do config.yaml, e a lista de vozes do provador (--vozes)."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from ..audio.alto_falante import AltoFalante
from . import Voz
from .edge import VozEdge

log = logging.getLogger("socrates.voz")


def criar_voz(cfg, alto_falante: AltoFalante, avisar=None) -> Voz:
    """cfg é o ConfigVoz. Com provedor gemini, o Edge fica de reserva."""
    edge = VozEdge(cfg.nome, cfg.velocidade, alto_falante, cfg.tom)
    if cfg.provedor != "gemini":
        return edge
    chave = os.getenv("GEMINI_API_KEY")
    if not chave:
        log.warning("voz gemini sem GEMINI_API_KEY; usando Edge")
        if avisar:
            avisar("Falta GEMINI_API_KEY no .env para a voz do Gemini. Usando a voz do Edge.")
        return edge
    from .gemini import VozGemini
    from .reserva import VozComReserva
    gemini = VozGemini(chave, cfg.gemini_voz, cfg.gemini_modelo, cfg.gemini_estilo, alto_falante)
    return VozComReserva(gemini, edge, avisar)


@dataclass
class Candidata:
    rotulo: str
    provedor: str           # edge | gemini
    nome: str               # voz do Edge ou do Gemini
    velocidade: str = "+0%"
    tom: str = "+0Hz"

    def config_yaml(self) -> str:
        if self.provedor == "gemini":
            return f"voz:\n  provedor: gemini\n  gemini_voz: {self.nome}"
        return (f"voz:\n  provedor: edge\n  nome: {self.nome}\n"
                f"  velocidade: \"{self.velocidade}\"\n  tom: \"{self.tom}\"")


CANDIDATAS = [
    Candidata("Antonio (a voz atual)", "edge", "pt-BR-AntonioNeural", "+5%", "+0Hz"),
    Candidata("Antonio, mais grave e calmo", "edge", "pt-BR-AntonioNeural", "-4%", "-6Hz"),
    Candidata("Antonio, bem grave (voz de sábio)", "edge", "pt-BR-AntonioNeural", "-8%", "-12Hz"),
    Candidata("Andrew multilíngue (sotaque leve)", "edge", "en-US-AndrewMultilingualNeural"),
    Candidata("Brian multilíngue (sotaque leve)", "edge", "en-US-BrianMultilingualNeural"),
    Candidata("Florian multilíngue (sotaque leve)", "edge", "de-DE-FlorianMultilingualNeural"),
    Candidata("Duarte (português de Portugal)", "edge", "pt-PT-DuarteNeural"),
    Candidata("Gemini Sadaltager (conhecedor)", "gemini", "Sadaltager"),
    Candidata("Gemini Charon (informativo)", "gemini", "Charon"),
    Candidata("Gemini Gacrux (maduro)", "gemini", "Gacrux"),
    Candidata("Gemini Algenib (rouco)", "gemini", "Algenib"),
    Candidata("Gemini Iapetus (claro)", "gemini", "Iapetus"),
]

FRASE_TESTE = ("Olá! Eu sou o Sócrates. Vamos estudar juntos? "
               "Me diga o assunto, e eu começo as perguntas.")


def voz_da_candidata(c: Candidata, alto_falante: AltoFalante, cfg) -> Voz | None:
    if c.provedor == "edge":
        return VozEdge(c.nome, c.velocidade, alto_falante, c.tom)
    chave = os.getenv("GEMINI_API_KEY")
    if not chave:
        return None
    from .gemini import VozGemini
    return VozGemini(chave, c.nome, cfg.gemini_modelo, cfg.gemini_estilo, alto_falante)
