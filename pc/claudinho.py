#!/usr/bin/env python3
"""Agente do Claudinho no computador.

Junta o que os hooks e a statusLine do Claude Code gravaram, mais os tokens
dos historicos, num JSON pequeno (o "estado") e serve para o Kindle na rede
de casa, em http://<ip>:<porta>/estado.json.

    python3 claudinho.py                 roda conforme o config.json
    python3 claudinho.py --demo MODO     dados ficticios (testar sem Claude Code)
    python3 claudinho.py --estado        imprime o estado atual e sai
    python3 claudinho.py --porta 8787    usa outra porta

Modos de demo: cozinhando, cebola, pensando, chamando, prato, esperando,
descansando, varios

So usa a biblioteca padrao do Python. A logica de sessoes e tokens veio do
server.py do kindle-claude (guithepc, licenca MIT).
"""
import glob
import hashlib
import hmac
import json
import os
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATE = os.path.join(DATA, "state.json")
STATUS = os.path.join(DATA, "statusline.json")
CONFIG = os.path.join(BASE, "config.json")
PROJECTS = os.path.expanduser("~/.claude/projects")
VERSAO = 1

PRATO_SECONDS = 60          # quanto tempo o "prato pronto" fica depois de terminar
REST_AFTER = 30 * 60        # parado ha mais que isso = descansando
TOOL_LINGER = 45            # a ferramenta continua na barra esse tempo depois de usada
TOOL_STALE = 10 * 60        # ferramenta "rodando" ha mais que isso: considera encerrada
PARADO_APOS = 10 * 60       # "trabalhando" sem nenhum evento ha mais que isso: foi
                            # interrompido (Esc ou erro de API nao disparam o Stop)
TOKENS_A_CADA = 30          # segundos entre recontagens dos historicos
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# limites de tamanho do que vai para o Kindle (o painel corta o resto de qualquer jeito)
MAX_FERRAMENTA = 40
MAX_DESCRICAO = 80
MAX_PROJETO = 40


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_config():
    cfg = {"porta": 8787, "token": ""}
    cfg.update(read_json(CONFIG))
    return cfg


def cortar(texto, n):
    """Uma linha so, sem espacos repetidos, com no maximo `n` caracteres."""
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


# ------------------------------------------------------------------ tokens

# por arquivo: ate onde ja foi lido e as mensagens encontradas. Os historicos
# so crescem, entao a cada recontagem le apenas o pedaco novo.
_tok_cache = {}
_tok_result = {"t": 0, "valor": (0, 0, None)}


def _ler_novas(path, cache, cutoff_dt):
    try:
        tamanho = os.path.getsize(path)
    except OSError:
        return
    if tamanho < cache["pos"]:                 # arquivo foi reescrito: recomeca
        cache["pos"], cache["entries"] = 0, {}
    if tamanho == cache["pos"]:
        return
    with open(path, "rb") as f:
        f.seek(cache["pos"])
        bloco = f.read()
    fim = bloco.rfind(b"\n")
    if fim < 0:                                 # linha ainda sendo escrita
        return
    pos = cache["pos"]
    for bruta in bloco[:fim + 1].split(b"\n"):
        inicio, pos = pos, pos + len(bruta) + 1
        if b'"usage"' not in bruta:
            continue
        try:
            d = json.loads(bruta.decode("utf-8", errors="ignore"))
            msg = d.get("message") or {}
            usage = msg.get("usage")
            if not usage:
                continue
            dt = datetime.fromisoformat(d["timestamp"].replace("Z", "+00:00")).astimezone()
        except Exception:
            continue
        if dt < cutoff_dt:
            continue
        key = f'{msg.get("id")}|{d.get("requestId")}'
        if key == "None|None":
            key = f"{path}:{inicio}"
        tokens = sum(int(usage.get(k) or 0) for k in (
            "input_tokens", "output_tokens",
            "cache_creation_input_tokens", "cache_read_input_tokens"))
        cache["entries"][key] = (dt, tokens)
    cache["pos"] += fim + 1


