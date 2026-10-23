# Testar no computador (emulador do KOReader)

O KOReader tem uma versão para Linux que roda numa janela. O plugin é o mesmo do Kindle, então dá para testar tudo antes de copiar para o aparelho: a linha do topo na leitura, o painel, o toque para voltar e a conexão com o agente.

Funciona numa máquina virtual Linux (Ubuntu, Debian, Fedora…) ou num Linux de verdade. No macOS também existe KOReader, mas este guia usa Linux.

## 1. Instalar o KOReader na VM

1. Abra a página de [releases do KOReader](https://github.com/koreader/koreader/releases) e baixe o arquivo que termina em **`.AppImage`** (x86_64). Também há um `.deb` para Ubuntu/Debian, se preferir instalar.
2. Torne executável e rode uma vez, para ele criar a pasta de configuração:

   ```sh
   chmod +x koreader-*.AppImage
   ./koreader-*.AppImage
   ```

   Se reclamar de FUSE (Ubuntu 22.04 em diante), instale `libfuse2` ou rode com `--appimage-extract-and-run`.
3. Feche o KOReader.

## 2. Colocar o plugin

O KOReader de computador procura plugins em `~/.config/koreader/plugins/`. Um link simbólico evita copiar de novo a cada mudança:

```sh
cd kindle-claude2.0
mkdir -p ~/.config/koreader/plugins
ln -s "$PWD/kindle/claudinho.koplugin" ~/.config/koreader/plugins/
```

## 3. Rodar o agente com dados de demonstração

Gere a configuração apontando para a própria VM (sem mexer no Claude Code):

```sh
python3 pc/setup.py --no-prompt --ip 127.0.0.1 --no-hooks
```

Deixe o agente rodando em outro terminal, com um estado fictício:

```sh
python3 pc/claudinho.py --demo chamando
```

Demos disponíveis: `cozinhando`, `cebola`, `pensando`, `chamando`, `prato`, `esperando`, `descansando`, `varios`. Para trocar, pare com Ctrl+C e rode com outra.

## 4. Abrir o KOReader com a tela do Kindle 10

O tamanho padrão do emulador já é 600×800, o mesmo do Kindle básico. Para ver quais áreas da tela são atualizadas (o equivalente ao "piscar" do e-ink), ligue o `EMULATE_READER_FLASH`:

```sh
EMULATE_READER_W=600 EMULATE_READER_H=800 EMULATE_READER_FLASH=1 ./koreader-*.AppImage
```

## 5. O que conferir

| Teste | Como | Esperado |
|---|---|---|
| Menu | clique no topo da tela → aba Ferramentas | item **Claudinho (Claude Code)** |
| Conexão | Claudinho → Conexão → Testar a conexão agora | "Conectado. Claude: Te chamando!" |
| Linha do topo | abra um livro (qualquer EPUB) | "Claude ○○● 11%" centralizada no topo, em branco numa pílula preta no demo `chamando`; o texto começa logo abaixo dela |
| Tocar na linha | clique na linha do topo | abre o painel; um clique no resto da faixa de cima abre o menu do KOReader, como antes |
| Aviso de permissão | abra um livro com o demo `chamando` | "O Claude está te chamando. Bash · Apagar a pasta build" uma vez; nas buscas seguintes, não repete |
| Só a linha atualiza | troque a demo e espere até 1 min (ou use "Testar a conexão") | com o `EMULATE_READER_FLASH`, só a faixa do topo pisca |
| Virar a página | vire algumas páginas | a linha continua lá, sem piscar a mais |
| Painel | Claudinho → Abrir o painel | o painel em pé (girado), com o mascote animando |
| Voltar | clique em qualquer lugar do painel | volta para o livro |
| Sem sinal | pare o agente e espere 3 buscas | linha cinza, sem bolinha cheia e com "--"; painel "Sem sinal do PC" |
| Desligar a linha | Claudinho → Mostrar o status no topo da página | a linha some e o texto sobe para a sua margem; ligando de novo, desce |

Livros para testar: qualquer EPUB de domínio público, por exemplo do [Projeto Gutenberg](https://www.gutenberg.org/).

Dica: para não esperar 60 s entre buscas, use **Claudinho → Atualizar a cada → Lendo → 30 segundos**.

## 6. Com o Claude Code de verdade

Rode o setup completo (`python3 pc/setup.py`), reinicie o Claude Code e use normalmente. A linha do topo e o painel passam a seguir as suas sessões.

## Onde ver erros

O KOReader de computador escreve o log no terminal. Erros do plugin aparecem com `Claudinho:`; para ver também as mensagens de depuração, ligue **Configurações → Dispositivo → Modo desenvolvedor → Ativar registro de depuração**.
