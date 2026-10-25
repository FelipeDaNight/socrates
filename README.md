# Sócrates

Assistente de estudo por voz, em português, inspirado no Jarvis — mas com o método
de Sócrates: em vez de só entregar respostas, ele **pergunta** até você aprender.

> Status: **fase 0** — fundação pronta, conversa por texto com o cérebro real.

## Como rodar (Windows)

Precisa do [Python 3.11+](https://www.python.org/downloads/) (marque *Add to PATH* na instalação).

```powershell
cd socrates
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.exemplo .env
```

Pegue uma chave grátis em <https://console.groq.com/keys> (sem cartão), cole no `.env`:

```
GROQ_API_KEY=gsk_sua_chave_aqui
```

E converse:

```powershell
python main.py
```

| Comando     | O que faz                                          |
|-------------|----------------------------------------------------|
| `/explicar` | Explica o assunto e confere se você entendeu       |
| `/testar`   | Vira examinador: perguntas estilo banca, com pistas |
| `/limpar`   | Esquece a conversa atual                           |
| `/sair`     | Encerra                                            |

Se aparecer "modelo não encontrado", rode `python main.py --modelos` e copie um nome
da lista para `config.yaml`.

## Trocar o cérebro

Mude uma linha no `config.yaml`:

```yaml
llm:
  provedor: gemini   # groq | gemini | ollama
```

## Arquitetura

```
main.py                  ponto de partida
config.yaml              nome, modos, provedores
socrates/
  core/orquestrador.py   máquina de estados: dormindo → ouvindo → pensando → falando
  core/persona.py        a personalidade e os modos (explicar / testar)
  core/frases.py         quebra o streaming em frases (para falar sem esperar)
  llm/                   cérebros intercambiáveis (Groq, Gemini, Ollama)
  stt/                   ouvido — fase 1
  tts/                   voz — fase 1
  ferramentas/           ações registradas com @ferramenta — fase 2
tests/                   python -m pytest
```

Cada módulo fica atrás de uma interface, então qualquer peça pode ser trocada sem
mexer no resto.

## Roteiro

- [x] **Fase 0** — fundação, configuração, cérebro com streaming, modos, testes
- [ ] **Fase 1** — microfone + Whisper (ouvido) e edge-tts com voz Antonio (fala)
- [ ] **Fase 2** — palavra de ativação "Sócrates", interrupção, ferramentas
- [ ] **Fase 3** — memória de longo prazo, interface visual animada

## Testes

```powershell
python -m pytest
```
