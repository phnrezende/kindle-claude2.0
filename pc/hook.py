#!/usr/bin/env python3
"""Hook do Claude Code: registra o que cada sessao esta fazendo.

Baseado no hook.py do kindle-claude (guithepc, licenca MIT).
So usa a biblioteca padrao, nunca falha e nunca imprime nada.

Eventos usados:
  UserPromptSubmit -> cozinhando (pensando)
  PreToolUse       -> ferramenta rodando
  PostToolUse      -> ferramenta terminou
  Notification     -> precisa de voce (pedindo permissao / esperando)
  Stop             -> terminou (prato pronto, depois esperando)
  SessionEnd       -> sessao fechada
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATE = os.path.join(DATA, "state.json")
LOCK = os.path.join(DATA, "state.lock")
MAX_TOOLS = 12
FORGET_AFTER = 6 * 3600   # sessoes paradas ha mais que isso saem do arquivo


class FileLock:
    """Trava entre processos: varios agentes podem chamar o hook ao mesmo tempo."""

    def __init__(self, path):
        self.f = open(path, "a+")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.f, fcntl.LOCK_EX)
        except ImportError:                      # Windows
            import msvcrt
            self.f.seek(0)
            for _ in range(200):
                try:
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.01)
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


def short_desc(tool, inp):
    if not isinstance(inp, dict):
        return ""
    if tool == "Bash":
        return inp.get("description") or (inp.get("command") or "").split("\n")[0]
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return os.path.basename(str(inp[key]).rstrip("/\\")) or str(inp[key])
    for key in ("pattern", "query", "url", "description", "prompt", "subject"):
        if inp.get(key):
            return str(inp[key]).split("\n")[0]
    return ""


def display_name(tool):
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        return "mcp:" + (parts[1] if len(parts) > 1 else "?"), (parts[2] if len(parts) > 2 else "")
    return tool, ""


def update(state, event, now):
    name = event.get("hook_event_name", "")
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
            desc = f"{fn} {desc}".strip()
        s.update(status="working", tool_running=True, tool_name=tool,
                 tool_desc=desc.strip(), tool_started=now)
        tools = state.setdefault("tools", [])
        tools.append({"name": tool, "desc": desc.strip(), "t": now, "session": sid})
        state["tools"] = tools[-MAX_TOOLS:]
    elif name == "PostToolUse":
        s.update(status="working", tool_running=False)
    elif name == "UserPromptSubmit":
        s.update(status="working", tool_running=False)
    elif name == "Notification":
        s.update(status="waiting", tool_running=False, waiting_since=now)
    elif name == "Stop":
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
