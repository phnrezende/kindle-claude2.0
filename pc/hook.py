#!/usr/bin/env python3
"""Hook do Claude Code: registra o que cada sessao esta fazendo.

Baseado no hook.py do kindle-claude (guithepc, licenca MIT).
So usa a biblioteca padrao, nunca falha e nunca imprime nada.

Eventos usados:
  UserPromptSubmit -> cozinhando (pensando)
  PreToolUse       -> ferramenta rodando
  PostToolUse      -> ferramenta terminou
  PostToolUseFailure -> ferramenta terminou com erro (sem isso, um teste que
                      falha deixava a ferramenta "rodando")
  Notification     -> precisa de voce (so pedido de permissao ou pergunta;
                      o aviso de "parado ha 60 s" e os outros sao ignorados)
  Stop             -> terminou (prato pronto, depois esperando)
  StopFailure      -> parou por erro da API (tambem conta como terminou)
  SessionEnd       -> sessao fechada

Privacidade: para o Kindle vai so o nome do arquivo, o padrao de busca, o
dominio de uma URL ou a descricao curta que o Claude da ao comando. De uma
ferramenta MCP (Linear, Gmail, Notion...) vai so o nome da funcao, porque os
campos dela costumam ser conteudo seu; do TaskCreate vai so o titulo (subject),
nunca o texto da tarefa. O comando em si, prompts e textos de busca nao saem
daqui.

O caminho do historico da sessao (transcript_path) fica guardado: o Claude Code
nao avisa os hooks quando voce aperta Esc ou recusa uma permissao, mas o
historico mostra, e o claudinho.py le dali.
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
MAX_RODANDO = 8           # ferramentas em paralelo guardadas por sessao
FORGET_AFTER = 6 * 3600   # sessoes paradas ha mais que isso saem do arquivo

# notification_type que querem uma resposta sua
PEDE_VOCE = {"permission_prompt", "elicitation_dialog", "elicitation_url_dialog", "agent_needs_input"}
# palavras que vem antes do programa num comando e nao dizem nada
PREFIXOS = {"sudo", "doas", "env", "time", "nohup", "exec", "command", "nice"}
# opcoes desses prefixos que levam um valor: em "sudo -u postgres psql" o programa e o psql
OPCOES_COM_VALOR = {
    "sudo": {"-u", "-g", "-h", "-p", "-C", "-D", "-r", "-t", "-U", "-T"},
    "doas": {"-u", "-C"},
    "env": {"-u", "-C", "-S"},
    "nice": {"-n"},
    "time": {"-f", "-o"},
}
# ferramentas cujo "description" e o texto da tarefa (conteudo seu): vai so o titulo
SO_TITULO = {"TaskCreate", "TaskUpdate"}
# ferramentas de busca: o padrao diz mais que a pasta onde se busca
BUSCAS = {"Grep", "Glob"}


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


def numero(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def cortar(texto, n=MAX_DESC):
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


def programa(cmd):
    """So o nome do programa de um comando ("npm", "git"), sem argumentos."""
    partes = cmd.split()
    prefixo = None                               # o ultimo sudo/env/nice... visto
    i = 0
    while i < len(partes):
        parte = partes[i].strip("'\"(")
        i += 1
        nome, igual, _ = parte.partition("=")
        if igual and nome.isidentifier():        # FOO=bar antes do comando
            continue
        if not parte:
            continue
        if parte in PREFIXOS:
            prefixo = parte
            continue
        if prefixo and parte.startswith("-"):    # opcao do prefixo: "sudo -u postgres"
            if parte in OPCOES_COM_VALOR.get(prefixo, ()):
                i += 1                           # pula o valor da opcao tambem
            continue
        return os.path.basename(parte)
    return ""


def primeira_linha(v):
    return cortar(str(v).split("\n")[0])


def short_desc(tool, inp):
    if not isinstance(inp, dict):
        return ""
    if tool == "Bash":
        if inp.get("description"):
            return cortar(inp["description"])
        nome = programa(str(inp.get("command") or ""))
        return cortar(nome + " …") if nome else ""
    if tool in SO_TITULO:
        return primeira_linha(inp.get("subject") or "")
    if tool in BUSCAS and inp.get("pattern"):
        return primeira_linha(inp["pattern"])
    for key in ("file_path", "notebook_path", "path"):
        if inp.get(key):
            return cortar(os.path.basename(str(inp[key]).rstrip("/\\")) or str(inp[key]))
    if inp.get("url"):
        return cortar(urlparse(str(inp["url"])).hostname or "")
    for key in ("pattern", "subject", "description"):
        if inp.get(key):
            return primeira_linha(inp[key])
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
    sid = str(event.get("session_id") or "sem-id")    # chave do JSON: sempre texto
    if not isinstance(state.get("sessions"), dict):
        state["sessions"] = {}
    sessions = state["sessions"]
    if not isinstance(sessions.get(sid), dict):
        sessions[sid] = {}
    s = sessions[sid]
    cwd = event.get("cwd")
    if isinstance(cwd, str) and cwd:
        s["project"] = os.path.basename(cwd.rstrip("/\\")) or cwd
    transcript = event.get("transcript_path")
    if isinstance(transcript, str) and transcript:
        s["transcript"] = transcript

    # ferramentas rodando agora, pelo tool_use_id: com varias em paralelo (um build
    # junto com um Read), o fim de uma nao pode dar a sessao como "pensando"
    rodando = s.get("rodando") if isinstance(s.get("rodando"), dict) else {}
    rodando = {k: v for k, v in rodando.items() if isinstance(v, dict)}
    tid = event.get("tool_use_id")
    tid = tid if isinstance(tid, str) and tid else None

    if name == "PreToolUse":
        nome = str(event.get("tool_name") or "?")
        tool, fn = display_name(nome)
        if nome.startswith("mcp__"):
            # MCP: os campos (description, subject, title...) sao conteudo, nao descricao
            desc = cortar(fn)
        else:
            desc = short_desc(nome, event.get("tool_input"))
        s.update(status="working", tool_running=True, tool_name=tool,
                 tool_desc=desc, tool_started=now, tool_id=tid)
        if tid:
            rodando[tid] = {"tool": tool, "desc": desc, "t": now}
            # um PostToolUse perdido nao pode acumular para sempre
            for k in sorted(rodando, key=lambda k: numero(rodando[k].get("t")))[:-MAX_RODANDO]:
                del rodando[k]
        tools = state["tools"] if isinstance(state.get("tools"), list) else []
        item = {"name": tool, "desc": desc, "t": now, "session": sid}
        if tid:
            item["id"] = tid
        tools.append(item)
        state["tools"] = tools[-MAX_TOOLS:]
    elif name in ("PostToolUse", "PostToolUseFailure"):
        if tid:
            rodando.pop(tid, None)
        if rodando:
            # outra ferramenta continua rodando: ela passa a ser a da barra
            u_id = max(rodando, key=lambda k: numero(rodando[k].get("t")))
            u = rodando[u_id]
            s.update(status="working", tool_running=True, tool_name=str(u.get("tool") or ""),
                     tool_desc=str(u.get("desc") or ""), tool_started=numero(u.get("t")), tool_id=u_id)
        else:
            s.update(status="working", tool_running=False)
    elif name == "UserPromptSubmit":
        rodando = {}
        s.update(status="working", tool_running=False)
    elif name == "Notification":
        s.update(status="waiting", tool_running=False, waiting_since=now)
    elif name in ("Stop", "StopFailure"):
        rodando = {}
        s.update(status="done", tool_running=False, done_at=now)
    elif name == "SessionEnd":
        rodando = {}
        s.update(status="closed", tool_running=False)
    else:
        return False

    if rodando:
        s["rodando"] = rodando
    else:
        s.pop("rodando", None)
    s["last_event"] = now
    state["last_event"] = now
    for k in [k for k, v in sessions.items() if not isinstance(v, dict) or now - numero(v.get("last_event")) > FORGET_AFTER]:
        del sessions[k]
    return True


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        return
    if not isinstance(event, dict):
        return
    os.makedirs(DATA, exist_ok=True)
    with FileLock(LOCK):
        try:
            with open(STATE, encoding="utf-8") as f:
                state = json.load(f)
        except Exception:
            state = {}
        if not isinstance(state, dict) or "sessions" not in state:   # formato antigo: recomeca limpo
            state = {"tools": state.get("tools", []) if isinstance(state, dict) else []}
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
