"""O banco das trilhas para o app estudo-prf: formato do app, números estáveis, sem duplicar."""

import json

from socrates.estudo import exportar_app as ex
from socrates.estudo import material as mat
from socrates.estudo.trilha import Trilha, carregar_trilhas


def app_falso(tmp_path):
    (tmp_path / "bancos").mkdir()
    (tmp_path / "bancos/index.json").write_text(json.dumps(
        [{"id": "prf-2021-p1", "arquivo": "bancos/prf-2021-p1.json", "titulo": "PRF 2021", "n": 1}]))
    (tmp_path / "bancos/prf-2021-p1.json").write_text(json.dumps(
        {"id": "prf-2021-p1", "titulo": "PRF 2021", "tipo": "ce",
         "questoes": [{"n": 1, "materia": "M", "topico": "T", "tipo": "ce", "resp": "C", "enunciado": "E."}]}))
    (tmp_path / "bancos/lei-index.json").write_text("[]")
    return tmp_path


def test_banco_no_formato_do_app(tmp_path):
    app = app_falso(tmp_path)
    total, novos = ex.atualizar_app(app)
    banco = json.loads((app / ex.ARQUIVO).read_text(encoding="utf-8"))
    conferidas = [t for t in carregar_trilhas() if not t.auto]
    assert total == novos == sum(len(t.itens) for tr in conferidas for t in tr.topicos)
    assert banco["tipo"] == "ce" and not banco["sincroniza_simulado"] and "13/11/2026" in banco["aviso"]
    ns = [q["n"] for q in banco["questoes"]]
    assert ns == list(range(1, total + 1))
    q = banco["questoes"][0]
    assert set(q) >= {"n", "materia", "topico", "tipo", "resp", "enunciado", "just", "ref"}
    materias = {q["materia"] for q in banco["questoes"]}
    assert materias == {tr.materia for tr in conferidas if tr.plano in ("", "prf")}
    assert {"Direito Penal", "Direito Processual Penal", "Legislação Especial",
            "Legislação de Trânsito"} <= materias
    indice = json.loads((app / "bancos/index.json").read_text(encoding="utf-8"))
    assert indice[-1] == {"id": ex.ID, "arquivo": ex.ARQUIVO, "titulo": ex.TITULO, "n": total,
                          "origem": "socrates"}
    assert ex.atualizar_app(app) == (total, 0)                   # rodar de novo não duplica
    assert len(json.loads((app / "bancos/index.json").read_text(encoding="utf-8"))) == 2


def test_numero_do_item_nao_muda_quando_entra_item_novo(tmp_path):
    def trilha(itens):
        return Trilha.de_json({"id": "prf-x", "materia": "X", "atualizado": "2026-11-13", "plano": "prf",
                               "topicos": [{"id": "a", "titulo": "A", "itens": itens}]})
    i1 = {"t": "Primeiro item certo ou errado.", "r": "C", "j": "Art. 1º."}
    i2 = {"t": "Segundo item certo ou errado.", "r": "E", "j": "Art. 2º."}
    v1 = ex.banco_do_app([trilha([i1, i2])])
    v2 = ex.banco_do_app([trilha([i1, i2, dict(i1, t="Terceiro item novo.")])], anterior=v1)
    assert [(q["ref"], q["n"]) for q in v2["questoes"]] == [("trilha:prf-x:a:1", 1), ("trilha:prf-x:a:2", 2),
                                                            ("trilha:prf-x:a:3", 3)]
    auto = Trilha.de_json({"id": "prf-y", "materia": "Y", "auto": True, "topicos": [
        {"id": "b", "titulo": "B", "itens": [i1], "origem": "auto"}]})
    assert ex.banco_do_app([auto])["questoes"] == []             # autoestudo não vai para o app


def test_socrates_nao_carrega_o_proprio_espelho(tmp_path):
    app = app_falso(tmp_path)
    ex.atualizar_app(app)
    m = mat.carregar(app, tmp_path / "privado", baixar_se_faltar=False)
    assert list(m.bancos) == ["prf-2021-p1"]
    baixados = []

    def buscar(url):
        caminho = url.replace("https://x/", "")
        baixados.append(caminho)
        return (app / caminho).read_bytes()

    mat.baixar("https://x/", tmp_path / "copia", escrever=lambda *a: None, buscar=buscar)
    assert ex.ARQUIVO not in baixados and "bancos/prf-2021-p1.json" in baixados


def test_resumos_vao_para_o_app_na_ordem_do_edital(tmp_path):
    app = app_falso(tmp_path)
    ex.atualizar_app(app)
    r = json.loads((app / ex.ARQUIVO_RESUMOS).read_text(encoding="utf-8"))
    conferidas = [t for t in carregar_trilhas() if not t.auto and t.plano in ("", "prf")]
    assert r["id"] == ex.ID_RESUMOS and r["atualizado"] == "2026-11-13" and "13/11/2026" in r["aviso"]
    assert {m["trilha"] for m in r["materias"]} == {t.id for t in conferidas}
    assert r["materias"][0]["materia"] == "Legislação de Trânsito"          # a que mais cai
    banco = json.loads((app / ex.ARQUIVO).read_text(encoding="utf-8"))
    for m in r["materias"]:
        tr = next(t for t in conferidas if t.id == m["trilha"])
        assert [t["id"] for t in m["topicos"]] == [t.id for t in tr.topicos]
        for t in m["topicos"]:
            assert t["pontos"] and t["titulo"] and t["peso"] in (1, 2, 3)
            # os itens do tópico no banco são achados pelo título (é o "topico" das questões)
            assert t["itens"] == sum(1 for q in banco["questoes"] if q["topico"] == t["titulo"]
                                     and q["materia"] == m["materia"]), t["id"]
            assert all(q["banco"] == "prf-2021-p1" and isinstance(q["item"], int) for q in t["questoes"])
    ctb = next(m for m in r["materias"] if m["trilha"] == "prf-transito")
    contran = next(t for t in ctb["topicos"] if t["id"] == "contran")
    assert {"banco": "prf-2021-p1", "item": 82} in contran["questoes"] and contran["novidades"]
    # o espelho do Sócrates não baixa os resumos de volta
    m = mat.carregar(app, tmp_path / "privado", baixar_se_faltar=False)
    assert list(m.bancos) == ["prf-2021-p1"]
