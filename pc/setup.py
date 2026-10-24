#!/usr/bin/env python3
"""Claudinho setup assistant (runs on the computer).

    python3 setup.py               turn on the hooks + statusLine and set up the connection
    python3 setup.py connection    only set up the connection again (IP, port, token)
    python3 setup.py remove        take the hooks and the statusLine out of Claude Code

Without questions (for scripts):
    python3 setup.py --no-prompt [--ip 192.168.0.10] [--port 8787] [--token X]
    --no-hooks    leave ~/.claude/settings.json alone
    --new-token   make a new token (copy the plugin to the Kindle again afterwards)
    --shell bash|powershell
                  Windows only: which shell Claude Code runs the commands with.
                  By default, bash when Git Bash is installed, PowerShell otherwise.

If CLAUDE_CONFIG_DIR is set, its settings.json is used instead of ~/.claude.

When it finishes it writes:
    pc/config.json                         what the agent (claudinho.py) uses
    kindle/claudinho.koplugin/config.lua   what the Kindle plugin uses

The setup always talks in English. The language of the Kindle screens is
chosen on the Kindle itself (Claudinho > Language).

(Os comentarios do codigo seguem em portugues. Os nomes antigos dos comandos,
como "conexao", "remover", --sem-perguntas, --sem-hooks e --porta, continuam
valendo.)
"""
import json
import os
import re
import secrets
import shutil
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA = os.path.join(BASE, "data")
CONFIG = os.path.join(BASE, "config.json")
ORIG = os.path.join(DATA, "orig_statusline.txt")
PLUGIN = os.path.join(ROOT, "kindle", "claudinho.koplugin")
PLUGIN_CONFIG = os.path.join(PLUGIN, "config.lua")
PY = sys.executable or "python3"
HOOK_PATH = os.path.join(BASE, "hook.py")
STATUS_PATH = os.path.join(BASE, "statusline.py")
# a marca no fim deixa reconhecer os comandos do Claudinho mesmo se a pasta mudar
MARCA = "--claudinho"
EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "PostToolUseFailure": "*", "UserPromptSubmit": None,
          "Notification": None, "Stop": None, "StopFailure": None, "SessionEnd": None}
# um comando como os nossos: "python" ".../pc/hook.py"
CAMINHO_PC = re.compile(r'"([^"]*[\\/]pc[\\/](hook|statusline)\.py)"')

sys.path.insert(0, BASE)
import claudinho  # noqa: E402  (mesmo diretorio)
import shells  # noqa: E402

SETTINGS = os.path.join(claudinho.pasta_claude(), "settings.json")


def comando(script, shell="bash", sistema=None):
    """O comando que o Claude Code roda para um dos nossos scripts.

    No Windows os caminhos vao com barras normais, que o Git Bash e o PowerShell
    entendem (o Git Bash come as barras invertidas fora de aspas). No PowerShell,
    um caminho entre aspas no comeco do comando so roda com o operador &."""
    py, alvo = PY, script
    if (sistema or os.name) == "nt":
        py, alvo = py.replace("\\", "/"), alvo.replace("\\", "/")
    if shell == "powershell":
        return f'& "{py}" "{alvo}" {MARCA}'
    return f'"{py}" "{alvo}" {MARCA}'


def deste_repo(cmd, arquivo):
    """O comando roda o `arquivo` desta pasta (com barras de qualquer tipo)?"""
    proprio = os.path.join(BASE, arquivo)
    cmd = cmd or ""
    return proprio in cmd or proprio.replace("\\", "/") in cmd


# ------------------------------------------------------------------ util

def tem_opcao(*nomes):
    return any(n in sys.argv for n in nomes)


def args_opt(*nomes, default=None):
    for name in nomes:
        if name in sys.argv:
            i = sys.argv.index(name)
            if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
                return sys.argv[i + 1]
            sys.exit(f"Missing value for {name}.")
    return default


def interativo():
    return not tem_opcao("--no-prompt", "--sem-perguntas") and sys.stdin.isatty()


def perguntar(texto, padrao=""):
    if not interativo():
        return padrao
    sufixo = f" [{padrao}]" if padrao else ""
    resp = input(f"{texto}{sufixo}: ").strip()
    return resp or padrao


def porta_valida(valor):
    valor = str(valor).strip()
    if valor.isdigit() and 0 < int(valor) < 65536:
        return int(valor)
    return None


