#!/usr/bin/env python3
"""Assistente de instalacao do Claudinho no computador.

    python3 setup.py             liga hooks + statusLine e escolhe local ou remoto
    python3 setup.py modo        so troca a conexao (local <-> remoto)
    python3 setup.py remover     tira os hooks e a statusLine do Claude Code

Sem perguntas (para scripts):
    python3 setup.py --modo local  [--ip 192.168.0.10] [--porta 8787]
    python3 setup.py --modo remoto --url https://claudinho-relay.SEU.workers.dev \\
                     [--token-pc X] [--token Y] [--sem-publicar]
    --sem-hooks   nao mexe no ~/.claude/settings.json

Ao final ele grava:
    pc/config.json                         o que o agente (claudinho.py) usa
    kindle/claudinho.koplugin/config.lua   o que o plugin do Kindle usa
"""
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(BASE)
DATA = os.path.join(BASE, "data")
CONFIG = os.path.join(BASE, "config.json")
ORIG = os.path.join(DATA, "orig_statusline.txt")
PLUGIN = os.path.join(ROOT, "kindle", "claudinho.koplugin")
PLUGIN_CONFIG = os.path.join(PLUGIN, "config.lua")
RELAY = os.path.join(ROOT, "relay")
SETTINGS = os.path.expanduser("~/.claude/settings.json")
PY = sys.executable or "python3"
HOOK_PATH = os.path.join(BASE, "hook.py")
STATUS_PATH = os.path.join(BASE, "statusline.py")
HOOK_CMD = f'"{PY}" "{HOOK_PATH}"'
STATUS_CMD = f'"{PY}" "{STATUS_PATH}"'
EVENTS = {"PreToolUse": "*", "PostToolUse": "*", "UserPromptSubmit": None,
          "Notification": None, "Stop": None, "SessionEnd": None}

sys.path.insert(0, BASE)
import claudinho  # noqa: E402  (mesmo diretorio)


# ------------------------------------------------------------------ util

def args_opt(name, default=None):
    if name in sys.argv:
        i = sys.argv.index(name)
        if i + 1 < len(sys.argv):
            return sys.argv[i + 1]
    return default


def interativo():
    return "--modo" not in sys.argv and sys.stdin.isatty()


def perguntar(texto, padrao=""):
    if not interativo():
        return padrao
    sufixo = f" [{padrao}]" if padrao else ""
    resp = input(f"{texto}{sufixo}: ").strip()
    return resp or padrao


def sim_nao(texto, padrao=True):
    if not interativo():
        return padrao
    op = "S/n" if padrao else "s/N"
    resp = input(f"{texto} [{op}]: ").strip().lower()
    if not resp:
        return padrao
    return resp in ("s", "sim", "y", "yes")


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
    with open(SETTINGS, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=False)


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


# ------------------------------------------------------------------ relay

def npx():
    return shutil.which("npx") or shutil.which("npx.cmd")


