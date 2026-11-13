"""Aula guiada de um tópico da trilha, ponto por ponto.

  "Sócrates, me ensina legítima defesa"

1. Cada ponto aparece no quadro (o texto conferido) e o cérebro explica falando, com um
   exemplo, e termina com uma pergunta curta para ver se o aluno entendeu.
2. O aluno responde ou tira dúvida: o cérebro avalia com base no ponto (não inventa).
3. "Próximo" (ou "entendi") passa ao ponto seguinte. "Repete" explica de outro jeito.
   "Parar" pausa; "me ensina <tópico>" de novo continua de onde parou.
4. No fim, itens de fixação estilo banca, corrigidos pelo gabarito, e o resumo da aula.
"""

from __future__ import annotations

import re
import time

from . import respostas
from .caderno import Caderno
from .treino import Item, Saida, Sessao, _quadro_seguro, plural
from .trilha import Topico, Trilha

FIXACAO = 4          # itens de fixação no fim da aula

# Sempre é "pode seguir"
_SEGUIR = re.compile(r"^(?:socrates )?(?:proximo|proxima|continua|continue|continuar|segue|seguir|"
                     r"pode seguir|pode continuar|pode passar|avanca|avancar|entendi|ja entendi|"
                     r"entendido|vamos para o proximo|passa|pula|proximo ponto|outro ponto)\b")
# Só é "pode seguir" quando o Sócrates acabou de perguntar se pode seguir
_CONCORDA = re.compile(r"^(?:socrates )?(?:sim|pode|ok|okay|beleza|claro|isso|bora|vamos|manda|"
                       r"certo|tranquilo|show|perfeito|vai|uhum|aham|com certeza)\b")


