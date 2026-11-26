"""O que o Sócrates guarda para sempre, entre um dia e outro:

  memoria.json    fatos do aluno ("a prova é em março", "erra muito crase")
  licoes.json     lições que ele tirou dos próprios erros ("artigo de lei: sempre ler_lei")
  melhorias.json  a CAIXA DO CLAUDE: pedidos do aluno e ideias do Sócrates para o código dele

Fica tudo em Documentos\\Socrates, em JSON simples: dá para abrir e corrigir à mão.

A caixa do Claude: o Sócrates não digita mais no app do Claude (dependia do app aberto, na
conversa certa, e atrapalhava quando o Claude estava trabalhando). Ele só anota aqui; uma
tarefa agendada do Claude lê a caixa toda noite, faz o que tiver sentido (com testes), marca
cada item como "feita" ou "descartada" (com a resposta) e deixa recado_do_claude.txt, que o
Sócrates lê na saudação.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import unicodedata
from datetime import date, timedelta
from pathlib import Path

log = logging.getLogger("socrates.memoria")

PASTA = Path.home() / "Documents" / "Socrates"
_VAZIAS = {"a", "o", "as", "os", "de", "da", "do", "das", "dos", "e", "que", "em", "no", "na",
           "um", "uma", "para", "pra", "com", "por", "se", "ele", "ela", "nao", "mais", "muito"}


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def _palavras(texto: str) -> set[str]:
    return {p for p in _norm(texto).split() if p not in _VAZIAS and len(p) > 1}


def parecido(a: str, b: str) -> bool:
    """Mesma ideia escrita de outro jeito (para não guardar repetido)."""
    pa, pb = _palavras(a), _palavras(b)
    if not pa or not pb:
        return _norm(a) == _norm(b)
    comum = len(pa & pb)
    return comum / len(pa | pb) >= 0.6 or comum / min(len(pa), len(pb)) >= 0.85


# Lição que diz que ele "não consegue" algo que as ferramentas dele fazem é lição ERRADA (em
# 14/11 a reflexão concluiu que ele fingia abrir o Spotify; com a lição, ele passou a se
# recusar a abrir o Spotify de verdade).
_NEGA = re.compile(r"\b(nao (?:consig\w*|consegue|pode|posso|tenho (?:acesso|permissao))|limitac\w*|"
                   r"impossib\w*|em vez de fingir|fing\w*)\b")
_CAPACIDADE = re.compile(r"\b(abri\w*|fech\w*|aplicativ\w*|programa\w*|spotify|youtube|music\w*|"
                         r"bloco de notas|tela|janela\w*|volume|timer|pomodoro|navegador|site\w*|"
                         r"claude|controle de aplicativos|controlar)\b")


def nega_capacidade(texto: str) -> bool:
    """A frase diz que ele não consegue mexer no computador (o que ele consegue)."""
    t = _norm(texto)
    return bool(_NEGA.search(t) and _CAPACIDADE.search(t))


# Lições que a reflexão tirou do PRÓPRIO registro, e não do aluno (25/11): "registre o uso de
# ferramentas com [usou a ferramenta X]" (a marca é do registro e foi parar na voz) e "ao não
# reconhecer o nome, peça clarificação" (fala sem o nome é ignorada de propósito: TV, jogo,
# outras pessoas; o agente nem chega a ver essas falas).
_DO_REGISTRO = re.compile(r"\busou a ferramenta\b|\bregistr\w* (?:sempre )?(?:o )?uso (?:de|das) ferramenta"
                          r"|\b(?:nao|sem) (?:reconhec\w*|ouvir|dizer|falar) (?:o )?(?:seu |meu )?nome"
                          r"|\bausencia (?:do|de) nome\b|\bconfirma\w* (?:do |de )?nome\b")


def licao_ruim(texto: str) -> bool:
    """A frase fala das anotações do registro ou do nome de chamada, não de como responder."""
    return bool(_DO_REGISTRO.search(_norm(texto)))


class Lista:
    """Frases guardadas em disco, sem repetidas, com limite (as mais antigas saem)."""

    def __init__(self, arquivo: Path, limite: int, hoje=date.today):
        self.arquivo = Path(arquivo)
        self.limite = limite
        self.hoje = hoje
        self._trava = threading.Lock()

    def itens(self) -> list[dict]:
        try:
            dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        return [d for d in dados if isinstance(d, dict) and str(d.get("t", "")).strip()]

    def textos(self) -> list[str]:
        return [d["t"] for d in self.itens()]

    def _gravar(self, itens: list[dict]) -> None:
        self.arquivo.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.arquivo.with_suffix(".tmp")
        tmp.write_text(json.dumps(itens, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.arquivo)

    def adicionar(self, texto: str, **extra) -> bool:
        """True se entrou; False se já existia algo igual (aí só renova a data)."""
        texto = re.sub(r"\s+", " ", (texto or "")).strip().rstrip(".") + "."
        if len(texto) < 4:
            return False
        with self._trava:
            itens = self.itens()
            for d in itens:
                if parecido(d["t"], texto):
                    d["d"] = self.hoje().isoformat()
                    self._gravar(itens)
                    return False
            itens.append({"t": texto, "d": self.hoje().isoformat(), **extra})
            self._gravar(itens[-self.limite:])
        log.info("guardei em %s: %s", self.arquivo.name, texto)
        return True

    def remover(self, trecho: str) -> list[str]:
        """Tira as frases que falam do trecho ("esquece a data da prova")."""
        alvo = _palavras(trecho)
        if not alvo:
            return []
        with self._trava:
            itens = self.itens()
            fora = [d for d in itens if alvo <= _palavras(d["t"]) or parecido(d["t"], trecho)
                    or len(alvo & _palavras(d["t"])) >= max(2, len(alvo) - 1)]
            if fora:
                self._gravar([d for d in itens if d not in fora])
        return [d["t"] for d in fora]

    def recentes(self, dias: int | None = None) -> list[dict]:
        itens = self.itens()
        if dias is None:
            return itens
        corte = (self.hoje() - timedelta(days=dias)).isoformat()
        return [d for d in itens if d.get("d", "") >= corte]

    def para_prompt(self, titulo: str, maximo: int = 20) -> str:
        itens = self.itens()[-maximo:]
        if not itens:
            return ""
        return titulo + "\n" + "\n".join(f"- {d['t']}" for d in itens)


class Memorias:
    """As três listas juntas (o agente e a reflexão usam)."""

    def __init__(self, pasta: Path | None = None, hoje=date.today):
        pasta = Path(pasta) if pasta else PASTA
        self.aluno = Lista(pasta / "memoria.json", 60, hoje)
        self.licoes = Lista(pasta / "licoes.json", 25, hoje)
        self.melhorias = Lista(pasta / "melhorias.json", 30, hoje)

    def melhorias_pendentes(self) -> list[dict]:
        return [d for d in self.melhorias.recentes(21) if d.get("status", "nova") == "nova"]

    def para_o_claude(self, texto: str, origem: str = "aluno") -> tuple[str, dict | None]:
        """Põe um pedido na caixa do Claude. Devolve (como ficou, o item):
          "nova"       entrou na caixa
          "ja_estava"  já estava esperando o Claude ler
          "reaberta"   o Claude já tinha feito/descartado e o ALUNO pediu de novo (ainda falha)
          "ja_feita" / "ja_descartada"   ideia do Sócrates que o Claude já resolveu"""
        lista = self.melhorias
        texto = re.sub(r"\s+", " ", (texto or "")).strip().rstrip(".") + "."
        if len(texto) < 4:
            return "vazia", None
        hoje = lista.hoje().isoformat()
        with lista._trava:
            itens = lista.itens()
            for d in itens:
                if not parecido(d["t"], texto):
                    continue
                status = d.get("status", "nova")
                if status in ("nova", "enviada"):
                    d["d"] = hoje
                    lista._gravar(itens)
                    return "ja_estava", d
                if origem != "aluno":
                    return ("ja_feita" if status == "feita" else "ja_descartada"), d
                d.update(status="nova", d=hoje, origem="aluno", de_novo=True, antes=status)
                lista._gravar(itens)
                log.info("reabri na caixa do Claude (%s antes): %s", status, d["t"])
                return "reaberta", d
            novo = {"t": texto, "d": hoje, "status": "nova", "origem": origem}
            itens.append(novo)
            lista._gravar(itens[-lista.limite:])
        log.info("caixa do Claude (%s): %s", origem, texto)
        return "nova", novo


# Como cada item da caixa aparece para o Sócrates (e para o aluno)
ROTULO_STATUS = {"nova": "na caixa, o Claude lê hoje à noite",
                 "enviada": "enviada ao Claude",
                 "feita": "o Claude já fez",
                 "descartada": "o Claude analisou e não fez"}
