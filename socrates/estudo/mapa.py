"""Mapa da trilha: uma página (HTML) com todos os tópicos do edital, o domínio de cada
um, o próximo passo, o que você já aprendeu e as leis que mudaram.

  "Sócrates, mostra meu mapa de penal"  ->  abre Documentos\\Socrates\\mapa-<trilha>.html
  "Sócrates, mostra meu mapa"           ->  abre Documentos\\Socrates\\mapa.html (todas as matérias
                                            e o que o autoestudo aprendeu)
"""

from __future__ import annotations

import html
from pathlib import Path

from .progresso import ROTULOS, Progresso

PASTA = Path.home() / "Documents" / "Socrates"

_CORES = {"novo": "var(--cinza)", "comecou": "var(--azul)", "praticando": "var(--azul)",
          "fraco": "var(--vermelho)", "dominado": "var(--verde)", "esfriando": "var(--ambar)"}

_CSS = """
:root{--fundo:#f6f4ef;--cartao:#fffdf9;--texto:#22201c;--suave:#6b665d;--linha:#e4dfd5;
--laranja:#d9661a;--verde:#2f8a57;--azul:#2f6fb0;--vermelho:#c0392b;--ambar:#b7791f;--cinza:#9a948a}
@media (prefers-color-scheme:dark){:root{--fundo:#16140f;--cartao:#1f1c17;--texto:#ece7dd;
--suave:#a49d90;--linha:#36312a;--laranja:#ff8a3d;--verde:#5cc28a;--azul:#6aa7e6;--vermelho:#ef6b5d;
--ambar:#e0a84a;--cinza:#7d776d}}
*{box-sizing:border-box}body{margin:0;background:var(--fundo);color:var(--texto);
font:16px/1.5 "Segoe UI",system-ui,sans-serif}
main{max-width:960px;margin:0 auto;padding:28px 16px 60px}
h1{font-size:28px;margin:0 0 4px}h2{font-size:19px;margin:34px 0 12px}
.sub{color:var(--suave);margin:0}
.passo{background:var(--cartao);border:1px solid var(--linha);border-left:5px solid var(--laranja);
border-radius:12px;padding:16px 18px;margin:22px 0}
.passo b{color:var(--laranja)}.diga{color:var(--suave);font-style:italic}
.numeros{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;margin:18px 0}
.num{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;padding:12px 14px}
.num strong{display:block;font-size:26px;line-height:1.1}.num span{color:var(--suave);font-size:14px}
.topico{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;padding:14px 16px;
margin:10px 0;display:grid;grid-template-columns:1fr auto;gap:6px 14px;align-items:center}
.topico h3{margin:0;font-size:17px}.edital{color:var(--suave);font-size:13px}
.selo{font-size:13px;font-weight:600;padding:3px 10px;border-radius:99px;color:#fff;white-space:nowrap}
.barra{grid-column:1/-1;height:8px;background:var(--linha);border-radius:99px;overflow:hidden}
.barra i{display:block;height:100%;border-radius:99px}
.info{grid-column:1/-1;color:var(--suave);font-size:13px}
.peso{color:var(--laranja);font-size:13px;margin-left:6px}
ul.lista{padding-left:20px}ul.lista li{margin:6px 0}
.novidade{background:var(--cartao);border:1px solid var(--linha);border-radius:10px;padding:10px 14px;margin:8px 0}
.auto{font-size:12px;font-weight:600;color:var(--azul);border:1px solid var(--azul);border-radius:99px;
padding:1px 8px;margin-left:8px;white-space:nowrap}
.materias{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px;margin:18px 0}
.materia{background:var(--cartao);border:1px solid var(--linha);border-radius:12px;padding:14px 16px;
color:inherit;text-decoration:none;display:block}
.materia h3{margin:0 0 4px;font-size:17px}.materia p{margin:4px 0 8px;color:var(--suave);font-size:14px}
.pilha{display:flex;height:9px;border-radius:99px;overflow:hidden;background:var(--linha)}
.pilha i{display:block;height:100%}
details{margin:8px 0}summary{cursor:pointer;font-weight:600;padding:6px 0}
footer{color:var(--suave);font-size:13px;margin-top:40px}
@media (max-width:560px){.topico{grid-template-columns:1fr}.selo{justify-self:start}}
"""


def _e(texto) -> str:
    return html.escape(str(texto or ""))


