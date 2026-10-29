# Sócrates

Assistente de estudo por voz, em português, inspirado no Jarvis — mas com o método
de Sócrates: em vez de só entregar respostas, ele **pergunta** até você aprender.

> Status: **fase 1** — conversa por voz: você fala, ele transcreve, pensa e responde
> falando, frase a frase.

## Como rodar (Windows)

Precisa do [Python 3.11+](https://www.python.org/downloads/) (marque *Add to PATH* na instalação).

```powershell
git clone https://github.com/FelipeDaNight/socrates
cd socrates
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Pegue uma chave grátis em <https://console.groq.com/keys> (sem cartão) e grave no `.env`
sem ela aparecer na tela:

```powershell
$k = Read-Host "Cole a chave"
Set-Content .env "GROQ_API_KEY=$k"
cls
```

Teste o som uma vez e depois converse:

```powershell
.venv\Scripts\python main.py --diagnostico
.venv\Scripts\python main.py
```

**Enter vazio** grava sua voz (ele para sozinho quando você fica em silêncio).
Digitar continua funcionando. Para só texto: `main.py --texto`.

| Falado              | Digitado    | O que faz                                           |
|---------------------|-------------|-----------------------------------------------------|
| "modo explicar"     | `/explicar` | Explica o assunto e confere se você entendeu        |
| "modo prova"        | `/testar`   | Vira examinador: perguntas estilo banca, com pistas |
| "limpar conversa"   | `/limpar`   | Esquece a conversa atual                            |
| "encerrar"          | `/sair`     | Encerra                                             |

### Se algo não funcionar

| Sintoma                              | O que fazer                                                   |
|--------------------------------------|---------------------------------------------------------------|
| "Não ouvi nada"                      | `sensibilidade: 2.0` no `config.yaml`; confira o microfone padrão do Windows |
| Grava barulho à toa / não para       | `sensibilidade: 4.0`                                          |
| Corta você no meio da frase          | `silencio_seg: 1.8`                                           |
| Fala rápido ou devagar demais        | `velocidade: "-10%"` ou `"+15%"`                              |
| "modelo não encontrado"              | `main.py --modelos` e copie um nome para `config.yaml`        |

## Como funciona

```
Enter → microfone (para no silêncio) → Whisper no Groq → cérebro (streaming)
      → frases → voz Antonio (próxima frase gerada enquanto a atual toca) → alto-falante
```

| Peça         | Tecnologia                                   | Custo                 |
|--------------|----------------------------------------------|-----------------------|
| Ouvido       | Whisper large-v3-turbo no Groq               | grátis (com limites)  |
| Cérebro      | gpt-oss-120b no Groq (troca no config)       | grátis (com limites)  |
| Voz          | edge-tts, voz pt-BR-AntonioNeural            | grátis                |
| Som          | sounddevice + miniaudio                      | local                 |

## Arquitetura

```
main.py                    ponto de partida, conversa e diagnóstico
config.yaml                nome, modos, provedores, voz, microfone
socrates/
  core/orquestrador.py     máquina de estados: dormindo → ouvindo → pensando → falando
  core/persona.py          a personalidade e os modos (explicar / testar)
  core/frases.py           quebra o streaming em frases
  core/narrador.py         fala frase a frase, sintetizando a próxima em paralelo
  core/comandos.py         comandos falados ou digitados
  llm/                     cérebros intercambiáveis (Groq, Gemini, Ollama)
  stt/                     ouvido: Whisper + filtro de alucinações
  tts/                     voz: edge-tts + limpeza de markdown
  audio/                   microfone com detecção de silêncio, alto-falante
  ferramentas/             ações registradas com @ferramenta — fase 2
tests/                     32 testes, rodam sem microfone nem internet
```

Cada módulo fica atrás de uma interface, então qualquer peça pode ser trocada sem
mexer no resto.

## Roteiro

- [x] **Fase 0** — fundação, configuração, cérebro com streaming, modos, testes
- [x] **Fase 1** — microfone, Whisper (ouvido), voz Antonio frase a frase, comandos por voz
- [ ] **Fase 2** — palavra de ativação "Sócrates", interrupção, ferramentas
- [ ] **Fase 3** — memória de longo prazo, interface visual animada

## Testes

```powershell
.venv\Scripts\python -m pytest
```
