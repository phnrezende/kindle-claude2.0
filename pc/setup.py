#!/usr/bin/env python3
"""Assistente de instalacao do Claudinho no computador.

    python3 setup.py             liga hooks + statusLine e configura a conexao
    python3 setup.py conexao     so reconfigura a conexao (IP, porta, token)
    python3 setup.py remover     tira os hooks e a statusLine do Claude Code

Sem perguntas (para scripts):
    python3 setup.py --sem-perguntas [--ip 192.168.0.10] [--porta 8787] [--token X]
    --sem-hooks   nao mexe no ~/.claude/settings.json

Ao final ele grava:
    pc/config.json                         o que o agente (claudinho.py) usa
    kindle/claudinho.koplugin/config.lua   o que o plugin do Kindle usa
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

def args_opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith("--"):
            return sys.argv[i + 1]
        sys.exit(f"Faltou o valor de {name}.")
    return default


def interativo():
    return "--sem-perguntas" not in sys.argv and sys.stdin.isatty()


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
        print(f"Backup do settings.json salvo em {bak}")
    tmp = SETTINGS + ".tmp-claudinho"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    os.replace(tmp, SETTINGS)         # o Claude Code nunca le um arquivo pela metade


def instalar_hooks():
    titulo("Hooks e statusLine do Claude Code")
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
        print("Sua statusLine antiga foi guardada e continua aparecendo.")
    cfg["statusLine"] = {"type": "command", "command": STATUS_CMD}
    save_settings(cfg)
    print("Hooks ligados. Reinicie as sessoes do Claude Code que ja estavam abertas.")


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
    print("Hooks e statusLine do Claudinho removidos.")


# ------------------------------------------------------------------ config

def lua_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def gravar_configs(cfg, url_kindle):
    with open(CONFIG, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)
    gerado = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(PLUGIN_CONFIG, "w", encoding="utf-8") as f:
        f.write("-- Gerado por pc/setup.py. Para mudar, rode o setup de novo ou use o menu\n")
        f.write("-- do plugin no Kindle (Claudinho > Conexao).\n")
        f.write("return {\n")
        f.write(f"    url = {lua_str(url_kindle)},\n")
        f.write(f"    token = {lua_str(cfg.get('token', ''))},\n")
        f.write(f"    gerado_em = {lua_str(gerado)},\n")
        f.write("}\n")
    print(f"\nGravado: {CONFIG}")
    print(f"Gravado: {PLUGIN_CONFIG}")


def configurar_conexao():
    atual = claudinho.load_config() if os.path.exists(CONFIG) else {}
    titulo("Conexao com o Kindle (mesma rede Wi-Fi)")
    if atual.get("modo") == "remoto":
        print("O modo remoto foi removido. Agora o Kindle le direto do PC, na mesma rede.")

    token = args_opt("--token") or atual.get("token") or secrets.token_urlsafe(18)
    ip = args_opt("--ip") or perguntar("IP deste computador na rede", claudinho.ip_local())

    porta = porta_valida(args_opt("--porta", atual.get("porta") or 8787))
    if porta is None:
        sys.exit("A porta precisa ser um numero entre 1 e 65535.")
    while True:
        resp = porta_valida(perguntar("Porta", str(porta)))
        if resp is not None:
            porta = resp
            break
        print("Digite um numero entre 1 e 65535.")

    cfg = {"porta": porta, "token": token}
    url = f"http://{ip}:{porta}/estado.json"
    gravar_configs(cfg, url)
    print(f"""
Pronto. Agora:
  1. Deixe rodando:  python3 "{os.path.join(BASE, 'claudinho.py')}"
  2. Copie a pasta "{PLUGIN}" para koreader/plugins/ no Kindle.
Dica: se o IP do PC mudar, reserve um IP fixo para ele no roteador.""")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remover":
        remover_hooks()
        return
    if len(sys.argv) > 1 and sys.argv[1] in ("conexao", "modo"):
        configurar_conexao()
        return
    if "--sem-hooks" not in sys.argv:
        instalar_hooks()
    configurar_conexao()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
