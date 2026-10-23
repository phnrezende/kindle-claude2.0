# Problemas e soluções

## Primeiro passo

No Kindle: **Claudinho → Conexão → Testar a conexão agora**. A mensagem diz o que falhou.

No PC:

```sh
python3 pc/claudinho.py --state           # o estado que o Kindle receberia
cat pc/data/state.json                    # o que os hooks gravaram
curl -H "Authorization: Bearer SEU_TOKEN" http://localhost:8787/estado.json
```

## Tabela

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| Menu Claudinho não aparece | pasta no lugar errado | tem que ficar `koreader/plugins/claudinho.koplugin/main.lua` (não uma pasta a mais dentro) |
| "token recusado" | token do Kindle diferente do PC | Conexão → Token, com o `token` de `pc/config.json` |
| "sem resposta" / "tempo esgotado" | IP do PC mudou, firewall, ou agente parado | confira o IP (`python3 pc/setup.py connection`), libere a porta 8787 no firewall, deixe o `claudinho.py` rodando |
| "Wi-Fi desligado" | o Kindle está sem rede | ligue o Wi-Fi no KOReader |
| Sempre "Fogão desligado" | os hooks não estão chegando | reinicie as sessões do Claude Code abertas antes do setup; confira `pc/data/state.json` |
| "--" no % da sessão e da semana | plano sem `rate_limits`, ou ainda sem resposta na sessão | aparece depois da primeira resposta, nos planos Pro/Max |
| Painel em inglês (ou em português) sem querer | o idioma segue o do KOReader | Claudinho → Idioma (*Language*) e escolha o idioma |
| Overlay cobre o texto | com as margens padrão, cobre o fim das primeiras linhas | aumente a margem que o aviso indicar (Margens, no menu de baixo) ou use Claudinho → Overlay na leitura → Onde mostrar → Na barra de status |
| Nada aparece na barra de status | a barra está escondida | toque embaixo da página para mostrar a barra de status do KOReader |
| Painel de cabeça para baixo do jeito que você segura | lado do logo | Claudinho → Painel → Logo do Kindle à direita |
| Kindle dorme com o painel aberto | opção desligada | Claudinho → Painel → Não deixar o Kindle dormir |
| Fantasmas no painel | e-ink | o painel faz refresh completo a cada 10 trocas (estados novos ou minutos, então no máximo a cada 10 min); trocar de estado também limpa |
| Kindle não dorme mais, depois de o KOReader fechar ou travar com o painel aberto | o protetor de tela ficou desligado | abra o KOReader de novo: no início, o plugin devolve o protetor de tela |
| Sempre "sem conexão" numa Wi-Fi de visitante ou do trabalho | a rede isola os aparelhos | use a rede de casa, ou o roteador do celular com o PC e o Kindle nele |
| "Te chamando!" sem nada pedindo permissão | versão antiga do Claude Code, sem `notification_type` | atualize o Claude Code |
| "Te chamando!" depois de aprovar | a ferramenta aprovada ainda está rodando | é normal: volta a "Cozinhando…" quando ela terminar |
| "Te chamando!" depois de recusar ou apertar Esc | sessão iniciada antes de atualizar o Claudinho (o hook ainda não sabia o caminho do histórico) | reinicie a sessão do Claude Code; até lá, sai sozinho em 30 min |
| Moveu a pasta do repositório e o Claude Code mostra erro de hook | os hooks apontam para a pasta antiga | rode `python3 pc/setup.py` de novo na pasta nova: ele troca os hooks antigos |
| Windows: erro de hook em todo comando, ou a statusLine some | os comandos foram gravados para um shell diferente do que o Claude Code usa (por exemplo, o Git Bash foi instalado ou removido depois do setup) | rode `python3 pc/setup.py` de novo; para forçar, `--shell bash` ou `--shell powershell` |
| Sempre "Fogão desligado", e você usa `CLAUDE_CONFIG_DIR` | o setup e o agente precisam da mesma variável | rode o setup e o `claudinho.py` num terminal com `CLAUDE_CONFIG_DIR` definida |
| Desconfia que alguém viu o token (Wi-Fi aberta, por exemplo) | o token vai sem criptografia | `python3 pc/setup.py connection --new-token` e copie o plugin de novo |
| O agente não abre: "Could not listen on …" | o `"host"` do `pc/config.json` não é um IP deste computador agora | corrija o `"host"` ou tire essa chave para responder em todas as redes |

## Deixar o agente sempre ligado

O `claudinho.py` só responde enquanto está rodando. Para ele subir sozinho quando você entra no computador (troque os caminhos pelos seus; `which python3` mostra o do Python):

**Linux (systemd)**: crie `~/.config/systemd/user/claudinho.service`:

```ini
[Unit]
Description=Claudinho (Claude Code no Kindle)

[Service]
ExecStart=/usr/bin/python3 /caminho/para/kindle-claude2.0/pc/claudinho.py
Restart=on-failure

[Install]
WantedBy=default.target
```

e rode `systemctl --user enable --now claudinho`. O log fica em `journalctl --user -u claudinho`.

**macOS (launchd)**: crie `~/Library/LaunchAgents/com.claudinho.agente.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.claudinho.agente</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>/caminho/para/kindle-claude2.0/pc/claudinho.py</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
</dict>
</plist>
```

e rode `launchctl load ~/Library/LaunchAgents/com.claudinho.agente.plist`. Na primeira vez, o macOS pode perguntar se o Python pode aceitar conexões: aceite.

**Windows**: aperte Win+R, digite `shell:startup` e crie ali um atalho para `pythonw.exe "C:\caminho\para\kindle-claude2.0\pc\claudinho.py"` (o `pythonw` roda sem janela).

Se você usa `CLAUDE_CONFIG_DIR`, defina a variável também no serviço (`Environment=` no systemd, `EnvironmentVariables` no launchd).

## Desfazer

```sh
python3 pc/setup.py remove           # tira hooks e statusLine (volta a sua statusLine antiga)
```

No Kindle, apague a pasta `koreader/plugins/claudinho.koplugin`.
