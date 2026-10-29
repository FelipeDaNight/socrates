"""Ponto de partida do Sócrates.

    python main.py               conversar por voz (Enter para falar)
    python main.py --texto       conversar só por texto
    python main.py --diagnostico testar microfone, voz e transcrição
    python main.py --modelos     listar modelos do provedor configurado
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from socrates import config, log
from socrates.audio import ErroAudio
from socrates.audio.microfone import AjustesMic, Microfone
from socrates.config import ErroConfig
from socrates.core.comandos import Comando, interpretar
from socrates.core.narrador import ecoar, narrar
from socrates.core.orquestrador import Orquestrador
from socrates.llm import ErroCerebro, criar_cerebro
from socrates.stt import ErroOuvido
from socrates.tts import ErroVoz

AJUDA_TEXTO = """Comandos:
  /explicar  modo explicação (padrão)
  /testar    modo prova: ele te faz perguntas estilo banca
  /limpar    esquece a conversa atual
  /sair      encerra"""

AJUDA_VOZ = """Como usar:
  Aperte Enter e fale. Ele para de gravar sozinho quando você faz silêncio.
  Ou digite a pergunta normalmente.

Comandos (falados ou digitados):
  "modo explicar"    ou /explicar
  "modo prova"       ou /testar
  "limpar conversa"  ou /limpar
  "encerrar"         ou /sair"""

CONFIRMACOES = {
    Comando.EXPLICAR: "Modo explicação. Pode perguntar.",
    Comando.TESTAR: "Modo prova. Me diga o assunto e eu começo as perguntas.",
    Comando.LIMPAR: "Pronto, esqueci a conversa. Vamos do zero.",
}


def escrever(texto: str) -> None:
    print(texto, end="", flush=True)


class Sentidos:
    """Microfone, ouvido e voz juntos. Ausente no modo texto."""

    def __init__(self, cfg: config.Config):
        from socrates.audio import importar_sounddevice
        from socrates.stt.groq_whisper import OuvidoWhisper
        from socrates.tts.edge import VozEdge

        if not cfg.ouvido.chave:
            raise ErroConfig(f"Falta a chave {cfg.ouvido.chave_env} no .env para transcrever a voz.")
        importar_sounddevice()   # falha cedo se o som não estiver disponível
        m = cfg.microfone
        self.mic = Microfone(AjustesMic(m.silencio_seg, m.max_seg, m.espera_seg, m.sensibilidade),
                             dispositivo=m.dispositivo)
        self.ouvido = OuvidoWhisper(cfg.ouvido.base_url, cfg.ouvido.chave, cfg.ouvido.modelo)
        self.voz = VozEdge(cfg.voz.nome, cfg.voz.velocidade)

    async def ouvir(self) -> str:
        print("Ouvindo... (fale; eu paro quando você fizer silêncio)")
        try:
            wav = await asyncio.to_thread(self.mic.gravar)
            if wav is None:
                print("Não ouvi nada. Se você falou, rode: python main.py --diagnostico")
                return ""
            print("Transcrevendo...")
            texto = await self.ouvido.transcrever(wav)
        except (ErroAudio, ErroOuvido) as e:
            print(f"[ouvido] {e}")
            return ""
        if not texto:
            print("Não entendi. Pode repetir?")
            return ""
        print(f"Você disse: {texto}")
        return texto

    async def dizer(self, texto: str) -> None:
        try:
            await self.voz.tocar(await self.voz.sintetizar(texto))
        except (ErroVoz, ErroAudio) as e:
            print(f"[voz] {e}")


async def responder(soc: Orquestrador, texto: str, sentidos: Sentidos | None, nome: str) -> None:
    print(f"{nome}: ", end="", flush=True)
    pedacos = ecoar(soc.conversar(texto), escrever)
    try:
        if sentidos:
            await narrar(pedacos, sentidos.voz,
                         ao_falhar=lambda e: print(f"\n[voz] {e} Continuando só em texto.", end=""))
        else:
            async for _ in pedacos:
                pass
        print()
    except ErroCerebro as e:
        print(f"\n[erro] {e}")
    except ErroAudio as e:
        print(f"\n[som] {e}")


async def conversar(cfg: config.Config, usar_voz: bool) -> None:
    soc = Orquestrador(criar_cerebro(cfg.llm), cfg.nome, cfg.modo_inicial, cfg.historico_max)

    sentidos = None
    if usar_voz:
        try:
            sentidos = Sentidos(cfg)
        except (ErroAudio, ErroConfig) as e:
            print(f"[voz desligada] {e}\nSeguindo no modo texto.")

    modo_entrada = "voz" if sentidos else "texto"
    print(f"\n{cfg.nome} pronto ({cfg.llm.provedor} / {cfg.llm.modelo}, {modo_entrada}).")
    print(AJUDA_VOZ if sentidos else AJUDA_TEXTO)
    if sentidos and cfg.voz.saudacao:
        await sentidos.dizer(f"Olá! Eu sou o {cfg.nome}. Aperte Enter e fale comigo.")

    while True:
        dica = "Enter para falar, ou digite: " if sentidos else "Você: "
        try:
            texto = (await asyncio.to_thread(input, f"\n[{soc.modo}] {dica}")).strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not texto:
            if not sentidos:
                continue
            texto = await sentidos.ouvir()
            if not texto:
                continue

        comando = interpretar(texto)
        if comando is Comando.SAIR:
            break
        if comando is Comando.AJUDA:
            print(AJUDA_VOZ if sentidos else AJUDA_TEXTO)
            continue
        if comando in (Comando.EXPLICAR, Comando.TESTAR):
            soc.mudar_modo(comando.value)
        if comando is Comando.LIMPAR:
            soc.limpar()
        if comando:
            print(CONFIRMACOES[comando])
            if sentidos:
                await sentidos.dizer(CONFIRMACOES[comando])
            continue

        await responder(soc, texto, sentidos, cfg.nome)

    despedida = "Até a próxima. Bons estudos!"
    print(f"\n{cfg.nome}: {despedida}")
    if sentidos:
        await sentidos.dizer(despedida)


async def listar_modelos(cfg: config.Config) -> None:
    cerebro = criar_cerebro(cfg.llm)
    print(f"Modelos disponíveis no {cfg.llm.provedor}:")
    for m in await cerebro.listar_modelos():
        marca = "  <- configurado" if m == cfg.llm.modelo else ""
        print(f"  {m}{marca}")


async def diagnostico(cfg: config.Config) -> None:
    """Testa cada peça separada e diz qual falhou."""
    import numpy as np

    from socrates.audio import TAXA_MIC, importar_sounddevice

    print("=== Diagnóstico do Sócrates ===\n")
    print("1/4  Som do computador")
    try:
        sd = importar_sounddevice()
        print(f"     Microfone:    {sd.query_devices(kind='input')['name']}")
        print(f"     Alto-falante: {sd.query_devices(kind='output')['name']}")
        s = Sentidos(cfg)
    except Exception as e:
        print(f"     FALHOU: {e}")
        return

    print("\n2/4  Voz (você deve ouvir uma frase)")
    try:
        await s.voz.tocar(await s.voz.sintetizar("Olá! Se você está me ouvindo, a minha voz está funcionando."))
        print("     OK, áudio enviado ao alto-falante.")
    except (ErroVoz, ErroAudio) as e:
        print(f"     FALHOU: {e}")

    print("\n3/4  Microfone: aperte Enter, fale uma frase e fique em silêncio")
    await asyncio.to_thread(input, "     ")
    try:
        wav = await asyncio.to_thread(s.mic.gravar)
    except ErroAudio as e:
        print(f"     FALHOU: {e}")
        return
    print(f"     Ruído da sala: limiar {s.mic.ultimo_limiar:.0f}")
    if wav is None:
        print("     Não detectei fala. Tente sensibilidade: 2.0 no config.yaml,")
        print("     e confira o microfone padrão em Configurações > Som do Windows.")
        return
    amostras = np.frombuffer(wav[44:], dtype=np.int16)
    print(f"     Gravei {len(amostras) / TAXA_MIC:.1f} s. Tocando de volta o que ouvi...")
    await s.voz.alto_falante.tocar_wav(amostras, TAXA_MIC)

    print("\n4/4  Transcrição (Whisper no Groq)")
    try:
        print(f"     Entendi: \"{await s.ouvido.transcrever(wav)}\"")
    except ErroOuvido as e:
        print(f"     FALHOU: {e}")
        return
    print("\nTudo certo. Rode: .venv\\Scripts\\python main.py")


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # acentos certos no Windows
    p = argparse.ArgumentParser(description="Sócrates, assistente de estudo")
    p.add_argument("--texto", action="store_true", help="conversa só por texto")
    p.add_argument("--diagnostico", action="store_true", help="testa microfone, voz e transcrição")
    p.add_argument("--modelos", action="store_true", help="lista os modelos do provedor")
    args = p.parse_args()

    try:
        cfg = config.carregar()
    except ErroConfig as e:
        print(f"[configuração] {e}")
        sys.exit(1)
    log.configurar(cfg.log_nivel, cfg.log_arquivo)

    if args.modelos:
        tarefa = listar_modelos(cfg)
    elif args.diagnostico:
        tarefa = diagnostico(cfg)
    else:
        tarefa = conversar(cfg, usar_voz=cfg.voz.ativa and not args.texto)
    try:
        asyncio.run(tarefa)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
