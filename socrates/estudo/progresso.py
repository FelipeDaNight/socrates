"""O que o aluno estudou, o que aprendeu e qual o próximo passo.

Domínio de um tópico = acerto recente nas questões, lacunas e itens dele. Respostas
antigas valem menos (meia-vida de 3 semanas), e poucos dados puxam a nota para o meio,
para um acerto de sorte não virar "domina".

Estados:  novo -> começou -> praticando -> domina
                              \\-> precisa reforçar      domina + 30 dias parado -> revisar
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from .caderno import Caderno
from .treino import Item, plural
from .trilha import Topico, Trilha

MEIA_VIDA = 21          # dias: uma resposta de 3 semanas atrás vale metade
JANELA = 120            # dias considerados
MINIMO_DOMINA = 5       # respostas para poder dizer que domina
ESFRIA = 30             # dias sem praticar até um tópico dominado pedir revisão

ROTULOS = {"novo": "não começou", "comecou": "começou", "fraco": "precisa reforçar",
           "praticando": "praticando", "dominado": "domina", "esfriando": "revisar"}


def _data(texto: str | None) -> date | None:
    try:
        return date.fromisoformat(texto) if texto else None
    except ValueError:
        return None


@dataclass
class Situacao:
    topico: Topico
    estado: str
    dominio: float | None          # 0 a 1 (None = sem respostas)
    respostas: int
    acertos: int
    ultima: date | None
    aula_vistos: int
    aula_total: int
    aula_concluida: bool

    @property
    def rotulo(self) -> str:
        return ROTULOS[self.estado]

    @property
    def pct(self) -> int | None:
        return None if self.dominio is None else round(100 * self.dominio)


@dataclass
class Passo:
    acao: str                  # revisao | aula | continuar | reforco | relembrar | praticar | simulado
    topico: Topico | None
    motivo: str                # frase falada
    comando: str               # o que o aluno pode dizer para começar


@dataclass
class Progresso:
    trilha: Trilha
    caderno: Caderno
    bancos: dict
    lacunas: list[Item] = field(default_factory=list)

    def __post_init__(self):
        self.ids = {t.id: self.trilha.ids_do_topico(t, self.bancos, self.lacunas)
                    for t in self.trilha.topicos}
        self.todos = set().union(*self.ids.values()) if self.ids else set()
        self.itens: dict[str, Item] = {}
        for t in self.trilha.topicos:
            for it in self.trilha.itens_do_topico(t, self.bancos):
                self.itens.setdefault(it.id, it)
        for lac in self.lacunas:
            if lac.id in self.todos:
                self.itens.setdefault(lac.id, lac)

    @property
    def hoje(self) -> date:
        return self.caderno.relogio()

    def chave_aula(self, topico: Topico) -> str:
        return f"{self.trilha.id}:{topico.id}"

    # ---------- domínio ----------
    def _respostas(self, ids: set[str]) -> list[tuple[date, bool]]:
        eventos = [(d, bool(e.get("ok"))) for e in self.caderno.eventos
                   if e.get("k") == "r" and e.get("i") in ids and (d := _data(e.get("d")))]
        if eventos:
            return eventos
        saida = []      # caderno antigo, sem diário: usa os totais de cada item
        for i in ids:
            it = self.caderno.itens.get(i)
            d = _data(it.get("ultima")) if it else None
            if d:
                saida += [(d, True)] * it.get("acertos", 0) + [(d, False)] * it.get("erros", 0)
        return saida

    def situacao(self, topico: Topico) -> Situacao:
        hoje = self.hoje
        respostas = [(d, ok) for d, ok in self._respostas(self.ids[topico.id])
                     if (hoje - d).days <= JANELA]
        peso = soma = 0.0
        for d, ok in respostas:
            w = 0.5 ** (max(0, (hoje - d).days) / MEIA_VIDA)
            peso += w
            soma += w * ok
        dominio = (soma + 0.5) / (peso + 1) if respostas else None
        aula = self.caderno.dados["aulas"].get(self.chave_aula(topico), {})
        datas = [d for d, _ in respostas]
        if _data(aula.get("data")):
            datas.append(_data(aula.get("data")))
        ultima = max(datas) if datas else None
        n = len(respostas)
        acertos = sum(ok for _, ok in respostas)
        geral = (acertos + 0.5) / (n + 1) if n else None   # sem desconto de tempo
        if n == 0 and not aula.get("vistos"):
            estado = "novo"
        elif n < 3:
            estado = "comecou"
        elif geral >= 0.8 and dominio >= 0.7 and n >= MINIMO_DOMINA:
            # dominou; se faz tempo que não pratica, pede revisão
            estado = "esfriando" if ultima and (hoje - ultima).days > ESFRIA else "dominado"
        elif dominio < 0.6:
            estado = "fraco"
        else:
            estado = "praticando"
        return Situacao(topico, estado, dominio, n, acertos, ultima,
                        int(aula.get("vistos", 0)), len(topico.pontos), bool(aula.get("concluida")))

    def situacoes(self) -> list[Situacao]:
        return [self.situacao(t) for t in self.trilha.topicos]

    def contagem(self, sits: list[Situacao] | None = None) -> dict[str, int]:
        sits = sits or self.situacoes()
        c = {k: 0 for k in ROTULOS}
        for s in sits:
            c[s.estado] += 1
        return c

    def vencidos(self) -> list[str]:
        return [i for i in self.caderno.vencidos() if i in self.todos]

    # ---------- direção ----------
    def proximo_passo(self) -> Passo:
        sits = self.situacoes()
        m = self.trilha.materia
        venc = self.vencidos()
        if len(venc) >= 5:
            return Passo("revisao", None,
                         f"Você tem {plural(len(venc), 'item', 'itens')} de {m} vencidos na revisão. "
                         "Revisar agora fixa o que já estudou.", f"revisa meus erros de {m.lower()}")
        meio = [s for s in sits if s.aula_vistos and not s.aula_concluida]
        if meio:
            s = max(meio, key=lambda x: x.ultima or date.min)
            return Passo("continuar", s.topico,
                         f"Terminar a aula de {s.topico.titulo}, que parou no ponto "
                         f"{s.aula_vistos} de {s.aula_total}.", f"me ensina {s.topico.titulo.lower()}")
        fracos = sorted((s for s in sits if s.estado == "fraco"),
                        key=lambda s: (-s.topico.peso, s.dominio))
        if fracos:
            s = fracos[0]
            return Passo("reforco", s.topico,
                         f"Reforçar {s.topico.titulo}: você está acertando {s.pct} por cento.",
                         f"me ensina {s.topico.titulo.lower()}")
        frios = [s for s in sits if s.estado == "esfriando"]
        if frios:
            s = min(frios, key=lambda x: x.ultima or date.min)
            return Passo("relembrar", s.topico,
                         f"Relembrar {s.topico.titulo}: você dominava, mas faz mais de "
                         f"{ESFRIA} dias que não pratica.", f"questões de {s.topico.titulo.lower()}")
        novos = [s for s in sits if s.estado == "novo"]
        if novos:
            s = novos[0]
            peso = {3: " Cai muito na prova.", 2: "", 1: ""}.get(s.topico.peso, "")
            return Passo("aula", s.topico,
                         f"Próximo tópico do edital: {s.topico.titulo}.{peso}",
                         f"me ensina {s.topico.titulo.lower()}")
        praticar = sorted((s for s in sits if s.estado in ("comecou", "praticando")),
                          key=lambda s: (s.respostas, -s.topico.peso))
        if praticar:
            s = praticar[0]
            return Passo("praticar", s.topico,
                         f"Praticar {s.topico.titulo}: ainda tem poucas respostas para eu "
                         "saber se você domina.", f"questões de {s.topico.titulo.lower()}")
        return Passo("simulado", None,
                     f"Você domina todos os tópicos de {m}. Hora de um simulado para manter.",
                     f"simulado de {m.lower()}")

    # ---------- o que aprendeu ----------
    def erros_atuais(self, limite: int = 3) -> list[tuple[Item, str]]:
        """Itens cuja última resposta foi errada, com a regra para lembrar."""
        saida = []
        recentes = sorted(((it.get("ultima", ""), i) for i, it in self.caderno.itens.items()
                           if i in self.itens and it.get("ok") is False), reverse=True)
        for _, i in recentes[:limite]:
            item = self.itens[i]
            regra = item.comentario() or (f"a resposta é {item.gabarito_falado()}"
                                          if item.tipo == "lacuna" else "")
            saida.append((item, regra))
        return saida

    def resumo_aprendizado(self) -> tuple[str, str]:
        """(fala, quadro)"""
        sits = self.situacoes()
        m = self.trilha.materia
        if all(s.estado == "novo" for s in sits):
            passo = self.proximo_passo()
            return (f"Você ainda não começou {m}. {passo.motivo} Para começar, diga: {passo.comando}.",
                    f"# {m} · {self.trilha.concurso}\nNada estudado ainda.\nComece por: "
                    f"{passo.topico.titulo if passo.topico else passo.comando}")
        dom = [s for s in sits if s.estado == "dominado"]
        prat = [s for s in sits if s.estado in ("praticando", "comecou", "esfriando")]
        fracos = [s for s in sits if s.estado == "fraco"]
        novos = [s for s in sits if s.estado == "novo"]
        falas = []
        if dom:
            falas.append("Você já domina " + _lista([s.topico.titulo for s in dom]) + ".")
        if prat:
            falas.append("Está praticando " + _lista([_com_pct(s) for s in prat[:3]]) + ".")
        if fracos:
            falas.append("Precisa reforçar " + _lista([_com_pct(s) for s in fracos[:3]]) + ".")
        if novos:
            falas.append(f"Ainda {plural(len(novos), 'tópico não começou', 'tópicos não começaram')}.")
        erros = self.erros_atuais(2)
        if erros:
            item, regra = erros[0]
            if regra:
                falas.append(f"Um ponto para rever, de {item.topico}: {regra}")
        linhas = [f"# {m} · o que você já sabe",
                  f"Domina {len(dom)} · praticando {len(prat)} · reforçar {len(fracos)} · "
                  f"faltam {len(novos)} (de {len(sits)})"]
        for s in dom[:3]:
            linhas.append(f"- ✓ {s.topico.titulo} ({s.pct}%)")
        for s in (fracos + prat)[:4]:
            linhas.append(f"- {s.topico.titulo}: {s.rotulo}" + (f" ({s.pct}%)" if s.pct is not None else ""))
        for item, regra in erros[:2]:
            if regra:
                linhas.append(f"Rever: {regra[:150]}")
        return " ".join(falas), "\n".join(linhas)

    def mapa_resumido(self) -> tuple[str, str]:
        """Direção: o próximo passo e onde está na trilha."""
        sits = self.situacoes()
        c = self.contagem(sits)
        passo = self.proximo_passo()
        feitos = len(sits) - c["novo"]
        fala = (f"Em {self.trilha.materia} você já começou {feitos} de {len(sits)} tópicos do edital "
                f"e domina {c['dominado']}. Próximo passo: {passo.motivo} Diga: {passo.comando}.")
        linhas = [f"# {self.trilha.materia} · próximo passo", passo.motivo,
                  f"(diga: {passo.comando})", "",
                  f"Domina {c['dominado']} · praticando {c['praticando'] + c['comecou']} · "
                  f"reforçar {c['fraco']} · revisar {c['esfriando']} · faltam {c['novo']}"]
        proximos = [s for s in sits if s.estado == "novo"][:3]
        if proximos:
            linhas.append("Depois: " + ", ".join(s.topico.titulo for s in proximos))
        return fala, "\n".join(linhas)


def _lista(nomes: list[str]) -> str:
    if len(nomes) <= 1:
        return "".join(nomes)
    return ", ".join(nomes[:-1]) + " e " + nomes[-1]


def _com_pct(s: Situacao) -> str:
    return s.topico.titulo + (f" ({s.pct} por cento)" if s.pct is not None else "")


# ---------- diário: o que estudou num período ----------

PERIODOS = {"hoje": (0, 0), "ontem": (1, 1), "semana": (6, 0), "mes": (29, 0)}


def periodo_da_fala(t: str) -> str:
    if "ontem" in t:
        return "ontem"
    if "hoje" in t:
        return "hoje"
    if " mes" in f" {t}" or "mensal" in t:
        return "mes"
    return "semana"


def diario(caderno: Caderno, periodo: str, trilhas: list[Trilha] = ()) -> tuple[str, str]:
    """(fala, quadro) do que foi estudado no período: tempo, aulas, questões, lacunas,
    artigos lidos e dúvidas."""
    inicio_dias, fim_dias = PERIODOS.get(periodo, PERIODOS["semana"])
    hoje = caderno.relogio()
    ini = (hoje - timedelta(days=inicio_dias)).isoformat()
    fim = (hoje - timedelta(days=fim_dias)).isoformat()
    dentro = lambda d: d and ini <= d[:10] <= fim  # noqa: E731
    nome = {"hoje": "Hoje", "ontem": "Ontem", "semana": "Nos últimos 7 dias",
            "mes": "Nos últimos 30 dias"}[periodo if periodo in PERIODOS else "semana"]

    sessoes = [s for s in caderno.dados["sessoes"] if dentro(s.get("data"))]
    estudo = [e for e in caderno.dados["estudo"] if dentro(e.get("data"))]
    eventos = [e for e in caderno.eventos if dentro(e.get("d"))]
    minutos = sum(e.get("minutos", 0) for e in estudo) + sum(
        s.get("minutos", 0) for s in sessoes if s.get("tipo") not in ("fixacao",))
    titulos = {f"{tr.id}:{t.id}": t.titulo for tr in trilhas for t in tr.topicos}
    aulas = list(dict.fromkeys(titulos.get(e.get("t"), e.get("t")) for e in eventos
                               if e.get("k") == "aula"))
    respostas = [e for e in eventos if e.get("k") == "r"]
    questoes = [e for e in respostas if not str(e.get("i", "")).startswith("lei:")]
    lacunas = [e for e in respostas if str(e.get("i", "")).startswith("lei:")]
    artigos = list(dict.fromkeys(e.get("ref") for e in eventos if e.get("k") == "artigo"))
    duvidas = list(dict.fromkeys(titulos.get(e.get("t"), e.get("t")) for e in eventos
                                 if e.get("k") == "duvida"))
    materias = list(dict.fromkeys(e.get("materia") for e in estudo if e.get("materia")))

    if not (minutos or aulas or respostas or artigos or duvidas):
        quando = {"hoje": "hoje", "ontem": "ontem"}.get(periodo, "nesse período")
        return (f"Não encontrei estudo registrado {quando}.",
                f"# {nome}\nNada registrado.")
    falas, linhas = [], [f"# {nome} você estudou"]
    if minutos:
        h, mi = divmod(round(minutos), 60)
        tempo = f"{h} h {mi:02d} min" if h else f"{mi} min"
        falas.append(f"{nome} você estudou {_tempo_falado(minutos)}"
                     + (f", de {_lista(materias[:3])}" if materias else "") + ".")
        linhas.append(f"Tempo: {tempo}" + (f" ({', '.join(materias[:3])})" if materias else ""))
    if aulas:
        falas.append(("Teve aula de " if len(aulas) == 1 else "Teve aulas de ") + _lista(aulas[:3]) + ".")
        linhas.append("Aulas: " + ", ".join(aulas[:4]))
    if questoes:
        ac = sum(1 for e in questoes if e.get("ok"))
        pct = round(100 * ac / len(questoes))
        falas.append(f"Respondeu {plural(len(questoes), 'questão', 'questões')}, com {pct} por cento de acerto.")
        linhas.append(f"Questões: {len(questoes)} · {pct}% de acerto")
    if lacunas:
        ac = sum(1 for e in lacunas if e.get("ok"))
        falas.append(f"Fez {plural(len(lacunas), 'lacuna', 'lacunas')} de lei seca e acertou {ac}.")
        linhas.append(f"Lacunas: {len(lacunas)} · {ac} certas")
    if artigos:
        if len(artigos) == 1:
            falas.append(f"Leu o {artigos[0]}.")
        else:
            falas.append(f"Leu {len(artigos)} artigos, como o {artigos[0]}.")
        linhas.append("Artigos: " + ", ".join(a for a in artigos[:6] if a))
    if duvidas:
        falas.append("Tirou dúvidas sobre " + _lista([d for d in duvidas[:3] if d]) + ".")
        linhas.append("Dúvidas: " + ", ".join(d for d in duvidas[:4] if d))
    return " ".join(falas), "\n".join(linhas)


def _tempo_falado(minutos: float) -> str:
    h, m = divmod(round(minutos), 60)
    if h and m:
        return f"{plural(h, 'hora', 'horas')} e {plural(m, 'minuto', 'minutos')}"
    if h:
        return plural(h, "hora", "horas")
    return plural(m, "minuto", "minutos")
