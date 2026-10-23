# Como funciona

## De onde vêm os dados (no PC)

Igual ao [kindle-claude](https://github.com/guithepc/kindle-claude), de onde vem esta parte:

- **Hooks** (`pc/hook.py`): `PreToolUse`, `PostToolUse`, `UserPromptSubmit`, `Notification`, `Stop` e `SessionEnd` gravam cada sessão, pelo `session_id`, em `pc/data/state.json`. Uma trava de arquivo deixa vários agentes escreverem ao mesmo tempo (agora também no Windows).
- **statusLine** (`pc/statusline.py`): guarda `rate_limits.five_hour` e `rate_limits.seven_day` em `pc/data/statusline.json`, e continua mostrando a statusLine que você já tinha.
- **Tokens**: o agente soma `input + output + cache_creation + cache_read` dos históricos em `~/.claude/projects/**/*.jsonl`, sem contar duas vezes a mesma mensagem, a cada 30 s no máximo.

## O estado

O agente (`pc/claudinho.py`) junta as sessões, escolhe a mais urgente (pedindo permissão > trabalhando > terminou > descansando) e monta o estado:

| Campo | O que é |
|---|---|
| `modo` | `cozinhando`, `chamando` (pedindo permissão), `prato` (acabou de terminar), `esperando`, `descansando` |
| `desde` | quando o modo começou (relógio do PC) |
| `ferramenta`, `descricao` | o que está rodando agora, ou "pensando…" / "nada no fogo" |
| `ativos`, `projeto` | quantas sessões estão trabalhando e o projeto da que aparece |
| `antes` | as últimas 4 ferramentas |
| `sessao`, `semana` | `pct` usado e o texto de quando zera, já no fuso do PC |
| `tokens` | `hoje`, `hora`, `media`, arredondados ao que o Kindle mostra |
| `rev` | resumo do conteúdo: muda só quando algo visível muda |
| `agora` | relógio do PC no momento |
| `pc_offline` | o agente foi encerrado |

O `rev` ignora o `agora` e arredonda os números para a precisão que o painel mostra. Assim, o Kindle e o relay só trabalham quando a tela realmente mudaria.

## Transporte

O Kindle sempre **puxa**. Os dois modos falam o mesmo protocolo:

| | Modo local | Modo remoto |
|---|---|---|
| Endereço | `http://IP-DO-PC:8787/estado.json` | `https://SEU-RELAY.workers.dev/estado` |
| Quem responde | o agente no PC | o relay (Cloudflare Worker + Durable Object) |
| Autenticação | `Authorization: Bearer TOKEN` | idem (o PC grava com outro token) |
| Nada mudou | `304` (com `If-None-Match`) | `304` |
| `X-Claudinho-Idade` | sempre 0 | segundos desde o último envio do PC |

## No Kindle (plugin)

### Buscas

- A cada **60 s** lendo e **30 s** com o painel aberto (configurável). Na biblioteca, sem painel, não busca nada.
- A requisição roda num **subprocesso** (como o KOReader faz em outras buscas em segundo plano). O processo principal só confere a cada 0,25 s se a resposta chegou, então a virada de página nunca espera a rede.
- Se o Wi-Fi está desligado, nem tenta (não fica travado resolvendo nome).
- Ao dormir, para. Ao acordar, busca em 3 s. Quando o Wi-Fi conecta, busca em 1 s.

### Relógios

O Kindle calcula a diferença entre o relógio dele e o do PC a cada resposta completa (`agora` do estado mais a idade informada pelo servidor). O "há X min" e o "sem sinal" usam essa correção, então um Kindle com a hora errada não mostra tempos absurdos. O relógio grande do painel é o do Kindle.

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
