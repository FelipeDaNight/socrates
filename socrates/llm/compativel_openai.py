"""Cérebro para qualquer provedor com API no formato OpenAI.

Groq, Gemini e Ollama aceitam esse formato, então uma classe cobre os três.
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

from .base import Cerebro, ErroCerebro, Mensagem

log = logging.getLogger("socrates.llm")


class CerebroCompativelOpenAI(Cerebro):
    def __init__(self, base_url: str, chave: str, modelo: str,
                 temperatura: float = 0.6, nome: str = "openai-compat",
                 tentativas: int = 3):
        self.nome = nome
        self.modelo = modelo
        self.temperatura = temperatura
        self.tentativas = tentativas
        self._cliente = AsyncOpenAI(base_url=base_url, api_key=chave)

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        espera = 2.0
        for tentativa in range(1, self.tentativas + 1):
            try:
                fluxo = await self._cliente.chat.completions.create(
                    model=self.modelo,
                    messages=mensagens,
                    temperature=self.temperatura,
                    stream=True,
                )
                async for pedaco in fluxo:
                    if pedaco.choices and pedaco.choices[0].delta.content:
                        yield pedaco.choices[0].delta.content
                return
            except openai.RateLimitError:
                # Plano grátis tem limite por minuto: espera e tenta de novo.
                log.warning("Limite de uso atingido (tentativa %d), esperando %.0fs",
                            tentativa, espera)
                if tentativa == self.tentativas:
                    raise ErroCerebro("Limite do plano grátis atingido. Espere um minuto.")
                await asyncio.sleep(espera)
                espera *= 2
            except openai.AuthenticationError as e:
                raise ErroCerebro("Chave de API inválida. Confira o arquivo .env.") from e
            except openai.NotFoundError as e:
                raise ErroCerebro(
                    f"Modelo '{self.modelo}' não encontrado. "
                    "Rode 'python main.py --modelos' para ver os disponíveis."
                ) from e
            except openai.APIConnectionError as e:
                raise ErroCerebro("Sem conexão com o provedor. Verifique a internet.") from e

    async def listar_modelos(self) -> list[str]:
        modelos = await self._cliente.models.list()
        return sorted(m.id for m in modelos.data)
