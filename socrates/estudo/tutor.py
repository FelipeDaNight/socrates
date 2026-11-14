"""O tutor: entende os pedidos de estudo e cuida do treino ou da aula em andamento.

Pedidos que ele resolve sozinho (rápido, sem gastar o limite grátis):
  "questões da PRF"                    "10 questões de trânsito da PRF"
  "simulado da PRF" / "simulado de 20 questões do CBMGO"
  "questões que eu errei"              "revisa meus erros"
  "lacunas do CTB" / "lacunas de hoje" "lê o artigo 165 do CTB"
  "como estou indo?"                   "o que eu estudo hoje?"
Trilhas (Direito Penal, Processo Penal, Legislação Especial e o que o autoestudo completar):
  "me ensina legítima defesa"          "vamos estudar processo penal"  (aula guiada)
  "o que eu estudo de penal?"          "qual o próximo passo?"    (direção)
  "o que eu estudei hoje/essa semana?" "o que eu já aprendi?"     (diário e domínio)
  "questões de furto" / "questões de drogas"  "simulado de penal"   "meu mapa"
Autoestudo (ele estuda sozinho o edital):
  "o que você está aprendendo?"  "o que você aprendeu hoje?"  "aprende sobre crase"
  "pausa o aprendizado"  "volta a aprender"
Qualquer outra coisa segue para o cérebro, levando junto as notas da trilha e os
trechos da lei, quando a pergunta for sobre eles.
"""

from __future__ import annotations

import logging
import random
import re
from dataclasses import dataclass

from . import autoestudo as auto
from .aula import Aula
from .caderno import Caderno
from .lei import Leis, lei_citada
from .material import ID_PRIVADO, Material
from .progresso import Progresso, _lista, diario, periodo_da_fala
from .respostas import norm
from .treino import (NOME_LEI, Item, Saida, Sessao, fonte_curta, item_de_lacuna, item_de_questao,
                     plural)
from .plano import Plano, TopicoPlano, achar_materia, achar_topico
from .trilha import Topico, Trilha, carregar_trilhas

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
_TREINO = re.compile(r"\b(me testa|me teste|treina|treinar|exercicios)\b")
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

# ----- trilha -----
_AULA = re.compile(r"\b(me ensina|me ensine|ensina|ensinar|aula|me da uma aula|vamos estudar|"
                   r"quero estudar|bora estudar|estudar|proximo topico|proximo assunto|"
                   r"continua a aula|continuar a aula|retoma a aula|retomar a aula)\b")
_DIRECAO = re.compile(r"\b(o que (?:eu )?(?:estudo|devo estudar|vou estudar|falta|tenho que estudar)"
                      r"|qual (?:e )?o proximo passo|proximo passo|por onde (?:eu )?(?:comeco|continuo|sigo)"
                      r"|o que vem agora|me (?:da|de) uma direcao|me orienta|qual o proximo topico"
                      r"|o que falta)\b")
_ESTUDADO = re.compile(r"\b(o que (?:eu )?(?:ja )?estudei|o que (?:eu )?fiz (?:hoje|ontem|essa semana|"
                       r"nessa semana|nesta semana|esta semana|no mes|esse mes)|meu historico|"
                       r"historico de estudo|resumo (?:do|de) (?:hoje|dia|estudo|semana)|meu diario)\b")
_APRENDIDO = re.compile(r"\b(o que (?:eu )?(?:ja )?aprendi|o que (?:eu )?(?:ja )?sei|o que (?:eu )?"
                        r"(?:ja )?domino|o que (?:eu )?(?:ainda )?(?:erro|nao sei)|meus pontos fracos|"
                        r"onde (?:eu )?(?:mais )?erro|como (?:eu )?(?:estou|to|tou|vou) (?:em|no|na))\b")
_MAPA = re.compile(r"\b(mapa|minha trilha|a trilha|meu progresso|progresso (?:de|em|no))\b")
_MAPA_SOLTO = re.compile(r"\b(meu mapa|mapa (?:de|do|da) (?:estudo|estudos|trilha|edital)|minha trilha|"
                         r"meu progresso)\b")