def token_stats():
    """(hoje, ultima hora, media por dia nos 7 dias anteriores com uso)."""
    now = datetime.now().astimezone()
    today = now.date()
    hour_ago = now - timedelta(hours=1)
    cutoff = time.time() - 8 * 86400
    cutoff_dt = now - timedelta(days=8)
    seen, per_day, last_hour = set(), {}, 0
    vistos = set()
    for path in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            if os.path.getmtime(path) < cutoff:
                continue
        except OSError:
            continue
        vistos.add(path)
        cache = _tok_cache.setdefault(path, {"pos": 0, "entries": {}})
        _ler_novas(path, cache, cutoff_dt)
        # mensagens com mais de 8 dias nao entram em nenhuma conta
        velhas = [k for k, (dt, _) in cache["entries"].items() if dt < cutoff_dt]
        for k in velhas:
            del cache["entries"][k]
        for key, (dt, tokens) in cache["entries"].items():
            if key in seen:
                continue
            seen.add(key)
            per_day[dt.date()] = per_day.get(dt.date(), 0) + tokens
            if dt >= hour_ago:
                last_hour += tokens
    for path in [p for p in _tok_cache if p not in vistos]:   # apagados ou antigos
        del _tok_cache[path]
    past = [v for day, v in per_day.items() if today - timedelta(days=7) <= day < today]
    avg = sum(past) / len(past) if past else None
    return per_day.get(today, 0), last_hour, avg


def token_stats_cached(now):
    if now - _tok_result["t"] >= TOKENS_A_CADA:
        try:
            _tok_result["valor"] = token_stats()
        except Exception:
            pass
        _tok_result["t"] = now
    return _tok_result["valor"]


# ------------------------------------------------------------------ sessoes

def session_view(s, now):
    """(prioridade, modo, desde, ferramenta, descricao) de uma sessao."""
    last = float(s.get("last_event") or 0)
    status = s.get("status")
    if status == "waiting":
        since = float(s.get("waiting_since") or last)
        asked_tool = now - float(s.get("tool_started") or 0) < 120
        if asked_tool and s.get("tool_name"):
            return 5, "chamando", since, s["tool_name"], s.get("tool_desc", "")
        return 5, "chamando", since, "", "esperando sua resposta"
    if status == "working":
        started = float(s.get("tool_started") or 0)
        recent = now - started < TOOL_LINGER
        if (s.get("tool_running") and now - started < TOOL_STALE) or recent:
            return 4, "cozinhando", last, s.get("tool_name", ""), s.get("tool_desc", "")
        if now - last < PARADO_APOS:
            return 3, "cozinhando", last, "", "pensando…"
        # sem evento nenhum ha muito tempo: foi interrompido e o Stop nao veio
        return 1, "esperando", last, "", "nada no fogo"
    if status == "done":
        done_at = float(s.get("done_at") or last)
        if now - done_at < PRATO_SECONDS:
            return 2, "prato", done_at, "", "nada no fogo"
        return 1, "esperando", done_at, "", "nada no fogo"
    return 0, "descansando", last, "", "nada no fogo"


def derive(state, now):
    """Junta todas as sessoes numa so: mostra a mais urgente e conta as ativas."""
    sessions = state.get("sessions") or {}
    live = [s for s in sessions.values()
            if s.get("status") != "closed" and now - float(s.get("last_event") or 0) < REST_AFTER]
    views = [(session_view(s, now), s) for s in live]
    active = sum(1 for v, _ in views if v[0] >= 3)
    if not views:
        last = max([float(s.get("last_event") or 0) for s in sessions.values()] or
                   [float(state.get("last_event") or 0)])
        return {"mode": "descansando", "since": last, "tool": "", "desc": "nada no fogo",
                "active": 0, "project": ""}
    (rank, mode, since, tool, desc), s = max(
        views, key=lambda vs: (vs[0][0], float(vs[1].get("last_event") or 0)))
    return {"mode": mode, "since": since, "tool": tool, "desc": desc,
            "active": active, "project": s.get("project", "")}


