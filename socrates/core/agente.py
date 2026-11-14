"""O cérebro que decide.

Antes, cada fala passava por uma fila de regras fixas e a primeira que encaixava
decidia ("bloco de notas + artigo 7" virava só "mostrar o artigo"). Agora a fala
vai ao modelo junto com uma caixa de ferramentas, e ELE decide o que fazer,
combinando várias se precisar:

  "abre o bloco de notas e coloca o artigo 7 do CTB"   -> ler_lei(CTB, 7, bloco_de_notas)
  "e os primeiros artigos do Código Penal?"           -> ler_lei(CP, 1-5): texto OFICIAL
  "resume o 1º capítulo de Vidas Secas; se não tiver, aprenda"
                                                      -> pesquisar_internet + aprender_assunto
  "minha prova é dia 15 de março"                     -> lembrar(...)
  "não, eu queria que você escrevesse"                -> faz certo + anotar_licao(...)

As regras do tutor continuam valendo no meio de um treino ou de uma aula ("certo",
"letra B", "próximo") e como reserva quando a internet ou o limite grátis falham.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from .. import ferramentas
from ..ferramentas import Ferramenta
from .orquestrador import compactar

log = logging.getLogger("socrates.agente")

# ---------------------------------------------------------------- o jeito de pensar

INSTRUCAO = """Você é o {nome}, assistente de estudo que conversa por VOZ, em português do Brasil,
com um aluno que estuda para concursos (PRF e Bombeiros de Goiás). Você não é um menu de
comandos: você entende o pedido, DECIDE sozinho e AGE com as ferramentas.

Como decidir:
- Use as ferramentas para agir. Pode usar várias em sequência na mesma resposta
  (ex.: ler_lei com destino bloco_de_notas para "abre o bloco de notas e coloca o artigo 7").
- Aja primeiro. Pergunte só se o pedido for realmente ambíguo e errar for caro. Nunca pergunte
  "resumir ou detalhar?" nem "posso dividir em partes?": escolha o melhor e faça.
- Falas curtas ("vai", "pode", "sim", "continua", "os próximos", "e o 7?") continuam o que você
  acabou de fazer ou de oferecer na conversa.
- Pergunta sobre o que você consegue fazer ("você consegue ver o Claude?") é pedido para fazer,
  se der para fazer agora.
- "Cloud", "Claudio", "Cláudia" e "Clode" na transcrição são o Claude, o app onde o programador
  do Sócrates trabalha.
- Para saber se um programa está aberto use janelas_abertas; para ler o que está nele use
  mostrar_janela e depois ver_tela passando a pergunta exata do aluno.
- Pedido de estudo guiado (aula de um tópico, questões, simulado, revisão, lacunas, mapa, plano
  do dia, desempenho, o que estudou) vai para estudar, com o pedido em palavras simples.

Verdade:
- Texto de lei, número de artigo, pena e prazo SÓ com ler_lei (texto oficial) ou com as notas do
  seu material. NUNCA de memória. Se o aluno te corrigir sobre lei, confira com ler_lei antes de
  concordar ou discordar.
- Matéria de concurso: use as notas do material (vêm junto quando existem) ou buscar_no_material.
- Livro, obra, fato atual ou algo que você não sabe com segurança: pesquisar_internet.
  Se mesmo assim não souber, diga com franqueza.

Memória e evolução:
- Fato durável sobre o aluno (data da prova, dificuldade, preferência, objetivo) -> lembrar.
- Se o aluno te corrigir ou reclamar do seu jeito, faça o que ele quer E registre uma lição curta
  com anotar_licao, para não repetir o erro.
- Assunto que você não tem no material: responda o que der e chame aprender_assunto para
  estudá-lo a fundo sozinho.
- Se faltar uma capacidade sua, registre com sugerir_melhoria (vai para o Claude depois).

Fala (sua resposta vira áudio):
- Frases curtas e naturais, sem markdown, no máximo 4 ou 5 frases faladas, salvo se ele pedir mais.
- Quadro branco: escreva entre [QUADRO] e [/QUADRO] (título com #, itens com -, fórmula entre
  $$ $$), até 10 linhas, quando ajudar a ver. ler_lei já põe a lei no quadro: não repita o texto,
  comente o essencial.
