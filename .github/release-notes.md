O status do Claude Code no seu Kindle, como um plugin do KOReader. Este Release serve para instalar **sem git**.

## O que baixar

- **`claudinho.koplugin-….zip`**: o plugin, para o Kindle.
- **Source code (zip)**: o projeto inteiro. Do computador, você só precisa da pasta `pc/`.

## No computador

Precisa de Python 3.9+ e do Claude Code.

1. Descompacte o **Source code (zip)** e abra um terminal na pasta.
2. Rode `python3 pc/setup.py` (no Windows, `python pc\setup.py`). No fim, ele mostra o **endereço** e o **token** para o Kindle: anote os dois.
3. Deixe rodando: `python3 pc/claudinho.py`.

## No Kindle

Precisa de jailbreak e do KOReader (guias no [Kindle Modding](https://kindlemodding.org/jailbreaking/)). Kindle e computador na mesma rede Wi-Fi.

1. Ligue o Kindle no cabo e descompacte o **`claudinho.koplugin-….zip`** dentro de `koreader/plugins/`. Tem que ficar `koreader/plugins/claudinho.koplugin/main.lua`.
2. Ejete e abra o KOReader. Em **Ferramentas → Claudinho (Claude Code) → Conexão**:
   - **Endereço**: o que o setup mostrou, como `http://192.168.0.10:8787/estado.json`;
   - **Token**: o que o setup mostrou.
3. **Conexão → Testar a conexão agora**. Deve aparecer "Conectado".

Atualizando de uma versão anterior: substitua a pasta `claudinho.koplugin` inteira. O endereço e o token ficam guardados nas configurações do KOReader.

Mais detalhes no [README](https://github.com/phnrezende/kindle-claude2.0#readme).

---

**English:** download `claudinho.koplugin-….zip`, unzip it into `koreader/plugins/` on the Kindle, and set **Claudinho → Connection → Address** and **Token** to what `python3 pc/setup.py` prints on the computer (from the Source code zip). Then **Test the connection now**.
