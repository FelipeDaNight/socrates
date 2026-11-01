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


@dataclass
class Config:
    nome: str
    modo_inicial: str
    historico_max: int
    llm: ConfigLLM
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
    claude_enter: bool = True
    log_nivel: str = "INFO"
    log_arquivo: str | None = None
    bruto: dict = field(default_factory=dict, repr=False)


class ErroConfig(Exception):
    """Algo no config.yaml ou no .env está faltando ou errado."""


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

    provedor = dados.get("llm", {}).get("provedor", "groq")
    prov = dados.get("provedores", {}).get(provedor)
    if prov is None:
        raise ErroConfig(f"Provedor '{provedor}' não está em 'provedores' no config.yaml.")

    chave_env = prov.get("chave_env")
    chave = os.getenv(chave_env) if chave_env else "ollama"
    if chave_env and not chave:
        raise ErroConfig(
            f"Falta a chave {chave_env}. Copie .env.exemplo para .env e cole sua chave lá."
        )

    llm = ConfigLLM(
        provedor=provedor,
        base_url=prov["base_url"],
        modelo=prov["modelo"],
        chave=chave,
        temperatura=float(dados.get("llm", {}).get("temperatura", 0.6)),
    )
    ouvido = _preencher(ConfigOuvido, dados.get("ouvido"))
    ouvido.chave = os.getenv(ouvido.chave_env)

    log = dados.get("log", {})
    return Config(
        nome=dados.get("nome", "Sócrates"),
        modo_inicial=dados.get("modo_inicial", "explicar"),
        historico_max=int(dados.get("historico_max", 20)),
        llm=llm,
        voz=_preencher(ConfigVoz, dados.get("voz")),
        ouvido=ouvido,
        microfone=_preencher(ConfigMic, dados.get("microfone")),
        escuta=_preencher(ConfigEscuta, dados.get("escuta")),
        visor=_preencher(ConfigVisor, dados.get("visor")),
        local=dados.get("local"),
        pesquisa=bool((dados.get("pesquisa") or {}).get("ativa", True)),
        acoes=bool((dados.get("acoes") or {}).get("ativas", True)),
        programas=(dados.get("acoes") or {}).get("programas") or {},
        visao_modelo=(dados.get("visao") or {}).get("modelo", "qwen/qwen3.8-27b"),
        claude_enter=bool((dados.get("claude") or {}).get("enviar_com_enter", True)),
        log_nivel=log.get("nivel", "INFO"),
        log_arquivo=log.get("arquivo"),
        bruto=dados,
    )
