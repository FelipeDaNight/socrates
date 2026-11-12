"""Cérebro que, quando você pede uma AÇÃO ("abre a calculadora", "toca lo-fi no
YouTube", "inicia um pomodoro"), usa as ferramentas do seu computador.

Pedidos que não são ações seguem para o cérebro normal (com pesquisa, se
estiver ligada), sem custo extra.
"""

from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from typing import AsyncIterator

from .. import ferramentas
from .base import Cerebro, Mensagem

log = logging.getLogger("socrates.acoes")

INSTRUCAO = """Você pode controlar o computador do aluno usando as ferramentas.
Use a ferramenta certa para o pedido; pode usar várias em sequência (ex.: ver_tela e depois
responder sobre o que viu). Depois de uma ação, confirme em UMA frase curta e natural
(ex.: "Pronto, abri a calculadora."). Se o pedido era para ver ou ler algo (tela, texto
copiado), responda ao aluno sobre o conteúdo, no seu jeito de professor, usando o quadro
se houver fórmula ou questão. Nunca diga que fez algo sem ter chamado a ferramenta.
Se a ferramenta der erro, explique em uma frase.
Se a ferramenta responder AGUARDANDO CONFIRMAÇÃO, a ação ainda NÃO aconteceu: pergunte ao
aluno, em uma frase curta, se pode fazer (ex.: "Vou mandar para o Claude: ... Posso mandar?")."""

MARCADOR = "executar"   # o modelo responde isso quando percebe um pedido de ação

INSTRUCAO_MARCADOR = """Você consegue mexer no computador do aluno: abrir e fechar programas,
trocar de janela, ver o que está na tela, saber quais janelas estão abertas, ler o texto que ele
copiou, copiar texto, escrever no Bloco de Notas, abrir sites e pastas, tocar no YouTube ou no
Spotify, passar ou pausar a música, volume, timer, anotar, bloquear a tela, mudar a cor do seu
visor, mandar pedidos de mudança para o Claude (quem programa você) e se atualizar.
Se o aluno pedir uma dessas ações, responda APENAS com a palavra EXECUTAR e mais nada.
Nunca diga que não consegue abrir programas ou mexer no computador."""

# Jeitos educados de pedir, antes do verbo: "você pode abrir...", "quero que você toque..."
_CORTESIA = (r"(?:(?:voce|vc|tu)\s+)?(?:pode|poderia|podia|consegue|conseguiria|da pra|da para"
             r"|quero que (?:voce |vc )?|preciso que (?:voce |vc )?|tem como|me ajuda a|faz o favor de)?\s*")
# Verbos de ação no começo da frase (imperativo ou infinitivo)
_VERBO = re.compile(
    r"^" + _CORTESIA +
    r"(abre|abra|abrir|abri|toca|toque|tocar|coloca|coloque|colocar|bota|bote|botar|poe|ponha"
    r"|aumenta|aumente|aumentar|abaixa|abaixe|abaixar|diminui|diminua|diminuir|baixa|baixe"
    r"|muta|silencia|silenciar|tira o som|anota|anote|anotar|salva|salve|bloqueia|bloqueie|bloquear"
    r"|cancela|cancele|cancelar|para o timer|pare o timer|inicia|inicie|iniciar|comeca|comece"
    r"|liga|ligue|ligar|executa|execute|executar|roda|rode|rodar"
    r"|fecha|feche|fechar|copia|copie|copiar|digita|digite|digitar|minimiza|minimize)\b"
)
# Verbos que são ação em qualquer lugar da frase ("o teste não deu certo, fecha o bloco de notas")
_VERBO_SOLTO = re.compile(r"\b(fecha|feche|fechar|digita|digite|digitar|minimiza|minimize)\b")
# Escrever é ação quando o destino é o Bloco de Notas (no quadro é explicação)
_ESCREVER = re.compile(r"\b(escreve|escreva|escrever|cria|crie|criar|faz|faca|fazer)\b.*\bbloco de notas\b")
# Assuntos que são sempre ação, em qualquer parte da frase
_ASSUNTO = re.compile(
    r"\b(volume|timer|cronometro|pomodoro|alarme|me avisa daqui|me avise daqui|me lembra daqui"
    r"|quanto tempo falta|no youtube|no spotify|minhas anotacoes|meu caderno"
    r"|no chrome|no navegador|no edge|no firefox|numa aba|nova aba"
    r"|(?:passa|passe|pula|pule|troca|troque|volta|volte|pausa|pause|pausar|para|pare|continua|retoma)"
    r" (?:a |essa |de |pra |para a |o )?(?:musica|faixa|som|video)|proxima musica|musica anterior"
    r"|cor do visor|sua cor|cor (?:pra|para) (?:azul|verde|roxo|vermelho|laranja|ciano|rosa|branco)"
    r"|visor (?:azul|verde|roxo|vermelho|laranja|ciano|rosa|branco)"
    r"|minha tela|na tela|da tela|nessa tela|o que (?:eu )?(?:estou|to|tou) vendo"
    r"|janelas abertas|o que (?:esta|ta) aberto|quais programas"
    r"|copiei|copiado|area de transferencia"
    r"|claude|cloud|cloudy|claudio|claudia|clode|claud"
    r"|se atualiza|se atualizar|atualiza o socrates|atualizar o socrates|versao nova)\b"
)


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    t = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()
    return re.sub(r"^(por favor|pfv|pf) ", "", t)


