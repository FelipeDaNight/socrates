"""Mapa da trilha: uma página (HTML) com todos os tópicos do edital, o domínio de cada
um, o próximo passo, o que você já aprendeu e as leis que mudaram.

  "Sócrates, mostra meu mapa de penal"  ->  abre Documentos\\Socrates\\mapa-<trilha>.html
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

    bloco_atual = None
    for s in sits:
        t = s.topico
        if t.bloco != bloco_atual:
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
        partes.append(
            f"<div class='topico'><div><h3>{_e(t.titulo)}<span class='peso' title='quanto cai'>"
            f"{peso}</span></h3><div class='edital'>{_e(t.edital)}</div></div>"
            f"<span class='selo' style='background:{cor}'>{_e(ROTULOS[s.estado])}"
            f"{'' if s.pct is None else f' · {s.pct}%'}</span>"
            f"<div class='barra'><i style='width:{largura}%;background:{cor}'></i></div>"
            f"<div class='info'>{_e(' · '.join(info) or 'ainda não estudado')}</div></div>")

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
