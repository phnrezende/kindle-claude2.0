# Como funciona

## De onde vêm os dados (no PC)

Igual ao [kindle-claude](https://github.com/guithepc/kindle-claude), de onde vem esta parte:

- **Hooks** (`pc/hook.py`): `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop`, `StopFailure` e `SessionEnd` gravam cada sessão, pelo `session_id`, em `pc/data/state.json`. Uma trava de arquivo deixa vários agentes escreverem ao mesmo tempo (também no Windows).
- Do `Notification`, só contam os avisos em que o Claude espera uma resposta sua: pedido de permissão e perguntas (`permission_prompt`, `elicitation_dialog`…). O aviso de "parado há 60 s" (`idle_prompt`) e os outros são ignorados, para o Kindle não ficar "Te chamando!" depois de cada resposta.
- **statusLine** (`pc/statusline.py`): guarda `rate_limits.five_hour` e `rate_limits.seven_day` em `pc/data/statusline.json`, e continua mostrando a statusLine que você já tinha.
- **Tokens**: o agente soma `input + output + cache_creation + cache_read` dos históricos em `~/.claude/projects/**/*.jsonl`, sem contar duas vezes a mesma mensagem, a cada 30 s no máximo. Cada arquivo é lido só a partir de onde parou da última vez.

## O estado

O agente (`pc/claudinho.py`) junta as sessões, escolhe a mais urgente (pedindo permissão > trabalhando > terminou > descansando) e monta o estado:

| Campo | O que é |
|---|---|
| `modo` | `cozinhando`, `chamando` (pedindo permissão), `prato` (acabou de terminar), `esperando`, `descansando` |
| `desde` | quando o modo começou (relógio do PC) |
| `ferramenta`, `descricao` | o que está rodando agora (vazios quando não há ferramenta) |
| `ativos`, `projeto` | quantas sessões estão trabalhando e o projeto da que aparece |
| `antes` | as últimas 4 ferramentas |
| `sessao`, `semana` | `pct` usado e a `hora` em que zera, no fuso do PC; na semana, também o `dia` (1 = segunda … 7 = domingo) |
| `tokens` | `hoje`, `hora`, `media`, arredondados ao que o Kindle mostra |
| `rev` | resumo do conteúdo: muda só quando algo visível muda |
| `agora` | relógio do PC no momento |

O estado leva só dados, nenhuma frase pronta (versão 2 do formato). As frases ("Cozinhando…", "pensando…", "zera às 15:00") são montadas no Kindle, no idioma escolhido, por `claudinho/textos.lua`. Por isso trocar o idioma não depende do PC. Um agente antigo (versão 1, que mandava as frases em português) continua funcionando.

O `rev` ignora o `agora` e arredonda os números para a precisão que o painel mostra (`2,5 mi`, `32 mil`). Assim, o Kindle só redesenha quando a tela realmente mudaria.

Uma sessão "trabalhando" sem nenhum evento há mais de 10 minutos passa a contar como parada. O `Stop` não dispara quando você interrompe com Esc, e um erro da API dispara o `StopFailure`; sem isso, o Kindle ficaria "Cozinhando…" por meia hora. Uma ferramenta que roda mais de 10 minutos seguidos (um build longo, por exemplo) também cai nessa regra.

## O que sai do PC

O estado é um JSON pequeno, assim:

```json
{"v":2,"modo":"cozinhando","desde":1792715237,"ferramenta":"Edit",
 "descricao":"DashboardController.java","ativos":1,"projeto":"camaleao",
 "antes":["Read","Grep","Bash"],"sessao":{"pct":11,"hora":"15:00"},
 "semana":{"pct":19,"hora":"21:00","dia":7},
 "tokens":{"hoje":2500000,"hora":400000,"media":1800000},"rev":"bcd87aea4697","agora":1792715244}
```

Na `descricao` vai só:

- o nome do arquivo (Read, Edit, Write…), sem a pasta;
- o padrão de busca (Grep, Glob);
- o domínio de uma URL (WebFetch), sem o caminho;
- a descrição curta que o Claude dá ao comando (Bash) ou à tarefa. Se o comando não tiver descrição, vai só o nome do programa (`npm …`), nunca o comando com os argumentos.

Prompts, textos de pesquisa, comandos inteiros e conteúdo de arquivos não saem do PC. Cada texto é cortado em até 80 caracteres.

## Transporte

O Kindle sempre **puxa**, pela rede de casa:

| | |
|---|---|
| Endereço | `http://IP-DO-PC:8787/estado.json` |
| Autenticação | `Authorization: Bearer TOKEN` (o token do `pc/config.json`) |
| Nada mudou | `304` (com `If-None-Match`) |

É HTTP simples, sem criptografia: qualquer aparelho na mesma rede consegue ver o estado passando, mas sem o token não consegue pedir.

## No Kindle (plugin)

### Buscas

- A cada **60 s** lendo e **30 s** com o painel aberto (configurável). Na biblioteca, sem painel, não busca nada.
- A requisição roda num **subprocesso** (como o KOReader faz em outras buscas em segundo plano). O processo principal só confere a cada 0,25 s se a resposta chegou, então a virada de página nunca espera a rede.
- Se o Wi-Fi está desligado, nem tenta (não fica travado resolvendo nome).
- Ao dormir, para. Ao acordar, busca em 3 s. Quando o Wi-Fi conecta, busca em 1 s.
- Três buscas seguidas sem resposta, ou mais de 10 minutos sem nenhuma resposta, e o Kindle mostra **"Sem sinal do PC"**.

### Relógios

O Kindle calcula a diferença entre o relógio dele e o do PC a cada resposta completa (o `agora` do estado). O "há X min" usa essa correção, então um Kindle com a hora errada não mostra tempos absurdos. O relógio grande do painel é o do Kindle.

### Overlay

O overlay é registrado como um *view module* do leitor (`ReaderView:registerViewModule`), o mesmo mecanismo que o KOReader usa para a orelha de marcador e o rodapé. Por isso:

- ele é desenhado junto com cada página, sem piscar a mais na virada;
- quando o estado muda, o plugin pede refresh **só do retângulo do cantinho** (`ui`), e só se o quadro ou o estilo mudaram;
- não há animação por padrão: são três desenhos fixos, para não gastar bateria nem deixar fantasma no e-ink.

### Painel

- Desenhado deitado em 800×600 × escala, com as posições, fontes e espaçamentos do original, e girado para a tela em pé (90° ou 270°). Em outras telas, a escala ajusta e o pixel art usa células inteiras.
- Estado novo do PC: redesenha tudo, com refresh completo quando o modo muda e a cada 10 trocas, para limpar fantasmas.
- A cada minuto: só a coluna da esquerda (relógio, data e "há X min").
- Animação: só o retângulo do mascote, 1,5 s por quadro (1 s pedindo permissão, 4 s descansando). Trabalhando, sorteia 10 blocos entre sopa, cebola, tempero e frigideira, sem repetir o mesmo bloco seguido.
- Enquanto está aberto, avisa o KOReader para não suspender e, no Kindle, desliga o protetor de tela (`preventScreenSaver`). Ao fechar, devolve tudo como estava.

### Fontes

O KOReader abre fontes variáveis só no peso padrão. Por isso o plugin traz Inter Tight ExtraBold/Black e JetBrains Mono Regular/Bold como arquivos estáticos, gerados com `tools/gerar_fontes.py`.

## Bateria

Não foi medida no aparelho. O que mais gasta é o Wi-Fi ligado. Lendo com o overlay, são uma busca pequena por minuto e um refresh minúsculo só quando o estado muda. O painel aberto, com animação, gasta bem mais: deixe no carregador.
