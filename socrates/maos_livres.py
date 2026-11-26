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
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from . import ferramentas
from .audio import TAXA_MIC, ErroAudio
from .audio.escuta import EventoMicrofone, Fala
from .ferramentas import claude
from .audio.microfone import para_wav
from .config import Config
from .core.comandos import Comando, interpretar
from .core.despertar import chamou, nome_do_claude
from .core.narrador import ecoar, narrar
from .core.orquestrador import Orquestrador
from .llm import ErroCerebro
from .llm.acoes import pede_acao
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

Trilhas da PRF: Penal, Processo Penal, Legislação Especial (aulas e direção):
  "me ensina legítima defesa"   "vamos estudar processo penal"   "o que eu estudo de penal?"
  "o que eu estudei hoje?"   "o que eu já aprendi?"   "questões de drogas"   "meu mapa"
  Na aula: responda a pergunta dele; "próximo", "repete" ou "parar".
  Clique no visor (ou aperte Espaço) para ele parar de falar.

Autoestudo (ele estuda sozinho o edital enquanto você está quieto; veja no canto do visor):
  "o que você está aprendendo?"   "o que você aprendeu hoje?"   "aprende sobre crase"
  "pausa o aprendizado"   "volta a aprender"

Ele decide sozinho (fale do seu jeito, pode pedir duas coisas juntas):
  "abre o bloco de notas e coloca o artigo 7 do CTB"   "e os primeiros artigos do Código Penal?"
  "lembra que minha prova é em março"   "o que você sabe de mim?"   "manda suas ideias para o Claude"

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
    "e 'grafico:' se couber um gráfico). Se ele pediu mapa mental, esquema, cenários ou passo a "
    "passo, use a linha 'mapa:', 'cenarios:' ou 'fluxo:' e os ramos com - (detalhes recuados). "
    "Nada fora do quadro.")

_PEDE_QUADRO = re.compile(
    r"\b(quadro|formula|formulas|grafico|graficos|desenh\w*|mostr\w*|escrev\w*|equac\w*"
    r"|calcul\w*|resolv\w*|passo a passo|demonstr\w*|teorema|funcao|derivada|integral"
    r"|mapas? menta(?:l|is)|esquemas?|cenarios?|fluxogramas?|diagramas?|organogramas?)\b")


_DO_TREINO = re.compile(r"\b(quadro|questao|questoes|item|itens|afirmacao|alternativa|gabarito|"
                        r"anterior|proxima|proximo|explica\w*|dica|repete|repita)\b")


def _sem_acento(texto: str) -> str:
    return unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()


AVISO_OUVIDO_SEG = 300   # avisa em voz que não está ouvindo no máximo a cada 5 minutos
VOZ_MIN_JANELA = 0.1     # segundos de voz (detector) para valer como fala, na janela
VOZ_MIN_FORA = 0.2       # fora da janela só vale o nome ("Sócrates" tem mais de meio segundo)


def pede_quadro(pedido: str) -> bool:
    """O aluno pediu algo visual? (aí o quadro tem que aparecer)"""
    t = unicodedata.normalize("NFKD", pedido).encode("ascii", "ignore").decode().lower()
    return bool(_PEDE_QUADRO.search(t))