def titulo(txt):
    print(f"\n== {txt}")


# ------------------------------------------------------------------ hooks

def comando_nosso(cmd, arquivo):
    """O comando roda o `arquivo` ("hook.py" ou "statusline.py") do Claudinho?

    Vale para esta pasta, para os comandos com a marca e para instalacoes de uma
    pasta que nao existe mais (o repositorio mudou de lugar): esses comandos so
    dariam erro, entao sao trocados pelos novos."""
    cmd = cmd or ""
    if deste_repo(cmd, arquivo) or (MARCA in cmd and arquivo in cmd):
        return True
    m = CAMINHO_PC.search(cmd)
    return bool(m and m.group(2) + ".py" == arquivo and not os.path.exists(m.group(1)))


def is_ours(entry):
    if not isinstance(entry, dict):
        return False
    return any(isinstance(h, dict) and comando_nosso(h.get("command"), "hook.py")
               for h in entry.get("hooks") or [])


def antigos(entries):
    """Quantos desses hooks sao do Claudinho, mas de outra pasta (que mudou de
    lugar ou e outra copia do repositorio)."""
    return sum(1 for e in entries if isinstance(e, dict) for h in e.get("hooks") or []
               if isinstance(h, dict) and comando_nosso(h.get("command"), "hook.py")
               and not deste_repo(h.get("command"), "hook.py"))


def escolher_shell():
    """O shell dos comandos gravados: --shell, ou o que o Claude Code usaria aqui."""
    pedido = args_opt("--shell")
    if pedido:
        if pedido not in ("bash", "powershell"):
            sys.exit("Use --shell bash or --shell powershell.")
        return pedido
    shell = shells.shell_do_claude()
    if os.name == "nt":
        if shell == "bash":
            print("Git Bash found: Claude Code runs the commands with bash.")
        else:
            print("Git Bash not found: Claude Code runs the commands with PowerShell,"
                  " so they are written for PowerShell. If you install Git Bash later, run the setup again.")
    return shell


def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    # utf-8-sig: um settings.json salvo com BOM (Bloco de Notas antigo) tambem abre
    with open(SETTINGS, encoding="utf-8-sig") as f:
        return json.load(f)


def save_settings(cfg):
    os.makedirs(os.path.dirname(SETTINGS), exist_ok=True)
    if os.path.exists(SETTINGS):
        bak = f"{SETTINGS}.bak-claudinho-{int(time.time())}"
        shutil.copy2(SETTINGS, bak)
        print(f"Backed up settings.json to {bak}")
    tmp = SETTINGS + ".tmp-claudinho"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS)         # o Claude Code nunca le um arquivo pela metade


def instalar_hooks():
    titulo("Claude Code hooks and statusLine")
    shell = escolher_shell()
    hook_cmd, status_cmd = comando(HOOK_PATH, shell), comando(STATUS_PATH, shell)
    cfg = load_settings()
    hooks = cfg.setdefault("hooks", {})
    velhos = sum(antigos(lst) for lst in hooks.values() if isinstance(lst, list))
    for event in list(hooks):                     # tira os nossos de todos os eventos
        if not isinstance(hooks[event], list):
            continue
        hooks[event] = [e for e in hooks[event] if not is_ours(e)]
        if not hooks[event]:
            del hooks[event]
    for event, matcher in EVENTS.items():
        lst = hooks.get(event) if isinstance(hooks.get(event), list) else []
        h = {"type": "command", "command": hook_cmd}
        if shell == "powershell":
            h["shell"] = "powershell"             # campo "shell" dos hooks: sem adivinhar
        entry = {"hooks": [h]}
        if matcher:
            entry["matcher"] = matcher
        lst.append(entry)
        hooks[event] = lst

    os.makedirs(DATA, exist_ok=True)
    if velhos:
        print(f"Replaced {velhos} Claudinho hook(s) that pointed to another folder"
              " (an old or moved copy) with the ones from this folder.")
    atual = cfg.get("statusLine") if isinstance(cfg.get("statusLine"), dict) else {}
    current = atual.get("command", "")
    if current and not comando_nosso(current, "statusline.py"):
        with open(ORIG, "w", encoding="utf-8") as f:
            f.write(current)
        print("Your old statusLine was saved and will keep showing.")
    # padding, refreshInterval... da sua statusLine continuam valendo
    extras = {k: v for k, v in atual.items() if k not in ("type", "command")}
    cfg["statusLine"] = {**extras, "type": "command", "command": status_cmd}
    save_settings(cfg)
    print(f"Hooks are on ({SETTINGS}). Restart any Claude Code sessions that were already open.")


