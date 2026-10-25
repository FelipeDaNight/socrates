"""Ponto de partida do Sócrates.

Fase 0: conversa por texto no terminal (o cérebro já é o de verdade).
Fase 1 troca o input() pelo microfone e o print() pela voz.

    python main.py            conversar
    python main.py --modelos  listar modelos do provedor configurado
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from socrates import config, log
from socrates.config import ErroConfig
from socrates.core.orquestrador import Orquestrador
from socrates.llm import ErroCerebro, criar_cerebro

AJUDA = """Comandos:
  /explicar  modo explicação (padrão)
  /testar    modo prova: ele te faz perguntas estilo banca
  /limpar    esquece a conversa atual
  /sair      encerra"""


async def listar_modelos(cfg: config.Config) -> None:
    cerebro = criar_cerebro(cfg.llm)
    print(f"Modelos disponíveis no {cfg.llm.provedor}:")
    for m in await cerebro.listar_modelos():
        marca = "  <- configurado" if m == cfg.llm.modelo else ""
        print(f"  {m}{marca}")


async def conversar(cfg: config.Config) -> None:
    soc = Orquestrador(criar_cerebro(cfg.llm), cfg.nome, cfg.modo_inicial, cfg.historico_max)
    print(f"\n{cfg.nome} pronto ({cfg.llm.provedor} / {cfg.llm.modelo}).")
    print(AJUDA)

    while True:
        try:
            texto = await asyncio.to_thread(input, f"\n[{soc.modo}] Você: ")
        except (EOFError, KeyboardInterrupt):
            break
        texto = texto.strip()
        if not texto:
            continue

        comando = texto.lower()
        if comando in ("/sair", "sair"):
            break
        if comando in ("/explicar", "/testar"):
            soc.mudar_modo(comando[1:])
            print(f"Modo: {soc.modo}")
            continue
        if comando == "/limpar":
            soc.limpar()
            print("Conversa esquecida.")
            continue
        if comando in ("/ajuda", "/help"):
            print(AJUDA)
            continue

        print(f"{cfg.nome}: ", end="", flush=True)
        try:
            async for pedaco in soc.conversar(texto):
                print(pedaco, end="", flush=True)
            print()
        except ErroCerebro as e:
            print(f"\n[erro] {e}")

    print(f"\n{cfg.nome}: Até a próxima. Bons estudos!")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # acentos certos no Windows
    p = argparse.ArgumentParser(description="Sócrates, assistente de estudo")
    p.add_argument("--modelos", action="store_true", help="lista os modelos do provedor")
    args = p.parse_args()

    try:
        cfg = config.carregar()
    except ErroConfig as e:
        print(f"[configuração] {e}")
        sys.exit(1)
    log.configurar(cfg.log_nivel, cfg.log_arquivo)

    try:
        asyncio.run(listar_modelos(cfg) if args.modelos else conversar(cfg))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
