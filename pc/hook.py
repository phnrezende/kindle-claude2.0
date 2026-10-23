#!/usr/bin/env python3
"""Hook do Claude Code: registra o que cada sessao esta fazendo.

Baseado no hook.py do kindle-claude (guithepc, licenca MIT).
So usa a biblioteca padrao, nunca falha e nunca imprime nada.

Eventos usados:
  UserPromptSubmit -> cozinhando (pensando)
  PreToolUse       -> ferramenta rodando
  PostToolUse      -> ferramenta terminou
  Notification     -> precisa de voce (so pedido de permissao ou pergunta;
                      o aviso de "parado ha 60 s" e os outros sao ignorados)
  Stop             -> terminou (prato pronto, depois esperando)
  StopFailure      -> parou por erro da API (tambem conta como terminou)
  SessionEnd       -> sessao fechada

Privacidade: para o Kindle vai so o nome do arquivo, o padrao de busca, o
dominio de uma URL ou a descricao curta que o Claude da ao comando. O comando
em si, prompts e textos de busca nao saem daqui.
"""
import json
import os
import sys
import time
from urllib.parse import urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATE = os.path.join(DATA, "state.json")
LOCK = os.path.join(DATA, "state.lock")
MAX_TOOLS = 12
MAX_DESC = 80
FORGET_AFTER = 6 * 3600   # sessoes paradas ha mais que isso saem do arquivo

# notification_type que querem uma resposta sua
PEDE_VOCE = {"permission_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"}
# palavras que vem antes do programa num comando e nao dizem nada
PREFIXOS = {"sudo", "env", "time", "nohup", "exec", "command", "nice"}


class FileLock:
    """Trava entre processos: varios agentes podem chamar o hook ao mesmo tempo."""

    def __init__(self, path):
        self.f = open(path, "a+")
        self.travado = False

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
            self.travado = True
        except ImportError:                      # Windows
            import msvcrt
            self.f.seek(0)
            for _ in range(500):                 # ate ~5 s
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    self.travado = True
                    break
                except OSError:
                    time.sleep(0.01)
            if not self.travado:
                self.f.close()
                raise TimeoutError("trava do state.json ocupada")
        return self

    def __exit__(self, *exc):
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_UN)
        except ImportError:
            import msvcrt
            try:
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        self.f.close()


def cortar(texto, n=MAX_DESC):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


def programa(cmd):
    """So o nome do programa de um comando ("npm", "git"), sem argumentos."""
    for parte in cmd.split():
        parte = parte.strip("'\"(")
        nome, igual, _ = parte.partition("=")
        if igual and nome.isidentifier():        # FOO=bar antes do comando
            continue
        if parte in PREFIXOS or not parte:
            continue
        return os.path.basename(parte)
    return ""


def short_desc(tool, inp):
    if not isinstance(inp, dict):
        return ""
    if tool == "Bash":
        if inp.get("description"):
            return cortar(inp["description"])
        nome = programa(str(inp.get("command") or ""))
        return cortar(nome + " …") if nome else ""
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return cortar(os.path.basename(str(inp[key]).rstrip("/\\")) or str(inp[key]))
    if inp.get("url"):
        return cortar(urlparse(str(inp["url"])).hostname or "")
    for key in ("pattern", "description", "subject"):
        if inp.get(key):
            return cortar(str(inp[key]).split("\n")[0])
    return ""


def display_name(tool):
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        return "mcp:" + (parts[1] if len(parts) > 1 else "?"), (parts[2] if len(parts) > 2 else "")
    return tool, ""


def precisa_de_voce(event):
    """O Notification tambem avisa "parado ha 60 s", login, agente terminou...
    So conta como "te chamando" quando o Claude realmente espera uma resposta."""
    tipo = event.get("notification_type")
    if tipo:
        return tipo in PEDE_VOCE
    # versoes antigas do Claude Code nao mandam o tipo: decide pela mensagem
    return "permission" in str(event.get("message") or "").lower()


def update(state, event, now):
    name = event.get("hook_event_name", "")
    if name == "Notification" and not precisa_de_voce(event):
        return False
    sid = event.get("session_id") or "sem-id"
    sessions = state.setdefault("sessions", {})
    s = sessions.setdefault(sid, {})
    cwd = event.get("cwd")
    if cwd:
        s["project"] = os.path.basename(cwd.rstrip("/\\")) or cwd

    if name == "PreToolUse":
        tool, fn = display_name(event.get("tool_name", "?"))
        desc = short_desc(event.get("tool_name", ""), event.get("tool_input"))
        if fn:
            desc = cortar(f"{fn} {desc}")
        s.update(status="working", tool_running=True, tool_name=tool,
                 tool_desc=desc, tool_started=now)
        tools = state.setdefault("tools", [])
        tools.append({"name": tool, "desc": desc, "t": now, "session": sid})
        state["tools"] = tools[-MAX_TOOLS:]
    elif name == "PostToolUse":
        s.update(status="working", tool_running=False)
    elif name == "UserPromptSubmit":
        s.update(status="working", tool_running=False)
    elif name == "Notification":
        s.update(status="waiting", tool_running=False, waiting_since=now)
    elif name in ("Stop", "StopFailure"):
        s.update(status="done", tool_running=False, done_at=now)
    elif name == "SessionEnd":
        s.update(status="closed", tool_running=False)
    else:
        return False

    s["last_event"] = now
    state["last_event"] = now
    for k in [k for k, v in sessions.items() if now - float(v.get("last_event") or 0) > FORGET_AFTER]:
        del sessions[k]
    return True


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return
    os.makedirs(DATA, exist_ok=True)
    with FileLock(LOCK):
        try:
            with open(STATE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
        if "sessions" not in state:      # formato antigo: recomeca limpo
            state = {"tools": state.get("tools", [])}
        if not update(state, event, time.time()):
            return
        tmp = STATE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
