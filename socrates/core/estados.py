from enum import Enum


class Estado(Enum):
    DORMINDO = "dormindo"   # esperando a palavra "Sócrates"
    OUVINDO = "ouvindo"     # gravando o que você fala
    PENSANDO = "pensando"   # cérebro gerando a resposta
    FALANDO = "falando"     # respondendo em voz


# Para onde cada estado pode ir. Qualquer outra transição é um bug.
TRANSICOES: dict[Estado, set[Estado]] = {
    Estado.DORMINDO: {Estado.OUVINDO},
    Estado.OUVINDO: {Estado.PENSANDO, Estado.DORMINDO},
    Estado.PENSANDO: {Estado.FALANDO, Estado.DORMINDO},
    Estado.FALANDO: {Estado.DORMINDO, Estado.OUVINDO},  # OUVINDO = interrupção
}


class TransicaoInvalida(Exception):
    pass
