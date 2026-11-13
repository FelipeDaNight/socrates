"""O tutor: entende os pedidos de estudo e cuida do treino em andamento.

Pedidos que ele resolve sozinho (rápido, sem gastar o limite grátis):
  "questões da PRF"                    "10 questões de trânsito da PRF"
  "simulado da PRF" / "simulado de 20 questões do CBMGO"
  "questões que eu errei"              "revisa meus erros"
  "lacunas do CTB" / "lacunas de hoje" "lê o artigo 165 do CTB"
  "como estou indo?"                   "o que eu estudo hoje?"
Qualquer outra coisa segue para o cérebro (com os trechos da lei, se for o caso).
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

from .caderno import Caderno
from .lei import Leis, lei_citada
from .material import ID_PRIVADO, Material
from .respostas import norm
from .treino import (NOME_LEI, Item, Saida, Sessao, fonte_curta, item_de_lacuna, item_de_questao,
                     plural)

log = logging.getLogger("socrates.tutor")

POR_SESSAO = 10
SIMULADO_PADRAO = 20

_BANCOS = [  # (palavras faladas, id do banco)
    (re.compile(r"\b(prf|policia rodoviaria|rodoviaria federal|cebraspe|cespe)\b"), "prf-2021-p1"),
    (re.compile(r"\b(cbmgo|cbm go|bombeiros?|aocp)\b"), "cbmgo-2022-soldado"),
    (re.compile(r"\b(gran|minhas questoes|caderno privado|meus erros do gran)\b"), ID_PRIVADO),
]
_QUESTOES = re.compile(r"\b(questoes|questao|perguntas de prova|itens|simulado|prova)\b")
_COMECAR = re.compile(r"\b(questoes|questao|simulado|treino|treinar|treina|me testa|me teste|"
                      r"pratica|praticar|bora|vamos|quero|faz|faca|manda|comeca|comecar|inicia)\b")
_ERRADAS = re.compile(r"\b(que (?:eu )?errei|erradas|que errei)\b")
_REVISAO = re.compile(r"\b(revisa|revisar|revise|revisao|revisoes)\b.*\b(erros|errei|caderno|hoje|vencid\w*|cartoes)\b"
                      r"|\b(minha|minhas|a|as) revis(ao|oes)\b|^revis(ao|ar|a)\b")
_LACUNAS = re.compile(r"\blacunas?\b")
_DESEMPENHO = re.compile(r"\b(como (?:eu )?(?:estou|to|tou|vou) indo|meu desempenho|minhas estatisticas"
                         r"|meu rendimento|quanto (?:eu )?estudei|quantas questoes (?:eu )?fiz"
                         r"|meus numeros|minha evolucao)\b")
_PLANO = re.compile(r"\b(o que (?:eu )?(?:estudo|devo estudar|vou estudar|faco|estudar) hoje"
                    r"|plano (?:de|do|pra|para) (?:hoje|dia|estudo)|por onde (?:eu )?comec\w*"
                    r"|o que (?:eu )?estudo agora|o que (?:tem|temos) pra hoje)\b")
_LER_ARTIGO = re.compile(r"\bart(?:igo|\.)?s?\s*\d")
_NUMERO = re.compile(r"\b(\d{1,3})\s+(?:questoes|questao|itens|perguntas|lacunas)\b")
_NUMEROS_FALADOS = {"cinco": 5, "dez": 10, "quinze": 15, "vinte": 20, "trinta": 30, "quarenta": 40,
                    "cinquenta": 50, "tres": 3}


@dataclass
class Pedido:
    tipo: str                    # questoes | simulado | revisao | lacunas | artigo | desempenho | plano
    banco: str | None = None
    materia: str | None = None
    n: int | None = None
    so_erradas: bool = False
    lei: str | None = None


class Tutor:
    def __init__(self, material: Material, caderno: Caderno, planilha=None, sortear=None):
        self.material = material
        self.caderno = caderno
        self.planilha = planilha
        self.leis = Leis(material)
        self.sessao: Sessao | None = None
        self.sortear = sortear or random.Random()

    # ---------- entender o pedido ----------
    def _quantos(self, t: str) -> int | None:
        m = _NUMERO.search(t)
        if m:
            return max(1, min(int(m.group(1)), 120))
        for palavra, n in _NUMEROS_FALADOS.items():
            if re.search(rf"\b{palavra} (?:questoes|questao|itens|perguntas|lacunas)\b", t):
                return n
        return None

    def _materia(self, t: str, banco: str | None) -> tuple[str | None, str | None]:
        """Acha a matéria dita ("trânsito", "português") no banco (ou em qualquer um)."""
        candidatos = [banco] if banco else list(self.material.bancos)
        palavras = [p for p in t.split() if len(p) >= 5 and p not in
                    {"questoes", "questao", "simulado", "treino", "treinar", "quero", "fazer",
                     "sobre", "minhas", "lacunas", "provas", "socrates", "erradas", "comeca"}]
        for bid in candidatos:
            materias = {q.get("materia", "") for q in self.material.bancos.get(bid, {}).get("questoes", [])}
            for m in sorted(materias):
                nm = norm(m)
                if any(p in nm or (p[:-1] in nm and len(p) > 6) for p in palavras):
                    return bid, m
        return banco, None

    def entender(self, texto: str) -> Pedido | None:
        t = norm(texto)
        t = re.sub(r"^(?:socrates|ei socrates|ok)\s+", "", t)
        if _DESEMPENHO.search(t):
            return Pedido("desempenho")
        if _PLANO.search(t):
            return Pedido("plano")
        if _LACUNAS.search(t) and _COMECAR.search(t) or re.match(r"^(as |minhas )?lacunas\b", t):
            lei = lei_citada(texto)
            return Pedido("lacunas", lei=lei, n=self._quantos(t))
        if _REVISAO.search(t) and not _LACUNAS.search(t):
            return Pedido("revisao", n=self._quantos(t))
        if _LER_ARTIGO.search(t) and self.leis.pedido_de_artigo(texto):
            return Pedido("artigo")
        banco = next((bid for rx, bid in _BANCOS if rx.search(t)), None)
        if banco and banco not in self.material.bancos:
            banco = None if banco != ID_PRIVADO else banco
        quer_questoes = bool(_QUESTOES.search(t))
        if not (banco or quer_questoes):
            return None
        if not _COMECAR.search(t) and not quer_questoes:
            return None                 # "o que cai na PRF?" é conversa, não treino
        banco, materia = self._materia(t, banco)
        if banco is None:
            if not quer_questoes or _ERRADAS.search(t) is None:
                return None             # "questões de crase": sem banco, o cérebro cria
        tipo = "simulado" if "simulado" in t else "questoes"
        return Pedido(tipo, banco=banco, materia=materia, n=self._quantos(t),
                      so_erradas=bool(_ERRADAS.search(t)))

    # ---------- montar o treino ----------
    def _itens_do_banco(self, banco_id: str) -> list[Item]:
        banco = self.material.bancos[banco_id]
        return [i for q in banco.get("questoes", []) if (i := item_de_questao(banco, q))]

    def _escolher_questoes(self, p: Pedido) -> tuple[list[Item], str]:
        bancos = [p.banco] if p.banco else list(self.material.bancos)
        itens = [i for b in bancos for i in self._itens_do_banco(b)]
        if p.materia:
            itens = [i for i in itens if i.materia == p.materia]
        if p.so_erradas:
            itens = [i for i in itens if self.caderno.itens.get(i.id, {}).get("erros")]
            return itens[: p.n or POR_SESSAO], "Questões que você errou"
        if p.tipo == "simulado":
            n = min(p.n or SIMULADO_PADRAO, len(itens))
            escolhidas = self.sortear.sample(itens, n)
            escolhidas.sort(key=lambda i: itens.index(i))     # na ordem da prova
        else:
            novas = [i for i in itens if not self.caderno.visto(i.id)]
            velhas = [i for i in itens if self.caderno.visto(i.id)]
            self.sortear.shuffle(novas)
            self.sortear.shuffle(velhas)
            escolhidas = (novas + velhas)[: p.n or POR_SESSAO]
        nome = fonte_curta(self.material.bancos[bancos[0]]) if len(bancos) == 1 else "Questões"
        if p.materia:
            nome += f", {p.materia}"
        return escolhidas, ("Simulado " if p.tipo == "simulado" else "") + nome

    def _todas_lacunas(self, lei: str | None = None) -> list[Item]:
        saida = []
        for _caderno, bloco in self.material.blocos():
            if lei and bloco.get("lei") != lei:
                continue
            for art in bloco.get("artigos", []):
                for lac in art.get("lacunas") or []:
                    if lac.get("c") and lac.get("r"):
                        saida.append(item_de_lacuna(bloco, art, lac))
        return saida

    def _escolher_lacunas(self, p: Pedido) -> list[Item]:
        todas = self._todas_lacunas(p.lei)
        n = p.n or POR_SESSAO
        vencidas_ids = set(self.caderno.vencidos("lei:"))
        vencidas = [i for i in todas if i.id in vencidas_ids]
        novas = [i for i in todas if not self.caderno.visto(i.id)]   # na ordem da lei
        return (vencidas + novas)[:n]

    def _escolher_revisao(self, p: Pedido) -> list[Item]:
        vencidos = self.caderno.vencidos()
        if not vencidos:
            return []
        indice = {i.id: i for b in self.material.bancos for i in self._itens_do_banco(b)}
        indice.update({i.id: i for i in self._todas_lacunas()})
        return [indice[v] for v in vencidos if v in indice][: p.n or 15]

    # ---------- atender ----------
    @property
    def em_treino(self) -> bool:
        return self.sessao is not None

    def atender(self, texto: str) -> Saida | None:
        """Devolve o que fazer, ou None se o pedido não é de estudo (vai ao cérebro)."""
        p = self.entender(texto)
        if self.sessao is not None:
            if p is not None and p.tipo in ("artigo", "desempenho", "plano"):
                saida = self._consulta(p, texto)        # o treino continua depois
                saida.fala += " Diga repete para voltar à questão."
                return saida
            if p is None:
                saida = self.sessao.atender(texto)
                if saida.fim:
                    self._fechar_sessao()
                return saida
            fim = self.encerrar()                       # pediu outro treino: fecha este
            nova = self._comecar(p, texto)
            nova.fala = (fim.fala + " " if fim and fim.fala else "") + nova.fala
            return nova
        if p is None:
            return None
        return self._comecar(p, texto)

    def _consulta(self, p: Pedido, texto: str) -> Saida:
        if p.tipo == "desempenho":
            return self.desempenho()
        if p.tipo == "plano":
            return self.plano()
        lei, num = self.leis.pedido_de_artigo(texto)
        a = self.leis.artigo(lei, num)
        if a is None:
            nome = NOME_LEI.get(lei, lei)
            return Saida(fala=f"Não tenho o artigo {num[0]}{('-' + num[1]) if num[1] else ''} "
                              f"do {nome} no material.")
        fala, quadro = self.leis.apresentar(a)
        return Saida(fala=fala, quadro=quadro)

    def _comecar(self, p: Pedido, texto: str) -> Saida:
        log.info("pedido de estudo: %s", p)
        if p.tipo in ("desempenho", "plano", "artigo"):
            return self._consulta(p, texto)
        if self.material.vazio:
            return Saida(fala="Ainda não tenho o material de estudo. Rode main.py --material "
                              "com a internet ligada.")
        if p.tipo == "lacunas":
            itens = self._escolher_lacunas(p)
            titulo = "Lacunas" + (f" do {NOME_LEI.get(p.lei, p.lei)}" if p.lei else "")
            modo = "lacunas"
            if not itens:
                return Saida(fala="Não tenho lacunas novas nem vencidas" +
                                  (f" do {NOME_LEI.get(p.lei, p.lei)}." if p.lei else "."))
        elif p.tipo == "revisao":
            itens, titulo, modo = self._escolher_revisao(p), "Revisão", "revisao"
            if not itens:
                return Saida(fala="Nada para revisar hoje. Que tal questões novas ou lacunas?")
        else:
            itens, titulo = self._escolher_questoes(p)
            modo = "simulado" if p.tipo == "simulado" else "treino"
            if not itens:
                falta = "que você errou" if p.so_erradas else (p.materia or "")
                return Saida(fala=f"Não achei questões {falta} nesse banco.".replace("  ", " "))
        self.sessao = Sessao(itens, modo, titulo, self.caderno,
                             self.material.bancos.get(p.banco) if p.banco else None)
        return self.sessao.abrir()

    def encerrar(self) -> Saida | None:
        if self.sessao is None:
            return None
        saida = self.sessao.encerrar()
        self._fechar_sessao()
        return saida

    def _fechar_sessao(self) -> None:
        s, self.sessao = self.sessao, None
        if s is None or not s.registros:
            return
        resumo = s.resumo()
        self.caderno.anotar_sessao(resumo)
        try:
            self.caderno.salvar()
        except OSError as e:
            log.warning("caderno não salvo: %s", e)
        self._para_planilha(s)

    def _para_planilha(self, s: Sessao) -> None:
        if self.planilha is None or not self.planilha.ativa or s.modo == "lacunas":
            return
        data = self.caderno.relogio().isoformat()
        grupos: dict[tuple[str, str, str], list[int]] = {}
        for r in s.registros:
            if r.dada is None and s.modo != "simulado":
                continue
            fonte = re.sub(r"\s*(?:·\s*)?(?:item \d+|Q\d+)$", "", r.item.fonte)
            g = grupos.setdefault((r.item.materia, r.item.topico, fonte), [0, 0, 0])
            g[0] += 1
            g[1] += r.ok
            g[2] += (not r.ok and r.dada is not None)
        sufixo = " (simulado)" if s.modo == "simulado" else " (Sócrates)"
        for (materia, topico, fonte), (feitas, ac, er) in grupos.items():
            self.planilha.enviar("questoes", {"data": data, "materia": materia, "topico": topico,
                                              "feitas": feitas, "acertos": ac, "erros": er,
                                              "fonte": fonte + sufixo})
        for r in s.registros:
            if not r.ok and r.dada is not None:
                self.planilha.enviar("erro", {"data": data, "topico": r.item.topico,
                                              "tipo": "Teoria que eu não sabia",
                                              "confianca": "Certeza",
                                              "regra": r.item.comentario() or f"Rever: {r.item.topico}",
                                              "lei": "", "fonte": r.item.fonte})
        if s.modo == "simulado" and s.banco and s.banco.get("sincroniza_simulado"):
            ac, er, _ = s.contagem()
            self.planilha.enviar("simulado", {"data": data, "nome": s.titulo,
                                              "itens": len(s.registros), "acertos": ac,
                                              "erros": er,
                                              "tempo": max(1, round(s.resumo()["minutos"]))})

    # ---------- o ouvido ----------
    def dica_do_ouvido(self) -> str | None:
        if self.sessao is not None and self.sessao.espera_resposta_curta:
            from ..stt.groq_whisper import DICA_TREINO
            return DICA_TREINO
        return None

    def contexto_da_lei(self, pergunta: str) -> str:
        return self.leis.trechos(pergunta)

    # ---------- desempenho e plano ----------
    def _ultimos(self, dias: int):
        sessoes, estudo = self.caderno.desde(dias)
        por: dict[str, list[int]] = {}
        for s in sessoes:
            if s.get("tipo") == "lacunas":
                continue
            for m, (f, a, e) in (s.get("por_materia") or {}).items():
                x = por.setdefault(m, [0, 0, 0])
                x[0] += f
                x[1] += a
                x[2] += e
        return sessoes, estudo, por

    def desempenho(self) -> Saida:
        sessoes, estudo, por = self._ultimos(7)
        minutos = sum(e["minutos"] for e in estudo) + sum(
            s.get("minutos", 0) for s in sessoes if s.get("tipo") != "lacunas")
        feitas = sum(a + e for _, a, e in por.values())
        acertos = sum(a for _, a, _ in por.values())
        vencidos = len(self.caderno.vencidos())
        if not sessoes and not estudo:
            return Saida(fala="Ainda não tenho registros desta semana. Que tal começar com "
                              "questões da PRF ou as lacunas do CTB?")
        horas, mins = divmod(round(minutos), 60)
        tempo = (f"{horas} hora{'s' if horas != 1 else ''} e {mins} minutos" if horas
                 else f"{mins} minutos")
        linhas = ["# Seus últimos 7 dias", f"Tempo de estudo: {tempo}"]
        fala = f"Nos últimos sete dias você estudou {tempo}"
        if feitas:
            pct = round(100 * acertos / feitas)
            linhas.append(f"Questões: {feitas} · {pct}% de acerto")
            fala += f" e respondeu {plural(feitas, 'questão', 'questões')}, com {pct} por cento de acerto."
        else:
            fala += "."
        ordem = sorted(((m, a, e) for m, (_, a, e) in por.items() if a + e >= 2),
                       key=lambda x: x[1] / (x[1] + x[2]))
        for m, a, e in ordem[:5]:
            linhas.append(f"- {m}: {a} de {a + e} ({round(100 * a / (a + e))}%)")
        if ordem and ordem[0][1] / (ordem[0][1] + ordem[0][2]) < 0.7:
            fala += f" O ponto mais fraco é {ordem[0][0]}."
        if vencidos:
            linhas.append(f"Revisões para hoje: {vencidos}")
            fala += f" Você tem {vencidos} revisões para hoje."
        return Saida(fala=fala, quadro="\n".join(linhas))

    def _proximo_trecho_de_lei(self) -> tuple[str, str] | None:
        """O próximo trecho da lei que o aluno vinha treinando (ou a primeira)."""
        recentes = sorted(((it.get("ultima", ""), i) for i, it in self.caderno.itens.items()
                           if i.startswith("lei:")), reverse=True)
        blocos = list(self.material.blocos())
        if recentes:
            bloco_id = recentes[0][1].split(":")[1]
            lei = next((b.get("lei") for _, b in blocos if b.get("id") == bloco_id), None)
            blocos.sort(key=lambda cb: cb[1].get("lei") != lei)   # a mesma lei primeiro
        for _caderno, bloco in blocos:
            lacunas = [item_de_lacuna(bloco, a, l) for a in bloco.get("artigos", [])
                       for l in a.get("lacunas") or [] if l.get("c")]
            if lacunas and any(not self.caderno.visto(i.id) for i in lacunas):
                return NOME_LEI.get(bloco.get("lei"), bloco.get("lei")), bloco.get("rotulo", "")
        return None

    def plano(self) -> Saida:
        _s, _e, por = self._ultimos(14)
        vencidos = len(self.caderno.vencidos())
        linhas, falas = ["# Plano de hoje"], []
        if vencidos:
            linhas.append(f"- Revisar {plural(vencidos, 'item que venceu', 'itens que venceram')}"
                          " (diga: revisa meus erros)")
            falas.append(f"revisar {plural(vencidos, 'item que venceu', 'itens que venceram')} hoje")
        trecho = self._proximo_trecho_de_lei()
        if trecho:
            linhas.append(f"- Lei seca: {trecho[0]}, {trecho[1]} (diga: lacunas do {trecho[0]})")
            falas.append(f"a lei seca: {trecho[0]}, {trecho[1].split(' · ')[-1]}")
        fracas = sorted(((m, a, e) for m, (_, a, e) in por.items() if a + e >= 3),
                        key=lambda x: x[1] / (x[1] + x[2]))
        if fracas and fracas[0][1] / (fracas[0][1] + fracas[0][2]) < 0.75:
            m = fracas[0][0]
            linhas.append(f"- 10 questões de {m} (seu ponto mais fraco)")
            falas.append(f"e dez questões de {m}, que é onde você mais erra")
        else:
            linhas.append("- 10 questões novas da PRF (diga: questões da PRF)")
            falas.append("e dez questões novas da PRF")
        linhas.append("- Um pomodoro de 25 minutos para cada bloco")
        fala = "Sugestão para hoje: " + (", ".join(falas[:-1]) + " " + falas[-1] if len(falas) > 1
                                          else falas[0]) + ". Quer começar pelo primeiro?"
        return Saida(fala=fala, quadro="\n".join(linhas))

    # ---------- pomodoro ----------
    def registrar_estudo(self, materia: str, minutos: float) -> str:
        nome = self.planilha.nome_da_materia(materia) if self.planilha else materia
        self.caderno.anotar_estudo(nome, minutos)
        try:
            self.caderno.salvar()
        except OSError as e:
            log.warning("caderno não salvo: %s", e)
        if self.planilha is not None and self.planilha.ativa:
            self.planilha.enviar("estudo", {"data": self.caderno.relogio().isoformat(),
                                            "materia": nome, "minutos": round(minutos)})
            return f"Anotei {round(minutos)} minutos de {nome} na planilha."
        return f"Anotei {round(minutos)} minutos de {nome}."