_EXPLICITO = re.compile(r"^(?:socrates )?(?:quero|vamos|bora|faz|faca|me da|me de|manda|comeca|"
                        r"inicia|abre|mostra|le |leia|questoes|simulado|lacunas|revisa|me ensina|"
                        r"ensina|aula|o que (?:eu )?(?:estudo|estudei|aprendi|falta)|qual o proximo|"
                        r"para a aula|encerra a aula)")


@dataclass
class Pedido:
    tipo: str                    # questoes | simulado | revisao | lacunas | artigo | desempenho | plano
    banco: str | None = None     # | aula | direcao | estudado | aprendido | mapa
    materia: str | None = None
    n: int | None = None
    so_erradas: bool = False
    lei: str | None = None
    trilha: Trilha | None = None
    topico: Topico | None = None
    periodo: str | None = None
    alvo: TopicoPlano | None = None       # tópico do edital que ainda não tem conteúdo
    comando: str | None = None            # autoestudo: status | hoje | pausar | retomar | pedir


_CONSULTAS = ("artigo", "desempenho", "plano", "direcao", "estudado", "aprendido", "mapa", "auto")
_ORDEM_PASSO = {"continuar": 0, "reforco": 1, "revisao": 2, "relembrar": 3, "aula": 4, "praticar": 5,
                "simulado": 6}


