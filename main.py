"""Ponto de partida do Sócrates.

    python main.py               mãos livres: diga "Sócrates" e fale (com o visor)
    python main.py --sem-visor   mãos livres, sem a janela laranja
    python main.py --texto       conversar só por texto
    python main.py --diagnostico testar microfone, voz e transcrição
    python main.py --modelos     listar modelos do provedor configurado
    python main.py --pesquisa    testar a pesquisa na internet
    python main.py --provedores  testar cada cérebro grátis do rodízio (Groq, Mistral, Gemini)
    python main.py --local       preparar o cérebro LOCAL (Ollama): tudo pensado no seu PC
    python main.py --nuvem       voltar a pensar na nuvem (Groq/Mistral/Gemini)
    python main.py --vozes       ouvir as vozes disponíveis e escolher
    python main.py --acoes       testar janelas, texto copiado, bloco de notas e visão da tela
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import sys
import threading

from socrates import config, log
from socrates.audio import ErroAudio
from socrates.config import ErroConfig
from socrates.core.comandos import Comando, interpretar
from socrates.core.orquestrador import Orquestrador
from socrates.llm import ErroCerebro, criar_cerebro
from socrates.visor.painel import Painel

AJUDA_TEXTO = """Comandos:
  /explicar  modo explicação (padrão)
  /testar    modo prova: ele te faz perguntas estilo banca
  /limpar    esquece a conversa atual
  /sair      encerra"""


def criar_socrates_local(cfg: config.Config) -> Orquestrador:
    """Tudo pensado no seu PC: o modelo do Ollama com as ferramentas no mesmo pedido."""
    from socrates import ferramentas
    from socrates.core import contexto
    from socrates.ferramentas import claude, computador, tela
    from socrates.llm.ollama import ClienteOllama, CerebroLocal

    nomes = ferramentas.nomes_das_acoes(com_busca=cfg.local_cfg.pesquisa) if cfg.acoes else []
    esquemas = [ferramentas.REGISTRO[n].esquema() for n in nomes]

    async def executar(nome: str, args: dict) -> str:
        return await asyncio.to_thread(ferramentas.executar, nome, args)

    computador.adicionar_programas(cfg.programas)
    claude.ENVIAR_COM_ENTER = cfg.claude_enter
    cerebro = CerebroLocal(cfg.local_cfg.modelo, ClienteOllama(cfg.local_cfg.url), esquemas,
                           executar, cfg.local_cfg.contexto, cfg.llm.temperatura)
    tela.VISAO["local"] = cerebro
    threading.Thread(target=cerebro.aquecer, daemon=True).start()   # já carrega na memória
    print(f"[cérebro] local: {cfg.local_cfg.modelo} no seu computador ({len(nomes)} ferramentas)")
    return Orquestrador(cerebro, cfg.nome, cfg.modo_inicial, cfg.historico_max,
                        contexto=lambda: contexto.data_e_lugar(cfg.local),
                        contexto_no_fim=True, extra_sistema=contexto.INSTRUCAO_LOCAL)


def criar_socrates(cfg: config.Config) -> Orquestrador:
    """Cérebro (com ações no PC e pesquisa) + data, hora e cidade a cada pergunta."""
    if cfg.cerebro == "local":
        return criar_socrates_local(cfg)
    from socrates.core import contexto
    from socrates.llm import pesquisa_disponivel

    pesquisa = cfg.pesquisa and pesquisa_disponivel(cfg.rodizio or [cfg.llm])
    if cfg.pesquisa and not pesquisa:
        print("[pesquisa] Nenhum provedor com busca (só o Groq com gpt-oss). Seguindo sem internet.")
    if cfg.acoes:
        from socrates.ferramentas import computador, tela
        computador.adicionar_programas(cfg.programas)
        tela.VISAO.update(base_url=cfg.ouvido.base_url, chave=cfg.ouvido.chave,
                          modelo=cfg.visao_modelo)
        tela.VISOES[:] = cfg.visoes
        from socrates.ferramentas import claude
        claude.ENVIAR_COM_ENTER = cfg.claude_enter
    cerebro = criar_cerebro(cfg.llm, pesquisa=pesquisa, acoes=cfg.acoes,
                            rodizio=cfg.rodizio, rodizio_acoes=cfg.rodizio_acoes)
    usados = " > ".join(f"{c.provedor}" for c in cfg.rodizio) or cfg.llm.provedor
    print(f"[cérebros] {usados}" + (f"  (sem chave, pulados: {', '.join(sorted(set(cfg.sem_chave)))})"
                                    if cfg.sem_chave else ""))
    return Orquestrador(cerebro, cfg.nome, cfg.modo_inicial, cfg.historico_max,
                        contexto=lambda: contexto.montar(cfg.local, pesquisa, acoes=cfg.acoes))


class Sentidos:
    """Microfone, ouvido e voz juntos."""

    def __init__(self, cfg: config.Config, painel: Painel | None = None):
        from socrates.audio import importar_sounddevice
        from socrates.audio.alto_falante import AltoFalante
        from socrates.audio.escuta import Escuta
        from socrates.audio.microfone import AjustesMic, Microfone
        from socrates.stt.groq_whisper import OuvidoWhisper
        from socrates.tts.fabrica import criar_voz

        if not cfg.ouvido.chave:
            raise ErroConfig(f"Falta a chave {cfg.ouvido.chave_env} no .env para transcrever a voz.")
        importar_sounddevice()   # falha cedo se o som não estiver disponível
        m = cfg.microfone
        ajustes = AjustesMic(m.silencio_seg, m.max_seg, m.espera_seg, m.sensibilidade)
        self.mic = Microfone(ajustes, dispositivo=m.dispositivo)            # diagnóstico
        self.escuta = Escuta(ajustes, dispositivo=m.dispositivo, painel=painel)
        self.ouvido = OuvidoWhisper(cfg.ouvido.base_url, cfg.ouvido.chave, cfg.ouvido.modelo)
        self.alto_falante = AltoFalante(painel=painel)
        self.voz = criar_voz(cfg.voz, self.alto_falante,
                             avisar=lambda t: print(f"\n[voz] {t}"))


# ---------------- mãos livres ----------------

async def maos_livres(cfg: config.Config, painel: Painel) -> None:
    from socrates.maos_livres import Conversa, ler_teclado

    try:
        sentidos = Sentidos(cfg, painel)
    except (ErroAudio, ErroConfig) as e:
        painel.encerrado = True   # fecha o visor
        print(f"[voz desligada] {e}\nSeguindo no modo texto.")
        await conversar_texto(cfg)
        return

    from socrates.ferramentas import aparencia, computador
    from socrates.maos_livres import Aviso

    aparencia.PAINEL = painel

    soc = criar_socrates(cfg)
    fila: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_running_loop()
    painel.ao_fechar = lambda: loop.call_soon_threadsafe(fila.put_nowait, None)
    computador.avisar = lambda texto: loop.call_soon_threadsafe(fila.put_nowait, Aviso(texto))

    ler_teclado(loop, fila)
    sentidos.escuta.iniciar(fila)
    try:
        await Conversa(cfg, soc, sentidos, painel).rodar(fila)
    finally:
        sentidos.escuta.parar()
        painel.encerrado = True


def rodar_maos_livres(cfg: config.Config, com_visor: bool) -> None:
    painel = Painel()
    painel.cor = cfg.visor.cor
    tem_tk = importlib.util.find_spec("tkinter") is not None
    if com_visor and not tem_tk:
        print("[visor] Tkinter não encontrado; seguindo sem a janela.")
    if not (com_visor and tem_tk):
        asyncio.run(maos_livres(cfg, painel))
        return

    # O visor (Tkinter) precisa da thread principal; o Sócrates roda numa paralela.
    def fundo():
        try:
            asyncio.run(maos_livres(cfg, painel))
        except Exception:
            logging.getLogger("socrates").exception("erro geral")
            import traceback
            traceback.print_exc()
        finally:
            painel.encerrado = True

    trabalho = threading.Thread(target=fundo, name="socrates", daemon=True)
    trabalho.start()
    from socrates.visor.janela import abrir
    abrir(painel, cfg.nome, cfg.visor.sempre_no_topo, cfg.visor.escala)
    trabalho.join(timeout=10)   # deixa ele terminar a despedida


# ---------------- só texto ----------------

def mostrar_quadro_texto(conteudo: str) -> None:
    print(f"\n┌─ quadro ─────────\n{conteudo}\n└──────────────────")


async def conversar_texto(cfg: config.Config) -> None:
    from socrates.core.quadro_fluxo import separar_quadro

    soc = criar_socrates(cfg)
    print(f"\n{cfg.nome} pronto ({config.descricao_cerebro(cfg)}, texto).")
    print(AJUDA_TEXTO)
    while True:
        try:
            texto = (await asyncio.to_thread(input, f"\n[{soc.modo}] Você: ")).strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not texto:
            continue
        from socrates import ferramentas
        if ferramentas.pendente_valido():
            resposta = await asyncio.to_thread(ferramentas.resolver_confirmacao, texto)
            if resposta is not None:
                print(f"{cfg.nome}: {resposta}")
                from socrates.ferramentas import claude
                if claude.REINICIAR.is_set():
                    break
                continue
        comando = interpretar(texto)
        if comando is Comando.SAIR:
            break
        if comando in (Comando.EXPLICAR, Comando.TESTAR):
            soc.mudar_modo(comando.value)
            print(f"Modo: {soc.modo}")
            continue
        if comando is Comando.LIMPAR:
            soc.limpar()
            print("Conversa esquecida.")
            continue
        if comando is not None:
            print(AJUDA_TEXTO)
            continue
        print(f"{cfg.nome}: ", end="", flush=True)
        try:
            async for pedaco in separar_quadro(soc.conversar(texto), mostrar_quadro_texto):
                print(pedaco, end="", flush=True)
            print()
        except ErroCerebro as e:
            print(f"\n[erro] {e}")
    print(f"\n{cfg.nome}: Até a próxima. Bons estudos!")


# ---------------- utilitários ----------------

async def provar_vozes(cfg: config.Config) -> None:
    """Toca a mesma frase em cada voz para você escolher de ouvido."""
    import os

    from socrates.audio import ErroAudio
    from socrates.audio.alto_falante import AltoFalante
    from socrates.tts import ErroVoz
    from socrates.tts.fabrica import CANDIDATAS, FRASE_TESTE, voz_da_candidata

    alto = AltoFalante()
    tem_gemini = bool(os.getenv("GEMINI_API_KEY"))
    print("=== Provador de vozes ===")
    print("Vou falar a mesma frase em cada voz. Anote o número da que você gostar.")
    if not tem_gemini:
        print("(As vozes do Gemini precisam de GEMINI_API_KEY no .env: grátis em aistudio.google.com/apikey)")
    for i, c in enumerate(CANDIDATAS, 1):
        voz = voz_da_candidata(c, alto, cfg.voz)
        if voz is None:
            print(f"\n{i:2d}. {c.rotulo}: pulada (sem GEMINI_API_KEY)")
            continue
        print(f"\n{i:2d}. {c.rotulo}")
        try:
            await voz.tocar(await voz.sintetizar(FRASE_TESTE))
        except (ErroVoz, ErroAudio) as e:
            print(f"    não funcionou: {e}")
            continue
        await asyncio.sleep(0.4)
    escolha = (await asyncio.to_thread(input, "\nQual número você prefere? (Enter para nenhuma) ")).strip()
    if escolha.isdigit() and 1 <= int(escolha) <= len(CANDIDATAS):
        c = CANDIDATAS[int(escolha) - 1]
        print(f"\nPara usar \"{c.rotulo}\", crie (ou edite) o arquivo config.local.yaml, "
              "na pasta do Sócrates, com:\n")
        print(c.config_yaml())
        if c.provedor == "gemini":
            print("\n(o Edge vira a voz reserva automaticamente)")


async def testar_acoes(cfg: config.Config) -> None:
    """Testa no Windows de verdade as ações que dependem do sistema."""
    from socrates.ferramentas import janelas, tela

    tela.VISAO.update(base_url=cfg.ouvido.base_url, chave=cfg.ouvido.chave, modelo=cfg.visao_modelo)
    tela.VISOES[:] = cfg.visoes
    print("=== Teste das ações no computador ===")

    def etapa(numero, titulo, funcao, *args):
        print(f"\n{numero}/4  {titulo}")
        try:
            resultado = funcao(*args)
        except Exception as e:
            print(f"     FALHOU: {e}")
            return
        for linha in str(resultado).splitlines()[:12]:
            print(f"     {linha}")

    etapa(1, "Janelas abertas", janelas.janelas_abertas)
    etapa(2, "Texto copiado (copie qualquer texto antes, com Ctrl+C)",
          janelas.ler_area_de_transferencia)
    etapa(3, "Escrever no Bloco de Notas (deve abrir uma nota de teste)",
          janelas.escrever_no_bloco_de_notas,
          "Teste do Sócrates: se você está lendo isto, escrever no Bloco de Notas funciona.",
          "teste do socrates")
    print("\n4/4  Ver a tela (tira um print agora e manda para o modelo de visão)")
    await asyncio.sleep(1.5)
    try:
        print("     " + tela.ver_tela("Descreva em 2 frases o que está na tela.").replace("\n", "\n     "))
    except Exception as e:
        print(f"     FALHOU: {e}")


ONDE_PEGAR_CHAVE = {
    "GROQ_API_KEY": "console.groq.com/keys",
    "MISTRAL_API_KEY": "console.mistral.ai/api-keys (plano Experiment, grátis)",
    "GEMINI_API_KEY": "aistudio.google.com/apikey",
}


async def testar_provedores(cfg: config.Config) -> None:
    """Manda um pedido mínimo a cada serviço do rodízio e mostra quem está ok."""
    import time as _t

    from socrates.llm import membro

    print("=== Cérebros grátis do rodízio ===\n")
    vistos = set()
    for c in [*cfg.rodizio, *cfg.rodizio_acoes]:
        if (c.provedor, c.modelo) in vistos:
            continue
        vistos.add((c.provedor, c.modelo))
        inicio = _t.monotonic()
        try:
            r = await membro(c)._criar(messages=[{"role": "user", "content": "Responda só: ok"}],
                                       max_tokens=200, stream=False)
            texto = (r.choices[0].message.content or "").strip()[:30]
            print(f"  OK     {c.provedor:13s} {c.modelo:28s} {_t.monotonic() - inicio:4.1f} s  \"{texto}\"")
        except Exception as e:
            print(f"  FALHOU {c.provedor:13s} {c.modelo:28s} {str(e)[:90]}")
    faltam = {}
    provs = cfg.bruto.get("provedores", {})
    for nome in sorted(set(cfg.sem_chave)):
        env = (provs.get(nome) or {}).get("chave_env")
        if env:
            faltam.setdefault(env, []).append(nome)
    for env, nomes in faltam.items():
        print(f"  --     {', '.join(nomes):13s} sem {env} no .env  ->  {ONDE_PEGAR_CHAVE.get(env, '')}")
    print("\nVisão da tela:", " > ".join(f"{v['nome']}:{v['modelo']}" for v in cfg.visoes) or "nenhuma")


async def listar_modelos(cfg: config.Config) -> None:
    cerebro = criar_cerebro(cfg.llm)
    print(f"Modelos disponíveis no {cfg.llm.provedor}:")
    for m in await cerebro.listar_modelos():
        marca = "  <- configurado" if m == cfg.llm.modelo else ""
        print(f"  {m}{marca}")


async def diagnostico(cfg: config.Config) -> None:
    """Testa cada peça separada e diz qual falhou."""
    import numpy as np

    from socrates.audio import TAXA_MIC, importar_sounddevice
    from socrates.stt import ErroOuvido
    from socrates.tts import ErroVoz

    print("=== Diagnóstico do Sócrates ===\n")
    print("1/6  Som do computador")
    try:
        sd = importar_sounddevice()
        print(f"     Microfone:    {sd.query_devices(kind='input')['name']}")
        print(f"     Alto-falante: {sd.query_devices(kind='output')['name']}")
        s = Sentidos(cfg)
    except Exception as e:
        print(f"     FALHOU: {e}")
        return

    print("\n2/6  Voz (você deve ouvir uma frase)")
    try:
        await s.voz.tocar(await s.voz.sintetizar("Olá! Se você está me ouvindo, a minha voz está funcionando."))
        print("     OK, áudio enviado ao alto-falante.")
    except (ErroVoz, ErroAudio) as e:
        print(f"     FALHOU: {e}")

    print("\n3/6  Microfone: aperte Enter, diga \"Sócrates, o que é crase?\" e fique em silêncio")
    await asyncio.to_thread(input, "     ")
    try:
        wav = await asyncio.to_thread(s.mic.gravar)
    except ErroAudio as e:
        print(f"     FALHOU: {e}")
        return
    print(f"     Ruído da sala: limiar {s.mic.ultimo_limiar:.0f}")
    if wav is None:
        print("     Não detectei fala. Tente sensibilidade: 2.0 no config.yaml,")
        print("     e confira o microfone padrão em Configurações > Som do Windows.")
        return
    amostras = np.frombuffer(wav[44:], dtype=np.int16)
    print(f"     Gravei {len(amostras) / TAXA_MIC:.1f} s. Tocando de volta o que ouvi...")
    await s.alto_falante.tocar_wav(amostras, TAXA_MIC)

    print("\n4/6  Transcrição (Whisper no Groq)")
    try:
        texto = await s.ouvido.transcrever(wav)
        print(f"     Entendi: \"{texto}\"")
    except ErroOuvido as e:
        print(f"     FALHOU: {e}")
        return

    print("\n5/6  Palavra de ativação")
    from socrates.core.despertar import chamou
    foi, pedido = chamou(texto)
    if foi:
        print(f"     OK, reconheci o nome. Pedido: \"{pedido}\"")
    else:
        print("     Não reconheci \"Sócrates\" nessa frase. Fale o nome mais devagar,")
        print("     no começo ou no fim da frase.")

    print("\n6/6  Pesquisa na internet")
    await testar_pesquisa(cfg, recuo="     ")
    print("\nTudo certo. Rode: .venv\\Scripts\\python main.py")


async def testar_pesquisa(cfg: config.Config, recuo: str = "") -> bool:
    """Faz uma pesquisa de verdade para ver se a sua conta do Groq tem acesso."""
    from socrates.core import contexto
    from socrates.llm import ErroPesquisa, pesquisa_disponivel
    from socrates.llm.pesquisa import _com_instrucao, limpar_resposta

    if not cfg.pesquisa:
        print(f"{recuo}Desligada no config.yaml (pesquisa: ativa: false).")
        return False
    grupo = [c for c in (cfg.rodizio or [cfg.llm]) if pesquisa_disponivel(c)]
    if not grupo:
        print(f"{recuo}Indisponível com {cfg.llm.provedor}/{cfg.llm.modelo}: "
              "só funciona no Groq com modelo gpt-oss.")
        return False
    pergunta = "Qual a cotação do dólar hoje?"
    print(f"{recuo}Perguntando: \"{pergunta}\" (pode levar uns segundos)")
    from socrates.llm import membro
    from socrates.llm.rodizio import CerebroRodizio
    cerebro = CerebroRodizio([membro(c) for c in grupo]) if len(grupo) > 1 else membro(grupo[0])
    mensagens = _com_instrucao([{"role": "system", "content": contexto.montar(cfg.local, True)},
                                {"role": "user", "content": pergunta}])
    try:
        resposta = limpar_resposta(await cerebro.pesquisar(mensagens))
    except (ErroPesquisa, ErroCerebro) as e:
        print(f"{recuo}FALHOU: {e}")
        print(f"{recuo}O Sócrates continua funcionando, só sem internet. Se a mensagem fala")
        print(f"{recuo}de plano, cobrança ou permissão, a busca não está liberada na sua conta.")
        return False
    print(f"{recuo}OK: {resposta}")
    return True


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")   # acentos certos no Windows
    p = argparse.ArgumentParser(description="Sócrates, assistente de estudo")
    p.add_argument("--texto", action="store_true", help="conversa só por texto")
    p.add_argument("--sem-visor", action="store_true", help="mãos livres sem a janela laranja")
    p.add_argument("--diagnostico", action="store_true", help="testa microfone, voz e transcrição")
    p.add_argument("--modelos", action="store_true", help="lista os modelos do provedor")
    p.add_argument("--pesquisa", action="store_true", help="testa a pesquisa na internet")
    p.add_argument("--provedores", action="store_true", help="testa cada cérebro grátis do rodízio")
    p.add_argument("--local", action="store_true",
                   help="prepara o cérebro local (Ollama): escolhe, baixa e testa o modelo")
    p.add_argument("--nuvem", action="store_true", help="volta para o cérebro na nuvem")
    p.add_argument("--modelo", help="com --local: escolher o modelo (ex.: qwen3.5:2b)")
    p.add_argument("--vozes", action="store_true", help="toca as vozes disponíveis para você escolher")
    p.add_argument("--acoes", action="store_true", help="testa janelas, texto copiado, bloco de notas e tela")
    args = p.parse_args()

    if args.local:   # não precisa de chave nenhuma
        from socrates.instalar_local import instalar
        sys.exit(0 if instalar(modelo=args.modelo) else 1)
    if args.nuvem:
        from socrates.instalar_local import voltar_para_nuvem
        voltar_para_nuvem()
        sys.exit(0)

    try:
        cfg = config.carregar()
    except ErroConfig as e:
        print(f"[configuração] {e}")
        sys.exit(1)
    log.configurar(cfg.log_nivel, cfg.log_arquivo)

    try:
        if args.modelos:
            asyncio.run(listar_modelos(cfg))
        elif args.pesquisa:
            asyncio.run(testar_pesquisa(cfg))
        elif args.provedores:
            asyncio.run(testar_provedores(cfg))
        elif args.vozes:
            asyncio.run(provar_vozes(cfg))
        elif args.acoes:
            asyncio.run(testar_acoes(cfg))
        elif args.diagnostico:
            asyncio.run(diagnostico(cfg))
        elif args.texto or not cfg.voz.ativa:
            asyncio.run(conversar_texto(cfg))
        else:
            rodar_maos_livres(cfg, com_visor=cfg.visor.ativo and not args.sem_visor)
    except KeyboardInterrupt:
        pass
    reiniciar_se_atualizou()


def reiniciar_se_atualizou() -> None:
    """Depois de "Sócrates, se atualiza": abre de novo, já com o código novo."""
    import subprocess

    from socrates.ferramentas import claude
    if not claude.REINICIAR.is_set():
        return
    print("\n[atualização] Reiniciando o Sócrates com a versão nova...\n")
    sys.exit(subprocess.call([sys.executable, *sys.argv]))


if __name__ == "__main__":
    main()