def gerar(progresso: Progresso, pasta: Path | None = None) -> Path:
    tr = progresso.trilha
    sits = progresso.situacoes()
    c = progresso.contagem(sits)
    passo = progresso.proximo_passo()
    pasta = pasta or PASTA
    pasta.mkdir(parents=True, exist_ok=True)

    partes = [f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
              f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
              f"<title>Mapa de {_e(tr.materia)} · {_e(tr.concurso)}</title><style>{_CSS}</style>"
              f"</head><body><main>",
              f"<h1>{_e(tr.materia)} · {_e(tr.concurso)}</h1>",
              f"<p class='sub'>Trilha do edital, banca {_e(tr.banca)}. Atualizado em "
              f"{_e(progresso.hoje.strftime('%d/%m/%Y'))}.</p>",
              f"<div class='passo'><b>Próximo passo:</b> {_e(passo.motivo)}<br>"
              f"<span class='diga'>Diga: “Sócrates, {_e(passo.comando)}”</span></div>",
              "<div class='numeros'>"]
    for chave, nome in (("dominado", "domina"), ("praticando", "praticando"), ("fraco", "reforçar"),
                        ("esfriando", "revisar"), ("novo", "não começou")):
        n = c[chave] + (c["comecou"] if chave == "praticando" else 0)
        partes.append(f"<div class='num'><strong>{n}</strong><span>{nome}</span></div>")
    venc = len(progresso.vencidos())
    partes.append(f"<div class='num'><strong>{venc}</strong><span>revisões vencidas</span></div></div>")

    partes += _topicos(sits)

    erros = progresso.erros_atuais(6)
    if erros:
        partes.append("<h2>Onde você ainda erra</h2><ul class='lista'>")
        for item, regra in erros:
            partes.append(f"<li><b>{_e(item.topico)}:</b> {_e(regra or item.gabarito_falado())}</li>")
        partes.append("</ul>")
    dominados = [s for s in sits if s.estado == "dominado"]
    if dominados:
        partes.append("<h2>O que você já domina</h2><ul class='lista'>")
        for s in dominados:
            partes.append(f"<li>{_e(s.topico.titulo)} ({s.pct}%)</li>")
        partes.append("</ul>")
    novidades = [(t.titulo, n) for t in tr.topicos for n in t.novidades]
    if novidades:
        partes.append("<h2>Leis que mudaram (materiais antigos estão desatualizados)</h2>")
        for titulo, n in novidades:
            partes.append(f"<div class='novidade'><b>{_e(titulo)}:</b> {_e(n)}</div>")
    partes.append(f"<footer>{_e(tr.fonte)} Gerado pelo Sócrates.</footer></main></body></html>")

    caminho = pasta / f"mapa-{tr.id}.html"
    caminho.write_text("".join(partes), encoding="utf-8")
    return caminho


def _topicos(sits, blocos: bool = True) -> list[str]:
    partes, bloco_atual = [], None
    for s in sits:
        t = s.topico
        if blocos and t.bloco != bloco_atual:
            bloco_atual = t.bloco
            partes.append(f"<h2>{_e(bloco_atual)}</h2>")
        cor = _CORES[s.estado]
        largura = 0 if s.dominio is None else max(4, round(100 * s.dominio))
        info = []
        if s.respostas:
            info.append(f"{s.acertos} de {s.respostas} certas")
        if s.aula_vistos:
            info.append("aula concluída" if s.aula_concluida else
                        f"aula: ponto {s.aula_vistos} de {s.aula_total}")
        if s.ultima:
            info.append(f"último estudo {s.ultima.strftime('%d/%m')}")
        peso = "★" * t.peso
        selo_auto = (f"<span class='auto' title='montado pelo autoestudo em {_e(t.gerado)}; confira na lei'>"
                     f"autoestudo</span>" if t.auto else "")
        partes.append(
            f"<div class='topico'><div><h3>{_e(t.titulo)}<span class='peso' title='quanto cai'>"
            f"{peso}</span>{selo_auto}</h3><div class='edital'>{_e(t.edital)}</div></div>"
            f"<span class='selo' style='background:{cor}'>{_e(ROTULOS[s.estado])}"
            f"{'' if s.pct is None else f' · {s.pct}%'}</span>"
            f"<div class='barra'><i style='width:{largura}%;background:{cor}'></i></div>"
            f"<div class='info'>{_e(' · '.join(info) or 'ainda não estudado')}</div></div>")
    return partes


_ORDEM = {"continuar": 0, "reforco": 1, "revisao": 2, "relembrar": 3, "aula": 4, "praticar": 5, "simulado": 6}


