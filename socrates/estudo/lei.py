"""Lei seca: achar o artigo pedido e os trechos oficiais que respondem uma dúvida.

  "Sócrates, lê o artigo 165 do CTB"  -> texto do artigo no quadro + resumo falado
  "Qual a pena de embriaguez ao volante?" -> o cérebro recebe o Art. 306 do CTB junto
                                              com a pergunta, e responde com base nele
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from .respostas import norm
from .treino import NOME_LEI, _cortar, _quadro_seguro

# ordem importa: "código de processo penal" antes de "código penal"
_LEIS = [
    ("CPP", re.compile(r"\b(cpp|codigo de processo penal|processo penal)\b")),
    ("CTB", re.compile(r"\b(ctb|codigo de transito|transito brasileiro|lei 9 ?503)\b")),
    ("CP", re.compile(r"\b(cp|codigo penal)\b")),
    ("L14133", re.compile(r"\b(14 ?133|lei de licitac\w*|licitac\w*|nova lei de licitacoes)\b")),
]
_ARTIGO = re.compile(r"\bart(?:igo|\.)?s?\s*(\d{1,3})\s*[º°o]?(?:\s*-\s*([A-Za-z])\b)?", re.I)
_ROTULO = re.compile(r"Art\.\s*(\d+)\s*º?(?:-([A-Z]))?")

# Palavras que fazem o assunto ser trânsito (para buscar no CTB sem dizer "CTB")
_TRANSITO = re.compile(r"\b(transito|multa|infracao|infracoes|habilitacao|cnh|condutor|veiculo"
                       r"|embriaguez|alcool|bafometro|velocidade|rodovia|pedestre|ciclista"
                       r"|estacionar|estacionamento|ultrapassa\w*|placa|licenciamento|contran"
                       r"|detran|pontos na carteira|suspensao do direito de dirigir|cassacao"
                       r"|cinto|capacete|farol|pista|acostamento)\b")
_VAZIAS = {"qual", "quais", "como", "quando", "onde", "porque", "sobre", "segundo", "artigo",
           "lei", "codigo", "transito", "brasileiro", "penal", "pena", "para", "pelo", "pela",
           "esta", "isso", "essa", "esse", "seria", "tem", "existe", "diz", "fala", "explica",
           "socrates", "me", "voce", "quero", "saber", "ctb", "dele", "dela", "nos", "uma"}


@dataclass
class Achado:
    lei: str
    bloco: dict
    artigo: dict


def lei_citada(texto: str) -> str | None:
    t = norm(texto)
    for codigo, rx in _LEIS:
        if rx.search(t):
            return codigo
    return None


def numero_do_artigo(texto: str) -> tuple[int, str] | None:
    m = _ARTIGO.search(texto)
    if not m:
        return None
    return int(m.group(1)), (m.group(2) or "").upper()


def _numero_do_rotulo(rotulo: str) -> tuple[int, str] | None:
    m = _ROTULO.match(rotulo or "")
    return (int(m.group(1)), m.group(2) or "") if m else None


class Leis:
    def __init__(self, material):
        self.material = material
        self.ultima_lei: str | None = None

    def todos(self, lei: str | None = None):
        for _caderno, bloco in self.material.blocos():
            if lei and bloco.get("lei") != lei:
                continue
            for artigo in bloco.get("artigos", []):
                yield Achado(bloco.get("lei", ""), bloco, artigo)

    def leis_disponiveis(self) -> list[str]:
        return list(dict.fromkeys(b.get("lei") for _, b in self.material.blocos()))

    # ---------- "lê o artigo 165 do CTB" ----------
    def pedido_de_artigo(self, texto: str) -> tuple[str, tuple[int, str]] | None:
        num = numero_do_artigo(texto)
        if not num:
            return None
        lei = lei_citada(texto) or self.ultima_lei
        if lei is None and len(self.leis_disponiveis()) == 1:
            lei = self.leis_disponiveis()[0]
        return (lei, num) if lei else None

    def artigo(self, lei: str, num: tuple[int, str]) -> Achado | None:
        for a in self.todos(lei):
            if _numero_do_rotulo(a.artigo.get("art", "")) == num:
                self.ultima_lei = lei
                return a
        return None

    @staticmethod
    def texto(a: Achado, limite: int = 900) -> str:
        linhas = [i["t"] for i in a.artigo.get("itens", []) if i.get("k") in ("lei", "vet")]
        return _cortar(" ".join(linhas), limite)

    def apresentar(self, a: Achado) -> tuple[str, str]:
        """(fala, quadro) de um artigo."""
        nome = NOME_LEI.get(a.lei, a.lei)
        art = a.artigo
        itens = [i["t"] for i in art.get("itens", []) if i.get("k") in ("lei", "vet")]
        quadro = [f"# {nome} · {art['art']}" + (f" ({art['titulo'].rstrip('.')})" if art.get("titulo") else "")]
        ficha = art.get("ficha") or {}
        if ficha.get("natureza") and ficha.get("pontos"):
            quadro.append(f"Infração {ficha['natureza']} · {ficha['pontos']} pontos"
                          + (f" · multa-base {ficha['multa_base']}" if ficha.get("multa_base") else ""))
        restante = 1100
        for t in itens[:10]:
            t = _cortar(t, min(260, restante))
            restante -= len(t)
            quadro.append(t)
            if restante < 80:
                quadro.append("(...)")
                break
        if art.get("mudou"):
            quadro.append("Texto alterado por: " + ", ".join(art["mudou"]))
        corrido = " ".join(itens)
        if art.get("morto"):
            fala = f"O {art['art']} do {nome} foi {art['morto'].lower()}."
        elif art.get("resumo"):
            fala = f"{art['art']} do {nome}. {art['resumo']}"
            if art.get("dica"):
                fala += f" Dica: {art['dica']}"
        elif len(corrido) <= 420:
            fala = corrido
        else:
            fala = _cortar(itens[0], 300) + " O resto está no quadro."
        return fala, _quadro_seguro("\n".join(quadro))

    def _mais_parecidos(self, lei: str, palavras: set[str], quantos: int,
                        fora: set, frase: str = "") -> list[Achado]:
        """Palavra rara vale mais ("cinto" aparece em 2 artigos, "dirigir" em 80)."""
        artigos = [(a, norm(" ".join(i["t"] for i in a.artigo.get("itens", []))
                            + " " + a.artigo.get("resumo", "")), norm(a.artigo.get("art", "")))
                   for a in self.todos(lei)]
        n = len(artigos) or 1
        peso = {}
        for p in palavras:
            df = sum(1 for _, corpo, _r in artigos if p in corpo)
            peso[p] = math.log((n + 1) / (df + 1)) if df else 0.0
        pontos = []
        for a, corpo, rotulo in artigos:
            if a.artigo.get("art") in fora or a.artigo.get("morto"):
                continue
            nota = sum(peso[p] for p in palavras if p in corpo)
            if rotulo in palavras or (len(rotulo) > 12 and f" {rotulo} " in f" {frase} "):
                nota += 6                   # definição do Anexo I com o mesmo nome
            if nota > 0:
                pontos.append((nota, -len(corpo), a))
        pontos.sort(key=lambda x: (x[0], x[1]), reverse=True)
        if not pontos:
            return []
        melhor = pontos[0][0]
        return [a for nota, _, a in pontos if nota >= melhor * 0.6][:quantos]

    # ---------- trechos para basear uma resposta ----------
    def trechos(self, pergunta: str, quantos: int = 2, limite: int = 700) -> str:
        """Os artigos mais ligados à pergunta, para o cérebro citar em vez de inventar.
        Só procura quando a pergunta é sobre uma lei que existe no material."""
        lei = lei_citada(pergunta)
        num = numero_do_artigo(pergunta)
        if lei is None and _TRANSITO.search(norm(pergunta)) and "CTB" in self.leis_disponiveis():
            lei = "CTB"
        if lei is None or lei not in self.leis_disponiveis():
            return ""
        achados: list[Achado] = []
        if num:
            a = self.artigo(lei, num)
            if a:
                achados.append(a)
        if len(achados) < quantos:
            palavras = {p for p in norm(pergunta).split() if len(p) >= 4 and p not in _VAZIAS}
            if palavras:
                achados += self._mais_parecidos(lei, palavras, quantos - len(achados),
                                                {x.artigo.get("art") for x in achados},
                                                norm(pergunta))
        if not achados:
            return ""
        partes = [f"{NOME_LEI.get(a.lei, a.lei)}, {a.artigo['art']}: {self.texto(a, limite)}"
                  for a in achados]
        return ("Trechos OFICIAIS da lei (texto compilado). Baseie a resposta neles e cite o "
                "artigo; se eles não responderem a pergunta, diga isso em vez de inventar:\n"
                + "\n".join(partes))