def pede_acao(pergunta: str) -> bool:
    t = _norm(pergunta)
    return bool(_VERBO.search(t) or _ASSUNTO.search(t) or _VERBO_SOLTO.search(t)
                or _ESCREVER.search(t))


ESTILO_CURTO = """Você é o Sócrates, assistente de estudo por voz, em português do Brasil.
Responda em frases curtas, para serem faladas, sem markdown. Se precisar mostrar fórmula ou
questão, escreva entre [QUADRO] e [/QUADRO]."""

HISTORICO_ACOES = 6     # só o fim da conversa: o plano grátis conta cada token
CORTE_MENSAGEM = 500


def _com_instrucao(mensagens: list[Mensagem]) -> list[Mensagem]:
    """Pedido ENXUTO para escolher ferramentas: estilo curto + data/cidade + fim da
    conversa. Sem a regra "responda EXECUTAR" (senão o modelo responde isso em vez
    de usar a ferramenta). Cerca de 1/3 do tamanho do pedido normal."""
    sistema = mensagens[0]["content"] if mensagens and mensagens[0]["role"] == "system" else ""
    contexto = [l for l in sistema.splitlines()
                if l.startswith(("Agora é", "O aluno mora", "Há pouco você viu"))]
    conversa = [dict(m) for m in mensagens if m["role"] in ("user", "assistant")
                and not (m["role"] == "assistant" and _norm(m["content"]) == MARCADOR)]
    conversa = conversa[-HISTORICO_ACOES:]
    for m in conversa[:-1]:
        if len(m["content"]) > CORTE_MENSAGEM:
            m["content"] = m["content"][:CORTE_MENSAGEM] + "..."
    topo = "\n\n".join([ESTILO_CURTO, *contexto, INSTRUCAO])
    return [{"role": "system", "content": topo}, *conversa]


async def _executar(nome: str, args: dict) -> str:
    return await asyncio.to_thread(ferramentas.executar, nome, args)


class CerebroComAcoes(Cerebro):
    def __init__(self, interno: Cerebro, base, nomes: list[str] | None = None):
        if not hasattr(base, "com_ferramentas"):
            raise TypeError("o cérebro base precisa ter com_ferramentas()")
        self.interno = interno
        self.base = base
        self.nome = f"{interno.nome}+acoes"
        self.nomes = nomes

    def esquemas(self) -> list[dict]:
        regs = ferramentas.REGISTRO
        nomes = self.nomes or list(regs)
        return [regs[n].esquema() for n in nomes if n in regs]

    async def responder(self, mensagens: list[Mensagem]) -> AsyncIterator[str]:
        pergunta = next((m["content"] for m in reversed(mensagens) if m["role"] == "user"), "")
        if pede_acao(pergunta):
            log.info("ação: %r", pergunta[:60])
            yield await self._agir(mensagens)
            return

        # Espia o começo: se o modelo respondeu EXECUTAR, era uma ação que o filtro não pegou
        inicio = ""
        fluxo = self.interno.responder(mensagens).__aiter__()
        async for pedaco in fluxo:
            inicio += pedaco
            if len(inicio.strip()) >= 12:
                break
        if _norm(inicio).startswith(MARCADOR):
            log.info("o modelo pediu ação: %r", pergunta[:60])
            async for _ in fluxo:
                pass
            yield await self._agir(mensagens)
            return
        if inicio:
            yield inicio
        async for pedaco in fluxo:
            yield pedaco

    async def _agir(self, mensagens: list[Mensagem]) -> str:
        texto = await self.base.com_ferramentas(_com_instrucao(mensagens), self.esquemas(),
                                                _executar)
        texto = texto.strip()
        if not texto or _norm(texto) == MARCADOR:
            return "Não consegui fazer isso agora. Tente pedir de outro jeito."
        return texto
