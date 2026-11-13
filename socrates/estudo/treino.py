"""Treino por voz: questões de prova (certo/errado e A–E), lacunas de lei seca,
simulado e revisão dos erros.

A correção é feita pelo GABARITO do banco, nunca pela opinião do modelo. O cérebro
só entra quando o aluno pede uma dica ou uma explicação, e aí recebe a questão,
o gabarito e o comentário para não inventar.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from . import respostas
from .caderno import Caderno

log = logging.getLogger("socrates.treino")

NOME_LEI = {"CP": "Código Penal", "L14133": "Lei 14.133/2021", "CPP": "Código de Processo Penal",
            "CTB": "CTB"}
LIMITE_FALA = 450        # enunciado maior que isso não é lido em voz alta: fica no quadro
LIMITE_QUADRO = 520


def _quadro_seguro(texto: str) -> str:
    """O quadro entende $...$ como fórmula: um "R$ 293,47" quebraria o desenho."""
    return texto.replace("$", r"\$")


def _cortar(texto: str, limite: int) -> str:
    texto = re.sub(r"\s+", " ", texto).strip()
    if len(texto) <= limite:
        return texto
    corte = texto[:limite].rsplit(" ", 1)[0]
    return corte + " (...)"


def plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def fonte_curta(banco: dict) -> str:
    return str(banco.get("titulo") or banco.get("id")).split(" · ")[0]


@dataclass
class Item:
    id: str
    tipo: str                    # ce | mc | lacuna
    materia: str
    topico: str
    fonte: str                   # "PRF 2021 Q12", "CTB · Art. 165"
    resp: str
    fala: str                    # como a pergunta é falada
    quadro: str                  # como aparece no quadro
    completo: str                # texto inteiro (Bloco de Notas e explicações)
    just: str = ""
    letras: str = "ABCDE"
    real: bool = True            # questão de prova (False = item de fixação da trilha)
    lei: str = ""                # lacunas: a lei de onde veio (CP, CTB...)
    oficial: str = ""            # gabarito oficial da prova, quando a lei mudou depois (resp é o de hoje)

    def comentario(self) -> str:
        """O comentário do gabarito, se ele ensinar algo (não só "Gabarito: CERTO")."""
        j = (self.just or "").strip()
        if not j or j.lower().startswith("gabarito oficial"):
            atencao = j.split("Atenção:", 1)
            return atencao[1].strip() if len(atencao) > 1 else ""
        return j

    def _falado(self, r: str) -> str:
        if self.tipo == "ce":
            return "Certo" if r == "C" else "Errado"
        if self.tipo == "mc":
            return f"letra {r}"
        return r

    def gabarito_falado(self) -> str:
        return self._falado(self.resp)

    @property
    def mudou(self) -> bool:
        """A lei mudou depois da prova: o gabarito de hoje não é o oficial."""
        return bool(self.oficial) and self.oficial != self.resp

    def contexto(self, revelar: bool, resposta_aluno: str | None = None) -> str:
        """O que o cérebro precisa saber para dar dica ou explicar sem inventar."""
        tipo = "uma questão real de prova" if self.real else "um item de fixação no estilo da banca"
        linhas = [f"O aluno está treinando com {tipo} ({self.fonte}, {self.materia}, "
                  f"tópico: {self.topico}). Texto:", self.completo]
        if revelar:
            if self.mudou:
                linhas.append(f"Gabarito pela lei ATUAL: {self.gabarito_falado()}. O gabarito oficial da "
                              f"prova foi {self._falado(self.oficial)}, mas a lei mudou depois dela; "
                              "ensine a regra de hoje e diga que a prova antiga cobrava a anterior.")
            else:
                linhas.append(f"Gabarito OFICIAL: {self.gabarito_falado()}.")
            if self.comentario():
                linhas.append(f"Comentário do gabarito: {self.comentario()}")
            if resposta_aluno:
                linhas.append(f"O aluno respondeu: {resposta_aluno}.")
            qual = "o gabarito pela lei atual" if self.mudou else "o gabarito oficial"
            linhas.append("Explique por que o gabarito é esse, em poucas frases faladas, e use o "
                          f"quadro se ajudar. Nunca contradiga {qual}. Se não tiver "
                          "certeza da regra, diga isso em vez de inventar lei ou artigo.")
        else:
            linhas.append("O aluno AINDA NÃO respondeu. Dê uma dica curta sobre a regra ou o "
                          "conceito, sem dizer a resposta e sem eliminar alternativas.")
        return "\n".join(linhas)


# ---------- montagem dos itens ----------

def item_de_questao(banco: dict, q: dict) -> Item | None:
    if q.get("img"):                    # figura não dá para mostrar por voz
        return None
    tipo = q.get("tipo") or banco.get("tipo") or "mc"
    topico = str(q.get("topico", ""))
    fonte = topico if " item " in f" {topico} " else f"{fonte_curta(banco)} Q{q.get('n')}"
    partes = [p for p in str(q.get("enunciado", "")).split("\n\n") if p.strip()]
    apoio = q.get("apoio") or {}
    texto_apoio = "\n".join([apoio.get("titulo", "")] + apoio.get("paragrafos", [])).strip()
    alternativas = q.get("alternativas") or {}
    afirmacoes = q.get("itens") or []
    resp = str(q.get("resp", "")).strip().upper()[:1]
    just, oficial = str(q.get("just", "")), ""
    atual = str(q.get("atual") or "").strip().upper()[:1]
    if atual and atual != resp:                 # a lei mudou depois da prova: treina-se a de hoje
        oficial, resp = resp, atual
        hoje = ("Certo" if atual == "C" else "Errado") if tipo == "ce" else f"letra {atual}"
        aviso = (f"A lei mudou depois da prova: hoje o gabarito é {hoje}. "
                 + str(q.get("atualizacao") or "")).strip()
        just = f"{just} {aviso}" if "Atenção:" in just else f"{just} Atenção: {aviso}".strip()

    completo = "\n\n".join(x for x in [texto_apoio, q.get("enunciado", ""), "\n".join(afirmacoes),
                                       q.get("enunciado2", ""),
                                       "\n".join(f"{k}) {v}" for k, v in alternativas.items()),
                                       q.get("fecho", "")] if x)
    titulo = f"# {fonte} · {q.get('materia', '')}"
    if tipo == "ce":
        item = partes[-1] if partes else ""
        tem_apoio = len(partes) > 1 or bool(texto_apoio)
        fala = (item if len(item) <= LIMITE_FALA else "Leia o item no quadro.")
        if tem_apoio and len(partes) > 1 and len(" ".join(partes[:-1])) > 300:
            fala = "Este item depende de um texto: diga mostra o texto para ler inteiro. " + fala
        fala += " Certo ou errado?"
        quadro = [titulo, _cortar(item, LIMITE_QUADRO), "", "Certo ou errado?"]
        letras = "CE"
    else:
        enun = str(q.get("enunciado", "")).strip()
        fala = enun if len(enun) <= LIMITE_FALA else "Leia o enunciado no quadro."
        if texto_apoio:
            fala = "Questão com texto de apoio: diga mostra o texto para ler inteiro. " + fala
        if afirmacoes:
            fala += f" São {len(afirmacoes)} afirmações, estão no quadro."
        fala += " Qual a alternativa?"
        limite = 260 if afirmacoes else 360
        quadro = [titulo, _cortar(enun, limite)]
        quadro += [f"- {_cortar(a, 260)}" for a in afirmacoes]
        quadro += [f"- {k}) {_cortar(v, 220)}" for k, v in alternativas.items()]
        letras = "".join(alternativas) or "ABCDE"
    return Item(id=f"{banco['id']}#{q.get('n')}", tipo=tipo, materia=q.get("materia", ""),
                topico=q.get("topico", ""), fonte=fonte, resp=resp, fala=fala.strip(),
                quadro=_quadro_seguro("\n".join(quadro)), completo=completo,
                just=just, letras=letras, oficial=oficial)


def item_de_lacuna(bloco: dict, artigo: dict, lacuna: dict) -> Item:
    lei = NOME_LEI.get(bloco.get("lei"), bloco.get("lei", ""))
    frase = lacuna["c"]
    fala = "Complete: " + frase.replace("____", ", branco, ")
    fala = re.sub(r"\s+", " ", fala)
    fala = re.sub(r",(\s*,)+", ",", re.sub(r"\s+,", ",", fala)).strip(" ,")
    titulo = f"# {lei} · {artigo['art']}"
    texto_lei = "\n".join(i["t"] for i in artigo.get("itens", []) if i.get("k") == "lei")
    return Item(id=f"lei:{bloco['id']}:{artigo['art']}:{lacuna.get('i')}", tipo="lacuna",
                materia="Lei seca", topico=f"{lei} · {artigo['art']}", fonte=f"{lei} · {artigo['art']}",
                resp=lacuna["r"], fala=fala,
                quadro=_quadro_seguro(f"{titulo}\n{frase.replace('____', '________')}"),
                completo=texto_lei, just=artigo.get("resumo", ""), lei=bloco.get("lei", ""))


# ---------- a sessão ----------

@dataclass
class Saida:
    """O que o Sócrates faz com uma fala do aluno durante o treino."""
    fala: str = ""
    quadro: str | None = None
    contexto: str | None = None     # se preenchido: o cérebro responde com este contexto
    fim: bool = False
    abrir_texto: str | None = None  # texto para abrir no Bloco de Notas
    abrir_pagina: str | None = None # página (arquivo .html) para abrir no navegador


@dataclass
class Registro:
    item: Item
    dada: str | None            # None = pulou / em branco
    ok: bool


@dataclass
class Sessao:
    itens: list[Item]
    modo: str                    # treino | simulado | lacunas | revisao
    titulo: str
    caderno: Caderno | None = None
    banco: dict | None = None
    pos: int = 0
    estado: str = "perguntando"  # perguntando | corrigida
    registros: list[Registro] = field(default_factory=list)
    inicio: float = field(default_factory=time.monotonic)

    @property
    def atual(self) -> Item | None:
        return self.itens[self.pos] if self.pos < len(self.itens) else None

    @property
    def ultimo(self) -> Registro | None:
        return self.registros[-1] if self.registros else None

    @property
    def espera_resposta_curta(self) -> bool:
        """Questões esperam "certo", "letra B"... (o ouvido usa outro vocabulário)."""
        a = self.atual
        return a is not None and a.tipo in ("ce", "mc") and self.estado == "perguntando"

    # ---------- começo ----------
    def abrir(self) -> Saida:
        n = len(self.itens)
        if self.modo == "simulado":
            intro = (f"Simulado com {n} questões. Não vou corrigir até o fim. "
                     "Diga pular para deixar em branco, e parar para encerrar. ")
        elif self.modo == "lacunas":
            intro = f"Vamos a {n} lacunas. Diga a palavra que falta. "
        elif self.modo == "revisao":
            intro = f"Revisão de {n} itens que você errou antes. "
        elif self.modo == "fixacao":
            intro = (f"Agora {plural(n, 'item', 'itens')} de fixação, no estilo da banca. "
                     "Responda certo ou errado. ")
        else:
            intro = (f"{self.titulo}: {n} questões. Para cada uma, responda; diga dica, explica, "
                     "pular, repete ou parar quando quiser. ")
        return self._apresentar(intro)

    def _apresentar(self, antes: str = "") -> Saida:
        a = self.atual
        if a is None:
            return self.encerrar(antes)
        self.estado = "perguntando"
        cab = f"{self.pos + 1} de {len(self.itens)}. " if len(self.itens) > 1 else ""
        return Saida(fala=(antes + cab + a.fala).strip(), quadro=a.quadro)

    # ---------- cada fala do aluno ----------
    def atender(self, texto: str) -> Saida:
        a = self.atual
        cmd = respostas.comando(texto)
        # uma resposta clara vale mais que uma palavra de comando no meio ("errado, explica")
        if a is not None and self.estado == "perguntando" and cmd not in ("parar",):
            dada = self._entender(a, texto)
            if dada is not None and cmd not in ("pular", "repetir", "texto"):
                return self._corrigir(a, dada)
        if cmd == "parar":
            return self.encerrar()
        if a is None:
            return self.encerrar()
        if cmd == "placar":
            return Saida(fala=self._placar() + " Vamos continuar. " + a.fala, quadro=a.quadro)
        if cmd == "repetir":
            return Saida(fala=a.fala, quadro=a.quadro)
        if cmd == "texto":
            return Saida(fala="Abri o texto completo no Bloco de Notas.", abrir_texto=a.completo)
        if cmd == "pular":
            if self.estado == "perguntando":
                self._anotar(a, None, False)
                fala = "Em branco. " if self.modo == "simulado" else \
                    f"Pulei. A resposta era {a.gabarito_falado()}. "
                self.pos += 1
                return self._apresentar(fala)
            self.pos += 1
            return self._apresentar()
        if cmd in ("dica", "explicar") and self.modo != "simulado":
            if self.estado == "corrigida":
                return Saida(contexto=self._contexto_explicacao())
            return Saida(contexto=a.contexto(revelar=False))   # ainda não respondeu: só dica
        if self.estado == "corrigida":
            # qualquer outra pergunta depois da correção: o cérebro responde sobre a questão
            if len(respostas.norm(texto).split()) >= 3:
                return Saida(contexto=self._contexto_explicacao())
            self.pos += 1
            return self._apresentar()
        # não entendeu a resposta
        if len(respostas.norm(texto).split()) >= 5 and self.modo != "simulado":
            return Saida(contexto=a.contexto(revelar=False))   # era uma dúvida
        pedir = {"ce": "Diga certo ou errado.", "mc": "Diga a letra, por exemplo: letra B."}
        return Saida(fala=f"Não entendi a resposta. {pedir.get(a.tipo, 'Diga a palavra que falta.')}")

    def _entender(self, a: Item, texto: str) -> str | None:
        if a.tipo == "ce":
            return respostas.certo_ou_errado(texto)
        if a.tipo == "mc":
            return respostas.alternativa(texto, a.letras)
        if respostas.comando(texto):
            return None
        t = respostas.norm(texto)
        if not t or t in ("nao sei", "sei la", "nao lembro"):
            return "" if t else None
        return texto.strip()

    def _corrigir(self, a: Item, dada: str) -> Saida:
        if a.tipo == "lacuna":
            ok = bool(dada) and respostas.lacuna_certa(dada, a.resp)
        else:
            ok = dada == a.resp
        self._anotar(a, dada, ok)
        if self.modo == "simulado":
            self.pos += 1
            return self._apresentar("Anotado. ")
        if a.tipo == "lacuna":
            fala = (f"Isso! {a.resp}. " if ok else f"A resposta é: {a.resp}. ")
            self.pos += 1
            return self._apresentar(fala)
        comentario = a.comentario()
        if ok:
            fala = "Certo! " + (_cortar(comentario, 260) + " " if comentario else "")
            self.pos += 1
            return self._apresentar(fala)
        self.estado = "corrigida"
        fala = (f"Não. O gabarito é {a.gabarito_falado()}. "
                + (_cortar(comentario, 300) + " " if comentario else "")
                + "Diga explica para entender, ou próxima para seguir.")
        return Saida(fala=fala)

    def _anotar(self, a: Item, dada: str | None, ok: bool) -> None:
        self.registros.append(Registro(a, dada, ok))
        if self.caderno is not None and (dada is not None or self.modo != "simulado"):
            self.caderno.registrar(a.id, ok, {"materia": a.materia, "topico": a.topico,
                                              "fonte": a.fonte})
            try:
                self.caderno.salvar()
            except OSError as e:
                log.warning("não consegui salvar o caderno: %s", e)

    def _contexto_explicacao(self) -> str:
        r = self.ultimo
        a = r.item if r else self.atual
        dada = None
        if r and r.dada:
            dada = {"C": "Certo", "E": "Errado"}.get(r.dada, r.dada) if a.tipo == "ce" else r.dada
        return a.contexto(revelar=True, resposta_aluno=dada) + \
            "\nDepois de explicar, pergunte se ele quer seguir para a próxima."

    # ---------- placar e fim ----------
    def contagem(self) -> tuple[int, int, int]:
        acertos = sum(1 for r in self.registros if r.ok)
        brancos = sum(1 for r in self.registros if r.dada is None)
        return acertos, len(self.registros) - acertos - brancos, brancos

    def _placar(self) -> str:
        ac, er, br = self.contagem()
        return (f"Até agora: {plural(ac, 'certa', 'certas')}, {plural(er, 'errada', 'erradas')}"
                + (f" e {plural(br, 'pulada', 'puladas')}." if br else "."))

    def nota_cebraspe(self) -> int:
        ac, er, _ = self.contagem()
        return ac - er

    def por_materia(self) -> dict[str, list[int]]:
        """materia -> [feitas, acertos, erros]"""
        saida: dict[str, list[int]] = {}
        for r in self.registros:
            m = saida.setdefault(r.item.materia, [0, 0, 0])
            m[0] += 1
            if r.ok:
                m[1] += 1
            elif r.dada is not None:
                m[2] += 1
        return saida

    def encerrar(self, antes: str = "") -> Saida:
        ac, er, br = self.contagem()
        feitas = len(self.registros)
        if not feitas:
            return Saida(fala=(antes + "Treino encerrado.").strip(), fim=True)
        pct = round(100 * ac / max(1, feitas - br))
        ce = any(r.item.tipo == "ce" for r in self.registros)
        fala = (f"{antes}Fim. Você respondeu {feitas - br}: {plural(ac, 'certa', 'certas')} e "
                f"{plural(er, 'errada', 'erradas')}, {pct} por cento.")
        if ce and self.modo == "simulado":
            fala += f" No estilo Cebraspe, com um errado anulando um certo, a nota é {ac - er}."
        linhas = [f"# Resultado · {self.titulo}",
                  f"Acertos: {ac} de {feitas - br} ({pct}%)" + (f" · em branco: {br}" if br else "")]
        if ce and self.modo == "simulado":
            linhas.append(f"Nota Cebraspe (certas − erradas): {ac - er}")
        materias = sorted(self.por_materia().items(),
                          key=lambda kv: kv[1][1] / max(1, kv[1][1] + kv[1][2]))
        for nome, (f, a_, e_) in materias[:6]:
            if a_ + e_:
                linhas.append(f"- {nome}: {a_} de {a_ + e_}")
        erradas = [r for r in self.registros if not r.ok and r.dada is not None]
        if erradas:
            fala += (" A que você errou foi" if len(erradas) == 1 else
                     f" As {len(erradas)} que você errou foram") + " para a revisão de amanhã."
            pior = materias[0][0] if materias else ""
            if pior and len(materias) > 1:
                fala += f" O ponto mais fraco foi {pior}."
        return Saida(fala=fala.strip(), quadro="\n".join(linhas), fim=True)

    def resumo(self) -> dict:
        ac, er, br = self.contagem()
        return {"tipo": self.modo, "titulo": self.titulo, "feitas": len(self.registros),
                "acertos": ac, "erros": er, "brancos": br,
                "minutos": round((time.monotonic() - self.inicio) / 60, 1),
                "por_materia": self.por_materia()}
