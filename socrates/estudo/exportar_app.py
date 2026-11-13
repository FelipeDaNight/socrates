"""Leva os itens das trilhas conferidas para o app estudo-prf (iPhone), como um banco.

O app mostra os bancos de `bancos/index.json` (Questões > Treinar por matéria). Aqui se
monta o banco "socrates-trilhas-prf" com os itens de fixação das trilhas CONFERIDAS
(nunca os do autoestudo, que ficam só no computador), um por questão Certo/Errado, com
a justificativa.

O número de cada item (n) não muda de uma versão para outra: o progresso, os erros e
os cartões de revisão do app ficam presos a ele. Item novo ganha o próximo número.

Também grava os RESUMOS (`bancos/socrates-resumos-prf.json`): a teoria de cada tópico
conferido (pontos, pegadinhas e novidades), na ordem do edital, com as questões da prova
ligadas a ele. O app mostra isso na tela "Resumos", com "treinar este tópico".

    python -m socrates.estudo.exportar_app CAMINHO_DO_APP
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from .plano import carregar_planos
from .trilha import Trilha, carregar_trilhas

ID = "socrates-trilhas-prf"
ARQUIVO = f"bancos/{ID}.json"
TITULO = "Sócrates · Fixação PRF"
ID_RESUMOS = "socrates-resumos-prf"
ARQUIVO_RESUMOS = f"bancos/{ID_RESUMOS}.json"


def _conferidas_prf(trilhas: list[Trilha]) -> list[Trilha]:
    """As trilhas conferidas da PRF, na ordem do edital (a matéria que mais cai primeiro)."""
    ordem = {}
    try:
        for plano in carregar_planos(ids=["prf"]):
            for i, m in enumerate(sorted(plano.materias, key=lambda x: -x.peso)):
                ordem.setdefault(m.trilha, i)
    except (OSError, ValueError, KeyError):
        pass
    escolhidas = [tr for tr in trilhas if not tr.auto and tr.plano in ("", "prf")]
    return sorted(escolhidas, key=lambda tr: (ordem.get(tr.id, 999), tr.materia))


def itens_conferidos(trilhas: list[Trilha]) -> list[dict]:
    saida = []
    for tr in trilhas:
        if tr.auto or tr.plano not in ("", "prf"):
            continue
        for t in tr.topicos:
            if t.auto:
                continue
            for k, it in enumerate(t.itens, 1):
                saida.append({"ref": f"trilha:{tr.id}:{t.id}:{k}", "materia": tr.materia,
                              "topico": t.titulo, "tipo": "ce", "resp": it["r"].strip().upper()[:1],
                              "enunciado": it["t"].strip(), "just": (it.get("j") or "").strip()})
    return saida


def banco_do_app(trilhas: list[Trilha], anterior: dict | None = None, atualizado: str = "") -> dict:
    """O banco no formato do app, mantendo o n de cada item já publicado."""
    numeros = {q["ref"]: q["n"] for q in (anterior or {}).get("questoes", []) if q.get("ref")}
    proximo = max(numeros.values(), default=0) + 1
    questoes = []
    for q in itens_conferidos(trilhas):
        n = numeros.get(q["ref"])
        if n is None:
            n, proximo = proximo, proximo + 1
        questoes.append({"n": n, **q})
    datas = sorted({tr.atualizado for tr in trilhas if not tr.auto and tr.atualizado})
    quando = atualizado or (datas[-1] if datas else "")
    quando_br = "/".join(reversed(quando.split("-"))) if quando else ""
    materias = list(dict.fromkeys(q["materia"] for q in questoes))
    lista = ", ".join(materias[:-1]) + " e " + materias[-1] if len(materias) > 1 else "".join(materias)
    return {
        "id": ID, "titulo": TITULO, "banca": "Cebraspe (estilo)", "ano": int(quando[:4]) if quando else None,
        "tipo": "ce", "sincroniza_simulado": False, "origem": "socrates",
        "aviso": ("Itens de fixação no estilo Cebraspe, os mesmos das aulas do Sócrates, escritos e "
                  "conferidos nas fontes oficiais (leis atualizadas até " + (quando_br or "a data da trilha") +
                  ")" + (f". Matérias: {lista}" if lista else "") + ". Não são questões de prova: as da "
                  "PRF 2021 estão no banco da prova. Certo/Errado; a justificativa cita o artigo."),
        "questoes": questoes,
    }


def _data_br(quando: str) -> str:
    return "/".join(reversed(quando.split("-"))) if quando else ""


def resumos_do_app(trilhas: list[Trilha], atualizado: str = "") -> dict:
    """A teoria dos tópicos conferidos, para a tela Resumos do app."""
    materias = []
    for tr in _conferidas_prf(trilhas):
        topicos = []
        for t in tr.topicos:
            if t.auto:
                continue
            reais = []
            for q in t.questoes:
                banco, _, item = q.partition("|")
                m = re.fullmatch(r"item (\d+)", item.strip())
                if banco and m:
                    reais.append({"banco": banco, "item": int(m.group(1))})
            topicos.append({"id": t.id, "titulo": t.titulo, "edital": t.edital, "peso": t.peso,
                            "pontos": list(t.pontos), "pegadinhas": list(t.pegadinhas),
                            "novidades": list(t.novidades), "itens": len(t.itens), "questoes": reais})
        if topicos:
            materias.append({"materia": tr.materia, "trilha": tr.id, "fonte": tr.fonte,
                             "atualizado": tr.atualizado, "topicos": topicos})
    datas = sorted({tr.atualizado for tr in trilhas if not tr.auto and tr.atualizado})
    quando = atualizado or (datas[-1] if datas else "")
    return {"id": ID_RESUMOS, "titulo": "Resumos do Sócrates · PRF", "atualizado": quando,
            "aviso": ("A teoria das trilhas conferidas do Sócrates, tópico por tópico, na ordem do edital "
                      "(leis atualizadas até " + (_data_br(quando) or "a data da trilha") + "). Os itens de "
                      "fixação de cada tópico estão no banco \"Sócrates · Fixação PRF\"."),
            "materias": materias}


def atualizar_app(pasta_app: Path, trilhas: list[Trilha] | None = None) -> tuple[int, int]:
    """Grava o banco no app e o registra no índice. Devolve (total, novos)."""
    pasta_app = Path(pasta_app)
    if trilhas is None:
        trilhas = carregar_trilhas(extra=pasta_app / "__sem_autoestudo__")   # só as conferidas
    arq = pasta_app / ARQUIVO
    try:
        anterior = json.loads(arq.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        anterior = None
    banco = banco_do_app(trilhas, anterior)
    antes = {q.get("ref") for q in (anterior or {}).get("questoes", [])}
    novos = sum(1 for q in banco["questoes"] if q["ref"] not in antes)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(banco, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    idx_arq = pasta_app / "bancos" / "index.json"
    indice = json.loads(idx_arq.read_text(encoding="utf-8"))
    entrada = {"id": ID, "arquivo": ARQUIVO, "titulo": TITULO, "n": len(banco["questoes"]),
               "origem": "socrates"}
    for i, e in enumerate(indice):
        if isinstance(e, dict) and e.get("id") == ID:
            indice[i] = entrada
            break
    else:
        indice.append(entrada)
    idx_arq.write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf-8")
    resumos = resumos_do_app(trilhas)
    (pasta_app / ARQUIVO_RESUMOS).write_text(json.dumps(resumos, ensure_ascii=False, indent=1) + "\n",
                                             encoding="utf-8")
    return len(banco["questoes"]), novos


if __name__ == "__main__":
    total, novos = atualizar_app(Path(sys.argv[1] if len(sys.argv) > 1 else "."))
    print(f"banco {ID}: {total} itens ({novos} novos); resumos em {ARQUIVO_RESUMOS}")
