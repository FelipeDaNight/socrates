"""O que o Sócrates precisa saber do "agora" a cada pergunta.

O modelo foi treinado até 2024 e não tem relógio: sem isto, ele não sabe
que dia é hoje nem onde você está.
"""

from __future__ import annotations

from datetime import datetime

DIAS = ["segunda-feira", "terça-feira", "quarta-feira", "quinta-feira",
        "sexta-feira", "sábado", "domingo"]
MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]

INSTRUCAO_PESQUISA = """Seu conhecimento vai só até 2024, mas você PODE pesquisar na internet.
Se a pergunta depender de algo que pode ter mudado depois disso (notícias, preços,
cotações, clima, resultados de jogos, editais e datas de concursos, quem ocupa um cargo,
lançamentos, horários de funcionamento), responda APENAS com a palavra PESQUISAR e mais nada.
Para matéria de estudo que não muda (gramática, história, matemática, leis antigas), responda direto."""

INSTRUCAO_SEM_PESQUISA = """Seu conhecimento vai só até 2024 e você NÃO tem acesso à internet.
Se perguntarem algo atual (notícias, preços, clima, editais), diga com franqueza que não
tem como saber e sugira onde a pessoa pode conferir."""


def agora(fuso: str = "America/Sao_Paulo") -> datetime:
    try:
        from zoneinfo import ZoneInfo
        return datetime.now(ZoneInfo(fuso))
    except Exception:   # Windows sem o pacote tzdata: usa o relógio do PC
        return datetime.now()


def data_por_extenso(momento: datetime) -> str:
    return (f"{DIAS[momento.weekday()]}, {momento.day} de {MESES[momento.month - 1]} "
            f"de {momento.year}, {momento.hour:02d}:{momento.minute:02d}")


def montar(local: str | None, pesquisa: bool, momento: datetime | None = None,
           acoes: bool = False) -> str:
    momento = momento or agora()
    partes = [f"Agora é {data_por_extenso(momento)} (horário de Brasília)."]
    if local:
        partes.append(f"O aluno mora em {local}. Use esse lugar quando ele perguntar "
                      "sobre clima ou algo \"aqui\" sem dizer a cidade.")
    partes.append(INSTRUCAO_PESQUISA if pesquisa else INSTRUCAO_SEM_PESQUISA)
    if acoes:
        from ..llm.acoes import INSTRUCAO_MARCADOR
        partes.append(INSTRUCAO_MARCADOR)
    return "\n".join(partes)