def demo(mode):
    now = time.time()
    tools = ["Read", "Grep", "Bash", "mcp:notion", "Edit"]
    descs = ["server.py", "rate_limits", "Rodar os testes", "notion-search", "DashboardController.java"]
    names = {"cozinhando": "Edit", "sopa": "Edit", "cebola": "Bash", "tempero": "Grep"}
    tool = names.get(mode, "Edit")
    tdesc = {"Edit": "DashboardController.java", "Bash": "Rodar os testes da API",
             "Grep": "rate_limits"}[tool]
    s = {"status": "working", "last_event": now - 7, "tool_running": True,
         "tool_started": now - 2, "tool_name": tool, "tool_desc": tdesc, "project": "camaleao"}
    state = {"sessions": {"demo": s},
             "tools": [{"name": a, "desc": b} for a, b in zip(tools, descs)]}
    if mode in names:
        state["tools"][-1] = {"name": tool, "desc": tdesc}
    elif mode in ("pensando", "frigideira"):
        s["tool_running"] = False
        s["tool_started"] = now - 120
    elif mode == "chamando":
        s.update(status="waiting", waiting_since=now - 40, last_event=now - 40, tool_started=now - 45,
                 tool_name="Bash", tool_desc="Apagar a pasta build")
    elif mode == "prato":
        s.update(status="done", done_at=now - 12, last_event=now - 12)
    elif mode == "esperando":
        s.update(status="done", done_at=now - 125, last_event=now - 125)
    elif mode == "descansando":
        s.update(status="done", done_at=now - 2700, last_event=now - 2700)
    elif mode == "varios":
        state["sessions"].update({
            "b": {"status": "working", "last_event": now - 20, "project": "kindle-dash"},
            "c": {"status": "working", "last_event": now - 3, "project": "orca-api"}})
    status = {"rate_limits": {
        "five_hour": {"used_percentage": 11, "resets_at": now + 3 * 3600},
        "seven_day": {"used_percentage": 19, "resets_at": now + 3 * 86400}}}
    return state, status, (2_480_000, 420_000, 1_830_000)


DEMOS = ["cozinhando", "cebola", "pensando", "chamando", "prato", "esperando", "descansando", "varios"]


# ------------------------------------------------------------------ estado

def fmt_reset(epoch, week):
    try:
        dt = datetime.fromtimestamp(float(epoch))
    except Exception:
        return ""
    return f"zera {WEEKDAYS[dt.weekday()]} {dt:%H:%M}" if week else f"zera às {dt:%H:%M}"


