# Como funciona

## De onde vêm os dados (no PC)

Igual ao [kindle-claude](https://github.com/guithepc/kindle-claude), de onde vem esta parte:

- **Hooks** (`pc/hook.py`): `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Notification`, `Stop`, `StopFailure` e `SessionEnd` gravam cada sessão, pelo `session_id`, em `pc/data/state.json`. Uma trava de arquivo deixa vários agentes escreverem ao mesmo tempo (também no Windows).
- Cada ferramenta é acompanhada pelo `tool_use_id`. Com várias em paralelo (um build longo junto com um Read), o fim de uma não faz a sessão parecer "pensando": a que continua rodando passa para a barra.
- Do `Notification`, só contam os avisos em que o Claude espera uma resposta sua: pedido de permissão e perguntas (`permission_prompt`, `elicitation_dialog`…). O aviso de "parado há 60 s" (`idle_prompt`) e os outros são ignorados, para o Kindle não ficar "Te chamando!" depois de cada resposta.
- O hook também guarda o caminho do histórico da sessão (`transcript_path`). Quando você aperta Esc ou recusa uma permissão, nenhum hook dispara, mas o Claude Code grava no histórico a interrupção (`[Request interrupted by user…]`) ou a decisão de permissão. O agente lê o pedaço novo desses históricos a cada resposta ao Kindle e passa a sessão para "esperando você". Só vale a conversa principal: o histórico de um subagente não conta.
- **statusLine** (`pc/statusline.py`): guarda `rate_limits.five_hour` e `rate_limits.seven_day` em `pc/data/statusline.json`, e continua mostrando a statusLine que você já tinha. Ela roda no mesmo shell que o Claude Code usaria (bash; no Windows, Git Bash ou PowerShell). Se ela falhar ou não imprimir nada, aparece a linha do Claudinho, em vez de uma linha vazia.
- **Tokens**: o agente soma `input + output + cache_creation + cache_read` dos históricos em `~/.claude/projects/**/*.jsonl` (ou na pasta de `CLAUDE_CONFIG_DIR`), sem contar duas vezes a mesma mensagem, a cada 30 s no máximo. Cada arquivo é lido só a partir de onde parou da última vez.

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

Se o horário de reset de um limite já passou, o agente manda 0%. O `statusline.json` só muda com o Claude Code aberto, e sem essa regra o Kindle continuaria mostrando o uso da janela que já terminou.

O `rev` ignora o `agora` e arredonda os números para a precisão que o painel mostra (`2,5 mi`, `32 mil`). Assim, o Kindle só redesenha quando a tela realmente mudaria.

Uma sessão "trabalhando" sem nenhum evento há mais de 10 minutos passa a contar como parada. O `Stop` não dispara quando você interrompe com Esc, e um erro da API dispara o `StopFailure`; o Esc o agente vê pelo histórico (acima), e esta regra fica de reserva para quando nem o histórico mostra nada. Uma ferramenta que roda mais de 10 minutos seguidos (um build longo, por exemplo) também cai nessa regra. Uma ferramenta que termina com erro (testes falhando, por exemplo) dispara `PostToolUseFailure` em vez de `PostToolUse`, e conta como terminada do mesmo jeito.

Depois que você aprova um pedido de permissão, o Kindle continua em "Te chamando!" até a ferramenta terminar: o Claude Code não avisa os hooks quando a permissão é dada, só quando a ferramenta acaba. Com ferramentas rápidas isso nem aparece; com um build longo, sim. Se você recusa (ou aperta Esc), o histórico mostra na hora, e o Kindle sai do "Te chamando!" na busca seguinte.

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
- o padrão de busca (Grep, Glob), mesmo quando a busca tem uma pasta;
- do `TaskCreate`/`TaskUpdate`, só o título (`subject`), nunca o texto da tarefa;
- o domínio de uma URL (WebFetch), sem o caminho;
- de uma ferramenta MCP (Linear, Gmail, Notion…), só o nome da função (`create_issue`), porque os campos dela costumam ser conteúdo seu, como o texto de uma issue ou o assunto de um e-mail;
- a descrição curta que o Claude dá ao comando (Bash) ou à tarefa. Se o comando não tiver descrição, vai só o nome do programa (`npm …`), nunca o comando com os argumentos.

Prompts, textos de pesquisa, comandos inteiros e conteúdo de arquivos não saem do PC. Cada texto é cortado em até 80 caracteres.

## Transporte

O Kindle sempre **puxa**, pela rede de casa:

| | |
|---|---|
| Endereço | `http://IP-DO-PC:8787/estado.json` |
| Autenticação | `Authorization: Bearer TOKEN` (o token do `pc/config.json`) |
| Nada mudou | `304` (com `If-None-Match`) |

É HTTP simples, sem criptografia. Um aparelho que só está na mesma rede não consegue pedir o estado sem o token. Mas o token vai na mesma requisição, também em texto puro: quem consegue ver o tráfego (numa Wi-Fi aberta, por exemplo) vê o estado e o token, e daí pode pedir quando quiser. Para trocar o token: `python3 pc/setup.py connection --new-token`, e copie o plugin de novo.

O agente responde em todas as redes em que o computador estiver. Para responder só numa, ponha o IP dela em `"host"` no `pc/config.json` (o setup mantém essa chave). Se o computador sair dessa rede, o agente avisa ao abrir.

## No Kindle (plugin)

### Buscas

- A cada **60 s** lendo e **30 s** com o painel aberto (configurável). Na biblioteca, sem painel, não busca nada.
- A requisição roda num **subprocesso** (como o KOReader faz em outras buscas em segundo plano). O processo principal só confere a cada 0,25 s se a resposta chegou, então a virada de página nunca espera a rede.
- Se o Wi-Fi está desligado, nem tenta (não fica travado resolvendo nome).
- Ao dormir, para. Ao acordar, busca em 3 s. Quando o Wi-Fi conecta, busca em 1 s.
- Três buscas seguidas sem resposta, ou mais de 10 minutos acordado sem nenhuma resposta, e o Kindle mostra **"Sem sinal do PC"**. O tempo dormindo não conta: ao acordar, a página mostra o último estado até a busca seguinte, em vez de piscar "sem sinal" a cada despertar.

### Relógios

O Kindle calcula a diferença entre o relógio dele e o do PC a cada resposta completa (o `agora` do estado). O "há X min" usa essa correção, então um Kindle com a hora errada não mostra tempos absurdos. O relógio grande do painel é o do Kindle.

### Overlay

O overlay é registrado como um *view module* do leitor (`ReaderView:registerViewModule`), o mesmo mecanismo que o KOReader usa para a orelha de marcador e o rodapé. Por isso:

- ele é desenhado junto com cada página, sem piscar a mais na virada;
- quando o estado muda, o plugin pede refresh **só do retângulo do cantinho** (`ui`), e só se o quadro ou o estilo mudaram;
- não há animação por padrão: são três desenhos fixos, para não gastar bateria nem deixar fantasma no e-ink.

O overlay é desenhado por cima da página. Nos livros de texto (EPUB, FB2…), o plugin compara a caixa com as margens do livro e, se ela cobre texto, avisa uma vez (por canto e tamanho) com a margem que resolve. Com as margens padrão do KOReader (15 em cima e embaixo), no Kindle básico o tamanho pequeno pede 66. Nos PDFs não dá para saber onde fica o texto, e o aviso não aparece.

**Na barra de status**: em vez do desenho, o plugin põe um texto curto ("Claude: TE CHAMANDO!") no "conteúdo externo" do rodapé do KOReader, o mesmo mecanismo do plugin de timer de leitura. Nunca cobre o texto, mas só aparece com a barra de status visível.

### Painel

- Desenhado deitado em 800×600 × escala, com as posições, fontes e espaçamentos do original, e girado para a tela em pé (90° ou 270°). Em outras telas, a escala ajusta e o pixel art usa células inteiras.
- Estado novo do PC: redesenha tudo, com refresh completo quando o modo muda.
- A cada minuto: só a coluna da esquerda (relógio, data e "há X min").
- A cada 10 trocas (estados novos e minutos), um refresh completo limpa os fantasmas do e-ink. Os minutos contam porque, com o Claude parado, não chega estado novo, mas a animação continua: o painel na mesa leva um refresh completo a cada 10 minutos.
- Animação: só o retângulo do mascote, 1,5 s por quadro (1 s pedindo permissão, 4 s descansando). Trabalhando, sorteia 10 blocos entre sopa, cebola, tempero e frigideira, sem repetir o mesmo bloco seguido.
- Enquanto está aberto, avisa o KOReader para não suspender e, no Kindle, desliga o protetor de tela (`preventScreenSaver`). Ao fechar, devolve tudo como estava. Se o KOReader fechar ou travar com o painel aberto, fica gravada uma marca, e o próximo início do KOReader devolve o protetor de tela.

### Fontes

O KOReader abre fontes variáveis só no peso padrão. Por isso o plugin traz Inter Tight ExtraBold/Black e JetBrains Mono Regular/Bold como arquivos estáticos, gerados com `tools/gerar_fontes.py`.

## Bateria

Não foi medida no aparelho. O que mais gasta é o Wi-Fi ligado. Lendo com o overlay, são uma busca pequena por minuto e um refresh minúsculo só quando o estado muda. O painel aberto, com animação, gasta bem mais: deixe no carregador.
