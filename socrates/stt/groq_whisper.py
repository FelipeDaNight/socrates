"""Transcrição com Whisper, rodando grátis nos servidores do Groq."""

from __future__ import annotations

import logging
import re
import unicodedata

import openai
from openai import AsyncOpenAI

from . import ErroOuvido, Ouvido

log = logging.getLogger("socrates.ouvido")

# O Whisper às vezes "inventa" estas frases quando o áudio é quase só ruído,
# porque foi treinado com muitas legendas de vídeo.
ALUCINACOES = {
    "legendas pela comunidade amaraorg",
    "obrigado por assistir",
    "obrigada por assistir",
    "obrigado",
    "inscrevase no canal",
    "e ai",
    "tchau tchau",
    "",
}

# Ajuda o Whisper a escrever certo os nomes que mais aparecem.
DICA = "Conversa com Sócrates, assistente de estudo para concursos e vestibulares."


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", sem_acento.lower()).strip()


def filtrar_alucinacao(texto: str) -> str:
    return "" if _normalizar(texto) in ALUCINACOES else texto.strip()


class OuvidoWhisper(Ouvido):
    def __init__(self, base_url: str, chave: str, modelo: str = "whisper-large-v3-turbo",
                 idioma: str = "pt", http_client=None):
        self.modelo = modelo
        self.idioma = idioma
        self._cliente = AsyncOpenAI(base_url=base_url, api_key=chave, http_client=http_client)

    async def transcrever(self, audio_wav: bytes) -> str:
        try:
            r = await self._cliente.audio.transcriptions.create(
                model=self.modelo,
                file=("fala.wav", audio_wav, "audio/wav"),
                language=self.idioma,
                prompt=DICA,
                temperature=0,
            )
        except openai.RateLimitError as e:
            raise ErroOuvido("Limite grátis de transcrição atingido. Espere um minuto.") from e
        except openai.AuthenticationError as e:
            raise ErroOuvido("Chave do Groq inválida. Confira o arquivo .env.") from e
        except openai.APIConnectionError as e:
            raise ErroOuvido("Sem conexão para transcrever. Verifique a internet.") from e
        except openai.APIStatusError as e:
            raise ErroOuvido(f"O Groq recusou o áudio ({e.status_code}).") from e
        texto = filtrar_alucinacao(r.text)
        log.info("transcrito: %r", texto)
        return texto
