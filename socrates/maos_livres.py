"""Conversa sem botão: o Sócrates fica ouvindo e responde quando é chamado.

Fluxo de cada fala que o microfone pega:

  fala → Whisper → disse "Sócrates"?  ou  está na janela de conversa?
           não → ignora (era conversa de outra pessoa, TV...)
           sim → pausa o microfone → responde falando → retoma o microfone
                 → abre a janela: por alguns segundos você fala sem dizer o nome

O microfone fica pausado enquanto ele fala, para não ouvir a própria voz.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
import unicodedata
from dataclasses import dataclass
from typing import Callable

import numpy as np

from . import ferramentas
from .audio import ErroAudio
from .audio.escuta import Fala
from .ferramentas import claude
from .audio.microfone import para_wav
from .config import Config
from .core.comandos import Comando, interpretar
from .core.despertar import chamou
from .core.narrador import ecoar, narrar
from .core.orquestrador import Orquestrador
from .llm import ErroCerebro
from .stt import ErroOuvido
from .tts import ErroVoz
from .visor.painel import Painel

log = logging.getLogger("socrates.conversa")


@dataclass
class Aviso:
    """Algo que o Sócrates precisa falar por conta própria (ex.: o timer acabou)."""
    texto: str

ECO_SEG = 0.3   # espera o som do alto-falante sumir da sala antes de reabrir o microfone

AJUDA = """Como usar:
  Diga "Sócrates" e o pedido: "Sócrates, me testa em crase".
  Depois que ele responde, você tem alguns segundos para continuar
  a conversa sem repetir o nome. Também dá para digitar e dar Enter.

Estudo com questões reais e lei seca:
  "questões da PRF"  "10 questões de trânsito da PRF"  "simulado do CBMGO"
  "lacunas do CTB"   "revisa meus erros"   "lê o artigo 165 do CTB"
  "pomodoro de português"   "como estou indo?"   "o que eu estudo hoje?"
  No treino: certo/errado ou "letra B"; dica, explica, repete, próxima, parar.
  Clique no visor (ou aperte Espaço) para ele parar de falar.

