"""Ver a tela: tira um print e pede a um modelo de visão para descrever.

O print só é tirado quando o aluno pede ("o que tem na minha tela?", "resolve a
questão que está na tela") e vai para o Groq (modelo de visão), nada fica salvo.
"""

from __future__ import annotations

import base64
import io
import logging
import re
import sys

from . import ferramenta

log = logging.getLogger("socrates.tela")

# Preenchido pelo main.py a partir do config.yaml
VISAO = {"base_url": "https://api.groq.com/openai/v1", "chave": None, "modelo": "qwen/qwen3.8-27b"}
# Reservas de visão (rodízio): [{"nome", "base_url", "chave", "modelo"}, ...]
VISOES: list[dict] = []

LARGURA_MAX = 1600


def capturar_tela() -> bytes:
    """Print da tela principal, reduzido, em JPEG."""
    from PIL import ImageGrab
    img = ImageGrab.grab()
    return preparar(img)


def preparar(img) -> bytes:
    img = img.convert("RGB")
    if img.width > LARGURA_MAX:
        img = img.resize((LARGURA_MAX, round(img.height * LARGURA_MAX / img.width)))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=75)
    return buf.getvalue()


def _sem_pensamento(texto: str) -> str:
    return re.sub(r"<think>.*?</think>", "", texto or "", flags=re.DOTALL).strip()


def descrever(jpeg: bytes, pergunta: str, cliente=None, modelo: str | None = None) -> str:
    from openai import OpenAI

    modelo = modelo or VISAO["modelo"]
    if cliente is None:
        if not VISAO["chave"]:
            return "Erro: falta a chave do Groq para ver a tela."
        cliente = OpenAI(base_url=VISAO["base_url"], api_key=VISAO["chave"], timeout=40,
                         max_retries=0)
    dados = base64.b64encode(jpeg).decode()
    pedido = ("Esta é a tela do computador de um estudante. "
              f"{pergunta or 'Descreva o que está na tela.'}\n"
              "Responda em português do Brasil. Se houver uma questão ou exercício, "
              "transcreva o texto dela por completo, com as alternativas.")
    r = cliente.chat.completions.create(
        model=modelo, temperature=0.2, max_tokens=1200,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": pedido},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{dados}"}}]}])
    return _sem_pensamento(r.choices[0].message.content)


@ferramenta("Tira um print e descreve a tela do aluno (questão, erro, o que está aberto).",
            params={"pergunta": "O que saber da tela"})
def ver_tela(pergunta: str = "") -> str:
    if sys.platform != "win32" and VISAO.get("captura") is None:
        return "Ver a tela só funciona no Windows."
    try:
        jpeg = (VISAO.get("captura") or capturar_tela)()
    except Exception as e:
        log.exception("print da tela falhou")
        return f"Erro: não consegui tirar o print da tela ({e})."
    if not VISOES:
        try:
            return "O que está na tela:\n" + descrever(jpeg, pergunta)
        except Exception as e:
            log.exception("visão falhou")
            return f"Erro: o modelo de visão não respondeu ({e})."
    from openai import OpenAI
    erros = []
    for v in VISOES:   # rodízio: se um serviço bater no limite, tenta o próximo
        try:
            cliente = OpenAI(base_url=v["base_url"], api_key=v["chave"], timeout=40, max_retries=0)
            return "O que está na tela:\n" + descrever(jpeg, pergunta, cliente, v["modelo"])
        except Exception as e:
            log.warning("visão no %s falhou: %s", v["nome"], e)
            erros.append(f"{v['nome']}: {str(e)[:80]}")
    return "Erro: nenhum modelo de visão respondeu (" + "; ".join(erros) + ")."