def rodar_mostrando(cmd, entrada=None):
    """Roda um comando mostrando a saida e devolve (codigo, texto)."""
    print("$", " ".join(cmd))
    p = subprocess.Popen(cmd, cwd=RELAY, stdin=subprocess.PIPE if entrada is not None else None,
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if entrada is not None:
        p.stdin.write(entrada + "\n")
        p.stdin.close()
    linhas = []
    for linha in p.stdout:
        print("  " + linha.rstrip())
        linhas.append(linha)
    return p.wait(), "".join(linhas)


def publicar_relay(token_pc, token_kindle):
    """Publica o relay com o wrangler. Devolve a URL ou None."""
    exe = npx()
    if not exe:
        print("Nao achei o Node/npx neste computador.")
        return None
    print("\nVou publicar o relay na sua conta Cloudflare (plano gratuito serve).")
    print("Se for a primeira vez, o navegador abre para voce entrar na conta.")
    code, out = rodar_mostrando([exe, "--yes", "deploy"])
    m = re.search(r"https://[\w.-]+\.workers\.dev", out)
    if code != 0 or not m:
        print("O deploy nao terminou. Veja a mensagem acima.")
        return None
    url = m.group(0)
    for nome, valor in (("TOKEN_PC", token_pc), ("TOKEN_KINDLE", token_kindle)):
        code, _ = rodar_mostrando([exe, "--yes", "secret", "put", nome], entrada=valor)
        if code != 0:
            print(f"Nao consegui gravar o segredo {nome}.")
            return None
    return url


def instrucoes_manuais(token_pc, token_kindle):
    print(f"""
Para publicar o relay voce mesmo (precisa do Node instalado):

  cd "{RELAY}"
  npx wrangler deploy
  npx wrangler secret put TOKEN_PC        (cole: {token_pc})
  npx wrangler secret put TOKEN_KINDLE    (cole: {token_kindle})

O deploy mostra a URL, algo como https://claudinho-relay.SEU-USUARIO.workers.dev
Passo a passo em docs/remoto.md.
""")


def testar_relay(url, token_pc, token_kindle):
    """Envia um estado de teste e le de volta com o token do Kindle."""
    estado = claudinho.montar_estado(demo_mode="descansando")
    try:
        cfg = {"relay_url": url, "token_pc": token_pc}
        claudinho.enviar(cfg, estado)
        req = urllib.request.Request(url.rstrip("/") + "/estado", headers={
            "Authorization": f"Bearer {token_kindle}", "User-Agent": "claudinho-setup/1"})
        with urllib.request.urlopen(req, timeout=10) as r:
            lido = json.loads(r.read().decode("utf-8"))
        if lido.get("rev") == estado["rev"]:
            print("Relay testado: o PC grava e o Kindle consegue ler.")
            return True
        print("O relay respondeu, mas com outro conteudo.")
    except urllib.error.HTTPError as e:
        print(f"O relay recusou o teste (HTTP {e.code}). Os segredos podem levar alguns segundos"
              " para valer; rode 'python3 setup.py modo' de novo se persistir.")
    except Exception as e:
        print(f"Nao consegui falar com o relay: {e}")
    return False


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
        f.write(f"    modo = {lua_str(cfg['modo'])},\n")
        f.write(f"    url = {lua_str(url_kindle)},\n")
        f.write(f"    token = {lua_str(cfg.get('token', ''))},\n")
        f.write(f"    gerado_em = {lua_str(gerado)},\n")
        f.write("}\n")
    print(f"\nGravado: {CONFIG}")
    print(f"Gravado: {PLUGIN_CONFIG}")


def configurar_modo():
    atual = claudinho.load_config() if os.path.exists(CONFIG) else {}
    titulo("Conexao com o Kindle")
    modo = args_opt("--modo")
    if not modo:
        print("1) Local   Kindle e PC na mesma rede Wi-Fi. Nada na internet.")
        print("2) Remoto  Funciona em redes diferentes, via um relay gratuito na Cloudflare.")
        escolha = perguntar("Escolha 1 ou 2", "2" if atual.get("modo") == "remoto" else "1")
        modo = "remoto" if escolha.strip() in ("2", "remoto", "r") else "local"

    token = args_opt("--token") or atual.get("token") or secrets.token_urlsafe(18)
    cfg = {"modo": modo, "porta": int(args_opt("--porta", atual.get("porta") or 8787)),
           "token": token, "relay_url": atual.get("relay_url", ""), "token_pc": atual.get("token_pc", "")}

    if modo == "local":
        ip = args_opt("--ip") or perguntar("IP deste computador na rede", claudinho.ip_local())
        cfg["porta"] = int(perguntar("Porta", str(cfg["porta"])))
        url = f"http://{ip}:{cfg['porta']}/estado.json"
        gravar_configs(cfg, url)
        print(f"""
Pronto (modo local). Agora:
  1. Deixe rodando:  python3 "{os.path.join(BASE, 'claudinho.py')}"
  2. Copie a pasta "{PLUGIN}" para koreader/plugins/ no Kindle.
Dica: se o IP do PC mudar, reserve um IP fixo para ele no roteador.""")
        return

    token_pc = args_opt("--token-pc") or cfg["token_pc"] or secrets.token_urlsafe(24)
    cfg["token_pc"] = token_pc
    url = args_opt("--url") or ""
    if not url and cfg["relay_url"] and sim_nao(f"Usar o relay que ja estava configurado ({cfg['relay_url']})?"):
        url = cfg["relay_url"]
    if not url and "--sem-publicar" not in sys.argv:
        if sim_nao("Publicar o relay agora com o wrangler (precisa do Node)?", bool(npx())):
            url = publicar_relay(token_pc, token) or ""
    if not url:
        instrucoes_manuais(token_pc, token)
        url = perguntar("Cole aqui a URL do relay (https://...workers.dev)")
    url = url.strip().rstrip("/")
    if not url.startswith("https://"):
        sys.exit("Preciso de uma URL https:// do relay. Rode 'python3 setup.py modo' quando tiver.")
    cfg["relay_url"] = url
    testar_relay(url, token_pc, token)
    gravar_configs(cfg, url + "/estado")
    print(f"""
Pronto (modo remoto). Agora:
  1. Deixe rodando:  python3 "{os.path.join(BASE, 'claudinho.py')}"
  2. Copie a pasta "{PLUGIN}" para koreader/plugins/ no Kindle.
O Kindle so precisa de internet; o PC tambem.""")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "remover":
        remover_hooks()
        return
    if len(sys.argv) > 1 and sys.argv[1] == "modo":
        configurar_modo()
        return
    if "--sem-hooks" not in sys.argv:
        instalar_hooks()
    configurar_modo()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nCancelado.")