def gerar_geral(progressos: list[Progresso], autoestudo=None, pasta: Path | None = None,
                planos=None) -> Path:
    """Uma página com todas as matérias: próximos passos, o resumo de cada uma, os tópicos
    e o que o autoestudo aprendeu."""
    pasta = pasta or PASTA
    pasta.mkdir(parents=True, exist_ok=True)
    hoje = progressos[0].hoje if progressos else None
    planos = planos if planos is not None else (getattr(autoestudo, "planos", None) or [])
    no_edital = {m.trilha: len(m.topicos) for p in planos for m in p.materias}
    dados = []
    for prog in progressos:
        sits = prog.situacoes()
        dados.append((prog, sits, prog.contagem(sits), prog.proximo_passo()))
    passos = sorted(((_ORDEM.get(p.acao, 9), i, prog.trilha, p) for i, (prog, _s, _c, p) in enumerate(dados)
                     if p.acao != "simulado"), key=lambda x: x[:2])[:3]

    partes = [f"<!doctype html><html lang='pt-BR'><head><meta charset='utf-8'>"
              f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
              f"<title>Meu mapa de estudo</title><style>{_CSS}</style></head><body><main>",
              "<h1>Meu mapa de estudo</h1>",
              f"<p class='sub'>Todas as trilhas do Sócrates. Atualizado em "
              f"{_e(hoje.strftime('%d/%m/%Y') if hoje else '')}.</p>"]
    for _o, _i, tr, p in passos:
        partes.append(f"<div class='passo'><b>{_e(tr.materia)}:</b> {_e(p.motivo)}<br>"
                      f"<span class='diga'>Diga: “Sócrates, {_e(p.comando)}”</span></div>")

    partes.append("<div class='materias'>")
    for prog, sits, c, _p in dados:
        tr = prog.trilha
        n = len(sits) or 1
        fatias = [("dominado", "var(--verde)"), ("praticando", "var(--azul)"), ("comecou", "var(--azul)"),
                  ("esfriando", "var(--ambar)"), ("fraco", "var(--vermelho)")]
        barra = "".join(f"<i style='width:{100 * c[k] / n:.1f}%;background:{cor}'></i>"
                        for k, cor in fatias if c[k])
        autos = sum(1 for s in sits if s.topico.auto)
        total = max(no_edital.get(tr.id, 0), len(sits))
        prontos = (f"{len(sits)} de {total} tópicos prontos" if total > len(sits)
                   else f"{len(sits)} tópico{'s' if len(sits) != 1 else ''}")
        partes.append(
            f"<a class='materia' href='#{_e(tr.id)}'><h3>{_e(tr.materia)}</h3>"
            f"<p>{_e(tr.concurso)} · {prontos} · domina {c['dominado']} · não começou {c['novo']}"
            f"{f' · {autos} do autoestudo' if autos else ''}</p><div class='pilha'>{barra}</div></a>")
    partes.append("</div>")

    if autoestudo is not None:
        lista = autoestudo.aprendidos(6)
        partes.append("<h2>O que o Sócrates aprendeu sozinho (últimos 7 dias)</h2>")
        partes.append(f"<p class='sub'>{_e(autoestudo.status())}</p>")
        if lista:
            partes.append("<ul class='lista'>")
            for e in reversed(lista[-25:]):
                tipo = "atualizou" if e.get("tipo") == "atualizar" else "aprendeu"
                partes.append(f"<li><b>{_e(e.get('titulo'))}</b> ({_e(e.get('materia'))}) · {tipo} em "
                              f"{_e(str(e.get('data', ''))[:10])} · {e.get('pontos', 0)} pontos, "
                              f"{e.get('itens', 0)} itens</li>")
            partes.append("</ul>")

    for prog, sits, c, _p in dados:
        tr = prog.trilha
        partes.append(f"<h2 id='{_e(tr.id)}'>{_e(tr.materia)} · {_e(tr.concurso)}</h2>")
        n = len(sits)
        partes.append(f"<details{' open' if len(dados) == 1 else ''}><summary>{n} tópico{'s' if n != 1 else ''} "
                      f"(domina {c['dominado']}, reforçar {c['fraco']}, não começou {c['novo']})</summary>")
        partes += _topicos(sits, blocos=False)
        partes.append("</details>")

    novidades = [(prog.trilha.materia, t.titulo, nv) for prog, *_ in dados for t in prog.trilha.topicos
                 for nv in t.novidades]
    if novidades:
        partes.append("<h2>Leis que mudaram (materiais antigos estão desatualizados)</h2>")
        for materia, titulo, nv in novidades[:60]:
            partes.append(f"<div class='novidade'><b>{_e(materia)} · {_e(titulo)}:</b> {_e(nv)}</div>")
    partes.append("<footer>Gerado pelo Sócrates. Tópicos com o selo autoestudo foram montados por ele a "
                  "partir da lei em vigor e de páginas da internet, conferidos por um segundo modelo.</footer>"
                  "</main></body></html>")
    caminho = pasta / "mapa.html"
    caminho.write_text("".join(partes), encoding="utf-8")
    return caminho
