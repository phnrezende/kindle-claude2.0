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
| Overlay cobre o texto | margem do livro pequena | aumente a margem superior do livro, mude o canto ou use o tamanho Mini |
| Painel de cabeça para baixo do jeito que você segura | lado do logo | Claudinho → Painel → Logo do Kindle à direita |
| Kindle dorme com o painel aberto | opção desligada | Claudinho → Painel → Não deixar o Kindle dormir |
| Fantasmas no painel | e-ink | o painel faz refresh completo a cada 10 trocas; trocar de estado também limpa |
| Sempre "sem conexão" numa Wi-Fi de visitante ou do trabalho | a rede isola os aparelhos | use a rede de casa, ou o roteador do celular com o PC e o Kindle nele |
| "Te chamando!" sem nada pedindo permissão | versão antiga do Claude Code, sem `notification_type` | atualize o Claude Code |
| "Te chamando!" depois de aprovar | a ferramenta aprovada ainda está rodando | é normal: volta a "Cozinhando…" quando ela terminar |
| Moveu a pasta do repositório e o Claude Code mostra erro de hook | os hooks apontam para a pasta antiga | rode `python3 pc/setup.py` de novo na pasta nova: ele troca os hooks antigos |

## Desfazer

```sh
python3 pc/setup.py remove           # tira hooks e statusLine (volta a sua statusLine antiga)
```

No Kindle, apague a pasta `koreader/plugins/claudinho.koplugin`.
