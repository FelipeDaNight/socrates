"""Transcrição com Whisper, rodando grátis nos servidores do Groq.

O Whisper "inventa" texto quando o áudio é só ruído, música ou silêncio. Aqui há
quatro defesas, da mais confiável para a mais simples:

  1. Confiança: o próprio Whisper devolve, para cada trecho, o quanto ele acha que
     havia fala (no_speech_prob), a certeza das palavras (avg_logprob) e se o texto
     ficou repetitivo (compression_ratio). Trecho ruim é descartado.
  2. Eco da dica: mandamos um vocabulário para ele acertar nomes ("Bhaskara", "CTB").
     No silêncio ele às vezes devolve esse vocabulário como se você tivesse dito.
  3. Repetição: "cosseno, cosseno, cosseno, cosseno...".
  4. Frases de legenda de vídeo ("Legendas pela comunidade...").
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass

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
    # vistas no registro de 22/11 (com a janela aberta, ele respondeu "Aplausos" com
    # palmas e pesquisou "Sous-titrage Société Radio-Canada" na internet)
    "aplausos",
    "amem",
    "musica",
    "risos",
    "soustitrage societe radiocanada",
    "thank you for watching",
    "thanks for watching",
    "",
}

# Vocabulário para o Whisper escrever certo os nomes que mais aparecem. É uma lista
# de palavras soltas DE PROPÓSITO: uma frase como "Pede pro Claude." virava um pedido
# fantasma quando ele a repetia no silêncio.
DICA = ("Sócrates, Bhaskara, Pitágoras, logaritmo, crase, regência, Cebraspe, AOCP, CTB, "
        "CONTRAN, PRF, CBMGO, Fuvest, ENEM, pomodoro, lacunas, Claude.")

# Durante uma aula de Direito Penal: os termos que mais aparecem
DICA_PENAL = ("Sócrates, Direito Penal, Cebraspe, PRF, dolo, culpa, tentativa, legítima defesa, "
              "abolitio criminis, peculato, concussão, prevaricação, estelionato, receptação, "
              "latrocínio, descaminho, imputabilidade, próximo.")

# Durante um treino de questões, o que se espera ouvir são respostas curtas
DICA_TREINO = ("Certo, errado, pular, próxima, repete, explica, dica, parar, "
               "letra A, letra B, letra C, letra D, letra E.")

# Limites de confiança (ver a explicação no topo). O log mostra as medidas de cada
# fala: se ele descartar o que você disse, ou aceitar ruído, é aqui que se ajusta.
SEM_FALA_MAX = 0.6        # acima disso o Whisper acha que não havia fala...
LOGPROB_COM_SEM_FALA = -0.6   # ...e, se além disso a certeza for baixa, é ruído
LOGPROB_MIN = -1.2        # certeza tão baixa que o texto é chute
COMPRESSAO_MAX = 2.6      # texto repetitivo demais
# Fala de 1 ou 2 palavras com certeza baixa quase sempre é ruído ("Mie.", "Hum...", "Bom.")
# e o cérebro tentava achar sentido nela (chegou a mandar de novo um pedido ao Claude).
LOGPROB_CURTA = -0.9
TEMPO_MAXIMO = 20.0          # segundos para o Groq devolver a transcrição
CURTAS_VALIDAS = {"sim", "nao", "certo", "certa", "errado", "errada", "proxima", "proximo", "pula",
                  "pular", "passa", "repete", "explica", "explique", "dica", "para", "parar", "chega",
                  "ok", "tchau", "obrigado", "obrigada", "valeu", "socrates", "pode", "vai", "bora",
                  "segue", "siga", "continua", "isso", "claro", "beleza", "letra", "a", "b", "c", "d",
                  "e", "oi", "ola", "manda", "pronto", "verdadeiro", "falso", "cancela", "sair"}


def _normalizar(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z ]", "", sem_acento.lower()).strip()


def _palavras(texto: str) -> list[str]:
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.findall(r"[a-z0-9]+", sem_acento.lower())


# Créditos de legenda que o Whisper "ouve" no silêncio ("Legenda por Sônia Ruberti")
_PREFIXOS_ALUCINADOS = ("legenda por", "legendas por", "legendado por", "legendas pela",
                        "transcricao e legendas", "traducao e legendas", "subtitles by",
                        "legenda adriana zanotto", "legendas adriana zanotto",   # 9 vezes em 22/11
                        "soustitrage", "soustitres", "subtitulos realizados")


# Uma letra só, repetida: "FFFF!" (25/11, sopro no microfone) virou pergunta do aluno
_UMA_LETRA = re.compile(r"([a-z])\1{2,}")


def filtrar_alucinacao(texto: str) -> str:
    n = _normalizar(texto)
    if n in ALUCINACOES or n.startswith(_PREFIXOS_ALUCINADOS):
        return ""
    if _UMA_LETRA.fullmatch(n.replace(" ", "")):
        return ""
    return texto.strip()


def e_eco(texto: str, dica: str) -> bool:
    """O texto é (quase só) um pedaço da dica, na mesma ordem?

    Ninguém fala "Bhaskara, Pitágoras, logaritmo" do nada: três palavras seguidas
    iguais às da dica são o Whisper repetindo o vocabulário."""
    t, d = _palavras(texto), _palavras(dica)
    if len(t) < 3:
        return False
    trios = {tuple(d[i:i + 3]) for i in range(len(d) - 2)}
    coberto = [False] * len(t)
    for i in range(len(t) - 2):
        if tuple(t[i:i + 3]) in trios:
            coberto[i] = coberto[i + 1] = coberto[i + 2] = True
    n = sum(coberto)
    return n >= 4 or n / len(t) >= 0.5


def sem_repeticoes(texto: str) -> str:
    """Tira "cosseno, cosseno, cosseno, cosseno" (4 ou mais iguais em seguida).

    Vale também para grupos de 2 ou 3 palavras repetidos 4 vezes ou mais
    ("E aí E aí E aí E aí E aí", inventado no silêncio em 22/11).
    Se não sobrar quase nada, a fala inteira era alucinação. Repetição de 6 vezes ou mais
    ninguém fala: é música ou invenção do Whisper, e a fala inteira sai (27/11, com o Spotify
    tocando: "...é uma luta, uma luta, uma luta [9 vezes]..." e ele respondeu)."""
    pedacos = re.findall(r"\S+", texto)
    chaves = ["".join(_palavras(p)) for p in pedacos]
    saida, cortou, i, mais_vezes = [], False, 0, 0
    while i < len(pedacos):
        maior = 0                  # quantos pedaços a repetição a partir de i cobre
        for n in (1, 2, 3):
            grupo = chaves[i:i + n]
            if len(grupo) < n or not all(grupo):
                continue
            k = 1
            while chaves[i + k * n:i + (k + 1) * n] == grupo:
                k += 1
            if k >= 4:
                maior = max(maior, k * n)
                mais_vezes = max(mais_vezes, k)
        if maior:
            cortou = True          # a sequência repetida some inteira
            i += maior
        else:
            saida.append(pedacos[i])
            i += 1
    if not cortou:
        return texto.strip()
    if mais_vezes >= REPETICAO_DE_MUSICA:
        return ""
    resto = " ".join(saida).strip()
    return resto if len(_palavras(resto)) >= 3 else ""


REPETICAO_DE_MUSICA = 6


@dataclass
class Medida:
    """Confiança de uma transcrição (a média dos trechos aproveitados)."""
    logprob: float | None = None
    sem_fala: float | None = None
    compressao: float | None = None
    descartados: int = 0

    def __str__(self) -> str:
        if self.logprob is None:
            return "sem medidas"
        return (f"certeza {self.logprob:.2f}, sem fala {self.sem_fala:.2f}, "
                f"compressão {self.compressao:.1f}"
                + (f", {self.descartados} trecho(s) descartado(s)" if self.descartados else ""))


def _campo(trecho, nome: str, padrao=None):
    if isinstance(trecho, dict):
        return trecho.get(nome, padrao)
    return getattr(trecho, nome, padrao)


def parece_legenda(texto: str, logprob: float | None) -> bool:
    """Com ruído, o Whisper inventa frases em MAIÚSCULAS ("A CIDADE NO BRASIL", "CELSO
    SÓRICA"), e com a janela aberta o Sócrates respondia a elas. Se chamou pelo nome, vale."""
    if logprob is None or logprob >= -0.6:
        return False
    letras = [c for c in texto if c.isalpha()]
    if len(letras) < 6 or sum(c.isupper() for c in letras) / len(letras) < 0.8:
        return False
    return "socrat" not in _normalizar(texto)


def curta_duvidosa(texto: str, logprob: float | None) -> bool:
    """1 ou 2 palavras, certeza baixa e não é uma resposta/comando conhecido: ruído."""
    if logprob is None or logprob >= LOGPROB_CURTA:
        return False
    palavras = _normalizar(texto).split()
    return 0 < len(palavras) <= 2 and not all(p in CURTAS_VALIDAS for p in palavras)


def trecho_confiavel(logprob: float | None, sem_fala: float | None,
                     compressao: float | None) -> bool:
    if compressao is not None and compressao > COMPRESSAO_MAX:
        return False
    if logprob is not None and logprob < LOGPROB_MIN:
        return False
    if (sem_fala is not None and logprob is not None
            and sem_fala > SEM_FALA_MAX and logprob < LOGPROB_COM_SEM_FALA):
        return False
    return True


def avaliar(resposta) -> tuple[str, Medida]:
    """Junta só os trechos confiáveis da resposta do Whisper."""
    trechos = _campo(resposta, "segments") or []
    if not trechos:   # servidor que não manda as medidas: fica o texto como veio
        return (_campo(resposta, "text", "") or "").strip(), Medida()
    bons, medida = [], Medida()
    somas = [0.0, 0.0, 0.0]
    for t in trechos:
        lp, sf, cr = (_campo(t, "avg_logprob"), _campo(t, "no_speech_prob"),
                      _campo(t, "compression_ratio"))
        if not trecho_confiavel(lp, sf, cr):
            medida.descartados += 1
            log.info("trecho descartado (parece ruído): %r [certeza %s, sem fala %s, compressão %s]",
                     (_campo(t, "text", "") or "").strip(), lp, sf, cr)
            continue
        bons.append((_campo(t, "text", "") or "").strip())
        for i, v in enumerate((lp, sf, cr)):
            somas[i] += v or 0.0
    if bons:
        medida.logprob, medida.sem_fala, medida.compressao = (s / len(bons) for s in somas)
    return " ".join(b for b in bons if b).strip(), medida


class OuvidoWhisper(Ouvido):
    def __init__(self, base_url: str, chave: str, modelo: str = "whisper-large-v3-turbo",
                 idioma: str = "pt", http_client=None):
        self.modelo = modelo
        self.idioma = idioma
        self.ultima_medida = Medida()
        # Sem limite, uma transcrição presa (internet ruim) travava a conversa por até 10
        # minutos, calada: "ele não me entende quando chamo". 20 s e uma nova tentativa.
        self._cliente = AsyncOpenAI(base_url=base_url, api_key=chave, http_client=http_client,
                                    timeout=TEMPO_MAXIMO, max_retries=1)

    async def transcrever(self, audio_wav: bytes, dica: str | None = None) -> str:
        dica = dica or DICA
        try:
            r = await self._cliente.audio.transcriptions.create(
                model=self.modelo,
                file=("fala.wav", audio_wav, "audio/wav"),
                language=self.idioma,
                prompt=dica,
                temperature=0,
                response_format="verbose_json",   # traz as medidas de confiança
            )
        except openai.RateLimitError as e:
            raise ErroOuvido("Limite grátis de transcrição atingido. Espere um minuto.") from e
        except openai.AuthenticationError as e:
            raise ErroOuvido("Chave do Groq inválida. Confira o arquivo .env.") from e
        except openai.APITimeoutError as e:
            raise ErroOuvido("A internet está lenta: a transcrição demorou demais.") from e
        except openai.APIConnectionError as e:
            raise ErroOuvido("Sem conexão para transcrever. Verifique a internet.") from e
        except openai.APIStatusError as e:
            raise ErroOuvido(f"O Groq recusou o áudio ({e.status_code}).") from e
        bruto, self.ultima_medida = avaliar(r)
        texto = filtrar_alucinacao(bruto)
        if bruto.strip() and not texto:
            log.info("descartado (frase que o Whisper inventa no silêncio): %r", bruto)
            return ""
        if texto and e_eco(texto, dica):
            log.info("descartado (eco da dica): %r", texto)
            texto = ""
        if texto:
            limpo = sem_repeticoes(texto)
            if limpo != texto:
                log.info("repetição removida: %r -> %r", texto, limpo)
            texto = limpo
        if texto and parece_legenda(texto, self.ultima_medida.logprob):
            log.info("descartado (frase em maiúsculas e incerta, parece invenção do Whisper): %r (%s)",
                     texto, self.ultima_medida)
            return ""
        if texto and curta_duvidosa(texto, self.ultima_medida.logprob):
            log.info("descartado (curto e incerto, parece ruído): %r (%s)", texto, self.ultima_medida)
            return ""
        log.info("transcrito: %r (%s)", texto, self.ultima_medida)
        return texto
