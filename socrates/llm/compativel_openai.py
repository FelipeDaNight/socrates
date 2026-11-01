"""Cérebro para qualquer provedor com API no formato OpenAI.

Groq, Gemini e Ollama aceitam esse formato, então uma classe cobre os três.

Limite do plano grátis (erro 429): cada modelo do Groq tem o próprio limite
de tokens por minuto. Quando um estoura, o pedido espera o tempo que o Groq
indica (se for curto) ou vai para o modelo reserva, que tem outro limite.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import AsyncIterator

import openai
from openai import AsyncOpenAI

from .base import Cerebro, ErroCerebro, ErroPesquisa, Mensagem

log = logging.getLogger("socrates.llm")

ESPERA_MAX_SEG = 12   # esperar mais que isso calado parece travado: melhor usar a reserva


def segundos_para_tentar(erro: openai.RateLimitError) -> float | None:
    """Quanto o Groq mandou esperar (cabeçalho retry-after), se disse."""
    try:
        valor = erro.response.headers.get("retry-after")
        return float(valor) if valor is not None else None
    except (AttributeError, ValueError, TypeError):
        return None


def mensagem_de_limite(erro: openai.RateLimitError, espera: float | None) -> str:
    texto = str(erro).lower()
    if "per day" in texto or "tpd" in texto or "rpd" in texto:
        return "Acabou o limite grátis de hoje do Groq. Amanhã ele renova."
    if espera and espera > 60:
        return f"Bati no limite grátis do Groq. Tente de novo em {round(espera / 60)} minutos."
    return "Bati no limite grátis do Groq por agora. Espere uns segundos e fale de novo."


class CerebroCompativelOpenAI(Cerebro):
    def __init__(self, base_url: str, chave: str, modelo: str,
                 temperatura: float = 0.6, nome: str = "openai-compat",
                 tentativas: int = 3, http_client=None, modelo_reserva: str | None = None):
        self.nome = nome
        self.modelo = modelo
        self.modelo_reserva = modelo_reserva if modelo_reserva != modelo else None
        self.temperatura = temperatura
        self.tentativas = tentativas
        self._reserva_ate = 0.0       # até quando usar a reserva (o principal estourou)
        # max_retries=0: quem decide esperar ou trocar de modelo é o _criar (a biblioteca
        # sozinha esperaria em silêncio o tempo todo do retry-after)
        self._cliente = AsyncOpenAI(base_url=base_url, api_key=chave, http_client=http_client,
                                    max_retries=0)

    # ---------- escolha do modelo e limite ----------
    def modelo_da_vez(self) -> str:
        if self.modelo_reserva and time.monotonic() < self._reserva_ate:
            return self.modelo_reserva
        return self.modelo

    def _extras(self, modelo: str) -> dict:
        return {"reasoning_effort": "low"} if "gpt-oss" in modelo else {}

    async def _criar(self, **pedido):
        """chat.completions.create com tratamento do limite grátis."""
        modelo = self.modelo_da_vez()
        tentou_reserva = modelo == self.modelo_reserva
        esperou = False
        while True:
            try:
                return await self._cliente.chat.completions.create(model=modelo, **pedido)
            except openai.RateLimitError as e:
                espera = segundos_para_tentar(e)
                log.warning("limite do %s (espera sugerida: %s s): %s", modelo, espera, e)
                if not esperou and espera is not None and espera <= ESPERA_MAX_SEG:
                    esperou = True
                    await asyncio.sleep(espera + 0.3)
                    continue
                if self.modelo_reserva and not tentou_reserva:
                    tentou_reserva, esperou = True, False
                    self._reserva_ate = time.monotonic() + max(espera or 60, 30)
                    modelo = self.modelo_reserva
                    log.warning("usando o modelo reserva %s", modelo)
                    continue
                raise ErroCerebro(mensagem_de_limite(e, espera)) from e
            except openai.AuthenticationError as e:
                raise ErroCerebro("Chave de API inválida. Confira o arquivo .env.") from e
            except openai.NotFoundError as e:
                raise ErroCerebro(f"Modelo '{modelo}' não encontrado. Rode "
                                  "'python main.py --modelos' para ver os disponíveis.") from e
            except openai.APIConnectionError as e:
                raise ErroCerebro("Sem conexão com o provedor. Verifique a internet.") from e

    # ---------- ferramentas ----------
    async def com_ferramentas(self, mensagens: list[Mensagem], esquemas: list[dict],
                              executar, max_rodadas: int = 4) -> str:
        """O cérebro escolhe ferramentas; `executar(nome, args)` roda no seu PC.

        Repete até o cérebro responder em texto (ou até max_rodadas).
        """
        msgs: list = [dict(m) for m in mensagens]
        for _ in range(max_rodadas):
            modelo = self.modelo_da_vez()
            try:
                r = await self._criar(messages=msgs, tools=esquemas, tool_choice="auto",
                                      temperature=0.2, stream=False, **self._extras(modelo))
            except openai.APIStatusError as e:
                log.warning("ferramentas recusadas (%s): %s", e.status_code, e.message)
                raise ErroCerebro(f"O Groq recusou o pedido ({e.status_code}).") from e
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

    # ---------- pesquisa ----------
    async def _pedir_pesquisa(self, mensagens: list[Mensagem], escolha: str):
        return await self._criar(
            messages=mensagens,
            tools=[{"type": "browser_search"}],
            tool_choice=escolha,
            reasoning_effort="low",   # recomendação do Groq: buscas mais curtas
            temperature=0.3,
            stream=False,
        )

    async def pesquisar(self, mensagens: list[Mensagem]) -> str:
        """Responde usando a busca na internet que roda nos servidores do Groq.

        Só funciona nos modelos gpt-oss do Groq. Não usa streaming: a busca
        acontece inteira do lado deles e volta uma resposta pronta.
        """
        try:
            try:
                r = await self._pedir_pesquisa(mensagens, "required")
            except openai.BadRequestError as e:
                # O modelo respondeu sem usar a busca: tenta mais uma vez, deixando livre
                if "tool_use_failed" not in str(e):
                    raise
                log.warning("modelo não usou a busca; tentando de novo")
                r = await self._pedir_pesquisa(mensagens, "auto")
        except ErroCerebro as e:
            raise ErroPesquisa(str(e)) from e
        except openai.APIStatusError as e:
            log.warning("pesquisa recusada (%s): %s", e.status_code, e.message)
            raise ErroPesquisa(f"O Groq recusou a pesquisa ({e.status_code}): {e.message}") from e
        texto = (r.choices[0].message.content or "") if r.choices else ""
        log.info("pesquisa: %d caracteres", len(texto))
        return texto

    # ---------- conversa ----------
    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        try:
            fluxo = await self._criar(messages=mensagens, temperature=self.temperatura,
                                      stream=True)
        except openai.APIStatusError as e:
            log.warning("pedido recusado (%s): %s", e.status_code, e.message)
            raise ErroCerebro(f"O Groq recusou o pedido ({e.status_code}).") from e
        try:
            async for pedaco in fluxo:
                if pedaco.choices and pedaco.choices[0].delta.content:
                    yield pedaco.choices[0].delta.content
        except openai.APIError as e:
            log.warning("resposta interrompida: %s", e)
            raise ErroCerebro("A resposta foi interrompida no meio. Tente de novo.") from e

    async def listar_modelos(self) -> list[str]:
        modelos = await self._cliente.models.list()
        return sorted(m.id for m in modelos.data)
