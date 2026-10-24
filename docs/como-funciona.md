# Como funciona

## De onde vêm os dados (no PC)

Igual ao [kindle-claude](https://github.com/guithepc/kindle-claude), de onde vem esta parte:

- **Hooks** (`pc/hook.py`): `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `UserPromptSubmit`, `Notification`, `Stop`, `StopFailure` e `SessionEnd` gravam cada sessão, pelo `session_id`, em `pc/data/state.json`. Uma trava de arquivo deixa vários agentes escreverem ao mesmo tempo (também no Windows).
- Cada ferramenta é acompanhada pelo `tool_use_id`. Com várias em paralelo (um build longo junto com um Read), o fim de uma não faz a sessão parecer "pensando": a que continua rodando passa para a barra.
- Do `Notification`, só contam os avisos em que o Claude espera uma resposta sua: pedido de permissão e perguntas (`permission_prompt`, `elicitation_dialog`…). O aviso de "parado há 60 s" (`idle_prompt`) e os outros são ignorados, para o Kindle não ficar "Te chamando!" depois de cada resposta.
- O hook também guarda o caminho do histórico da sessão (`transcript_path`). Quando você aperta Esc ou recusa uma permissão, nenhum hook dispara, mas o Claude Code grava no histórico a interrupção (`[Request interrupted by user…]`) ou a decisão de permissão. O agente lê o pedaço novo desses históricos a cada resposta ao Kindle e passa a sessão para "esperando você". Só vale a conversa principal: o histórico de um subagente não conta.
- **Uso da conta** (`pc/claudinho.py`): a cada 2 minutos, numa thread à parte (a resposta ao Kindle nunca espera a rede), o agente pede o uso da sessão de 5 h e da semana ao mesmo endpoint do `/usage` do Claude Code (`api.anthropic.com/api/oauth/usage`), com o login do `claude` do terminal, em `~/.claude/.credentials.json`. Funciona mesmo usando só o app de desktop, que não roda a statusLine. Detalhes em [Uso da conta](#uso-da-conta).
- **statusLine** (`pc/statusline.py`), a reserva: guarda `rate_limits.five_hour` e `rate_limits.seven_day` em `pc/data/statusline.json`, e continua mostrando a statusLine que você já tinha. O uso da conta, quando há, vale mais que ela. Ela roda no mesmo shell que o Claude Code usaria (bash; no Windows, Git Bash ou PowerShell). Se ela falhar ou não imprimir nada, aparece a linha do Claudinho, em vez de uma linha vazia.
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

Se o horário de reset de um limite já passou, o agente manda 0%. O `statusline.json` só muda com o Claude Code aberto (e o uso da conta pode estar sem rede), e sem essa regra o Kindle continuaria mostrando o uso da janela que já terminou.

O `rev` ignora o `agora` e arredonda os números para a precisão que o painel mostra (`2,5 mi`, `32 mil`). Assim, o Kindle só redesenha quando a tela realmente mudaria.

Uma sessão "trabalhando" sem nenhum evento há mais de 10 minutos passa a contar como parada. O `Stop` não dispara quando você interrompe com Esc, e um erro da API dispara o `StopFailure`; o Esc o agente vê pelo histórico (acima), e esta regra fica de reserva para quando nem o histórico mostra nada. Uma ferramenta que roda mais de 10 minutos seguidos (um build longo, por exemplo) também cai nessa regra. Uma ferramenta que termina com erro (testes falhando, por exemplo) dispara `PostToolUseFailure` em vez de `PostToolUse`, e conta como terminada do mesmo jeito.

Depois que você aprova um pedido de permissão, o Kindle continua em "Te chamando!" até a ferramenta terminar: o Claude Code não avisa os hooks quando a permissão é dada, só quando a ferramenta acaba. Com ferramentas rápidas isso nem aparece; com um build longo, sim. Se você recusa (ou aperta Esc), o histórico mostra na hora, e o Kindle sai do "Te chamando!" na busca seguinte.

## Uso da conta

O token de acesso do `claude` dura umas 8 horas, e só o `claude` do terminal o renova. Quem usa o app de desktop fica com ele vencido quase sempre. Por isso, quando ele vence (ou o endpoint responde 401), o agente renova do mesmo jeito que o Claude Code:

- `POST https://platform.claude.com/v1/oauth/token` com `grant_type=refresh_token`, o refresh token, o `client_id` do Claude Code e os mesmos escopos;
- grava o token novo, o refresh token novo e os vencimentos no `.credentials.json`. Gravar é obrigatório: cada renovação troca também o refresh token, e sem gravar o `claude` do terminal ficaria com um que não vale mais;
- muda só a parte `claudeAiOauth`, o resto do arquivo (o login dos plugins MCP, por exemplo) fica igual;
- antes, copia o arquivo para `.credentials.json.bak-claudinho`; grava num arquivo temporário e troca de uma vez, com as permissões do original (600 no Linux e no macOS);
- relê o arquivo antes de renovar: se o `claude` renovou nesse meio-tempo, usa o token dele.

Se a renovação for recusada (refresh token vencido ou revogado), o agente avisa uma vez para rodar `claude` e `/login`, e o % volta a vir da statusLine. Sem rede, tenta de novo em 10 minutos, mantendo o último valor; um limite que já zerou vira 0% (regra acima).

O endpoint é interno (o mesmo que o Claude Code usa), não documentado, e pode mudar. Para não usar: `"uso_da_conta": false` no `pc/config.json`. No macOS, o Claude Code guarda o login no Keychain, não no arquivo: aí o % vem só da statusLine.

## O que sai do PC

Para a Anthropic, só o que o Claude Code já manda: o pedido de uso (`api.anthropic.com`) e a renovação do login (`platform.claude.com`), com o seu token. Nada do estado nem dos históricos.

Para o Kindle, o estado é um JSON pequeno, assim:

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

- Com o painel aberto, a cada **30 s** (configurável). Na biblioteca, sem painel, não busca nada.
- **Pausado** (Claudinho → Pausar, ou o gesto "pausar/retomar"), não busca nada: nem lendo, nem com o painel, nem ao acordar ou quando o Wi-Fi conecta. A linha some (e a margem de cima volta à sua), o aviso de permissão não aparece e o painel não abre. A pausa fica gravada e vale até você retomar. O plugin não liga nem desliga o Wi-Fi: para poupar o máximo, desligue o Wi-Fi do Kindle também.
- Lendo, em **Atualizar a cada → Lendo** você escolhe uma coisa só: **adaptativo** (o padrão) ou um tempo fixo (30 s, 1, 2 ou 5 min).
- O **adaptativo** segue o que o Claude está fazendo: trabalhando ou pedindo permissão, a cada 30 s, para o aviso de permissão chegar antes; logo depois de terminar, 1 min; parado, 3 min (abaixo dos 10 min que viram "sem sinal"); sem sinal do PC, 2, 4, 8 e então 10 min, dobrando a cada falha: com o PC desligado à noite, o Kindle quase não liga o Wi-Fi.
- Como o intervalo depende do estado novo, a próxima busca é agendada quando a resposta chega (o agendamento feito antes da busca fica de reserva, caso ela não volte).
- A requisição roda num **subprocesso** (como o KOReader faz em outras buscas em segundo plano). O processo principal só confere a cada 0,25 s se a resposta chegou, então a virada de página nunca espera a rede.
- Se o Wi-Fi está desligado, nem tenta (não fica travado resolvendo nome).
- Ao dormir, para. Ao acordar, busca em 3 s. Quando o Wi-Fi conecta, busca em 1 s.
- Três buscas seguidas sem resposta, ou mais de 10 minutos acordado sem nenhuma resposta, e o Kindle mostra **"Sem sinal do PC"**. O tempo dormindo não conta: ao acordar, a página mostra o último estado até a busca seguinte, em vez de piscar "sem sinal" a cada despertar.

### Relógios

O Kindle calcula a diferença entre o relógio dele e o do PC a cada resposta completa (o `agora` do estado). O "há X min" usa essa correção, então um Kindle com a hora errada não mostra tempos absurdos. O relógio grande do painel é o do Kindle.

### Linha do topo

A linha "Claude ●○○ 75%" é registrada como um *view module* do leitor (`ReaderView:registerViewModule`), o mesmo mecanismo que o KOReader usa para a orelha de marcador e o rodapé. Por isso:

- ela é desenhada junto com cada página, sem piscar a mais na virada;
- a imagem dela (texto em Inter Tight, bolinhas desenhadas como círculos com antialiasing, pílula preta pedindo permissão) é feita uma vez e reaproveitada a cada página, até o que ela mostra mudar;
- quando muda (estado, % ou número de agentes), o plugin pede refresh **só da faixa dela** (`ui`), na largura toda, porque a largura muda junto ("9%" → "10%", "×3").

O que ela mostra sai de `E.linha_topo` (`claudinho/estado.lua`): a bolinha 1 para parado e terminou, 2 para trabalhando, 3 para pedindo permissão; o `%` da sessão de 5 h, limitado entre 0 e 100; e, com mais de um agente trabalhando ou pedindo permissão, "Claude ×N". Sem o `%` (plano sem limite, ou janela nova sem resposta ainda), mostra 0%: nada foi gasto de um limite que não existe ou acabou de começar. Só sem sinal do PC mostra "--", porque aí o Kindle não sabe, e um 0% pareceria um número de verdade.

Fica centralizada, 4 px abaixo do topo (ou do cabeçalho do livro, se ele estiver ligado), com 20 px de altura no Kindle básico.

**Tocar na linha abre o painel.** O plugin registra uma zona de toque (`registerTouchZones`) na faixa de cima da tela, na frente das do menu do KOReader (`readermenu_tap`, `readermenu_ext_tap`) e das de virar a página, como o rodapé faz. A zona é larga, mas o plugin só fica com o toque que cai na linha, com 10 px de folga para o dedo. Fora dela, ou com a linha desligada, ele devolve `false`, e o KOReader passa o toque adiante: o menu de cima continua abrindo com um toque no resto da faixa de cima, ou deslizando de cima para baixo.

**O aviso de permissão**: quando o estado passa a "pedindo permissão" enquanto você lê, o plugin mostra um aviso do KOReader na página (`InfoMessage`, some em 10 s ou com um toque), com a ferramenta e a descrição. Ele avisa uma vez por pedido: o `desde` do estado é a hora em que aquele pedido chegou (o `waiting_since` do hook), então as buscas seguintes do mesmo pedido não repetem, e um pedido novo avisa de novo. Com o painel aberto não avisa, porque o painel já mostra "Te chamando!", e esse pedido conta como visto. Com a linha do topo desligada e o aviso ligado, o plugin continua buscando o estado enquanto você lê.

**O espaço dela**: o mecanismo de texto do KOReader (crengine) só aceita as quatro margens da página (`setPageMargins`), e as linhas são calculadas antes de serem divididas em páginas; por isso não dá para o texto contornar só a linha. Nos livros de texto (EPUB, FB2…), o plugin aumenta a margem de cima até a linha caber, mais 4 px de respiro: com as margens padrão do KOReader, de 15 para 28. Detalhes:

- muda só a margem aplicada (`ReaderTypeset.unscaled_margins`), com o mesmo evento `SetPageMargins` que o KOReader usa. A que o KOReader grava no livro (`configurable.t_page_margin`) continua a sua, e é a ela que o plugin volta quando você desliga a linha;
- ajusta no `PreRenderDocument`, antes da primeira paginação, então o livro é paginado uma vez só ao abrir;
- depende só de a linha estar ligada, não do que o Claude está fazendo: cada troca de margem faz o KOReader paginar o livro de novo;
- se você mudar a margem no menu de baixo para menos que o necessário, a página continua com o necessário (e o livro guarda o que você escolheu); para mais, vale a sua.

Nos PDFs a página é fixa: a margem não muda, e a linha pode cobrir o começo da página.

### Painel

- Desenhado deitado em 800×600 × escala, com as posições, fontes e espaçamentos do original, e girado para a tela em pé (90° ou 270°). Em outras telas, a escala ajusta e o pixel art usa células inteiras. Todos os Kindles têm quase a mesma proporção do desenho (3:4): sobram no máximo 19 px em branco (Kindle básico de 11ª geração, 1,3% do lado); no Paperwhite e no Scribe, nenhum.
- Se a tela muda com o painel aberto (o Kindle girado, ou a janela redimensionada no computador), o painel se refaz no tamanho novo: escala, rotação, centro e a área de toque para fechar.
- Estado novo do PC: redesenha tudo, com refresh completo quando o modo muda.
- A cada minuto: só a coluna da esquerda (relógio, data e "há X min").
- A cada 10 trocas (estados novos e minutos), um refresh completo limpa os fantasmas do e-ink. Os minutos contam porque, com o Claude parado, não chega estado novo, mas a animação continua: o painel na mesa leva um refresh completo a cada 10 minutos.
- Animação: só o retângulo do mascote, 1,5 s por quadro (1 s pedindo permissão, 4 s descansando). Trabalhando, sorteia 10 blocos entre sopa, cebola, tempero e frigideira, sem repetir o mesmo bloco seguido.
- Enquanto está aberto, avisa o KOReader para não suspender e, no Kindle, desliga o protetor de tela (`preventScreenSaver`). Ao fechar, devolve tudo como estava. Se o KOReader fechar ou travar com o painel aberto, fica gravada uma marca, e o próximo início do KOReader devolve o protetor de tela.

### Fontes

O KOReader abre fontes variáveis só no peso padrão. Por isso o plugin traz Inter Tight ExtraBold/Black e JetBrains Mono Regular/Bold como arquivos estáticos, gerados com `tools/gerar_fontes.py`.

## Bateria

Não foi medida no aparelho. O que mais gasta é o Wi-Fi ligado. Lendo com a linha do topo, no adaptativo, o Kindle faz uma busca pequena a cada 30 s com o Claude trabalhando, a cada 3 min com ele parado e cada vez menos com o PC desligado. A tela só leva um refresh minúsculo quando a linha muda. O painel aberto, com animação, gasta bem mais: deixe no carregador.
