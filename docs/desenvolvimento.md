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

O `fumaca.lua` confere: menu registrado, endereço e token pelo menu (como no plugin do zip, sem `config.lua`), linha do topo no ReaderView (centralizada, pílula preta pedindo permissão), leitura em subprocesso, refresh só da faixa da linha, o toque na linha abrindo o painel (e o toque fora dela seguindo para o menu), o aviso de permissão (uma vez por pedido, nada com a opção desligada ou com o painel aberto), a busca (o intervalo de cada estado no adaptativo, os tempos fixos como escolha única no menu, e a próxima busca agendada com o estado novo), a pausa (nenhuma busca agendada, nem ao acordar; sem linha, margem, aviso nem painel; o gesto retoma, e pausar com o painel aberto o fecha), desligar e ligar a linha, painel girado, animação só na região do mascote, refresh completo a cada 10 minutos com o painel parado, toque fecha, a margem de cima reservada (sem mexer na que o livro grava, abaixo do cabeçalho do livro, e de volta ao desligar), "sem sinal" depois de 3 falhas e, simulando um Kindle, o protetor de tela devolvido depois de um travamento.

O `testes_pc.py` também confere, com históricos falsos, que um Esc ou uma permissão recusada tiram a sessão do "Te chamando!", e que os comandos gravados para o PowerShell (Windows sem Git Bash) usam `&` e barras normais. No Windows, ele também roda de verdade, numa pasta com espaço e acento, os hooks e a statusLine gravados pelo setup, no PowerShell e no Git Bash, como o Claude Code rodaria; e confere o `setup.py autostart`: o atalho na pasta Inicializar (`CLAUDINHO_STARTUP_DIR` troca a pasta no teste) abre o agente no `pythonw`, que responde e escreve o log.

O uso da conta é testado contra uma Anthropic de mentira (um servidor local; `CLAUDINHO_USO_URL` e `CLAUDINHO_TOKEN_URL` trocam os endereços), com um `.credentials.json` falso no HOME de teste: token válido (só consulta), vencido (renova como o Claude Code, grava só o `claudeAiOauth`, faz backup, mantém as permissões), recusado antes de vencer (renova e tenta de novo), renovação recusada (volta para a statusLine e pede `/login`), sem login e com `"uso_da_conta": false`.

## Testes no GitHub

O workflow `.github/workflows/testes.yml` roda a cada push na `main` e a cada pull request:

- `testes_pc.py` no Linux (Python 3.9, a menor versão suportada, e 3.13), no Windows e no macOS;
- `testes.lua`, `fumaca.lua` (contra o agente em `--demo chamando`) e `imagens.lua` (pt e en) no Linux, com o LuaJIT e os fontes do KOReader na versão de `KOREADER_VERSAO` (a mesma do emulador testado; o koreader-base vem como submódulo dela). Para testar com uma versão nova do KOReader, troque essa variável.

## Publicar uma versão

O plugin pronto para baixar (para quem não usa git) sai do workflow `.github/workflows/release.yml`. Ele roda quando uma tag `v*` chega ao GitHub:

1. Suba a versão em `VERSAO`, no `kindle/claudinho.koplugin/main.lua` (aparece em Claudinho → Sobre), e faça o commit.
2. `git tag v1.5 && git push origin v1.5`.

O workflow confere se a tag bate com o `VERSAO`, monta `claudinho.koplugin-v1.5.zip` a partir do repositório (sem o `config.lua`, que tem o endereço e o token de quem rodou o setup) e cria o Release com o texto de `.github/release-notes.md`. O GitHub junta o **Source code (zip)** sozinho.

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