class Conversa:
    def __init__(self, cfg: Config, soc: Orquestrador, sentidos, painel: Painel,
                 escrever: Callable[[str], None] | None = None, tutor=None, agente=None,
                 vad=None):
        self.cfg = cfg
        self.vad = vad                # detector de voz (audio/vad.py); None = tudo vai ao Whisper
        self.tutor = tutor
        self.agente = agente          # o cérebro que decide (core/agente.py); None = só as regras
        self._falhas_ouvido = 0       # transcrições que falharam seguidas
        self._avisou_ouvido = -1e9
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
            if isinstance(e, ErroVoz) and len(texto) > 12:
                self._avisar_sem_voz(texto)

    def _avisar_sem_voz(self, texto: str) -> None:
        """A voz falhou (o Edge e a reserva): o que ele ia falar aparece escrito no quadro e
        no canto do visor, para você não ficar sem resposta sem saber por quê."""
        texto = re.sub(r"\s+", " ", texto or "").strip()
        if not texto:
            return
        from .estudo.treino import _quadro_seguro

        log.warning("sem voz: mostrei escrito: %r", texto[:120])
        if not self._quadros_nesta:
            self._ao_quadro(_quadro_seguro(f"# Sem voz agora (leia aqui)\n{texto[:900]}"))
            self.painel.aprendendo = "◆ sem voz agora: a resposta está escrita no quadro"
        else:
            self.painel.aprendendo = "◆ sem voz agora: a resposta está escrita no terminal"

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
            mudas: list[str] = []
            try:
                await narrar(pedacos, self.s.voz,
                             ao_falhar=lambda e: self.escrever(f"\n[voz] {e} Seguindo em texto.\n"),
                             sem_voz=mudas.append)
                self.dizer_tela()
                self._avisar_sem_voz(" ".join(mudas))
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

    async def falar_resposta(self, texto: str) -> None:
        """Fala uma resposta pronta (a do agente), com o quadro e a interrupção de sempre."""
        from .core.quadro_fluxo import separar_quadro

        self.escrever(f"{self.cfg.nome}: ")

        async def fonte():
            yield texto

        pedacos = ecoar(separar_quadro(fonte(), self._ao_quadro), self.escrever)

        async def tarefa():
            mudas: list[str] = []
            try:
                await narrar(pedacos, self.s.voz,
                             ao_falhar=lambda e: self.escrever(f"\n[voz] {e} Seguindo em texto.\n"),
                             sem_voz=mudas.append)
                self.dizer_tela()
                self._avisar_sem_voz(" ".join(mudas))
            except ErroAudio as e:
                self.dizer_tela(f"\n[som] {e}")
            finally:
                self.painel.estado = "ocioso"

        await self._interrompivel(tarefa())

    async def _com_agente(self, pedido: str) -> bool:
        """O cérebro que decide cuida da fala. False = ele falhou (sem internet, limite):
        aí a conversa segue pelo caminho antigo (regras do tutor + conversa)."""
        self.painel.estado = "pensando"
        try:
            r = await self.agente.atender(pedido, self.soc.historico, self.soc.modo)
        except ErroCerebro as e:
            log.warning("o cérebro que decide falhou (%s); seguindo pelas regras", e)
            self.painel.estado = "ocioso"
            return False
        except Exception:
            log.exception("o cérebro que decide quebrou; seguindo pelas regras")
            self.painel.estado = "ocioso"
            return False
        if r.saida is not None:                 # o tutor assumiu (aula, treino, consulta)
            await self.executar_saida(pedido, r.saida)
            return True
        self._quadros_nesta = 0
        if r.quadro:
            self._ao_quadro(r.quadro)
        texto = r.texto or ("Pronto." if r.ferramentas else "")
        if not texto:
            self.painel.estado = "ocioso"
            return False
        self.soc.registrar(pedido, texto)
        await self.falar_resposta(texto)
        return True

    def _atalho_do_tutor(self, pedido: str) -> bool:
        """Pedido de estudo curto e claro ("questões da PRF", "me ensina furto", "meu
        mapa"): o tutor resolve na hora, sem gastar o cérebro. Frase longa, duas coisas
        juntas, correção ("não, eu quero...") ou coisa do PC vão para o cérebro que decide."""
        if self.tutor is None:
            return False
        t = unicodedata.normalize("NFKD", pedido).encode("ascii", "ignore").decode().lower()
        t = re.sub(r"[^a-z0-9 ]", " ", t).split()
        if not t or len(t) > 7 or t[0] in ("nao", "mas", "e", "entao") \
                or {"se", "depois", "mas", "tambem", "porque", "pq"} & set(t) or pede_acao(pedido):
            return False
        try:
            return self.tutor.entender(pedido) is not None
        except Exception:
            return False

    def _som_ligado(self) -> bool:
        """Abriu vídeo ou música: o som do PC entra no microfone. Para não responder ao
        vídeo, volta a esperar o nome "Sócrates"."""
        if not ferramentas.SOM_LIGADO.is_set():
            return False
        ferramentas.SOM_LIGADO.clear()
        self.painel.fechar_janela()
        self.dizer_tela('(som tocando: me chame pelo nome, "Sócrates", para continuar)')
        return True

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
        if getattr(saida, "abrir_pagina", None):
            await asyncio.to_thread(abrir_pagina, saida.abrir_pagina)
        if saida.quadro:
            self._quadros_nesta = 0
            self._ao_quadro(saida.quadro)
        if saida.contexto:                 # a aula: o ponto já está no quadro, o cérebro explica
            await self.responder(pedido, extra=saida.contexto)
            return
        if saida.fala:
            self.soc.registrar(pedido, saida.fala)   # o "sim"/"vai" seguinte sabe do que se trata
            self.dizer_tela(f"{self.cfg.nome}: {saida.fala}")
            await self._interrompivel(self._falar(saida.fala, False))

    async def _sem_voz(self, fala: np.ndarray, em_janela: bool) -> bool:
        """O trecho não tem voz humana (sopro, clique, TV, chiado)? Na janela de conversa a
        exigência é menor: "Sim." tem uns 0,13 s de voz; fora dela, só vale o nome, que é
        mais comprido."""
        if self.vad is None:
            return False
        try:
            voz = await asyncio.to_thread(self.vad.segundos_de_voz, fala)
        except Exception as e:
            log.warning("detector de voz falhou (%s); desligado nesta sessão", e)
            self.vad = None
            return False
        minimo = VOZ_MIN_JANELA if em_janela else VOZ_MIN_FORA
        if voz < minimo:
            log.info("descartado sem gastar o Whisper: %.2f s de voz em %.1f s de som",
                     voz, len(fala) / TAXA_MIC)
            return True
        return False

    async def _transcrever(self, fala: np.ndarray, em_janela: bool) -> str:
        if await self._sem_voz(fala, em_janela):
            return ""
        if em_janela:
            self.painel.estado = "pensando"
        try:
            dica = self.dica_do_ouvido()
            if dica:
                texto = await self.s.ouvido.transcrever(para_wav(fala), dica)
            else:
                texto = await self.s.ouvido.transcrever(para_wav(fala))
            self._falhas_ouvido = 0
            return texto
        except ErroOuvido as e:
            await self._ouvido_falhou(e)
            return ""
        finally:
            self.painel.estado = "ocioso"

    async def _ouvido_falhou(self, e: ErroOuvido) -> None:
        """Antes, fora da janela, a falha da transcrição era engolida calada: você chamava
        "Sócrates" e nada acontecia. Agora fica no registro, no terminal e no canto do
        visor, e na 2ª falha seguida ele avisa em voz (no máximo a cada 5 minutos)."""
        log.warning("não consegui transcrever: %s", e)
        self.dizer_tela(f"[ouvido] {e}")
        self.painel.aprendendo = f"◆ não consegui ouvir: {e}"
        self._falhas_ouvido += 1
        agora = time.monotonic()
        if self._falhas_ouvido >= 2 and agora - self._avisou_ouvido >= AVISO_OUVIDO_SEG:
            self._avisou_ouvido = agora
            await self.falar(f"Não estou conseguindo te ouvir. {e}", False)

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
        texto = nome_do_claude(texto)
        foi_chamado, pedido = chamou(texto)
        if foi_chamado:
            self.dizer_tela(f"\nVocê: {pedido or '(chamou)'}")
            return pedido
        if em_janela:
            self.dizer_tela(f"\nVocê: {texto}")
            return texto
        log.info("ignorado (sem o nome): %r", texto)
        return None

    def _recado_do_claude(self) -> str:
        """O Claude (que programa o Sócrates) pode deixar um recado na pasta dele: o que
        melhorou. Ele lê na saudação uma vez e guarda como lido."""
        from .core.memoria import PASTA
        arq = PASTA / "recado_do_claude.txt"
        try:
            texto = re.sub(r"\s+", " ", arq.read_text(encoding="utf-8")).strip()
        except OSError:
            return ""
        try:
            arq.replace(arq.with_name("recado_do_claude.lido.txt"))
        except OSError:
            pass
        return texto[:500]

    def _saudacao(self, palavra: bool) -> str:
        """Com o cérebro que decide, ele já chega com iniciativa: o plano do dia."""
        recado = self._recado_do_claude()
        if recado:
            recado = f"Recado do Claude: {recado} "
        fim = "É só me chamar pelo nome." if palavra else "Pode falar."
        if (self.agente is not None and self.tutor is not None
                and getattr(self.cfg, "agente", None) is not None
                and self.cfg.agente.saudacao_com_plano):
            try:
                plano = self.tutor.plano()
            except Exception:
                log.exception("plano do dia")
                plano = None
            if plano is not None and plano.fala:
                if plano.quadro:
                    self._ao_quadro(plano.quadro)
                fala = f"Olá! {recado}{plano.fala}"
                self.soc.registrar(None, fala)
                return fala
        fala = f"Olá! {recado}Eu sou o {self.cfg.nome}. {fim}"
        if recado:
            self.soc.registrar(None, fala)
        return fala

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
            await self.falar(self._saudacao(palavra), False)
        self.dizer_tela('\nEsperando você dizer "Sócrates"...' if palavra else "\nOuvindo...")

        while True:
            item = await fila.get()
            if item is None:
                break
            if isinstance(item, ErroAudio):
                self.dizer_tela(f"[microfone] {item} Você ainda pode digitar.")
                continue
            if isinstance(item, EventoMicrofone):     # caiu (e ele tenta reconectar) ou voltou
                self.dizer_tela(f"[microfone] {item.texto}")
                self.painel.aprendendo = "" if item.voltou else "◆ microfone desconectado: reconectando..."
                await self.falar(item.texto, False)
                continue
            if isinstance(item, Aviso):
                self.dizer_tela(f"\n{self.cfg.nome}: {item.texto}")
                self.soc.registrar(None, item.texto)
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
                    self.soc.registrar(pedido, resposta)
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

            no_pc = (self.agente is not None and pede_acao(pedido) and len(pedido.split()) >= 2
                     and not _DO_TREINO.search(_sem_acento(pedido)))
            # "abre o bloco de notas" no meio do treino vai ao agente; "coloca a questão no
            # quadro" é do treino (antes o agente inventava a questão)
            if (self.tutor is not None and self.tutor.em_treino and not _comando_geral(pedido)
                    and not no_pc):
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

            if (self.agente is not None and not self._atalho_do_tutor(pedido)
                    and await self._com_agente(pedido)):
                if not self._som_ligado():
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
            if self._som_ligado():
                continue
            self.abrir_janela()

        self.painel.fechar_janela()
        if self.tutor is not None:
            self.tutor.encerrar()          # guarda o treino que estava no meio
        despedida = ("Até já, volto atualizado." if claude.REINICIAR.is_set()
                     else "Até a próxima. Bons estudos!")
        self.dizer_tela(f"\n{self.cfg.nome}: {despedida}")
        await self.falar(despedida, False)


def abrir_pagina(caminho: str) -> None:
    """Abre uma página do Sócrates (o mapa da trilha) no navegador padrão."""
    try:
        from .ferramentas.computador import WINDOWS, _iniciar
        if WINDOWS:
            _iniciar(caminho)
            return
        import webbrowser
        webbrowser.open(Path(caminho).as_uri())
    except Exception as e:      # abrir a página é um extra: não derruba a conversa
        log.warning("não consegui abrir %s: %s", caminho, e)


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