class Aula:
    def __init__(self, trilha: Trilha, topico: Topico, caderno: Caderno, itens: list[Item],
                 texto_lei: str = "", progresso=None):
        self.trilha = trilha
        self.topico = topico
        self.caderno = caderno
        self.itens = itens                     # questões reais + itens de fixação do tópico
        self.texto_lei = texto_lei
        self.progresso = progresso
        self.chave = f"{trilha.id}:{topico.id}"
        registro = caderno.aula(self.chave)
        # retoma no ponto em que parou (o último que ele viu, porque pode não ter entendido)
        parou = registro.get("vistos", 0)
        self.retomada = not registro.get("concluida") and 0 < parou <= len(topico.pontos)
        self.k = parou - 1 if self.retomada else 0
        self.aguardando_seguir = False
        self.interrompida = False              # o aluno saiu para consultar algo
        self.sessao: Sessao | None = None
        self.inicio = time.monotonic()

    @property
    def n(self) -> int:
        return len(self.topico.pontos)

    # ---------- o que o cérebro recebe ----------
    def _cabecalho(self) -> str:
        t = self.topico
        linhas = [f"Você está dando uma AULA de {self.trilha.materia} para o concurso da "
                  f"{self.trilha.concurso} (banca {self.trilha.banca}), no seu jeito socrático.",
                  f"Tópico: {t.titulo} (edital: {t.edital}). Artigos: {', '.join(t.artigos)}."]
        if t.novidades:
            linhas.append("Atualizações legislativas recentes (valem mais do que o que você "
                          "lembra): " + " ".join(t.novidades))
        if t.pegadinhas:
            linhas.append("Pegadinhas que a banca usa: " + " ".join(t.pegadinhas))
        if self.texto_lei:
            linhas.append("Texto da lei: " + self.texto_lei)
        if t.auto:
            linhas.append("Este tópico foi montado pelo autoestudo (lei em vigor e páginas da internet, "
                          "conferido por um segundo modelo, mas não por um professor). Se o aluno "
                          "questionar um ponto, admita que pode haver erro e sugira conferir na lei.")
        return "\n".join(linhas)

    def _ctx_explicar(self, primeira: bool, de_novo: bool) -> str:
        ponto = self.topico.pontos[self.k]
        regras = [f"PONTO {self.k + 1} de {self.n} (já está no quadro do aluno): {ponto}",
                  "Explique SÓ este ponto, falando, em no máximo 5 frases curtas, com um exemplo "
                  "concreto (de preferência da rotina de um policial rodoviário).",
                  "NÃO use o quadro nesta resposta (o ponto já está lá).",
                  "Não invente artigo, pena, súmula ou lei que não esteja aqui. Se o ponto for "
                  "diferente do que você lembra, o ponto está certo: a lei mudou.",
                  "Termine com UMA pergunta curta e aberta para checar se ele entendeu "
                  "(não faça pergunta de certo ou errado)."]
        if primeira and self.retomada:
            regras.insert(1, f"Comece dizendo que vão continuar a aula de {self.topico.titulo} "
                             f"do ponto {self.k + 1}.")
        elif primeira:
            regras.insert(1, f"Comece com uma frase dizendo do que trata o tópico e que a aula tem "
                             f"{self.n} pontos e termina com itens de fixação.")
        if de_novo:
            regras.insert(1, "O aluno pediu para repetir: explique de OUTRO jeito, com outro exemplo.")
        return self._cabecalho() + "\n\n" + "\n".join(regras)

    def _ctx_responder(self) -> str:
        ponto = self.topico.pontos[self.k]
        return (self._cabecalho() + "\n\n" +
                f"PONTO atual ({self.k + 1} de {self.n}): {ponto}\n"
                "O aluno acabou de responder à sua pergunta ou fez uma dúvida sobre esse ponto. "
                "Se ele respondeu, diga se está certo com base no ponto; se estiver errado ou "
                "incompleto, corrija com gentileza e explique de novo, curto. Se for dúvida, "
                "responda com base no ponto e nos artigos, sem inventar. Use o quadro só se "
                "precisar de um esquema. Termine perguntando se pode seguir para o próximo ponto.")

    # ---------- passos ----------
    def abrir(self) -> Saida:
        return self._ponto(primeira=True)

    def _ponto(self, primeira: bool = False, de_novo: bool = False) -> Saida:
        reg = self.caderno.aula(self.chave)
        reg.update(vistos=max(reg.get("vistos", 0), self.k + 1), total=self.n,
                   data=self.caderno.relogio().isoformat())
        if reg.get("concluida") and self.k + 1 < self.n:
            reg["vistos"] = self.k + 1      # refazendo a aula: conta de novo
        self._salvar()
        self.aguardando_seguir = False
        quadro = _quadro_seguro(f"# {self.topico.titulo} · {self.k + 1}/{self.n}\n"
                                f"{self.topico.pontos[self.k]}")
        return Saida(quadro=quadro, contexto=self._ctx_explicar(primeira, de_novo))

    def retomar(self) -> Saida:
        """Volta ao ponto em que a aula estava (ou à questão da fixação)."""
        self.interrompida = False
        if self.sessao is not None and self.sessao.atual is not None:
            a = self.sessao.atual
            return Saida(fala=a.fala, quadro=a.quadro)
        return self._ponto()

    def atender(self, texto: str) -> Saida:
        if self.interrompida:
            t = respostas.norm(texto)
            if _SEGUIR.match(t) or _CONCORDA.match(t) or respostas.comando(texto) == "repetir":
                return self.retomar()
            self.interrompida = False
        if self.sessao is not None:
            saida = self.sessao.atender(texto)
            if saida.fim:
                return self._concluir(saida)
            return saida
        t = respostas.norm(texto)
        cmd = respostas.comando(texto)
        if cmd == "parar":
            return self.pausar()
        if cmd == "repetir":
            return self._ponto(de_novo=True)
        if _SEGUIR.match(t) or (self.aguardando_seguir and _CONCORDA.match(t)):
            return self._avancar()
        self.aguardando_seguir = True
        return Saida(contexto=self._ctx_responder())

    def _avancar(self) -> Saida:
        self.k += 1
        if self.k < self.n:
            return self._ponto()
        return self._fixacao()

    def _fixacao(self) -> Saida:
        vistos = [i for i in self.itens if self.caderno.visto(i.id)]
        novos = [i for i in self.itens if not self.caderno.visto(i.id)]
        escolhidos = (novos + vistos)[:FIXACAO]
        if not escolhidos:
            return self._concluir(None)
        self.sessao = Sessao(escolhidos, "fixacao", f"Fixação: {self.topico.titulo}", self.caderno)
        saida = self.sessao.abrir()
        saida.fala = "Fim da parte teórica. " + saida.fala
        return saida

    def _concluir(self, fim_da_fixacao: Saida | None) -> Saida:
        reg = self.caderno.aula(self.chave)
        reg.update(vistos=self.n, total=self.n, concluida=True,
                   data=self.caderno.relogio().isoformat())
        ac = er = 0
        if self.sessao is not None:
            ac, er, _ = self.sessao.contagem()
            resumo = self.sessao.resumo()
            resumo["tipo"] = "fixacao"
            self.caderno.anotar_sessao(resumo)
        minutos = (time.monotonic() - self.inicio) / 60
        self.caderno.anotar_evento("aula", t=self.chave, p=self.n, fim=True,
                                   min=round(minutos, 1))
        if minutos >= 2:
            self.caderno.anotar_estudo(self.trilha.materia, minutos)
        self._salvar()
        fala = f"Aula de {self.topico.titulo} concluída: {plural(self.n, 'ponto', 'pontos')}"
        if ac + er:
            fala += f" e {ac} de {ac + er} na fixação."
            if er:
                fala += " O que você errou volta amanhã na revisão."
        else:
            fala += "."
        linhas = [f"# Aula concluída · {self.topico.titulo}",
                  f"Pontos estudados: {self.n}"]
        if ac + er:
            linhas.append(f"Fixação: {ac} de {ac + er}")
        if self.progresso is not None:
            passo = self.progresso.proximo_passo()
            fala += f" Próximo passo: {passo.motivo}"
            linhas += ["", f"Próximo: {passo.motivo}", f"(diga: {passo.comando})"]
        return Saida(fala=fala, quadro="\n".join(linhas), fim=True)

    def pausar(self) -> Saida:
        reg = self.caderno.aula(self.chave)
        self.caderno.anotar_evento("aula", t=self.chave, p=self.k + 1, fim=False,
                                   min=round((time.monotonic() - self.inicio) / 60, 1))
        minutos = (time.monotonic() - self.inicio) / 60
        if minutos >= 2:
            self.caderno.anotar_estudo(self.trilha.materia, minutos)
        self._salvar()
        if reg.get("concluida"):
            return Saida(fala=f"Aula de {self.topico.titulo} encerrada.", fim=True)
        return Saida(fala=f"Aula pausada no ponto {self.k + 1} de {self.n}. Para continuar, diga: "
                          f"me ensina {self.topico.titulo.lower()}.", fim=True)

    def _salvar(self) -> None:
        try:
            self.caderno.salvar()
        except OSError:
            pass
