# Desenvolvimento

## Testes automáticos

O desenho e a lógica do plugin rodam fora do Kindle, num LuaJIT puro, com o Blitbuffer, o FreeType e o RenderText de verdade do KOReader. Precisa:

- LuaJIT (`apt install luajit`, ou compile de https://github.com/LuaJIT/LuaJIT);
- os fontes do [koreader](https://github.com/koreader/koreader) e do [koreader-base](https://github.com/koreader/koreader-base) clonados;
- a `libfreetype.so.6` do sistema (o `boot.lua` procura nos lugares de costume e cria o link em `libs/`, na pasta onde você roda; em outro lugar, defina `FREETYPE=caminho/da/libfreetype.so.6`).

```sh
# lado do PC (so Python): hooks, privacidade das descricoes, tokens, uso da conta, setup e servidor
python3 tools/testes_pc.py

export KO=~/src/koreader KOBASE=~/src/koreader-base

# logica pura: formatos, estado, linha do topo, relogios, json, empacotamento
luajit tools/harness/testes.lua

# o plugin inteiro com um KOReader simulado, contra o agente rodando
python3 pc/claudinho.py --demo chamando &
luajit tools/harness/fumaca.lua http://127.0.0.1:8787/estado.json SEU_TOKEN /tmp

# imagens do painel e da linha do topo (PGM; converta com qualquer programa de imagem)
luajit tools/harness/render.lua estado.json painel.pgm 1 13:12 "qui 22/10"   # [pt|en] no fim
luajit tools/harness/render.lua --linha estado.json linha.pgm 2               # a linha, em escala 2
luajit tools/harness/imagens.lua /tmp        # em portugues
luajit tools/harness/imagens.lua /tmp en     # em ingles
```

O `fumaca.lua` confere: menu registrado, linha do topo no ReaderView (centralizada, pílula preta pedindo permissão), leitura em subprocesso, refresh só da faixa da linha, o aviso de permissão (uma vez por pedido, nada com a opção desligada ou com o painel aberto), desligar e ligar a linha, painel girado, animação só na região do mascote, refresh completo a cada 10 minutos com o painel parado, toque fecha, a margem de cima reservada (sem mexer na que o livro grava, abaixo do cabeçalho do livro, e de volta ao desligar), "sem sinal" depois de 3 falhas e, simulando um Kindle, o protetor de tela devolvido depois de um travamento.

O `testes_pc.py` também confere, com históricos falsos, que um Esc ou uma permissão recusada tiram a sessão do "Te chamando!", e que os comandos gravados para o PowerShell (Windows sem Git Bash) usam `&` e barras normais. Esses comandos não foram rodados num Windows de verdade.

O uso da conta é testado contra uma Anthropic de mentira (um servidor local; `CLAUDINHO_USO_URL` e `CLAUDINHO_TOKEN_URL` trocam os endereços), com um `.credentials.json` falso no HOME de teste: token válido (só consulta), vencido (renova como o Claude Code, grava só o `claudeAiOauth`, faz backup, mantém as permissões), recusado antes de vencer (renova e tenta de novo), renovação recusada (volta para a statusLine e pede `/login`), sem login e com `"uso_da_conta": false`.
## Regerar sprites e fontes

```sh
python3 tools/gerar_sprites.py                       # design/sprites.json -> sprites.lua
pip install fonttools
python3 tools/gerar_fontes.py InterTight.ttf JetBrainsMono.ttf   # as variaveis do kindle-claude
```

Os sprites seguem a regra do original: grade 36×24, `#` traço, `+` cinza, `.` vazio. A arte em texto está em `design/pixelart/chef.py`.

## Detalhes do KOReader que importam

- **Nomes de módulos:** o KOReader junta as pastas de todos os plugins no caminho de busca do Lua. Por isso os módulos ficam em `claudinho/…` (`require("claudinho/estado")`), para não colidir com módulos do KOReader como `json`.
- **Fontes:** até o KOReader 2026.07, o `Font:getFace` põe a pasta de fontes na frente de qualquer nome, até de um caminho absoluto (`./fonts//mnt/us/…`), e a fonte não abre: o plugin caía na fonte padrão. Por isso ele passa um caminho que sobe até a raiz a partir da pasta de fontes (`../../…/mnt/us/koreader/plugins/…`), que funciona nas versões antigas e nas novas (`arquivo_fonte`, em `main.lua`). O `getFace` também escala o tamanho pela tela; o plugin compensa para desenhar no pixel exato do design. O `fumaca.lua` simula o `getFace` e não pega esse tipo de problema: confira no emulador (o log mostra `Font … not supported`).
- **Textos:** tudo o que aparece no Kindle (painel, menu, avisos, erros) está em `claudinho/textos.lua`, em português e inglês. O `testes.lua` confere que os dois idiomas têm as mesmas chaves. Mudou um texto? Gere as imagens nos dois idiomas com o `imagens.lua` para ver se cabe: o título tem 240 de largura, a linha de baixo 240 e o "zera às" 220 (unidades de design, em 800×600).
- **Instâncias:** o KOReader cria uma instância nova do plugin ao trocar entre a biblioteca e um livro. O último estado fica num módulo compartilhado, então nada some na troca.
