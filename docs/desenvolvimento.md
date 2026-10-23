# Desenvolvimento

## Testes automáticos

O desenho e a lógica do plugin rodam fora do Kindle, num LuaJIT puro, com o Blitbuffer, o FreeType e o RenderText de verdade do KOReader. Precisa:

- LuaJIT (`apt install luajit`, ou compile de https://github.com/LuaJIT/LuaJIT);
- os fontes do [koreader](https://github.com/koreader/koreader) e do [koreader-base](https://github.com/koreader/koreader-base) clonados;
- a `libfreetype.so.6` do sistema (o `boot.lua` procura nos lugares de costume e cria o link em `libs/`, na pasta onde você roda; em outro lugar, defina `FREETYPE=caminho/da/libfreetype.so.6`).

```sh
# lado do PC (so Python): hooks, privacidade das descricoes, tokens, setup e servidor
python3 tools/testes_pc.py

export KO=~/src/koreader KOBASE=~/src/koreader-base

# logica pura: formatos, estado, relogios, json, empacotamento
luajit tools/harness/testes.lua

# o plugin inteiro com um KOReader simulado, contra o agente rodando
python3 pc/claudinho.py --demo chamando &
luajit tools/harness/fumaca.lua http://127.0.0.1:8787/estado.json SEU_TOKEN /tmp

# imagens do painel e do overlay (PGM; converta com qualquer programa de imagem)
luajit tools/harness/render.lua estado.json painel.pgm 1 13:12 "qui 22/10"   # [pt|en] no fim
luajit tools/harness/imagens.lua /tmp        # em portugues
luajit tools/harness/imagens.lua /tmp en     # em ingles
```

O `fumaca.lua` confere: menu registrado, overlay no ReaderView, leitura em subprocesso, refresh só do cantinho, overlay acima da barra de status, painel girado, animação só na região do mascote, refresh completo a cada 10 minutos com o painel parado, toque fecha, o modo "na barra de status", o aviso de margem, "sem sinal" depois de 3 falhas e, simulando um Kindle, o protetor de tela devolvido depois de um travamento.

O `testes_pc.py` também confere, com históricos falsos, que um Esc ou uma permissão recusada tiram a sessão do "Te chamando!", e que os comandos gravados para o PowerShell (Windows sem Git Bash) usam `&` e barras normais. Esses comandos não foram rodados num Windows de verdade.

## Regerar sprites e fontes

```sh
python3 tools/gerar_sprites.py                       # design/sprites.json -> sprites.lua
pip install fonttools
python3 tools/gerar_fontes.py InterTight.ttf JetBrainsMono.ttf   # as variaveis do kindle-claude
```

Os sprites seguem a regra do original: grade 36×24, `#` traço, `+` cinza, `.` vazio. A arte em texto está em `design/pixelart/chef.py`.

## Detalhes do KOReader que importam

- **Nomes de módulos:** o KOReader junta as pastas de todos os plugins no caminho de busca do Lua. Por isso os módulos ficam em `claudinho/…` (`require("claudinho/estado")`), para não colidir com módulos do KOReader como `json`.
- **Fontes:** o `Font:getFace` só aceita caminho de arquivo começando com `/` ou `./`, e escala o tamanho pela tela. O plugin compensa a escala para desenhar no pixel exato do design.
- **Textos:** tudo o que aparece no Kindle (painel, menu, avisos, erros) está em `claudinho/textos.lua`, em português e inglês. O `testes.lua` confere que os dois idiomas têm as mesmas chaves. Mudou um texto? Gere as imagens nos dois idiomas com o `imagens.lua` para ver se cabe: o título tem 240 de largura, a linha de baixo 240 e o "zera às" 220 (unidades de design, em 800×600).
- **Instâncias:** o KOReader cria uma instância nova do plugin ao trocar entre a biblioteca e um livro. O último estado fica num módulo compartilhado, então nada some na troca.