def remover_hooks():
    cfg = load_settings()
    hooks = cfg.get("hooks", {})
    for event in list(hooks):
        if not isinstance(hooks[event], list):
            continue
        hooks[event] = [e for e in hooks[event] if not is_ours(e)]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        cfg.pop("hooks", None)
    atual = cfg.get("statusLine") if isinstance(cfg.get("statusLine"), dict) else {}
    if comando_nosso(atual.get("command", ""), "statusline.py"):
        if os.path.exists(ORIG):
            with open(ORIG, encoding="utf-8") as f:
                antiga = f.read().strip()
            extras = {k: v for k, v in atual.items() if k not in ("type", "command")}
            cfg["statusLine"] = {**extras, "type": "command", "command": antiga}
        else:
            cfg.pop("statusLine", None)
    save_settings(cfg)
    print("Claudinho's hooks and statusLine were removed.")


# ------------------------------------------------------------------ config

def lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def gravar_configs(cfg, url_kindle):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    gerado = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(PLUGIN_CONFIG, "w", encoding="utf-8") as f:
        f.write("-- Written by pc/setup.py. To change it, run the setup again or use the\n")
        f.write("-- plugin menu on the Kindle (Claudinho > Connection).\n")
        f.write("return {\n")
        f.write(f"    url = {lua_str(url_kindle)},\n")
        f.write(f"    token = {lua_str(cfg.get('token', ''))},\n")
        f.write(f"    gerado_em = {lua_str(gerado)},\n")
        f.write("}\n")
    print(f"\nWrote: {CONFIG}")
    print(f"Wrote: {PLUGIN_CONFIG}")


def configurar_conexao():
    atual = claudinho.load_config() if os.path.exists(CONFIG) else {}
    titulo("Connection to the Kindle (same Wi-Fi network)")
    if atual.get("modo") == "remoto":
        print("Remote mode was removed. The Kindle now reads straight from this computer,"
              " on the same network.")

    novo_token = tem_opcao("--new-token", "--novo-token")
    token = args_opt("--token") or (None if novo_token else atual.get("token")) or secrets.token_urlsafe(18)
    if novo_token and atual.get("token") and token != atual.get("token"):
        print("New token made: the old one stops working. Copy the plugin to the Kindle again"
              " (or type the new token in Claudinho > Connection > Token).")
    ip = args_opt("--ip") or perguntar("This computer's IP on the network", claudinho.ip_local())

    porta = porta_valida(args_opt("--port", "--porta", default=atual.get("porta") or 8787))
    if porta is None:
        sys.exit("The port has to be a number between 1 and 65535.")
    while True:
        resp = porta_valida(perguntar("Port", str(porta)))
        if resp is not None:
            porta = resp
            break
        print("Type a number between 1 and 65535.")

    # outras chaves que voce pos no config.json (como "host") continuam la;
    # as do modo remoto, que saiu, vao embora
    descartar = ("porta", "token", "modo", "relay_url", "token_pc")
    cfg = {k: v for k, v in atual.items() if k not in descartar} if os.path.exists(CONFIG) else {}
    cfg.update(porta=porta, token=token)
    url = f"http://{ip}:{porta}/estado.json"
    gravar_configs(cfg, url)
    print(f"""
Done. Now:
  1. Keep this running:  python3 "{os.path.join(BASE, 'claudinho.py')}"
  2. Copy the folder "{PLUGIN}" to koreader/plugins/ on the Kindle.
     Using the plugin zip from the GitHub Releases instead? Set these in
     Claudinho > Connection, on the Kindle:
       Address: {url}
       Token:   {token}
Tip: if this computer's IP changes, reserve a fixed IP for it on your router.
The Kindle screens can be in English or Portuguese: Claudinho > Language, on the Kindle.""")


def main():
    acao = sys.argv[1] if len(sys.argv) > 1 else ""
    if acao in ("remove", "remover"):
        remover_hooks()
        return
    if acao in ("connection", "conexao", "modo"):
        configurar_conexao()
        return
    if not tem_opcao("--no-hooks", "--sem-hooks"):
        instalar_hooks()
    configurar_conexao()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelled.")