def como_kindle(n):
    """Arredonda para a precisao que o Kindle mostra (E.fmt_tokens): "2,5 mi",
    "32 mil", "512". Assim o rev so muda quando o numero na tela mudaria."""
    if not n:
        return n
    passo = 100_000 if n >= 100_000 else 1000 if n >= 1000 else 1
    return int((n + passo // 2) // passo * passo)


def montar_estado(now=None, demo_mode=None):
    now = now or time.time()
    if demo_mode:
        state, status, (hoje, hora, media) = demo(demo_mode)
    else:
        state, status = read_json(STATE), read_json(STATUS)
        hoje, hora, media = token_stats_cached(now)
    info = derive(state, now)

    tools = state.get("tools") or []
    past = tools[:-1] if info["tool"] and tools else tools
    antes = [cortar(t.get("name", "?"), MAX_FERRAMENTA) for t in reversed(past[-4:])]

    rl = status.get("rate_limits") or {}

    def limite(key, week):
        d = rl.get(key) or {}
        pct = d.get("used_percentage")
        if pct is None:
            return {"pct": None, "zera": ""}
        return {"pct": int(round(float(pct))), "zera": fmt_reset(d.get("resets_at"), week)}

    estado = {
        "v": VERSAO,
        "modo": info["mode"],
        "desde": int(info["since"] or 0),
        "ferramenta": cortar(info["tool"], MAX_FERRAMENTA),
        "descricao": cortar(info["desc"], MAX_DESCRICAO),
        "ativos": info["active"],
        "projeto": cortar(info["project"], MAX_PROJETO),
        "antes": antes,
        "sessao": limite("five_hour", False),
        "semana": limite("seven_day", True),
        "tokens": {"hoje": como_kindle(int(hoje or 0)), "hora": como_kindle(int(hora or 0)),
                   "media": None if media is None else como_kindle(int(media))},
    }
    estado["rev"] = hashlib.sha1(json.dumps(estado, sort_keys=True).encode()).hexdigest()[:12]
    estado["agora"] = int(now)
    return estado


def to_bytes(estado):
    return json.dumps(estado, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ servidor

class Servidor:
    token = ""
    demo = None
    lock = threading.Lock()
    cache = (0.0, None, None)          # (quando, demo, estado)

    @classmethod
    def estado(cls, demo_mode):
        with cls.lock:
            t, d, e = cls.cache
            now = time.time()
            if e is None or d != demo_mode or now - t >= 1.0:
                e = montar_estado(now, demo_mode)
                cls.cache = (now, demo_mode, e)
            return e


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        try:
            if url.path == "/estado.json":
                if Servidor.token and not self.autorizado():
                    return self.reply(401, b'{"erro":"token invalido"}', "application/json")
                demo_mode = (q.get("demo") or [Servidor.demo])[0]
                if demo_mode is not None and demo_mode not in DEMOS:
                    return self.reply(400, b'{"erro":"demo desconhecida"}', "application/json")
                estado = Servidor.estado(demo_mode)
                etag = f'"{estado["rev"]}"'
                extra = {"ETag": etag}
                if self.headers.get("If-None-Match") == etag:
                    return self.reply(304, b"", None, extra)
                return self.reply(200, to_bytes(estado), "application/json; charset=utf-8", extra)
            if url.path == "/saude":
                return self.reply(200, b"ok\n", "text/plain")
            if url.path == "/":
                txt = ("Claudinho no ar.\n\nO Kindle le /estado.json"
                       " (com Authorization: Bearer TOKEN).\nTeste: /estado.json?demo=chamando\n")
                return self.reply(200, txt.encode(), "text/plain; charset=utf-8")
        except Exception as e:
            log(f"Erro ao responder {url.path}: {e!r}")
            return self.reply(500, b"erro interno", "text/plain; charset=utf-8")
        self.reply(404, b"nao encontrado", "text/plain")

    def autorizado(self):
        auth = self.headers.get("Authorization") or ""
        if not auth.lower().startswith("bearer "):
            return False
        token = auth[7:].strip()
        return bool(token) and hmac.compare_digest(token.encode(), Servidor.token.encode())

    def reply(self, code, body, ctype, extra=None):
        self.send_response(code)
        if ctype:
            self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if body:
            self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass


def ip_local():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))     # nao envia nada, so escolhe a interface
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def rodar(cfg, demo_mode):
    Servidor.token = cfg.get("token") or ""
    Servidor.demo = demo_mode
    porta = int(cfg.get("porta") or 8787)
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", porta), Handler)
    except OSError as e:
        sys.exit(f"Nao consegui abrir a porta {porta} ({e}). Ja tem outro claudinho.py rodando?"
                 " Use --porta para escolher outra.")
    log(f"O Kindle le http://{ip_local()}:{porta}/estado.json")
    if not Servidor.token:
        log("Aviso: sem token. Qualquer aparelho da rede consegue ler o estado. Rode setup.py.")
    if demo_mode:
        log(f"Demo ligada: '{demo_mode}' (dados ficticios)")
    log("Ctrl+C para sair.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------ main

def valor_de(args, nome, padrao=None):
    if nome not in args:
        return padrao
    i = args.index(nome)
    if i + 1 >= len(args) or args[i + 1].startswith("--"):
        return None
    return args[i + 1]


def main():
    args = sys.argv[1:]
    demo_mode = None
    if "--demo" in args:
        demo_mode = valor_de(args, "--demo") or "chamando"
        if demo_mode not in DEMOS:
            sys.exit(f"Demo desconhecida. Use uma destas: {', '.join(DEMOS)}")
    if "--estado" in args:
        print(json.dumps(montar_estado(demo_mode=demo_mode), ensure_ascii=False, indent=2))
        return
    cfg = load_config()
    if "--porta" in args:
        porta = valor_de(args, "--porta")
        if not porta or not porta.isdigit() or not 0 < int(porta) < 65536:
            sys.exit("Use --porta com um numero, por exemplo: --porta 8787")
        cfg["porta"] = int(porta)
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(CONFIG):
        log("Sem config.json ainda. Rode python3 setup.py para configurar.")
    elif cfg.get("modo") == "remoto":
        log("O modo remoto foi removido; servindo na rede local."
            " Rode python3 setup.py conexao e copie o plugin de novo para o Kindle.")
    rodar(cfg, demo_mode)


if __name__ == "__main__":
    main()