Comandos (falados ou digitados):
  "modo explicar"    /explicar   explica e confere se você entendeu
  "modo prova"       /testar     perguntas estilo banca
  "limpar conversa"  /limpar     esquece a conversa atual
  "apaga o quadro"   /apagar     limpa o quadro branco
  "obrigado"         /dormir     encerra o assunto; ele volta a esperar o nome
  "encerrar"         /sair       desliga o Sócrates"""

FALAS = {
    Comando.EXPLICAR: "Modo explicação. Pode perguntar.",
    Comando.TESTAR: "Modo prova. Me diga o assunto e eu começo as perguntas.",
    Comando.LIMPAR: "Pronto, esqueci a conversa. Vamos do zero.",
    Comando.DORMIR: "Por nada. É só me chamar.",
    Comando.APAGAR_QUADRO: "Quadro apagado.",
    Comando.AJUDA: "Diga Sócrates e o seu pedido. Os comandos estão na tela.",
}


PEDIDO_QUADRO = (
    "Escreva AGORA somente o quadro branco do que você acabou de explicar, entre [QUADRO] e "
    "[/QUADRO], seguindo o formato do quadro (título com #, fórmulas em $$ ... $$, itens com -, "
    "e 'grafico:' se couber um gráfico). Nada fora do quadro.")

_PEDE_QUADRO = re.compile(
    r"\b(quadro|formula|formulas|grafico|graficos|desenh\w*|mostr\w*|escrev\w*|equac\w*"
    r"|calcul\w*|resolv\w*|passo a passo|demonstr\w*|teorema|funcao|derivada|integral)\b")


def pede_quadro(pedido: str) -> bool:
    """O aluno pediu algo visual? (aí o quadro tem que aparecer)"""
    t = unicodedata.normalize("NFKD", pedido).encode("ascii", "ignore").decode().lower()
    return bool(_PEDE_QUADRO.search(t))


class Conversa:
    def __init__(self, cfg: Config, soc: Orquestrador, sentidos, painel: Painel,
                 escrever: Callable[[str], None] | None = None, tutor=None):
        self.cfg = cfg
        self.tutor = tutor
        self.soc = soc
        self.s = sentidos
        self.painel = painel
        self.escrever = escrever or (lambda t: print(t, end="", flush=True))
        self._cache: dict[str, bytes] = {}
        self._desenhos: set[asyncio.Task] = set()
        self._quadros_nesta = 0
        self._falando: asyncio.Task | None = None
        self.interrompido = False
        painel.interromper = self._pedir_interrupcao

    def _pedir_interrupcao(self) -> None:
        """Chamado pelo visor (outra thread): clique ou Espaço calam a fala."""
        tarefa = self._falando
        if tarefa is not None and not tarefa.done():
            tarefa.get_loop().call_soon_threadsafe(tarefa.cancel)

    def dizer_tela(self, texto: str = "") -> None:
        self.escrever(texto + "\n")

    # ---------- voz ----------
    async def _sintetizar(self, texto: str, guardar: bool) -> bytes:
        if guardar and texto in self._cache:
            return self._cache[texto]
        audio = await self.s.voz.sintetizar(texto)
        if guardar:
            self._cache[texto] = audio
        return audio

    async def falar(self, texto: str, guardar: bool = True) -> None:
        """Frases curtas e repetidas ("Sim?") ficam guardadas: respondem na hora."""
        await self._com_microfone_pausado(self._falar(texto, guardar))

    async def _falar(self, texto: str, guardar: bool) -> None:
        try:
            await self.s.voz.tocar(await self._sintetizar(texto, guardar))
        except (ErroVoz, ErroAudio) as e:
            self.dizer_tela(f"[voz] {e}")

    async def _com_microfone_pausado(self, tarefa) -> None:
        self.s.escuta.pausar()
        try:
            await tarefa
        finally:
            await asyncio.sleep(ECO_SEG)
            self.s.escuta.retomar()

    # ---------- quadro branco ----------
    def _ao_quadro(self, conteudo: str) -> None:
        self._quadros_nesta += 1
        titulo = next((l.lstrip("# ").strip() for l in conteudo.splitlines() if l.strip()), "")
        if not self.painel.tem_visor:
            self.escrever(f"\n┌─ quadro ─────────\n{conteudo}\n└──────────────────\n")
            return
        self.escrever(f" [quadro: {titulo}] ")
        tarefa = asyncio.create_task(self._desenhar(conteudo))
        self._desenhos.add(tarefa)
        tarefa.add_done_callback(self._desenhos.discard)

    async def _desenhar(self, conteudo: str) -> None:
        from .visor.quadro import renderizar
        try:
            png = await asyncio.to_thread(renderizar, conteudo, *self.painel.quadro_tamanho)
        except Exception:   # nunca derrubar a conversa por causa de um desenho
            log.exception("quadro falhou")
            self.escrever(f"\n[quadro] não consegui desenhar. Conteúdo:\n{conteudo}\n")
            return
        self.painel.mostrar_quadro(png)

    async def _quadro_extra(self) -> None:
        """O aluno pediu algo visual e o modelo respondeu sem quadro: pede só o quadro."""
        from .core.quadro_fluxo import ABRE, FECHA, separar_quadro

        log.info("resposta sem quadro; pedindo o quadro à parte")
        self.painel.estado = "pensando"
        try:
            texto = await self.soc.complemento(PEDIDO_QUADRO)
        except ErroCerebro as e:
            self.dizer_tela(f"[quadro] não consegui montar o quadro: {e}")
            return
        if ABRE.lower() not in texto.lower():
            texto = f"{ABRE}\n{texto}\n{FECHA}"   # o modelo esqueceu as marcas

        async def unico():
            yield texto

        async for _ in separar_quadro(unico(), self._ao_quadro):
            pass
        if self._quadros_nesta:
            inicio = texto.lower().find(ABRE.lower())
            self.soc.anexar_a_ultima_resposta(texto[inicio:])

    async def responder(self, texto: str, extra: str | None = None) -> None:
        from .core.quadro_fluxo import separar_quadro

        self.painel.estado = "pensando"
        self._quadros_nesta = 0
        self.escrever(f"{self.cfg.nome}: ")
        fala = separar_quadro(self.soc.conversar(texto, extra), self._ao_quadro)
        pedacos = ecoar(fala, self.escrever)

        async def tarefa():
            try:
                await narrar(pedacos, self.s.voz,
                             ao_falhar=lambda e: self.escrever(f"\n[voz] {e} Seguindo em texto.\n"))
                self.dizer_tela()
                if not self._quadros_nesta and pede_quadro(texto):
                    await self._quadro_extra()
            except ErroCerebro as e:
                log.warning("cérebro falhou: %s", e)
                self.dizer_tela(f"\n[erro] {e}")
                await self._falar(str(e), False)   # diz o motivo de verdade
            except ErroAudio as e:
                self.dizer_tela(f"\n[som] {e}")
            finally:
                self.painel.estado = "ocioso"

        await self._interrompivel(tarefa())

    async def _interrompivel(self, coro) -> None:
        """Fala que o aluno pode cortar (clique ou Espaço no visor)."""
        self.interrompido = False
        self._falando = asyncio.ensure_future(coro)
        try:
            await self._com_microfone_pausado(self._esperar_fala())
        finally:
            self._falando = None

    async def _esperar_fala(self) -> None:
        try:
            await self._falando
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise                   # o Sócrates inteiro está fechando
            self.s.voz.parar()
            self.interrompido = True
            self.painel.estado = "ocioso"
            self.dizer_tela(" [interrompido]")
            log.info("fala interrompida pelo aluno")

    # ---------- janela de conversa ----------
    def _janela(self) -> float:
        e = self.cfg.escuta
        treinando = self.tutor is not None and self.tutor.em_treino
        return e.janela_prova_seg if self.soc.modo == "testar" or treinando else e.janela_seg

    def abrir_janela(self) -> None:
        self.painel.abrir_janela(self._janela())

    def em_janela(self, quando: float | None = None) -> bool:
        return not self.cfg.escuta.palavra_ativacao or self.painel.em_janela(quando)

    # ---------- entrada ----------
    def dica_do_ouvido(self) -> str | None:
        """Vocabulário que o ouvido deve esperar agora (o treino troca)."""
        return self.tutor.dica_do_ouvido() if self.tutor is not None else None

    # ---------- estudo ----------
    async def executar_saida(self, pedido: str, saida) -> None:
        """Faz o que o tutor decidiu: falar, mostrar no quadro, abrir o texto, ou
        pedir ao cérebro (com a questão e o gabarito junto)."""
        if saida.abrir_texto:
            await asyncio.to_thread(ferramentas.executar, "escrever_no_bloco_de_notas",
                                    {"texto": saida.abrir_texto, "titulo": "questao"})
        if saida.contexto:
            await self.responder(pedido, extra=saida.contexto)
            return
        if saida.quadro:
            self._quadros_nesta = 0
            self._ao_quadro(saida.quadro)
        if saida.fala:
            self.dizer_tela(f"{self.cfg.nome}: {saida.fala}")
            await self._interrompivel(self._falar(saida.fala, False))

    async def _transcrever(self, fala: np.ndarray, em_janela: bool) -> str:
        if em_janela:
            self.painel.estado = "pensando"
        try:
            dica = self.dica_do_ouvido()
            if dica:
                return await self.s.ouvido.transcrever(para_wav(fala), dica)
            return await self.s.ouvido.transcrever(para_wav(fala))
        except ErroOuvido as e:
            if em_janela:
                self.dizer_tela(f"[ouvido] {e}")
            return ""
        finally:
            self.painel.estado = "ocioso"

    async def _pedido(self, item) -> str | None:
        """Transforma o que chegou da fila num pedido. None = não era para ele."""
        if isinstance(item, str):
            return item.strip()
        if isinstance(item, Fala):   # vale o momento em que você COMEÇOU a falar
            audio, em_janela = item.audio, self.em_janela(item.inicio)
        else:
            audio, em_janela = item, self.em_janela()
        texto = await self._transcrever(audio, em_janela)
        if not texto:
            return None
        foi_chamado, pedido = chamou(texto)
        if foi_chamado:
            self.dizer_tela(f"\nVocê: {pedido or '(chamou)'}")
            return pedido
        if em_janela:
            self.dizer_tela(f"\nVocê: {texto}")
            return texto
        log.info("ignorado (sem o nome): %r", texto)
        return None

    # ---------- laço principal ----------
    async def rodar(self, fila: asyncio.Queue) -> None:
        palavra = self.cfg.escuta.palavra_ativacao
        if self.painel.tem_visor:   # carrega o desenhista já: o 1º quadro sai sem demora
            aquecer = asyncio.create_task(asyncio.to_thread(_aquecer_quadro))
            self._desenhos.add(aquecer)
            aquecer.add_done_callback(self._desenhos.discard)
        from .config import descricao_cerebro
        self.dizer_tela(f"\n{self.cfg.nome} pronto ({descricao_cerebro(self.cfg)}).")
        self.dizer_tela(AJUDA)
        if self.cfg.voz.saudacao:
            await self.falar(f"Olá! Eu sou o {self.cfg.nome}. "
                             + ("É só me chamar pelo nome." if palavra else "Pode falar."), False)
        self.dizer_tela('\nEsperando você dizer "Sócrates"...' if palavra else "\nOuvindo...")

        while True:
            item = await fila.get()
            if item is None:
                break
            if isinstance(item, ErroAudio):
                self.dizer_tela(f"[microfone] {item} Você ainda pode digitar.")
                continue
            if isinstance(item, Aviso):
                self.dizer_tela(f"\n{self.cfg.nome}: {item.texto}")
                await self.falar(item.texto, False)
                self.abrir_janela()
                continue

            pedido = await self._pedido(item)
            if pedido is None:
                continue
            self.painel.legenda = pedido

            if ferramentas.pendente_valido():   # "Posso mandar?" -> "sim"
                resposta = await asyncio.to_thread(ferramentas.resolver_confirmacao, pedido)
                if resposta is not None:
                    self.dizer_tela(f"{self.cfg.nome}: {resposta}")
                    await self.falar(resposta, False)
                    if claude.REINICIAR.is_set():
                        break
                    self.abrir_janela()
                    continue

            if not pedido:                      # disse só "Sócrates"
                await self.falar("Sim?")
                self.abrir_janela()
                continue

            if self.tutor is not None and self.tutor.em_treino and not _comando_geral(pedido):
                saida = self.tutor.atender(pedido)
                if saida is not None:
                    await self.executar_saida(pedido, saida)
                    self.abrir_janela()
                    continue

            comando = interpretar(pedido)
            if comando is Comando.SAIR:
                break
            if comando:
                if comando is Comando.AJUDA:
                    self.dizer_tela(AJUDA)
                if comando in (Comando.EXPLICAR, Comando.TESTAR):
                    self.soc.mudar_modo(comando.value)
                if comando is Comando.LIMPAR:
                    self.soc.limpar()
                    self.painel.limpar_quadro()
                    if self.tutor is not None:
                        self.tutor.encerrar()
                if comando is Comando.APAGAR_QUADRO:
                    self.painel.limpar_quadro()
                self.dizer_tela(FALAS[comando])
                await self.falar(FALAS[comando])
                if comando is Comando.DORMIR:
                    self.painel.fechar_janela()
                    self.painel.legenda = ""
                else:
                    self.abrir_janela()
                continue

            extra = None
            if self.tutor is not None:
                try:
                    saida = self.tutor.atender(pedido)
                except Exception:          # um banco com defeito não derruba a conversa
                    log.exception("tutor falhou")
                    saida = None
                if saida is not None:
                    await self.executar_saida(pedido, saida)
                    self.abrir_janela()
                    continue
                extra = self.tutor.contexto_da_lei(pedido) or None
            await self.responder(pedido, extra)
            if ferramentas.SOM_LIGADO.is_set():
                # Abriu vídeo ou música: o som do PC entra no microfone. Para não
                # responder ao vídeo, volta a esperar o nome "Sócrates".
                ferramentas.SOM_LIGADO.clear()
                self.painel.fechar_janela()
                self.dizer_tela('(som tocando: me chame pelo nome, "Sócrates", para continuar)')
                continue
            self.abrir_janela()

        self.painel.fechar_janela()
        if self.tutor is not None:
            self.tutor.encerrar()          # guarda o treino que estava no meio
        despedida = ("Até já, volto atualizado." if claude.REINICIAR.is_set()
                     else "Até a próxima. Bons estudos!")
        self.dizer_tela(f"\n{self.cfg.nome}: {despedida}")
        await self.falar(despedida, False)


def _comando_geral(pedido: str) -> bool:
    """"Desligar", "obrigado", "apaga o quadro", "/sair" valem mesmo no meio do treino
    (o "parar"/"encerra" é do treino: termina só o treino)."""
    from .estudo.respostas import comando
    cmd = interpretar(pedido)
    return cmd is not None and (pedido.strip().startswith("/") or comando(pedido) != "parar")


def _aquecer_quadro() -> None:
    try:
        from .visor.quadro import renderizar
        renderizar("# .\n$$ x $$", 200, 120)
    except Exception:
        log.exception("não consegui preparar o quadro")


def ler_teclado(loop: asyncio.AbstractEventLoop, fila: asyncio.Queue) -> None:
    """Thread que lê o que você digita e manda para a mesma fila do microfone."""
    def ler():
        while True:
            try:
                linha = input()
            except (EOFError, KeyboardInterrupt, RuntimeError):
                return
            loop.call_soon_threadsafe(fila.put_nowait, linha)

    threading.Thread(target=ler, name="teclado", daemon=True).start()
