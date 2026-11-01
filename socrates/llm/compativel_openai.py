"""Cérebro para qualquer provedor com API no formato OpenAI.

Groq, Gemini e Ollama aceitam esse formato, então uma classe cobre os três.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

from .base import Cerebro, ErroCerebro, ErroPesquisa, Mensagem

log = logging.getLogger("socrates.llm")


class CerebroCompativelOpenAI(Cerebro):
    def __init__(self, base_url: str, chave: str, modelo: str,
                 temperatura: float = 0.6, nome: str = "openai-compat",
                 tentativas: int = 3, http_client=None):
        self.nome = nome
        self.modelo = modelo
        self.temperatura = temperatura
        self.tentativas = tentativas
        self._cliente = AsyncOpenAI(base_url=base_url, api_key=chave, http_client=http_client)

    async def com_ferramentas(self, mensagens: list[Mensagem], esquemas: list[dict],
                              executar, max_rodadas: int = 4) -> str:
        """O cérebro escolhe ferramentas; `executar(nome, args)` roda no seu PC.

        Repete até o cérebro responder em texto (ou até max_rodadas).
        """
        msgs: list = [dict(m) for m in mensagens]
        extra = {"reasoning_effort": "low"} if "gpt-oss" in self.modelo else {}
        for _ in range(max_rodadas):
            try:
                r = await self._cliente.chat.completions.create(
                    model=self.modelo, messages=msgs, tools=esquemas, tool_choice="auto",
                    temperature=0.2, stream=False, **extra,
                )
            except openai.RateLimitError as e:
                raise ErroCerebro("Limite do plano grátis atingido. Espere um minuto.") from e
            except openai.AuthenticationError as e:
                raise ErroCerebro("Chave de API inválida. Confira o arquivo .env.") from e
            except openai.APIConnectionError as e:
                raise ErroCerebro("Sem conexão com o provedor. Verifique a internet.") from e
            except openai.APIStatusError as e:
                raise ErroCerebro(f"O provedor recusou o pedido ({e.status_code}).") from e
            msg = r.choices[0].message
            chamadas = msg.tool_calls or []
            if not chamadas:
                return msg.content or ""
            msgs.append({
                "role": "assistant", "content": msg.content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments or "{}"}}
                               for c in chamadas],
            })
            for c in chamadas:
                try:
                    args = json.loads(c.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                resultado = await executar(c.function.name, args)
                msgs.append({"role": "tool", "tool_call_id": c.id, "content": resultado})
        return "Fiz o que pude, mas não consegui terminar o pedido."

    async def pesquisar(self, mensagens: list[Mensagem]) -> str:
        """Responde usando a busca na internet que roda nos servidores do Groq.

        Só funciona nos modelos gpt-oss do Groq. Não usa streaming: a busca
        acontece inteira do lado deles e volta uma resposta pronta.
        """
        try:
            r = await self._cliente.chat.completions.create(
                model=self.modelo,
                messages=mensagens,
                tools=[{"type": "browser_search"}],
                tool_choice="required",
                reasoning_effort="low",   # recomendação do Groq: buscas mais curtas
                temperature=0.3,
                stream=False,
            )
        except openai.RateLimitError as e:
            raise ErroPesquisa("Limite de pesquisas atingido. Espere um pouco.") from e
        except openai.AuthenticationError as e:
            raise ErroCerebro("Chave de API inválida. Confira o arquivo .env.") from e
        except openai.APIConnectionError as e:
            raise ErroPesquisa("Sem conexão para pesquisar. Verifique a internet.") from e
        except openai.APIStatusError as e:
            log.warning("pesquisa recusada (%s): %s", e.status_code, e.message)
            raise ErroPesquisa(f"O Groq recusou a pesquisa ({e.status_code}): {e.message}") from e
        texto = (r.choices[0].message.content or "") if r.choices else ""
        log.info("pesquisa: %d caracteres", len(texto))
        return texto

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
