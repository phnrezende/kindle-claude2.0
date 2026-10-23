#!/usr/bin/env python3
"""Claudinho setup assistant (runs on the computer).

    python3 setup.py               turn on the hooks + statusLine and set up the connection
    python3 setup.py connection    only set up the connection again (IP, port, token)
    python3 setup.py remove        take the hooks and the statusLine out of Claude Code

Without questions (for scripts):
    python3 setup.py --no-prompt [--ip 192.168.0.10] [--port 8787] [--token X]
    --no-hooks    leave ~/.claude/settings.json alone

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
SETTINGS = os.path.expanduser("~/.claude/settings.json")
PY = sys.executable or "python3"
HOOK_PATH = os.path.join(BASE, "hook.py")
STATUS_PATH = os.path.join(BASE, "statusline.py")
HOOK_CMD = f'"{PY}" "{HOOK_PATH}"'
STATUS_CMD = f'"{PY}" "{STATUS_PATH}"'
EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "UserPromptSubmit": None,
          "Notification": None, "Stop": None, "StopFailure": None, "SessionEnd": None}

sys.path.insert(0, BASE)
import claudinho  # noqa: E402  (mesmo diretorio)


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

def is_ours(entry):
    return any(HOOK_PATH in (h.get("command") or "") for h in entry.get("hooks", []))


def load_settings():
    if not os.path.exists(SETTINGS):
        return {}
    with open(SETTINGS, encoding="utf-8") as f:
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
    cfg = load_settings()
    hooks = cfg.setdefault("hooks", {})
    for event, matcher in EVENTS.items():
        lst = [e for e in hooks.get(event, []) if not is_ours(e)]
        entry = {"hooks": [{"type": "command", "command": HOOK_CMD}]}
        if matcher:
            entry["matcher"] = matcher
        lst.append(entry)
        hooks[event] = lst

    os.makedirs(DATA, exist_ok=True)
    current = (cfg.get("statusLine") or {}).get("command", "")
    if current and STATUS_PATH not in current:
        with open(ORIG, "w", encoding="utf-8") as f:
            f.write(current)
        print("Your old statusLine was saved and will keep showing.")
    cfg["statusLine"] = {"type": "command", "command": STATUS_CMD}
    save_settings(cfg)
    print("Hooks are on. Restart any Claude Code sessions that were already open.")


def remover_hooks():
    cfg = load_settings()
    hooks = cfg.get("hooks", {})
    for event in list(hooks):
        hooks[event] = [e for e in hooks[event] if not is_ours(e)]
        if not hooks[event]:
            del hooks[event]
    if not hooks:
        cfg.pop("hooks", None)
    if STATUS_PATH in (cfg.get("statusLine") or {}).get("command", ""):
        if os.path.exists(ORIG):
            cfg["statusLine"] = {"type": "command",
                                 "command": open(ORIG, encoding="utf-8").read().strip()}
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

    token = args_opt("--token") or atual.get("token") or secrets.token_urlsafe(18)
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

    cfg = {"porta": porta, "token": token}
    url = f"http://{ip}:{porta}/estado.json"
    gravar_configs(cfg, url)
    print(f"""
Done. Now:
  1. Keep this running:  python3 "{os.path.join(BASE, 'claudinho.py')}"
  2. Copy the folder "{PLUGIN}" to koreader/plugins/ on the Kindle.
Tip: if this computer's IP changes, reserve a fixed IP for it on your router.
The Kindle screens can be in English or Portuguese: Claudinho > Language, on the Kindle.""")


def main():
    comando = sys.argv[1] if len(sys.argv) > 1 else ""
    if comando in ("remove", "remover"):
        remover_hooks()
        return
    if comando in ("connection", "conexao", "modo"):
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