- Depois de uma ação, confirme em uma frase. Nunca diga que fez algo sem ter usado a ferramenta.
- Se uma ferramenta responder AGUARDANDO CONFIRMAÇÃO, pergunte em uma frase se pode fazer."""

MODO_PROVA = """Modo atual: PROVA. Se ele pedir para ser testado num assunto sem questões no
material, faça UMA pergunta por vez no estilo da banca (questão no quadro) e espere a resposta."""

NOTAS = ("Notas do seu material ligadas a esta fala (conferidas; use-as se ajudarem e cite o "
         "artigo):\n")

HISTORICO = 8
CORTE_NOTAS = 3000
ESPERA_NO_LIMITE = 3.0     # no limite grátis, espera no máximo isso e passa para o próximo cérebro

# Fala que pode precisar do computador. Sem isso, as ferramentas do PC ficam de fora do
# pedido (o plano grátis do Groq conta cada token: são ~2 mil a menos por pergunta).
_PC = re.compile(
    r"\b(abr\w*|fech\w*|bloco de notas|notepad|word|excel|calculadora|tela|janela\w*|programa\w*"
    r"|aplicativo\w*|app|site\w*|navegador|chrome|edge|youtube|spotify|music\w*|som|volume"
    r"|timer|cronometro|pomodoro|alarme|anot\w*|copi\w*|col\w*|area de transferencia|pasta\w*"
    r"|visor|cor|atualiz\w*|bloque\w*|claude|cloud|claudio|claudia|clode|chat|print|olh\w*"
    r"|ve|ver|vendo|vê|escrev\w*|digit\w*|mand\w*|toc\w*|pausa\w*|proxima|computador|pc)\b")

# ---------------------------------------------------------------- lei: nome e artigos

_LEIS = [  # (o que o aluno fala, sigla no registro de leis)
    (r"cpp|codigo de processo penal|processo penal", "CPP"),
    (r"cpm|codigo penal militar", "CPM"),
    (r"ctb|codigo de transito|codigo brasileiro de transito|transito|9 ?503", "CTB"),
    (r"cp|codigo penal|penal", "CP"),
    (r"cf|crfb|constituicao|carta magna", "CF"),
    (r"eca|estatuto da crianca", "ECA"),
    (r"lei de drogas|drogas|antidrogas", "L11343"),
    (r"estatuto do desarmamento|desarmamento", "L10826"),
    (r"maria da penha|violencia domestica", "L11340"),
    (r"crimes hediondos|hediondos?", "L8072"),
    (r"tortura", "L9455"),
    (r"crimes ambientais|meio ambiente", "L9605"),
    (r"abuso de autoridade", "L13869"),
    (r"organizac\w* criminos\w*|orcrim", "L12850"),
    (r"improbidade", "L8429"),
    (r"juizados especiais|juizados", "L9099"),
    (r"prisao temporaria", "L7960"),
    (r"estatuto do servidor|servidores publicos federais|regime juridico", "L8112"),
    (r"processo administrativo", "L9784"),
    (r"licitac\w*|contratos administrativos", "L14133"),
    (r"acesso a informacao|lai", "L12527"),
    (r"conflito de interesses", "L12813"),
    (r"susp|sistema unico de seguranca publica", "L13675"),
    (r"identificacao criminal", "L12037"),
    (r"antifaccao|faccoes criminosas", "L15358"),
    (r"carreira (?:de )?(?:policial )?rodoviari\w*", "L9654"),
    (r"codigo de etica", "D1171"),
    (r"pacto de sao jose|convencao americana", "D678"),
]
_LEIS_RX = [(re.compile(rf"\b(?:{rx})\b"), sigla) for rx, sigla in _LEIS]
MAX_ARTIGOS = 12
CORTE_ARTIGO = 1800          # por artigo, no que vai para o cérebro
CORTE_TOTAL = 7000
CORTE_QUADRO = 1100


def _norm(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ,;.\-]", " ", t)).strip()


def sigla_da_lei(texto: str, registro: dict | None = None) -> str | None:
    """"Código Penal" -> CP; "lei 11.343" -> L11343; "CF" -> CF."""
    registro = registro or {}
    bruto = (texto or "").strip()
    if bruto.upper() in registro or bruto.upper() in ("CTB", "CP", "CPP", "CF", "L14133"):
        return bruto.upper()
    t = _norm(bruto).replace(".", "")
    m = re.search(r"\b(?:(lei|l|decreto|d)\s*(?:n\s*)?)?(\d{3,5})(?:\s*(?:de|/)\s*\d{2,4})?\b", t)
    if m and (m.group(1) or not any(rx.search(t) for rx, _ in _LEIS_RX)):
        num = m.group(2)
        tipo = "D" if (m.group(1) or "").startswith("d") else "L"
        if f"{tipo}{num}" in registro:
            return f"{tipo}{num}"
        if num == "9503":
            return "CTB"
    for rx, sigla in _LEIS_RX:
        if rx.search(t):
            return sigla
    return None


def faixas_de_artigos(texto: str) -> list[tuple[tuple[int, str], tuple[int, str]]]:
    """"7" | "7-A" | "1-10" | "1 a 10" | "5, 7 e 121-A" | "primeiros" | "primeiros 10"
    -> [((ini, sufixo), (fim, sufixo))]."""
    t = _norm(texto).replace("º", "")
    t = re.sub(r"\b(?:arts?|artigos?)\b\.?", " ", t)
    t = re.sub(r"\b(?:do|da|o|os|as)\b", " ", t)
    t = re.sub(r"(\d)o\b", r"\1", t)                      # 7o (7º sem acento) -> 7
    t = re.sub(r"\s+", " ", t).strip()
    m = re.search(r"\bprimeir\w*(?:\s+(\d{1,3}))?", t)
    if m:
        return [((1, ""), (int(m.group(1) or 5), "Z"))]
    faixas = []
    for parte in re.split(r"\s*(?:,|;|\be\b)\s*", t):
        parte = parte.strip(" .")
        if not parte:
            continue
        r = re.fullmatch(r"(\d{1,4})(?:\s*-\s*([a-z]))?\s*(?:-|\ba\b|\bao\b|\bate\b)\s*"
                         r"(\d{1,4})(?:\s*-\s*([a-z]))?", parte)
        if r:
            ini = (int(r.group(1)), (r.group(2) or "").upper())
            fim = (int(r.group(3)), (r.group(4) or "Z").upper())
            if fim[0] >= ini[0]:
                faixas.append((ini, fim))
            continue
        r = re.fullmatch(r"(\d{1,4})\s*(?:-?\s*([a-z]))?", parte)
        if r:
            n = (int(r.group(1)), (r.group(2) or "").upper())
            faixas.append((n, n))
    return faixas


@dataclass
class Trecho:
    rotulo: str            # "Art. 7º"
    texto: str             # texto em vigor, sem as notas de redação
    numero: tuple[int, str]
    achado: object = None  # da lei seca do app (tem resumo e ficha), se veio de lá
    mudancas: list = field(default_factory=list)


class LeitorDeLei:
    """Texto oficial: primeiro a lei seca do app (instantâneo), depois a lei inteira do
    Planalto guardada pela Biblioteca (cache de 7 dias)."""

    def __init__(self, leis_locais=None, biblioteca=None):
        self.locais = leis_locais          # estudo.lei.Leis
        self._biblioteca = biblioteca      # estudo.leitor_lei.Biblioteca (ou fábrica)

    @property
    def biblioteca(self):
        if callable(self._biblioteca) and not hasattr(self._biblioteca, "artigos"):
            self._biblioteca = self._biblioteca()
        return self._biblioteca

    def nome(self, sigla: str) -> str:
        from ..estudo.treino import NOME_LEI
        if sigla in NOME_LEI:
            return NOME_LEI[sigla]
        b = self.biblioteca
        return b.nome(sigla) if b is not None else sigla

    def registro(self) -> dict:
        b = self.biblioteca
        return getattr(b, "registro", {}) if b is not None else {}

    def _locais(self, sigla: str) -> dict:
        if self.locais is None:
            return {}
        from ..estudo.lei import _numero_do_rotulo
        saida = {}
        for a in self.locais.todos(sigla):
            num = _numero_do_rotulo(a.artigo.get("art", ""))
            if num is not None:
                saida[num] = a
        return saida

    def _guardada(self, sigla: str) -> dict:
        """A lei do Planalto já guardada no PC (o autoestudo baixa as do edital)."""
        b = self.biblioteca
        try:
            return (b.em_cache(sigla) or {}) if b is not None and hasattr(b, "em_cache") else {}
        except Exception:
            return {}

    def ler(self, sigla: str, faixas) -> tuple[list[Trecho], str]:
        """(trechos, aviso). Aviso diz o que faltou.

        Ordem: a lei do Planalto já guardada (texto puro, na hora) > a lei seca do app
        (na hora, às vezes com anotações de estudo) > baixar a lei do Planalto."""
        guardada = self._guardada(sigla)
        if guardada:
            trechos, aviso = self._da_biblioteca(guardada, faixas)
            if trechos and not aviso.startswith("Não achei"):
                locais = self._locais(sigla)
                for t in trechos:                     # a ficha (pontos, multa) do quadro
                    t.achado = locais.get(t.numero)
                return trechos, aviso
        return self._ler(sigla, faixas)

    @staticmethod
    def _da_biblioteca(artigos: dict, faixas) -> tuple[list[Trecho], str]:
        escolhidos, faltou = {}, []
        for ini, fim in faixas:
            achados = [a for a in artigos.values() if ini <= (a.numero, a.sufixo) <= fim]
            if not achados:
                faltou.append(_rotulo_faixa(ini, fim))
            for a in achados:
                escolhidos[(a.numero, a.sufixo)] = Trecho(
                    a.rotulo, a.sem_notas(), (a.numero, a.sufixo),
                    mudancas=[f"{l} ({ano})" for l, ano in a.mudancas])
        trechos = [escolhidos[k] for k in sorted(escolhidos)][:MAX_ARTIGOS]
        aviso = f"Não achei: {', '.join(faltou)}." if faltou else ""
        if len(escolhidos) > MAX_ARTIGOS:
            aviso = (aviso + f" Mostrei só os {MAX_ARTIGOS} primeiros.").strip()
        return trechos, aviso

    def _ler(self, sigla: str, faixas) -> tuple[list[Trecho], str]:
        locais = self._locais(sigla)
        escolhidos: dict[tuple[int, str], Trecho] = {}
        faltou = []
        planalto = None
        for ini, fim in faixas:
            daqui = sorted(k for k in locais if ini <= k <= fim)
            esperados = set(range(ini[0], fim[0] + 1)) if ini != fim else {ini[0]}
            completo = {k[0] for k in daqui} >= esperados if ini != fim else ini in locais
            if completo:
                for k in daqui:
                    a = locais[k]
                    escolhidos[k] = Trecho(a.artigo.get("art", f"Art. {k[0]}"), _texto_local(a),
                                           k, achado=a, mudancas=list(a.artigo.get("mudou") or []))
                continue
            if planalto is None:
                try:
                    planalto = self.biblioteca.artigos(sigla) if self.biblioteca is not None else {}
                except Exception as e:          # sem internet e sem cópia guardada
                    log.warning("lei %s indisponível: %s", sigla, e)
                    planalto = {}
            de_la = sorted((a for a in planalto.values() if ini <= (a.numero, a.sufixo) <= fim),
                           key=lambda a: (a.numero, a.sufixo))
            if de_la:
                for a in de_la:
                    k = (a.numero, a.sufixo)
                    escolhidos.setdefault(k, Trecho(a.rotulo, a.sem_notas(), k,
                                                    mudancas=[f"{l} ({ano})" for l, ano in a.mudancas]))
            elif daqui:                          # só uma parte, mas é o que há
                for k in daqui:
                    a = locais[k]
                    escolhidos[k] = Trecho(a.artigo.get("art", ""), _texto_local(a), k, achado=a)
                faltou.append(_rotulo_faixa(ini, fim))
            else:
                faltou.append(_rotulo_faixa(ini, fim))
        trechos = [escolhidos[k] for k in sorted(escolhidos)][:MAX_ARTIGOS]
        aviso = f"Não achei: {', '.join(faltou)}." if faltou else ""
        if len(escolhidos) > MAX_ARTIGOS:
            aviso += f" Mostrei só os {MAX_ARTIGOS} primeiros."
        return trechos, aviso.strip()


def _texto_local(achado) -> str:
    """O texto da lei seca do app, um parágrafo (inciso, §) por linha."""
    return "\n".join(i["t"].strip() for i in achado.artigo.get("itens", [])
                     if i.get("k") in ("lei", "vet") and i.get("t", "").strip())


def _rotulo_faixa(ini, fim) -> str:
    a = f"{ini[0]}{'-' + ini[1] if ini[1] else ''}"
    if ini == fim:
        return f"art. {a}"
    b = f"{fim[0]}{'-' + fim[1] if fim[1] not in ('', 'Z') else ''}"
    return f"arts. {a} a {b}"


def quadro_de_trechos(nome: str, trechos: list[Trecho], leis_locais=None) -> str:
    from ..estudo.treino import _quadro_seguro
    unico = trechos[0].achado if len(trechos) == 1 else None
    if unico is not None and leis_locais is not None and (unico.artigo.get("ficha") or {}).get("natureza"):
        return leis_locais.apresentar(unico)[1]          # infração: pontos e multa no topo
    if len(trechos) == 1:
        t = trechos[0]
        linhas = [f"# {nome} · {t.rotulo}"]
        total = 0
        for l in t.texto.split("\n"):
            l = l.strip()
            if not l:
                continue
            if total + len(l) > CORTE_QUADRO:
                linhas.append(l[:max(0, CORTE_QUADRO - total)].rsplit(" ", 1)[0] + " (...)")
                break
            linhas.append(l)
            total += len(l)
        return _quadro_seguro("\n".join(linhas))
    primeiro, ultimo = trechos[0].rotulo, trechos[-1].rotulo.replace("Art.", "").strip()
    linhas = [f"# {nome} · {primeiro.replace('Art.', 'arts.')} a {ultimo}"]
    por = max(90, min(220, CORTE_QUADRO // len(trechos)))
    for t in trechos:
        corpo = re.sub(r"\s+", " ", t.texto).strip()
        corpo = re.sub(r"^Art\.\s*\S+\s*", "", corpo)
        if len(corpo) > por:
            corpo = corpo[:por].rsplit(" ", 1)[0] + "..."
        linhas.append(f"{t.rotulo} {corpo}")
    return _quadro_seguro("\n".join(linhas))


# ---------------------------------------------------------------- o resultado de um turno

@dataclass
class Resultado:
    texto: str = ""                  # o que falar (pode ter [QUADRO])
    saida: object = None             # o tutor assumiu (aula, treino, consulta)
    quadro: str | None = None        # quadro que uma ferramenta montou (a lei)
    ferramentas: list[str] = field(default_factory=list)
    resultados: list[str] = field(default_factory=list)   # o que cada ferramenta devolveu


# ---------------------------------------------------------------- o agente

class Agente:
    MAX_RODADAS = 5

    def __init__(self, cerebro, tutor=None, memorias=None, nome: str = "Sócrates",
                 contexto: Callable[[], str] | None = None, biblioteca=None,
                 acoes_pc: list[str] | None = None, executar_pc=None):
        if not hasattr(cerebro, "com_ferramentas"):
            raise TypeError("o agente precisa de um cérebro com com_ferramentas()")
        self.cerebro = cerebro
        self.tutor = tutor
        self.memorias = memorias
        self.nome = nome
        self.contexto = contexto
        self.leitor = LeitorDeLei(getattr(tutor, "leis", None), biblioteca or _biblioteca_padrao)
        self.acoes_pc = list(acoes_pc or [])
        self.executar_pc = executar_pc or ferramentas.executar
        self._turno = Resultado()
        self._ferramentas = self._montar()

    # ---------- caixa de ferramentas ----------
    def _montar(self) -> dict[str, Ferramenta]:
        f: dict[str, Ferramenta] = {}

        def reg(funcao, descricao, params=None, opcoes=None):
            f[funcao.__name__] = Ferramenta(funcao.__name__, descricao, funcao, False,
                                            params or {}, opcoes or {})

        reg(self.ler_lei,
            "Lê o texto OFICIAL de artigos de lei (CTB, Código Penal, CPP, Constituição, Lei de "
            "Drogas, 8.112, 14.133 e outras do edital) e mostra no quadro ou escreve no Bloco de "
            "Notas. Use sempre que pedirem artigos ou que a resposta depender da letra da lei.",
            {"lei": "Sigla ou nome: CTB, CP, CPP, CF, L11343, L8112, 'Lei de Drogas'...",
             "artigos": "'7', '121-A', '1-10', '5, 7 e 9' ou 'primeiros'"},
            {"destino": ["quadro", "bloco_de_notas"]})
        reg(self.buscar_no_material,
            "Busca nas suas trilhas conferidas (resumos, pegadinhas, novidades) e nos trechos de lei "
            "o que responde a uma dúvida de matéria de concurso.",
            {"pergunta": "A dúvida, em poucas palavras"})
        reg(self.estudar,
            "Estudo guiado com o tutor: aula de um tópico, questões reais da prova, simulado, revisão "
            "dos erros, lacunas da lei seca, mapa, plano do dia, desempenho, o que estudou, o que o "
            "autoestudo aprendeu. Ex.: 'me ensina prisão em flagrante', 'questões de crimes de "
            "trânsito', '10 questões da PRF', 'simulado da PRF', 'revisa meus erros', 'lacunas do "
            "CTB', 'meu mapa', 'o que eu estudo hoje', 'como estou indo', 'o que eu estudei hoje', "
            "'o que você aprendeu hoje'.",
            {"pedido": "O pedido em palavras simples, como nos exemplos"})
        reg(self.aprender_assunto,
            "Põe um assunto na frente da fila do seu autoestudo: você pesquisa na lei e na internet, "
            "confere com outro modelo e grava uma aula. Use quando pedirem para você aprender algo "
            "ou quando faltar material sobre um assunto.",
            {"assunto": "O assunto, curto (ex.: 'Vidas Secas, de Graciliano Ramos')"})
        reg(self.pesquisar_internet,
            "Pesquisa na internet: livros e obras, fatos atuais, notícias, editais, datas. "
            "Depois responda citando a fonte pelo nome.",
            {"pergunta": "O que pesquisar"})
        reg(self.lembrar,
            "Guarda para sempre um fato durável sobre o aluno (data da prova, dificuldades, "
            "preferências, objetivos, rotina).",
            {"fato": "O fato, numa frase curta"})
        reg(self.esquecer, "Apaga da sua memória o que o aluno pedir para esquecer.",
            {"assunto": "O que esquecer"})
        reg(self.anotar_licao,
            "Registra uma lição para você mesmo quando o aluno te corrige ou reclama do seu jeito "
            "(ex.: 'Quando ele pedir artigos, ler o texto oficial com ler_lei'). Vale para sempre.",
            {"licao": "A regra, curta, no imperativo"})
        reg(self.sugerir_melhoria,
            "Anota uma ideia de mudança no SEU código, para o Claude (seu programador) fazer depois. "
            "Use quando faltar uma capacidade ou algo seu falhar.",
            {"ideia": "A mudança, concreta"})
        return f

    def esquemas(self, com_pc: bool = True) -> list[dict]:
        meus = [f.esquema() for f in self._ferramentas.values()]
        if not com_pc:
            return meus
        pc = [ferramentas.REGISTRO[n].esquema() for n in self.acoes_pc if n in ferramentas.REGISTRO]
        return meus + pc

    def quer_pc(self, pedido: str, historico: list) -> bool:
        """A fala (ou a conversa logo antes) pode precisar de mexer no computador?"""
        from ..llm.acoes import _norm as norm_acao, pede_acao
        if not self.acoes_pc:
            return False
        if pede_acao(pedido) or _PC.search(norm_acao(pedido)):
            return True
        ultimo = next((m.get("content", "") for m in reversed(historico or [])
                       if m.get("role") == "user"), "")
        return bool(ultimo) and len(pedido.split()) <= 6 and bool(
            pede_acao(ultimo) or _PC.search(norm_acao(ultimo)))     # "e agora fecha", "de novo"

    # ---------- o turno ----------
    async def atender(self, pedido: str, historico: list | None = None,
                      modo: str = "explicar") -> Resultado:
        from ..llm.compativel_openai import ESPERA_LIMITE

        self._turno = Resultado()
        msgs = self.mensagens(pedido, historico or [], modo)
        esquemas = self.esquemas(com_pc=self.quer_pc(pedido, historico or []))
        marca = ESPERA_LIMITE.set(ESPERA_NO_LIMITE)
        try:
            texto = await self.cerebro.com_ferramentas(
                msgs, esquemas, self._executar, max_rodadas=self.MAX_RODADAS,
                parar=lambda: self._turno.saida is not None)
            texto = _limpar(texto)
            if self._turno.saida is None and self._sem_fechamento(texto):
                texto = await self._fechar(pedido, msgs)
        finally:
            ESPERA_LIMITE.reset(marca)
        self._turno.texto = texto
        self._anotar_duvida(pedido)
        log.info("agente: %r -> %s | %r", pedido[:100], ",".join(self._turno.ferramentas) or "-",
                 self._turno.texto[:400])
        return self._turno

    def _sem_fechamento(self, texto: str) -> bool:
        """O cérebro bateu no limite no meio (depois de agir) e devolveu o resultado cru de
        uma ferramenta, ou desistiu: falta a resposta para o aluno."""
        return texto.startswith("Fiz o que pude") or (bool(texto) and any(
            texto == r.strip() for r in self._turno.resultados))

    async def _fechar(self, pedido: str, msgs: list[dict]) -> str:
        """Pede só a resposta final (outro cérebro do rodízio, se preciso), com o que as
        ferramentas já devolveram. As ações NÃO são repetidas."""
        feito = "\n---\n".join(r[:1500] for r in self._turno.resultados)[-4000:]
        pedido_final = (f"(Você já usou as ferramentas {', '.join(self._turno.ferramentas)} para este "
                        f"pedido. Resultados:\n{feito}\n) Agora responda ao aluno, falando, em até 4 "
                        f"frases, sem repetir o texto da lei que já está no quadro. Pedido: {pedido}")
        conversa = [m for m in msgs[:-1]] + [{"role": "user", "content": pedido_final}]
        try:
            texto = _limpar("".join([p async for p in self.cerebro.responder(conversa)]))
        except Exception as e:
            log.warning("não consegui fechar a resposta: %s", e)
            texto = ""
        if texto:
            return texto
        if "ler_lei" in self._turno.ferramentas:
            return "Pronto, está no quadro." if self._turno.quadro else "Pronto, escrevi no Bloco de Notas."
        return "Pronto." if self._turno.ferramentas else ""

    def sistema(self, modo: str = "explicar") -> str:
        partes = [INSTRUCAO.format(nome=self.nome)]
        if modo == "testar":
            partes.append(MODO_PROVA)
        if self.contexto is not None:
            try:
                partes.append(self.contexto())
            except Exception:
                log.exception("contexto")
        m = self.memorias
        if m is not None:
            sobre = m.aluno.para_prompt("O que você sabe do aluno (memória de longo prazo):")
            licoes = m.licoes.para_prompt("Lições que você aprendeu com os próprios erros (siga):")
            partes += [p for p in (sobre, licoes) if p]
            pendentes = m.melhorias_pendentes()
            if pendentes:
                partes.append("Ideias de melhoria no seu código ainda não enviadas ao Claude (se "
                              "ele pedir, mande com pedir_ao_claude): "
                              + " | ".join(d["t"] for d in pendentes[-5:]))
        situacao = self.situacao()
        if situacao:
            partes.append(situacao)
        visto = ferramentas.texto_da_lembranca()
        if visto:
            partes.append(visto)
        return "\n\n".join(partes)

    def situacao(self) -> str:
        """O que está acontecendo no estudo agora (aula ou treino no meio)."""
        t = self.tutor
        if t is None:
            return ""
        aula = getattr(t, "aula", None)
        if aula is not None:
            return f"Aula em andamento: {aula.topico.titulo} ({aula.trilha.materia})."
        s = getattr(t, "sessao", None)
        if s is not None and s.atual is not None:
            q = re.sub(r"\s+", " ", s.atual.fala or "")[:300]
            return (f"Treino em andamento ({s.titulo}), questão {s.pos + 1} de {len(s.itens)}: {q}")
        return ""

    def mensagens(self, pedido: str, historico: list, modo: str = "explicar") -> list[dict]:
        conversa = []
        for m in compactar(list(historico)[-HISTORICO:]):
            if m.get("role") not in ("user", "assistant") or not (m.get("content") or "").strip():
                continue
            if conversa and conversa[-1]["role"] == m["role"]:      # dois avisos seguidos
                conversa[-1]["content"] += "\n" + m["content"]
            else:
                conversa.append({"role": m["role"], "content": m["content"]})
        if conversa and conversa[0]["role"] == "assistant":   # começa num aviso ou na saudação
            conversa.insert(0, {"role": "user", "content": "(começo da conversa)"})
        msgs = [{"role": "system", "content": self.sistema(modo)}, *conversa]
        notas = self._notas(pedido)
        if notas:
            msgs.append({"role": "system", "content": NOTAS + notas[:CORTE_NOTAS]})
        msgs.append({"role": "user", "content": pedido})
        return msgs

    def _notas(self, pedido: str) -> str:
        if self.tutor is None or not hasattr(self.tutor, "contexto_da_lei"):
            return ""
        try:
            return self.tutor.contexto_da_lei(pedido, anotar=False)
        except TypeError:                          # tutor antigo, sem o anotar
            return self.tutor.contexto_da_lei(pedido)
        except Exception:
            log.exception("notas do material")
            return ""

    def _anotar_duvida(self, pedido: str) -> None:
        """Pergunta livre sobre a matéria (sem aula nem treino): entra no diário."""
        if (self.tutor is None or self._turno.saida is not None
                or not hasattr(self.tutor, "anotar_duvida")
                or {"estudar", "lembrar", "esquecer"} & set(self._turno.ferramentas)):
            return
        try:
            self.tutor.anotar_duvida(pedido)
        except Exception:
            log.exception("diário")

    async def _executar(self, nome: str, args: dict) -> str:
        self._turno.ferramentas.append(nome)
        r = await self._rodar(nome, args)
        self._turno.resultados.append(r)
        return r

    async def _rodar(self, nome: str, args: dict) -> str:
        f = self._ferramentas.get(nome)
        if f is None:
            if nome not in self.acoes_pc:
                return f"Erro: a ferramenta {nome} não existe."
            return await asyncio.to_thread(self.executar_pc, nome, args or {})
        validos = set(inspect.signature(f.funcao).parameters)
        args = {k: v for k, v in (args or {}).items() if k in validos}
        try:
            r = f.funcao(**args)
            if inspect.isawaitable(r):
                r = await r
        except TypeError as e:
            return f"Erro nos argumentos de {nome}: {e}"
        except Exception as e:
            log.exception("ferramenta %s falhou", nome)
            return f"Erro em {nome}: {e}"
        log.info("ferramenta %s(%s) -> %s", nome, args, str(r)[:300])
        return str(r)

    # ---------- as ferramentas ----------
    async def ler_lei(self, lei: str, artigos: str, destino: str = "quadro") -> str:
        sigla = sigla_da_lei(lei, self.leitor.registro())
        if sigla is None:
            return (f"Erro: não conheço a lei '{lei}'. Conheço CTB, CP, CPP, CF e as leis do "
                    "edital (ex.: L11343, L8112, L14133).")
        faixas = faixas_de_artigos(str(artigos))
        if not faixas:
            return f"Erro: não entendi quais artigos ('{artigos}'). Ex.: '7', '1-10', '121-A'."
        trechos, aviso = await asyncio.to_thread(self.leitor.ler, sigla, faixas)
        nome = self.leitor.nome(sigla)
        if not trechos:
            return (f"Não tenho o texto oficial de {nome} ({artigos}) agora. {aviso} Diga isso ao "
                    "aluno; não cite o texto de memória.")
        self._anotar_leitura(sigla, nome, trechos)
        if destino == "bloco_de_notas":
            completo = "\n\n".join(t.texto for t in trechos)
            titulo = f"{sigla} {trechos[0].rotulo}" + (f" a {trechos[-1].rotulo}" if len(trechos) > 1 else "")
            feito = await asyncio.to_thread(self.executar_pc, "escrever_no_bloco_de_notas",
                                            {"texto": f"{nome}\n\n{completo}", "titulo": titulo})
            onde = f"Resultado do Bloco de Notas: {feito}"
        else:
            self._turno.quadro = quadro_de_trechos(nome, trechos, self.leitor.locais)
            onde = "Já está no quadro do aluno: não leia tudo, comente o essencial."
        partes, total = [], 0
        for t in trechos:
            corpo = t.texto if len(t.texto) <= CORTE_ARTIGO else t.texto[:CORTE_ARTIGO] + " [...]"
            if t.mudancas:
                corpo += f" (alterado por: {', '.join(map(str, t.mudancas[:3]))})"
            if total + len(corpo) > CORTE_TOTAL:
                partes.append("[... os demais artigos foram cortados aqui]")
                break
            partes.append(corpo)
            total += len(corpo)
        return (f"Texto oficial em vigor ({nome}):\n" + "\n\n".join(partes) +
                f"\n\n{onde} {aviso}".rstrip())

    def _anotar_leitura(self, sigla: str, nome: str, trechos: list[Trecho]) -> None:
        caderno = getattr(self.tutor, "caderno", None)
        if caderno is None:
            return
        try:
            ref = trechos[0].rotulo.replace("Art.", "art.") + (
                f" a {trechos[-1].rotulo.replace('Art.', '').strip()}" if len(trechos) > 1 else "")
            caderno.anotar_evento("artigo", ref=f"{ref} do {nome}")
        except Exception:
            log.exception("caderno")

    def buscar_no_material(self, pergunta: str) -> str:
        notas = self._notas(pergunta)
        return notas[:CORTE_NOTAS] if notas else "Nada no seu material sobre isso."

    def estudar(self, pedido: str) -> str:
        if self.tutor is None:
            return "O estudo guiado não está carregado (falta o material)."
        saida = self.tutor.atender(pedido)
        if saida is None:
            return ("O tutor não reconheceu esse pedido. Use um dos jeitos dos exemplos "
                    "(ex.: 'me ensina <tópico>', 'questões de <assunto>') ou responda você mesmo.")
        self._turno.saida = saida
        return "FEITO: o tutor assumiu e vai falar com o aluno."

    def aprender_assunto(self, assunto: str) -> str:
        auto = getattr(self.tutor, "autoestudo", None)
        if auto is None:
            return "Meu autoestudo está desligado: não dá para estudar sozinho agora."
        if hasattr(auto, "pedir_assunto"):
            fala, _ = auto.pedir_assunto(assunto)
        else:
            fala, _ = auto.pedir(f"aprende sobre {assunto}")
        return fala

    async def pesquisar_internet(self, pergunta: str) -> str:
        if getattr(self.cerebro, "pesquisa_ok", False):
            from ..llm.base import ErroPesquisa
            from ..llm.pesquisa import INSTRUCAO as INSTRUCAO_PESQUISA, limpar_resposta
            msgs = [{"role": "system", "content": INSTRUCAO_PESQUISA},
                    {"role": "user", "content": pergunta}]
            try:
                return limpar_resposta(await self.cerebro.pesquisar(msgs)) or "A busca não trouxe nada."
            except ErroPesquisa as e:
                log.warning("pesquisa embutida falhou: %s", e)
        from ..ferramentas.busca import pesquisar_na_internet
        return await asyncio.to_thread(pesquisar_na_internet, pergunta)

    def lembrar(self, fato: str) -> str:
        if self.memorias is None:
            return "Minha memória de longo prazo está desligada."
        novo = self.memorias.aluno.adicionar(fato)
        return "Guardado na memória." if novo else "Isso eu já sabia (atualizei a data)."

    def esquecer(self, assunto: str) -> str:
        if self.memorias is None:
            return "Minha memória de longo prazo está desligada."
        fora = self.memorias.aluno.remover(assunto)
        return ("Esqueci: " + " | ".join(fora)) if fora else "Não achei isso na memória."

    def anotar_licao(self, licao: str) -> str:
        if self.memorias is None:
            return "Sem memória para lições."
        self.memorias.licoes.adicionar(licao, origem="conversa")
        return "Lição registrada."

    def sugerir_melhoria(self, ideia: str) -> str:
        if self.memorias is None:
            return "Sem memória para ideias."
        self.memorias.melhorias.adicionar(ideia, status="nova", origem="conversa")
        return "Ideia anotada para o Claude."


def _biblioteca_padrao():
    from ..estudo.leitor_lei import Biblioteca
    from ..estudo.plano import carregar_leis
    return Biblioteca(carregar_leis())


def _limpar(texto: str) -> str:
    texto = (texto or "").strip()
    if texto.upper().startswith("FEITO:"):
        return ""
    return texto.replace(" ", " ").replace(" ", " ")
