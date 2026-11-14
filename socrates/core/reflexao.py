"""Todo dia o Sócrates relê o próprio registro (socrates.log) e aprende com os erros.

Ele procura onde entendeu errado, onde o aluno corrigiu ou repetiu o pedido, onde
inventou (lei, artigo), onde perguntou demais, onde a voz ou uma ferramenta falhou e o
que pediram que ele não sabia fazer. Disso saem:

  LIÇÕES    regras curtas que entram no prompt dele dali em diante (licoes.json)
  MELHORIAS ideias de mudança no código, que ele manda ao Claude quando o aluno deixar
            (melhorias.json)

Roda uma vez por dia, em segundo plano, quando há conversa nova no registro.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("socrates.reflexao")

MIN_EVENTOS = 4          # menos que isso não vale a pena refletir
CORTE_REGISTRO = 9000    # caracteres do registro que vão para o cérebro
MAX_LICOES = 5
MAX_MELHORIAS = 3

_DATA = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})")
_STR = r"""(?P<q{n}>['"])(?P<{nome}>.*?)(?P=q{n})"""
_CONVERSA = re.compile(r"socrates\.orquestrador: aluno: " + _STR.format(n=1, nome="aluno")
                       + r" \| .*? respondeu \(\d+ caracteres\): " + _STR.format(n=2, nome="resp")
                       + r"$")
_AGENTE = re.compile(r"socrates\.agente: agente: " + _STR.format(n=1, nome="aluno")
                     + r" -> (?P<ferr>\S+) \| " + _STR.format(n=2, nome="resp") + r"$")
_TUTOR = re.compile(r"socrates\.tutor: pedido de estudo: Pedido\(tipo='(?P<tipo>\w+)'")
_IGNORADO = re.compile(r"socrates\.conversa: ignorado \(sem o nome\): (?P<t>.*)$")
_FALHA = re.compile(r"\b(WARNING|ERROR)\s+socrates\.(?P<onde>[\w.]+): (?P<msg>.*)$")
_RUIDO = ("descansa", "limite do", "usando o modelo reserva", "autoestudo", "não conferi",
          "busca falhou")

PEDIDO = """Você é o {nome}, um assistente de estudo por voz, revisando o registro das suas
últimas conversas com o aluno para melhorar sozinho. Procure no registro:
- onde você entendeu errado ou fez outra coisa (o aluno corrigiu, repetiu ou reclamou);
- onde você inventou ou errou conteúdo (lei, artigo, número);
- onde perguntou demais em vez de agir;
- onde a voz, o ouvido ou uma ferramenta falhou;
- o que ele pediu e você não sabia fazer.

Responda SOMENTE com um JSON assim:
{{"licoes": ["regra curta, no imperativo, para você seguir daqui em diante"],
  "melhorias": ["mudança concreta no seu código, para o programador (Claude) fazer"]}}
No máximo {max_l} lições e {max_m} melhorias, só o que o registro MOSTRA (nada genérico).
Se não houver nada, devolva listas vazias.
{ja}
Registro (ALUNO = o que ele falou; SÓCRATES = sua resposta; [ferramentas]; FALHA = erro):
{registro}"""


def _sem_escape(texto: str) -> str:
    return texto.replace("\\n", " ").replace("\\'", "'").replace('\\"', '"')


def eventos_do_log(linhas: list[str], depois_de: str = "") -> tuple[list[str], str]:
    """(eventos legíveis, data do último) das linhas do registro posteriores a `depois_de`."""
    eventos: list[str] = []
    ultimo = depois_de
    for linha in linhas:
        m = _DATA.match(linha)
        if not m:
            continue
        quando = m.group(1)
        if quando <= depois_de:
            continue
        ultimo = max(ultimo, quando)
        hora = quando[11:16]
        c = _CONVERSA.search(linha) or _AGENTE.search(linha)
        if c:
            ferr = c.groupdict().get("ferr")
            extra = f" [{ferr}]" if ferr and ferr != "-" else ""
            eventos.append(f"{hora} ALUNO: {_sem_escape(c.group('aluno'))[:220]}")
            eventos.append(f"{hora} SÓCRATES{extra}: {_sem_escape(c.group('resp'))[:320]}")
            continue
        t = _TUTOR.search(linha)
        if t:
            eventos.append(f"{hora} [tutor: {t.group('tipo')}]")
            continue
        i = _IGNORADO.search(linha)
        if i:
            eventos.append(f"{hora} (ignorado por falta do nome: {i.group('t')[:80]})")
            continue
        f = _FALHA.search(linha)
        if f and not any(r in f.group("msg") for r in _RUIDO):
            eventos.append(f"{hora} FALHA ({f.group('onde')}): {f.group('msg')[:160]}")
    # falhas repetidas em sequência viram uma só linha
    compacto: list[str] = []
    for e in eventos:
        if compacto and "FALHA" in e and e[6:] == compacto[-1][6:]:
            continue
        compacto.append(e)
    return compacto, ultimo


def _json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto or "", re.S)
    if not m:
        return {}
    try:
        dados = json.loads(m.group(0))
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


def _frases(lista, maximo: int) -> list[str]:
    saida = []
    for x in lista or []:
        if isinstance(x, str) and 8 <= len(x.strip()) <= 300:
            saida.append(x.strip())
    return saida[:maximo]


class Reflexao:
    def __init__(self, cerebro, memorias, arquivo_log: Path, arquivo_estado: Path | None = None,
                 nome: str = "Sócrates", hoje=date.today):
        self.cerebro = cerebro                  # precisa de responder() (o rodízio)
        self.memorias = memorias
        self.arquivo_log = Path(arquivo_log)
        self.arquivo_estado = Path(arquivo_estado) if arquivo_estado else \
            memorias.licoes.arquivo.with_name("reflexao.json")
        self.nome = nome
        self.hoje = hoje

    def _estado(self) -> dict:
        try:
            return json.loads(self.arquivo_estado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _gravar_estado(self, estado: dict) -> None:
        try:
            self.arquivo_estado.parent.mkdir(parents=True, exist_ok=True)
            self.arquivo_estado.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
        except OSError as e:
            log.warning("não gravei o estado da reflexão: %s", e)

    def precisa(self) -> bool:
        return self._estado().get("data") != self.hoje().isoformat() and self.arquivo_log.exists()

    async def refletir(self) -> tuple[list[str], list[str]] | None:
        """Lê o registro novo e grava lições e melhorias. None = nada a fazer hoje."""
        if not self.precisa():
            return None
        estado = self._estado()
        try:
            linhas = self.arquivo_log.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            return None
        eventos, ultimo = eventos_do_log(linhas, estado.get("ate", ""))
        conversas = sum(1 for e in eventos if " ALUNO: " in e)
        if conversas < MIN_EVENTOS:
            log.info("reflexão: só %d conversas novas; fica para depois", conversas)
            return None
        registro = "\n".join(eventos)
        if len(registro) > CORTE_REGISTRO:
            registro = registro[-CORTE_REGISTRO:].split("\n", 1)[-1]
        ja = self.memorias.licoes.textos()
        pedido = PEDIDO.format(nome=self.nome, max_l=MAX_LICOES, max_m=MAX_MELHORIAS,
                               ja=("Lições que você já tem (não repita): " + " | ".join(ja[-15:]))
                               if ja else "", registro=registro)
        texto = "".join([p async for p in self.cerebro.responder(
            [{"role": "system", "content": "Responda só com JSON válido."},
             {"role": "user", "content": pedido}])])
        dados = _json(texto)
        licoes = [l for l in _frases(dados.get("licoes"), MAX_LICOES)
                  if self.memorias.licoes.adicionar(l, origem="reflexao")]
        melhorias = [m for m in _frases(dados.get("melhorias"), MAX_MELHORIAS)
                     if self.memorias.melhorias.adicionar(m, status="nova", origem="reflexao")]
        self._gravar_estado({"data": self.hoje().isoformat(), "ate": ultimo,
                             "quando": datetime.now().isoformat(timespec="seconds"),
                             "licoes": len(licoes), "melhorias": len(melhorias)})
        log.info("reflexão: %d lições novas, %d ideias de melhoria", len(licoes), len(melhorias))
        return licoes, melhorias


def aviso_da_reflexao(licoes: list[str], melhorias: list[str]) -> str:
    """O que ele conta ao aluno (ou "" se não aprendeu nada novo)."""
    if not licoes and not melhorias:
        return ""
    partes = ["Revisei nossas últimas conversas"]
    if licoes:
        n = len(licoes)
        partes.append(f"e anotei {n} {'lição' if n == 1 else 'lições'} para mim, "
                      f"como: {licoes[0].rstrip('.')}")
    fala = " ".join(partes) + "."
    if melhorias:
        fala += (f" Também tenho {len(melhorias)} ideia{'s' if len(melhorias) > 1 else ''} para "
                 "melhorar meu código. Se quiser, diga: manda suas ideias para o Claude.")
    return fala
