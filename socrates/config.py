"""Carrega config.yaml e as chaves do .env."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent


@dataclass
class ConfigLLM:
    provedor: str
    base_url: str
    modelo: str
    chave: str | None
    temperatura: float = 0.6
    modelo_acoes: str | None = None   # outro modelo = outro limite grátis por minuto


@dataclass
class ConfigAutoestudo:
    """O Sócrates estuda sozinho o edital enquanto está aberto (socrates/estudo/autoestudo.py)."""
    ativo: bool = True
    planos: list = field(default_factory=lambda: ["prf", "cbmgo"])
    por_dia: int = 40
    pausa_seg: float = 90
    ocioso_seg: float = 30
    cerebros: list = field(default_factory=list)       # ConfigLLM de quem escreve (com chave)
    conferentes: list = field(default_factory=list)    # ConfigLLM de quem confere (com chave)


@dataclass
class ConfigVoz:
    ativa: bool = True
    provedor: str = "edge"                  # edge | gemini
    nome: str = "pt-BR-AntonioNeural"       # voz do Edge
    velocidade: str = "+0%"
    tom: str = "+0Hz"
    saudacao: bool = True
    gemini_voz: str = "Sadaltager"
    gemini_modelo: str = "gemini-3.8-flash-tts"
    gemini_estilo: str = ("calmo, pausado e acolhedor, como um professor sábio e experiente, "
                          "em português do Brasil")


@dataclass
class ConfigOuvido:
    base_url: str = "https://api.groq.com/openai/v1"
    chave: str | None = None
    chave_env: str = "GROQ_API_KEY"
    modelo: str = "whisper-large-v3-turbo"


@dataclass
class ConfigMic:
    silencio_seg: float = 1.2
    max_seg: float = 30.0
    espera_seg: float = 8.0
    sensibilidade: float = 3.0
    dispositivo: int | str | None = None


@dataclass
class ConfigEscuta:
    palavra_ativacao: bool = True
    janela_seg: float = 15.0
    janela_prova_seg: float = 45.0


@dataclass
class ConfigVisor:
    ativo: bool = True
    sempre_no_topo: bool = False
    escala: float = 1.25
    cor: str = "laranja"


@dataclass
class ConfigLocal:
    modelo: str = "qwen3.5:4b"
    url: str = "http://localhost:11434"
    contexto: int = 6144
    pesquisa: bool = True


@dataclass
class ConfigAgente:
    ativo: bool = True              # o cérebro que decide (entende a fala e escolhe as ferramentas)
    reflexao: bool = True           # todo dia relê o próprio registro e escreve lições
    saudacao_com_plano: bool = True  # ao ligar, já sugere o que estudar


@dataclass
class Config:
    nome: str
    modo_inicial: str
    historico_max: int
    llm: ConfigLLM                                          # o primeiro do rodízio
    rodizio: list = field(default_factory=list)              # conversa, em ordem
    rodizio_acoes: list = field(default_factory=list)        # ações no PC, em ordem
    sem_chave: list = field(default_factory=list)            # provedores pulados
    autoestudo: ConfigAutoestudo = field(default_factory=ConfigAutoestudo)
    voz: ConfigVoz = field(default_factory=ConfigVoz)
    ouvido: ConfigOuvido = field(default_factory=ConfigOuvido)
    microfone: ConfigMic = field(default_factory=ConfigMic)
    escuta: ConfigEscuta = field(default_factory=ConfigEscuta)
    visor: ConfigVisor = field(default_factory=ConfigVisor)
    local: str | None = None
    pesquisa: bool = True
    acoes: bool = True
    programas: dict = field(default_factory=dict)
    visao_modelo: str = "qwen/qwen3.8-27b"
    visoes: list = field(default_factory=list)   # [{nome, base_url, chave, modelo}] em ordem
    cerebro: str = "nuvem"                       # nuvem (Groq/Mistral/Gemini) | local (Ollama)
    local_cfg: ConfigLocal = field(default_factory=ConfigLocal)
    claude_enter: bool = True
    agente: ConfigAgente = field(default_factory=ConfigAgente)
    log_nivel: str = "INFO"
    log_arquivo: str | None = None
    bruto: dict = field(default_factory=dict, repr=False)


def descricao_cerebro(cfg: "Config") -> str:
    if cfg.cerebro == "local":
        return f"local / {cfg.local_cfg.modelo}"
    return f"{cfg.llm.provedor} / {cfg.llm.modelo}"


class ErroConfig(Exception):
    """Algo no config.yaml ou no .env está faltando ou errado."""


def _cidade(dados: dict) -> str | None:
    """A cidade do aluno. Antes ficava em "local:", que é também a seção do cérebro local
    (e a segunda apagava a primeira); agora é "cidade:". "local: Cidade" ainda vale."""
    cidade = dados.get("cidade")
    if not cidade and isinstance(dados.get("local"), str):
        cidade = dados["local"]
    return str(cidade).strip() if cidade else None


def _preencher(classe, dados: dict | None):
    """Cria a dataclass só com as chaves que ela conhece (ignora o resto)."""
    conhecidas = classe.__dataclass_fields__
    return classe(**{k: v for k, v in (dados or {}).items() if k in conhecidas})


def mesclar(base: dict, extra: dict) -> dict:
    """Junta o config.local.yaml por cima do config.yaml, seção por seção."""
    junto = dict(base)
    for chave, valor in extra.items():
        if isinstance(valor, dict) and isinstance(junto.get(chave), dict):
            junto[chave] = mesclar(junto[chave], valor)
        else:
            junto[chave] = valor
    return junto


def gravar_local(extra: dict, caminho: Path | None = None) -> Path:
    """Guarda uma preferência no config.local.yaml, mantendo o que já estava lá."""
    caminho = caminho or RAIZ / "config.local.yaml"
    atual = {}
    if caminho.exists():
        atual = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    novo = mesclar(atual, extra)
    caminho.write_text("# Suas preferências (valem por cima do config.yaml; não vão para o GitHub)\n"
                       + yaml.safe_dump(novo, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return caminho


def _visoes(dados: dict, provedores: dict) -> list[dict]:
    """Groq (qwen) primeiro e depois as reservas que tiverem chave."""
    visao = dados.get("visao") or {}
    pedidos = [("groq", visao.get("modelo", "qwen/qwen3.8-27b"))]
    pedidos += list((visao.get("reservas") or {}).items())
    saida = []
    for nome, modelo in pedidos:
        prov = provedores.get(nome)
        chave = os.getenv(prov.get("chave_env") or "") if prov else None
        if prov and chave:
            saida.append({"nome": nome, "base_url": prov["base_url"], "chave": chave,
                          "modelo": modelo})
    return saida


def carregar(caminho: Path | str | None = None) -> Config:
    load_dotenv(RAIZ / ".env")
    caminho = Path(caminho) if caminho else RAIZ / "config.yaml"
    if not caminho.exists():
        raise ErroConfig(f"Não achei o arquivo de configuração: {caminho}")

    dados = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
    local = caminho.with_name("config.local.yaml")
    if local.exists():   # suas preferências: não vão para o GitHub nem travam o git pull
        try:
            dados = mesclar(dados, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
        except yaml.YAMLError as e:
            raise ErroConfig(f"Erro no config.local.yaml: {e}") from e

    llm_cfg = dados.get("llm", {}) or {}
    provedores = dados.get("provedores", {}) or {}
    temperatura = float(llm_cfg.get("temperatura", 0.6))

    def montar(nome: str) -> ConfigLLM:
        prov = provedores.get(nome)
        if prov is None:
            raise ErroConfig(f"Provedor '{nome}' não está em 'provedores' no config.yaml.")
        chave_env = prov.get("chave_env")
        return ConfigLLM(provedor=nome, base_url=prov["base_url"], modelo=prov["modelo"],
                         chave=(os.getenv(chave_env) if chave_env else "ollama") or None,
                         temperatura=temperatura, modelo_acoes=prov.get("modelo_acoes"))

    # Rodízio: a ordem em que os serviços grátis são tentados. Sem chave = pulado.
    nomes = llm_cfg.get("rodizio") or [llm_cfg.get("provedor", "groq")]
    rodizio = [montar(n) for n in nomes]
    rodizio_acoes = [montar(n) for n in (llm_cfg.get("rodizio_acoes") or [])]
    com_chave = [c for c in rodizio if c.chave]
    modo_cerebro = str(dados.get("cerebro", "nuvem")).lower()
    if modo_cerebro == "local" and not com_chave:   # no modo local a nuvem é opcional
        com_chave = [ConfigLLM("ollama", "http://localhost:11434/v1", "local", "ollama")]
    if not com_chave:
        faltam = ", ".join(sorted({provedores[c.provedor].get("chave_env") for c in rodizio
                                    if provedores[c.provedor].get("chave_env")}))
        raise ErroConfig(f"Nenhuma chave encontrada ({faltam}). Coloque pelo menos a "
                         "GROQ_API_KEY no arquivo .env.")
    llm = com_chave[0]
    ae = dados.get("autoestudo") or {}

    def com_chaves(nomes) -> list[ConfigLLM]:
        saida = []
        for n in nomes or []:
            if n in provedores:
                c = montar(n)
                if c.chave:
                    c.temperatura = 0.3          # material de estudo: menos criatividade
                    saida.append(c)
        return saida

    autoestudo = ConfigAutoestudo(
        ativo=bool(ae.get("ativo", True)),
        planos=list(ae.get("planos") or ["prf", "cbmgo"]),
        por_dia=int(ae.get("por_dia", 40)),
        pausa_seg=float(ae.get("pausa_seg", 90)),
        ocioso_seg=float(ae.get("ocioso_seg", 30)),
        cerebros=com_chaves(ae.get("cerebros") or ["mistral", "gemini", "groq_leve", "groq"]),
        conferentes=com_chaves(ae.get("conferentes") or ["gemini", "mistral_leve", "groq", "mistral"]),
    )
    ouvido = _preencher(ConfigOuvido, dados.get("ouvido"))
    ouvido.chave = os.getenv(ouvido.chave_env)

    log = dados.get("log", {})
    return Config(
        nome=dados.get("nome", "Sócrates"),
        modo_inicial=dados.get("modo_inicial", "explicar"),
        historico_max=int(dados.get("historico_max", 20)),
        llm=llm,
        rodizio=[c for c in rodizio if c.chave],
        rodizio_acoes=[c for c in rodizio_acoes if c.chave],
        sem_chave=[c.provedor for c in rodizio + rodizio_acoes if not c.chave],
        autoestudo=autoestudo,
        voz=_preencher(ConfigVoz, dados.get("voz")),
        ouvido=ouvido,
        microfone=_preencher(ConfigMic, dados.get("microfone")),
        escuta=_preencher(ConfigEscuta, dados.get("escuta")),
        visor=_preencher(ConfigVisor, dados.get("visor")),
        local=_cidade(dados),
        pesquisa=bool((dados.get("pesquisa") or {}).get("ativa", True)),
        acoes=bool((dados.get("acoes") or {}).get("ativas", True)),
        programas=(dados.get("acoes") or {}).get("programas") or {},
        visao_modelo=(dados.get("visao") or {}).get("modelo", "qwen/qwen3.8-27b"),
        claude_enter=bool((dados.get("claude") or {}).get("enviar_com_enter", True)),
        visoes=_visoes(dados, provedores),
        cerebro=modo_cerebro,
        local_cfg=_preencher(ConfigLocal, dados.get("local") if isinstance(dados.get("local"), dict)
                             else None),
        agente=_preencher(ConfigAgente, dados.get("agente")),
        log_nivel=log.get("nivel", "INFO"),
        log_arquivo=log.get("arquivo"),
        bruto=dados,
    )