class Tutor:
    def __init__(self, material: Material, caderno: Caderno, planilha=None, sortear=None,
                 trilhas: list[Trilha] | None = None, planos: list[Plano] | None = None,
                 autoestudo=None):
        self.material = material
        self.caderno = caderno
        self.planilha = planilha
        self.leis = Leis(material)
        self.sessao: Sessao | None = None
        self.aula: Aula | None = None
        self.sortear = sortear or random.Random()
        self._trilhas_fixas = trilhas is not None
        self.trilhas = carregar_trilhas() if trilhas is None else trilhas
        self.planos = planos or []
        self.autoestudo = autoestudo
        self._progressos: dict[str, Progresso] = {}
        self._recarregar = False

    # ---------- o autoestudo aprendeu algo novo ----------
    def marcar_recarga(self, _trilha: str | None = None) -> None:
        """Chamado pelo autoestudo (outra thread): recarrega as trilhas no próximo pedido."""
        self._recarregar = True

    def _talvez_recarregar(self) -> None:
        if not self._recarregar or self._trilhas_fixas:
            return
        self._recarregar = False
        try:
            self.trilhas = carregar_trilhas()
        except Exception:
            log.exception("não consegui recarregar as trilhas")
            return
        self._progressos.clear()

    def progresso(self, trilha: Trilha) -> Progresso:
        if trilha.id not in self._progressos:
            self._progressos[trilha.id] = Progresso(trilha, self.caderno, self.material.bancos,
                                                    self._todas_lacunas())
        return self._progressos[trilha.id]

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

    def _trilha_da_fala(self, texto: str) -> tuple[Trilha | None, Topico | None]:
        """A trilha da matéria citada ("processo penal"); senão, a do tópico mais parecido
        com a fala, entre todas as trilhas."""
        for tr in self.trilhas:
            if tr.menciona_materia(texto):
                return tr, tr.topico_citado(texto)
        melhor: tuple[int, int, Trilha, Topico] | None = None
        for i, tr in enumerate(self.trilhas):
            achados = tr.achar(texto)
            if achados:
                nota, topico = achados[0]
                if melhor is None or (nota, -i) > (melhor[0], -melhor[1]):
                    melhor = (nota, i, tr, topico)
        return (melhor[2], melhor[3]) if melhor else (None, None)

    def _banco_citado(self, t: str) -> str | None:
        """O banco de prova que a fala nomeia ("da PRF", "do CBMGO"), se ele estiver carregado."""
        bid = next((b for rx, b in _BANCOS if rx.search(t)), None)
        return bid if bid in self.material.bancos else None

    def _pedido_da_trilha(self, texto: str, t: str) -> Pedido | None:
        tr, topico = self._trilha_da_fala(texto)
        if _ESTUDADO.search(t):
            return Pedido("estudado", trilha=tr, periodo=periodo_da_fala(t))
        if _APRENDIDO.search(t) and (tr or not _DESEMPENHO.search(t)):
            return Pedido("aprendido", trilha=tr)
        if tr is None and self.trilhas and _MAPA_SOLTO.search(t):
            return Pedido("mapa")
        if tr is None:
            if _DIRECAO.search(t) and self.trilhas:
                return Pedido("plano")        # "qual o próximo passo?" sem matéria: o plano geral
            if _AULA.search(t) and self.planos and not _QUESTOES.search(t):
                alvo = achar_topico(self.planos, texto)
                if alvo is None:                       # "vamos estudar português"
                    m = achar_materia(self.planos, texto)
                    if m is not None and m.topicos:
                        alvo = max(m.topicos, key=lambda x: (x.peso, -m.topicos.index(x)))
                if alvo is not None:
                    return Pedido("aprender", alvo=alvo)
            return None
        if _MAPA.search(t):
            return Pedido("mapa", trilha=tr)
        if _DIRECAO.search(t) and not topico:
            return Pedido("direcao", trilha=tr)
        if _LER_ARTIGO.search(t) and self.leis.pedido_de_artigo(texto):
            return None                     # "artigo 155 do CP" é leitura do artigo
        if _AULA.search(t):
            return Pedido("aula", trilha=tr, topico=topico)
        if _LACUNAS.search(t):
            return None                     # lacunas da lei seca (tratadas adiante)
        if _REVISAO.search(t):
            return Pedido("revisao", trilha=tr, n=self._quantos(t))
        quer_treino = "simulado" in t or _QUESTOES.search(t) or _TREINO.search(t)
        if quer_treino and topico is None and self._banco_citado(t):
            return None                     # "questões de trânsito DA PRF": as da prova, no banco
        if "simulado" in t:
            return Pedido("simulado", trilha=tr, topico=topico, n=self._quantos(t))
        if _QUESTOES.search(t) or _TREINO.search(t):
            return Pedido("questoes", trilha=tr, topico=topico, n=self._quantos(t),
                          so_erradas=bool(_ERRADAS.search(t)))
        if _DESEMPENHO.search(t):
            return Pedido("aprendido", trilha=tr)
        return None

    def entender(self, texto: str) -> Pedido | None:
        t = norm(texto)
        t = re.sub(r"^(?:socrates|ei socrates|ok)\s+", "", t)
        if self.autoestudo is not None:
            cmd = auto.entender(texto)
            if cmd is not None:
                return Pedido("auto", comando=cmd[0])
        trilha = self._pedido_da_trilha(texto, t)
        if trilha is not None:
            return trilha
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
        if p.trilha is not None:
            vencidos = [v for v in vencidos if v in self.progresso(p.trilha).todos]
        if not vencidos:
            return []
        indice = {i.id: i for b in self.material.bancos for i in self._itens_do_banco(b)}
        indice.update({i.id: i for i in self._todas_lacunas()})
        for tr in self.trilhas:
            indice.update(self.progresso(tr).itens)
        return [indice[v] for v in vencidos if v in indice][: p.n or 15]

    def _escolher_da_trilha(self, p: Pedido) -> tuple[list[Item], str]:
        """Questões da trilha: do tópico pedido, ou da matéria toda, priorizando o que
        o aluno já estudou e onde ele está mais fraco."""
        tr = p.trilha
        prog = self.progresso(tr)
        if p.topico is not None:
            itens = tr.itens_do_topico(p.topico, self.material.bancos)
            titulo = f"{tr.materia}: {p.topico.titulo}"
        else:
            ordem = {"fraco": 0, "praticando": 1, "comecou": 1, "esfriando": 2, "dominado": 3, "novo": 4}
            sits = sorted(prog.situacoes(), key=lambda s: (ordem[s.estado], s.topico.ordem))
            itens = []
            for s in sits:
                itens += tr.itens_do_topico(s.topico, self.material.bancos)
            titulo = tr.materia
        unicos = list({i.id: i for i in itens}.values())
        if p.so_erradas:
            unicos = [i for i in unicos if self.caderno.itens.get(i.id, {}).get("erros")]
            return unicos[: p.n or POR_SESSAO], f"{titulo}, questões que você errou"
        if p.tipo == "simulado":
            n = min(p.n or SIMULADO_PADRAO, len(unicos))
            return self.sortear.sample(unicos, n), f"Simulado de {titulo}"
        novas = [i for i in unicos if not self.caderno.visto(i.id)]
        erradas = [i for i in unicos if self.caderno.itens.get(i.id, {}).get("ok") is False]
        resto = [i for i in unicos if i not in novas and i not in erradas]
        if p.topico is not None:
            self.sortear.shuffle(novas)
        self.sortear.shuffle(erradas)
        self.sortear.shuffle(resto)
        return (erradas[:3] + novas + erradas[3:] + resto)[: p.n or POR_SESSAO], titulo

    # ---------- atender ----------
    @property
    def em_treino(self) -> bool:
        return self.sessao is not None or self.aula is not None

    def atender(self, texto: str) -> Saida | None:
        """Devolve o que fazer, ou None se o pedido não é de estudo (vai ao cérebro)."""
        if self.aula is None and self.sessao is None:
            self._talvez_recarregar()
        p = self.entender(texto)
        if self.aula is not None:
            return self._na_aula(texto, p)
        if self.sessao is not None:
            if p is not None and p.tipo in _CONSULTAS:
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

    def _na_aula(self, texto: str, p: Pedido | None) -> Saida:
        """Na aula, quase tudo é resposta ou dúvida sobre o ponto. Só muda de rumo um
        pedido claro ("questões da PRF", "me ensina furto", "o que eu estudei hoje?")."""
        explicito = p is not None and bool(_EXPLICITO.match(norm(texto)))
        if explicito and p.tipo in _CONSULTAS and p.tipo != "direcao":
            saida = self._consulta(p, texto)
            if saida.contexto:
                saida.contexto += ("\nNo fim, diga que, para voltar à aula, é só ele dizer "
                                   "\"continua\".")
            else:
                saida.fala += " Diga continua para voltar à aula."
            self.aula.interrompida = True
            return saida
        if p is not None and p.tipo == "aula" and p.topico in (None, self.aula.topico):
            return self.aula.retomar()             # "me ensina <o mesmo tópico>" / "continua a aula"
        if explicito and not (p.tipo == "aula" and (p.topico is None or p.topico is self.aula.topico)):
            pausa = self.aula.pausar()
            self.aula = None
            nova = self._comecar(p, texto)
            nova.fala = (pausa.fala + " " + nova.fala).strip()
            return nova
        saida = self.aula.atender(texto)
        if saida.fim:
            self.aula = None
        return saida

    def _consulta(self, p: Pedido, texto: str) -> Saida:
        if p.tipo == "auto":
            return self._autoestudo(p.comando, texto)
        if p.tipo == "desempenho":
            return self.desempenho()
        if p.tipo == "plano":
            return self.plano()
        if p.tipo == "direcao":
            fala, quadro = self.progresso(p.trilha).mapa_resumido()
            return Saida(fala=fala, quadro=quadro)
        if p.tipo == "aprendido":
            if p.trilha is None:
                return self.aprendizado_geral()
            fala, quadro = self.progresso(p.trilha).resumo_aprendizado()
            return Saida(fala=fala, quadro=quadro)
        if p.tipo == "estudado":
            fala, quadro = diario(self.caderno, p.periodo or "semana", self.trilhas)
            return Saida(fala=fala, quadro=quadro)
        if p.tipo == "mapa":
            from .mapa import gerar, gerar_geral
            if p.trilha is None:
                caminho = gerar_geral([self.progresso(tr) for tr in self.trilhas], self.autoestudo,
                                      planos=self.planos)
                plano = self.plano()
                return Saida(fala="Abri o mapa de todas as matérias no navegador. " + plano.fala,
                             quadro=plano.quadro, abrir_pagina=str(caminho))
            prog = self.progresso(p.trilha)
            caminho = gerar(prog)
            fala, quadro = prog.mapa_resumido()
            return Saida(fala="Abri o mapa completo no navegador. " + fala, quadro=quadro,
                         abrir_pagina=str(caminho))
        lei, num = self.leis.pedido_de_artigo(texto)
        a = self.leis.artigo(lei, num)
        if a is None:
            nome = NOME_LEI.get(lei, lei)
            rotulo = f"{num[0]}{('-' + num[1]) if num[1] else ''}"
            for tr in self.trilhas:              # sem o texto literal: explica pelas notas da trilha
                topico = next((t for t in tr.topicos if t.tem_artigo(lei, num)), None)
                if topico is not None:
                    notas, _ = tr.notas(f"{texto} {topico.titulo}")
                    if not notas:
                        notas = "\n".join(f"- {x}" for x in topico.pontos)
                    self.caderno.anotar_evento("artigo", ref=f"art. {rotulo} do {nome}")
                    return Saida(contexto=(
                        f"O aluno pediu o artigo {rotulo} do {nome}. Você NÃO tem o texto literal "
                        f"dele aqui; diga isso em uma frase e explique o que o artigo prevê com base "
                        f"nas notas conferidas abaixo (tópico {topico.titulo}), sem inventar a "
                        f"redação. Use o quadro para a pena e os elementos.\n{notas}"))
            return Saida(fala=f"Não tenho o artigo {rotulo} do {nome} no material.")
        self.caderno.anotar_evento("artigo", ref=f"{a.artigo['art'].replace('Art.', 'art.')} do "
                                                  f"{NOME_LEI.get(lei, lei)}")
        fala, quadro = self.leis.apresentar(a)
        return Saida(fala=fala, quadro=quadro)

    def _comecar(self, p: Pedido, texto: str) -> Saida:
        log.info("pedido de estudo: %s", p)
        if p.tipo in _CONSULTAS:
            return self._consulta(p, texto)
        if p.tipo == "aprender":
            return self._aula_que_falta(p.alvo, texto)
        if p.tipo == "aula":
            return self._abrir_aula(p)
        if p.trilha is not None and p.tipo in ("questoes", "simulado"):
            itens, titulo = self._escolher_da_trilha(p)
            if not itens:
                return Saida(fala="Não achei questões para isso na trilha.")
            modo = "simulado" if p.tipo == "simulado" else "treino"
            self.sessao = Sessao(itens, modo, titulo, self.caderno)
            return self.sessao.abrir()
        if self.material.vazio and p.trilha is None:
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
            itens, modo = self._escolher_revisao(p), "revisao"
            titulo = "Revisão" + (f" de {p.trilha.materia}" if p.trilha else "")
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

    # ---------- autoestudo ----------
    def _autoestudo(self, comando: str, texto: str) -> Saida:
        a = self.autoestudo
        if comando == "pausar":
            return Saida(fala=a.pausar())
        if comando == "retomar":
            return Saida(fala=a.retomar())
        if comando == "pedir":
            fala, _ = a.pedir(texto)
            return Saida(fala=fala)
        if comando in ("hoje", "semana"):
            fala, quadro = a.resumo(0 if comando == "hoje" else 6)
            return Saida(fala=fala, quadro=quadro)
        return Saida(fala=a.status())

    def _aula_que_falta(self, alvo: TopicoPlano, texto: str) -> Saida:
        """Pediu aula de um tópico do edital que ainda não tem conteúdo: o autoestudo
        estuda primeiro; enquanto isso, o cérebro dá uma explicação inicial."""
        if self.autoestudo is not None:
            aviso, _ = self.autoestudo.pedir(alvo.titulo)
            combinado = ("Diga em uma frase que você ainda não tem a aula completa desse tópico e que vai "
                         "estudá-lo agora sozinho (pela lei e pela internet, conferindo com outro modelo) e "
                         "avisa quando a aula estiver pronta.")
        else:
            aviso = ""
            combinado = "Diga em uma frase que esse tópico ainda não tem aula pronta na trilha."
        return Saida(contexto=(
            f"O aluno pediu aula de \"{alvo.titulo}\" ({alvo.materia.materia}, concurso "
            f"{alvo.materia.plano.concurso}, banca {alvo.materia.plano.banca}). {combinado} Depois, "
            "explique o essencial em até 6 frases curtas, com cuidado: se não tiver certeza de um "
            "número (pena, prazo, artigo), não cite o número. Termine com uma pergunta curta."
            + (f"\n(O autoestudo respondeu: {aviso})" if aviso else "")))

    def _abrir_aula(self, p: Pedido) -> Saida:
        tr = p.trilha
        prog = self.progresso(tr)
        topico = p.topico
        if topico is None:                       # "vamos estudar penal": o tópico recomendado
            passo = prog.proximo_passo()
            topico = passo.topico or tr.topicos[0]
        texto_lei = ""
        for lei, ini, fim in topico.faixas()[:1]:
            if ini == fim or ini[0] == fim[0]:
                a = self.leis.artigo(lei, (ini[0], ini[1]))
                if a:
                    texto_lei = self.leis.texto(a, 700)
        self.aula = Aula(tr, topico, self.caderno, tr.itens_do_topico(topico, self.material.bancos),
                         texto_lei, prog)
        self.caderno.anotar_evento("aula", t=self.aula.chave, p=self.aula.k + 1, fim=False)
        return self.aula.abrir()

    def encerrar(self) -> Saida | None:
        if self.aula is not None:
            saida = self.aula.pausar()
            self.aula = None
            return saida
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
            if not r.item.real:
                fonte = f"Trilha {fonte.split(' ')[1] if ' ' in fonte else ''}".strip()
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
        if self.aula is not None and self.aula.sessao is None:
            from ..stt.groq_whisper import DICA_PENAL
            return DICA_PENAL
        sessao = self.sessao or (self.aula.sessao if self.aula else None)
        if sessao is not None and sessao.espera_resposta_curta:
            from ..stt.groq_whisper import DICA_TREINO
            return DICA_TREINO
        return None

    def contexto_da_lei(self, pergunta: str, anotar: bool = True) -> str:
        """O que o cérebro recebe junto com uma pergunta livre: as notas da trilha mais
        ligada à pergunta (se for sobre um tópico dela) e os trechos oficiais da lei.
        `anotar=False`: só consulta (o cérebro que decide anota depois, se era dúvida)."""
        partes = []
        if self.aula is None and self.sessao is None:
            self._talvez_recarregar()
        tr, topico = self._trilha_da_fala(pergunta)
        if tr is not None:
            notas, topicos = tr.notas(pergunta)
            if notas:
                partes.append(notas)
                if anotar:
                    self.caderno.anotar_evento("duvida", t=f"{tr.id}:{topicos[0].id}",
                                               q=pergunta.strip()[:120])
        trechos = self.leis.trechos(pergunta)
        if trechos:
            partes.append(trechos)
        return "\n\n".join(partes)

    def anotar_duvida(self, pergunta: str) -> None:
        """A pergunta livre foi sobre um tópico da trilha: conta como dúvida no diário."""
        tr, _ = self._trilha_da_fala(pergunta)
        if tr is not None:
            notas, topicos = tr.notas(pergunta)
            if notas and topicos:
                self.caderno.anotar_evento("duvida", t=f"{tr.id}:{topicos[0].id}",
                                           q=pergunta.strip()[:120])

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
            s.get("minutos", 0) for s in sessoes if s.get("tipo") not in ("lacunas", "fixacao"))
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

    def passos(self, n: int = 2) -> list[tuple[Trilha, object]]:
        """Os próximos passos das trilhas, do mais urgente (aula pela metade, tópico fraco)
        ao menos; no empate, a matéria que pesa mais na prova (a ordem do plano)."""
        peso = {}
        for i, plano in enumerate(self.planos):
            for m in plano.materias:
                peso.setdefault(m.trilha, m.peso * (1.0 if i == 0 else 0.5))
        lista = []
        for i, tr in enumerate(self.trilhas):
            passo = self.progresso(tr).proximo_passo()
            if passo.acao == "simulado" and len(self.trilhas) > 1:
                continue
            lista.append((_ORDEM_PASSO.get(passo.acao, 9), -peso.get(tr.id, 0), i, tr, passo))
        lista.sort(key=lambda x: x[:3])
        return [(tr, passo) for *_, tr, passo in lista[:n]]

    def aprendizado_geral(self) -> Saida:
        """"O que eu já aprendi?" sem dizer a matéria: todas as trilhas em que ele mexeu."""
        com_estudo = []
        for tr in self.trilhas:
            prog = self.progresso(tr)
            sits = prog.situacoes()
            if any(s.estado != "novo" for s in sits):
                com_estudo.append((tr, prog, sits))
        if len(com_estudo) == 1 or (not com_estudo and len(self.trilhas) == 1):
            tr, prog = (com_estudo[0][0], com_estudo[0][1]) if com_estudo else \
                (self.trilhas[0], self.progresso(self.trilhas[0]))
            fala, quadro = prog.resumo_aprendizado()
            return Saida(fala=fala, quadro=quadro)
        if not com_estudo:
            plano = self.plano()
            return Saida(fala="Você ainda não começou nenhuma trilha. " + plano.fala, quadro=plano.quadro)
        falas, linhas = [], ["# O que você já sabe"]
        for tr, prog, sits in com_estudo:
            c = prog.contagem(sits)
            linhas.append(f"- {tr.materia}: domina {c['dominado']}, praticando "
                          f"{c['praticando'] + c['comecou']}, reforçar {c['fraco']}, faltam {c['novo']}")
            partes = []
            if c["dominado"]:
                partes.append(f"domina {plural(c['dominado'], 'tópico', 'tópicos')}")
            pratica = c["praticando"] + c["comecou"] + c["esfriando"]
            if pratica:
                partes.append(f"está praticando {plural(pratica, 'tópico', 'tópicos')}")
            if c["fraco"]:
                partes.append(f"precisa reforçar {c['fraco']}")
            falas.append(f"em {tr.materia}, " + _lista(partes))
        fala = "Você já estudou " + plural(len(com_estudo), "matéria", "matérias") + ": " + \
            "; ".join(falas) + ". Para os detalhes, diga: o que eu já aprendi de e o nome da matéria."
        return Saida(fala=fala, quadro="\n".join(linhas))

    def plano(self) -> Saida:
        _s, _e, por = self._ultimos(14)
        vencidos = len(self.caderno.vencidos())
        linhas, falas = ["# Plano de hoje"], []
        if vencidos:
            linhas.append(f"- Revisar {plural(vencidos, 'item que venceu', 'itens que venceram')}"
                          " (diga: revisa meus erros)")
            falas.append(f"revisar {plural(vencidos, 'item que venceu', 'itens que venceram')} hoje")
        for tr, passo in self.passos(2):
            if passo.acao != "revisao":
                linhas.append(f"- {tr.materia}: {passo.motivo} (diga: {passo.comando})")
                falas.append(f"em {tr.materia}, {passo.motivo[0].lower()}{passo.motivo[1:].rstrip('.')}")
        trecho = self._proximo_trecho_de_lei()
        if trecho:
            linhas.append(f"- Lei seca: {trecho[0]}, {trecho[1]} (diga: lacunas do {trecho[0]})")
            falas.append(f"a lei seca: {trecho[0]}, {trecho[1].split(' · ')[-1]}")
        fracas = sorted(((m, a, e) for m, (_, a, e) in por.items() if a + e >= 3
                         and m not in [t.materia for t in self.trilhas]),
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
        tr, _ = self._trilha_da_fala(materia)
        if tr is not None and (not self.planilha or nome == materia):
            nome = tr.materia                       # "penal" -> "Direito Penal"
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
