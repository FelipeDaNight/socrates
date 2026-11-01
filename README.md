# Sócrates

Assistente de estudo por voz, em português, inspirado no Jarvis — mas com o método
de Sócrates: em vez de só entregar respostas, ele **pergunta** até você aprender.

<p align="center"><img src="docs/visor.gif" width="330" alt="Visor do Sócrates"></p>

> Status: **fase 1.5** — mãos livres: diga "Sócrates" e fale. Visor laranja que pulsa
> com a voz dele.

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

## Como usar

Não tem botão. Ele fica ouvindo e só responde quando você diz o nome:

- **"Sócrates, o que é crase?"** ou **"O que é crase, Sócrates?"**
- **"Sócrates"** sozinho: ele responde "Sim?" e espera o pedido.
- Depois que ele responde, você tem **15 segundos** para continuar a conversa sem
  repetir o nome (no modo prova são **45**, para dar tempo de pensar na resposta).
- **"Obrigado"** encerra o assunto: ele volta a esperar o nome.

Conversa de outras pessoas e TV sem o nome dele são ignoradas. Enquanto ele fala,
o microfone fica pausado, para ele não ouvir a própria voz. Digitar e dar Enter
também funciona.

| Falado              | Digitado    | O que faz                                           |
|---------------------|-------------|-----------------------------------------------------|
| "modo explicar"     | `/explicar` | Explica o assunto e confere se você entendeu        |
| "modo prova"        | `/testar`   | Vira examinador: perguntas estilo banca, com pistas |
| "limpar conversa"   | `/limpar`   | Esquece a conversa atual                            |
| "obrigado"          | `/dormir`   | Encerra o assunto; volta a esperar o nome           |
| "encerrar"          | `/sair`     | Desliga o Sócrates                                  |

### O visor

| Estado     | Como fica                                         |
|------------|---------------------------------------------------|
| Dormindo   | Apagado, girando devagar: diga "Sócrates"         |
| Atento     | Aceso: pode falar sem dizer o nome                |
| Ouvindo    | As barras seguem a sua voz                        |
| Pensando   | Os anéis giram rápido                             |
| Falando    | O núcleo e as barras pulsam com a voz dele        |

Sem a janela: `main.py --sem-visor`. Por cima das outras janelas:
`sempre_no_topo: true` no `config.yaml`. Estudando sozinho e não quer dizer o nome
toda vez: `palavra_ativacao: false`.

### Se algo não funcionar

| Sintoma                                  | O que fazer                                                   |
|------------------------------------------|---------------------------------------------------------------|
| Ele não reage quando você fala           | `sensibilidade: 2.0` no `config.yaml`; confira o microfone padrão do Windows |
| Reage a barulho à toa                    | `sensibilidade: 4.0`                                          |
| Corta você no meio da frase              | `silencio_seg: 1.8`                                           |
| Não reconhece o nome                     | Rode `--diagnostico`: a etapa 5 mostra como o Whisper escreveu |
| A conversa "fecha" rápido demais         | Aumente `janela_seg`                                          |
| Fala rápido ou devagar demais            | `velocidade: "-10%"` ou `"+15%"`                              |
| "Tkinter não encontrado"                 | Reinstale o Python marcando *tcl/tk and IDLE*, ou use `--sem-visor` |
| "modelo não encontrado"                  | `main.py --modelos` e copie um nome para `config.yaml`        |

## Como funciona

```
microfone sempre aberto → segmentador (separa cada fala pelo silêncio)
  → Whisper no Groq → disse "Sócrates"? ou está na janela de conversa?
      não → ignora
      sim → pausa o microfone → cérebro (streaming) → frases → voz Antonio
            → reabre o microfone e a janela de conversa
```

| Peça         | Tecnologia                                   | Custo                 |
|--------------|----------------------------------------------|-----------------------|
| Ouvido       | Whisper large-v3-turbo no Groq               | grátis (com limites)  |
| Cérebro      | gpt-oss-120b no Groq (troca no config)       | grátis (com limites)  |
| Voz          | edge-tts, voz pt-BR-AntonioNeural            | grátis                |
| Som          | sounddevice + miniaudio                      | local                 |
| Visor        | Tkinter (já vem com o Python)                | local                 |

Cada fala que o microfone separa vai para o Whisper, mesmo sem o nome. Num lugar
com muita conversa ou TV ligada, isso gasta o limite grátis do Groq mais rápido.

## Arquitetura

```
main.py                    ponto de partida: mãos livres, texto, diagnóstico
config.yaml                nome, modos, provedores, voz, microfone, escuta, visor
socrates/
  maos_livres.py           o laço da conversa sem botão
  core/orquestrador.py     máquina de estados e histórico
  core/persona.py          a personalidade e os modos (explicar / testar)
  core/despertar.py        reconhece "Sócrates" no começo ou no fim da frase
  core/narrador.py         fala frase a frase, sintetizando a próxima em paralelo
  core/comandos.py         comandos falados ou digitados
  audio/escuta.py          microfone sempre ligado, numa thread, com pausa
  audio/microfone.py       segmentador: separa as falas e reaprende o ruído da sala
  audio/alto_falante.py    toca a voz e avisa o visor do volume
  visor/janela.py          a janela laranja (Tkinter)
  visor/painel.py          estado compartilhado entre o Sócrates e o visor
  llm/  stt/  tts/         cérebro, ouvido e voz intercambiáveis
tests/                     67 testes, rodam sem microfone nem internet
```

## Roteiro

- [x] **Fase 0** — fundação, configuração, cérebro com streaming, modos, testes
- [x] **Fase 1** — microfone, Whisper (ouvido), voz Antonio frase a frase, comandos por voz
- [x] **Fase 1.5** — mãos livres com o nome "Sócrates", janela de conversa, visor laranja
- [ ] **Fase 2** — interromper enquanto ele fala, ferramentas (hora, lembretes, timer de estudo)
- [ ] **Fase 3** — memória de longo prazo (o que você errou, o que já estudou)

## Testes

```powershell
.venv\Scripts\python -m pytest
```
