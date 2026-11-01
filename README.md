# Sócrates

Assistente de estudo por voz, em português, inspirado no Jarvis — mas com o método
de Sócrates: em vez de só entregar respostas, ele **pergunta** até você aprender.

<p align="center"><img src="docs/visor.gif" width="330" alt="Visor do Sócrates"></p>

> Status: **fase 2** — mãos livres: diga "Sócrates" e fale. Mexe no seu computador,
> desenha fórmulas e gráficos num quadro branco, pesquisa na internet e sabe a data de hoje.

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
| "limpar conversa"   | `/limpar`   | Esquece a conversa atual e apaga o quadro           |
| "apaga o quadro"    | `/apagar`   | Apaga só o quadro branco                            |
| "obrigado"          | `/dormir`   | Encerra o assunto; volta a esperar o nome           |
| "encerrar"          | `/sair`     | Desliga o Sócrates                                  |

### Ações no computador

Sem nenhuma API: quem executa é o próprio Windows. O Groq só entende o pedido.

| Exemplo                                         | O que ele faz                               |
|-------------------------------------------------|---------------------------------------------|
| "Sócrates, abre a calculadora"                  | Abre programas: Word, Excel, Chrome, Spotify, bloco de notas... |
| "Sócrates, abre o qconcursos.com"               | Abre sites                                  |
| "Sócrates, toca lo-fi pra estudar no YouTube"   | Abre a busca no YouTube (ou no Google)      |
| "Sócrates, inicia um pomodoro de 25 minutos"    | Timer que **avisa falando** quando acaba    |
| "Sócrates, quanto tempo falta?"                 | Consulta ou cancela o timer                 |
| "Sócrates, aumenta o volume"                    | Volume: aumentar, diminuir, mudo            |
| "Sócrates, anota que a prova é dia 10"          | Caderno em `Documentos\Socrates\anotacoes.md` |
| "Sócrates, abre a pasta downloads"              | Abre pastas                                 |
| "Sócrates, bloqueia a tela"                     | Bloqueia o Windows                          |

Ações que apagam arquivos ou desligam o PC ficaram de fora de propósito. Programas
que ele não conhece entram no `config.yaml`:

```yaml
acoes:
  programas:
    anki: 'C:\Program Files\Anki\anki.exe'
```

### Quadro branco

Quando a explicação pede algo visual (fórmula, conta passo a passo, gráfico, ou a
questão com as alternativas no modo prova), o quadro abre ao lado do visor. A fórmula
**não é lida em voz alta**: ele explica falando e diz "veja no quadro".

<p align="center"><img src="docs/quadro.png" width="700" alt="Quadro branco do Sócrates"></p>

- "Sócrates, me explica a fórmula de Bhaskara"
- "Sócrates, desenha o gráfico de seno de x"
- "Sócrates, apaga o quadro"

### Perguntas do dia a dia

O modelo foi treinado até 2024, mas o Sócrates sabe a **data, a hora e a sua cidade**
(`local:` no `config.yaml`) e **pesquisa na internet** quando a pergunta é sobre algo atual:

- "Sócrates, qual a cotação do dólar hoje?"
- "Sócrates, vai chover amanhã?" (usa a sua cidade)
- "Sócrates, quando sai o edital da PRF?"
- "Sócrates, pesquisa o horário da farmácia do centro."

Ele avisa "Vou pesquisar isso." e responde citando a fonte pelo nome. Perguntas de
estudo ("o que é crase?") e de data e hora não gastam pesquisa. A busca é a
`browser_search` do Groq. Para conferir se a sua conta tem acesso:

```powershell
.venv\Scripts\python main.py --pesquisa
```

### O visor

| Estado     | Como fica                                         |
|------------|---------------------------------------------------|
| Dormindo   | Apagado, girando devagar: diga "Sócrates"         |
| Atento     | Aceso: pode falar sem dizer o nome                |
| Ouvindo    | As barras seguem a sua voz                        |
| Pensando   | Os anéis giram rápido                             |
| Falando    | O núcleo e as barras pulsam com a voz dele        |

Tamanho: `escala:` no `config.yaml` (1.0 pequeno, 1.25 médio, 1.5 grande).
Sem a janela: `main.py --sem-visor` (o quadro aparece como texto no terminal). Por cima das outras janelas:
`sempre_no_topo: true` no `config.yaml`. Estudando sozinho e não quer dizer o nome
toda vez: `palavra_ativacao: false`.

### A voz

Rode o provador: ele fala a mesma frase em cada voz e diz o que colocar no `config.yaml`.

```powershell
.venv\Scripts\python main.py --vozes
```

| Opção                         | Como é                                      | Precisa de          |
|-------------------------------|---------------------------------------------|---------------------|
| Antonio (Edge)                | A voz atual; dá para deixar mais grave com `tom: "-8Hz"` | nada        |
| Andrew, Brian, Florian (Edge) | Vozes multilíngues, falam português com sotaque leve | nada       |
| Gemini (Sadaltager, Charon, Gacrux...) | As mais naturais, com estilo de "professor calmo" | `GEMINI_API_KEY` |

A chave do Gemini é grátis em <https://aistudio.google.com/apikey>; grave no `.env`
do mesmo jeito que a do Groq, com `Add-Content` no lugar de `Set-Content`:

```powershell
$k = Read-Host "Cole a chave do Gemini"
Add-Content .env "GEMINI_API_KEY=$k"
cls
```

Com o Gemini, o Antonio fica de **reserva automática**: se o Gemini falhar ou bater o
limite grátis, a frase sai na voz do Antonio, sem o Sócrates ficar mudo.

### Se algo não funcionar

| Sintoma                                  | O que fazer                                                   |
|------------------------------------------|---------------------------------------------------------------|
| Ele não reage quando você fala           | `sensibilidade: 2.0` no `config.yaml`; confira o microfone padrão do Windows |
| Reage a barulho à toa                    | `sensibilidade: 4.0`                                          |
| Corta você no meio da frase              | `silencio_seg: 1.8`                                           |
| Não reconhece o nome                     | Rode `--diagnostico`: a etapa 5 mostra como o Whisper escreveu |
| A conversa "fecha" rápido demais         | Aumente `janela_seg`                                          |
| Fala rápido ou devagar demais            | `velocidade: "-10%"` ou `"+15%"`                              |
| "Não consegui pesquisar agora"           | Rode `--pesquisa` e veja o motivo; para desligar: `pesquisa: ativa: false` |
| Pesquisa quando não precisava (ou o contrário) | Me conte a frase: as regras ficam em `socrates/llm/pesquisa.py` |
| "Não conheço o programa"                 | Adicione em `acoes: programas:` no `config.yaml`              |
| Abriu programa quando era pergunta       | Me conte a frase: as regras ficam em `socrates/llm/acoes.py`  |
| Voz do Gemini falha                      | Ele usa o Antonio sozinho; rode `--vozes` para ver o erro      |
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
| Pesquisa     | browser_search do Groq (só com gpt-oss)      | depende da sua conta  |
| Ações no PC  | Python + Windows (os.startfile, teclas de volume) | local            |
| Quadro       | matplotlib (fórmulas em LaTeX e gráficos)    | local                 |
| Voz          | edge-tts (Antonio) ou Gemini TTS             | grátis / plano grátis |
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
  core/contexto.py         data, hora e cidade em cada pergunta
  llm/pesquisa.py          decide quando pesquisar e limpa a resposta para a voz
  llm/acoes.py             decide quando é ação e faz o vaivém com as ferramentas
  ferramentas/computador.py  as ações no PC (programas, sites, volume, timer, anotações)
  core/quadro_fluxo.py     separa o quadro branco da fala
  visor/quadro.py          desenha o quadro (fórmulas, gráficos com avaliação segura)
  tts/gemini.py            voz do Gemini; tts/reserva.py troca para o Edge se falhar
  core/narrador.py         fala frase a frase, sintetizando a próxima em paralelo
  core/comandos.py         comandos falados ou digitados
  audio/escuta.py          microfone sempre ligado, numa thread, com pausa
  audio/microfone.py       segmentador: separa as falas e reaprende o ruído da sala
  audio/alto_falante.py    toca a voz e avisa o visor do volume
  visor/janela.py          a janela laranja (Tkinter)
  visor/painel.py          estado compartilhado entre o Sócrates e o visor
  llm/  stt/  tts/         cérebro, ouvido e voz intercambiáveis
tests/                     178 testes, rodam sem microfone nem internet
```

## Roteiro

- [x] **Fase 0** — fundação, configuração, cérebro com streaming, modos, testes
- [x] **Fase 1** — microfone, Whisper (ouvido), voz Antonio frase a frase, comandos por voz
- [x] **Fase 1.5** — mãos livres com o nome "Sócrates", janela de conversa, visor laranja
- [x] **Fase 1.6** — sabe data, hora e cidade; pesquisa na internet quando precisa
- [x] **Fase 2** — ações no computador, quadro branco com fórmulas e gráficos, visor maior, vozes novas
- [ ] **Fase 2.5** — interromper enquanto ele fala
- [ ] **Fase 3** — memória de longo prazo (o que você errou, o que já estudou)

## Testes

```powershell
.venv\Scripts\python -m pytest
```
