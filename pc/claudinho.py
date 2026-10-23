#!/usr/bin/env python3
"""Agente do Claudinho no computador.

Junta o que os hooks e a statusLine do Claude Code gravaram, mais os tokens
dos historicos, num JSON pequeno (o "estado") e entrega para o Kindle:

  modo local   serve http://<ip>:<porta>/estado.json na rede de casa
  modo remoto  envia o estado para o relay na nuvem (Cloudflare), de onde o
               Kindle le em qualquer rede

    python3 claudinho.py                 roda conforme o config.json
    python3 claudinho.py --demo MODO     dados ficticios (testar sem Claude Code)
    python3 claudinho.py --estado        imprime o estado atual e sai

Modos de demo: cozinhando, cebola, pensando, chamando, prato, esperando,
descansando, varios

So usa a biblioteca padrao do Python. A logica de sessoes e tokens veio do
server.py do kindle-claude (guithepc, licenca MIT).
"""
import glob
import hashlib
import json
import os
import signal
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
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
TOKENS_A_CADA = 30          # segundos entre recontagens dos historicos
WEEKDAYS = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]

# envio para o relay (modo remoto)
ENVIO_TROCA_MODO = 3        # mudou o modo (ex.: pediu permissao): envia logo
ENVIO_DETALHES = 15         # so mudou ferramenta/numeros: no maximo a cada 15 s
ENVIO_BATIMENTO = 300       # nada mudou: avisa que esta vivo a cada 5 min


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True)


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def load_config():
    cfg = {"modo": "local", "porta": 8787, "token": "", "relay_url": "", "token_pc": ""}
    cfg.update(read_json(CONFIG))
    return cfg


# ------------------------------------------------------------------ tokens

_tok_cache = {}
_tok_result = {"t": 0, "valor": (0, 0, None)}


def token_stats():
    """(hoje, ultima hora, media por dia nos 7 dias anteriores com uso)."""
    now = datetime.now().astimezone()
    today = now.date()
    hour_ago = now - timedelta(hours=1)
    cutoff = time.time() - 8 * 86400
    seen, per_day, last_hour = set(), {}, 0
    for path in glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True):
        try:
            mtime = os.path.getmtime(path)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        cached = _tok_cache.get(path)
        if not cached or cached[0] != mtime:
            entries = {}
            with open(path, encoding="utf-8", errors="ignore") as f:
                for n, line in enumerate(f):
                    if '"usage"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                        msg = d.get("message") or {}
                        usage = msg.get("usage")
                        if not usage:
                            continue
                        dt = datetime.fromisoformat(
                            d["timestamp"].replace("Z", "+00:00")).astimezone()
                    except Exception:
                        continue
                    key = f'{msg.get("id")}|{d.get("requestId")}'
                    if key == "None|None":
                        key = f"{path}:{n}"
                    tokens = sum(int(usage.get(k) or 0) for k in (
                        "input_tokens", "output_tokens",
                        "cache_creation_input_tokens", "cache_read_input_tokens"))
                    entries[key] = (dt, tokens)
            cached = (mtime, entries)
            _tok_cache[path] = cached
        for key, (dt, tokens) in cached[1].items():
            if key in seen:
                continue
            seen.add(key)
            per_day[dt.date()] = per_day.get(dt.date(), 0) + tokens
            if dt >= hour_ago:
                last_hour += tokens
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
        return 3, "cozinhando", last, "", "pensando…"
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
    tdesc = {"Edit": "DashboardController.java", "Bash": "mvn test -pl api",
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
                 tool_name="Bash", tool_desc="rm -rf build/")
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


def _tres_digitos(n):
    """Arredonda para o que o Kindle consegue mostrar (evita reenvio a toa)."""
    if not n:
        return n
    mag = 10 ** max(0, len(str(int(n))) - 3)
    return int(round(n / mag) * mag)


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
    antes = [t.get("name", "?") for t in reversed(past[-4:])]

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
        "ferramenta": info["tool"] or "",
        "descricao": info["desc"] or "",
        "ativos": info["active"],
        "projeto": info["project"] or "",
        "antes": antes,
        "sessao": limite("five_hour", False),
        "semana": limite("seven_day", True),
        "tokens": {"hoje": _tres_digitos(int(hoje or 0)), "hora": _tres_digitos(int(hora or 0)),
                   "media": None if media is None else _tres_digitos(int(media))},
    }
    estado["rev"] = hashlib.sha1(json.dumps(estado, sort_keys=True).encode()).hexdigest()[:12]
    estado["agora"] = int(now)
    return estado


def to_bytes(estado):
    return json.dumps(estado, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


# ------------------------------------------------------------------ modo local

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
                if Servidor.token and not self.autorizado(q):
                    return self.reply(401, b'{"erro":"token invalido"}', "application/json")
                demo_mode = (q.get("demo") or [Servidor.demo])[0]
                estado = Servidor.estado(demo_mode)
                etag = f'"{estado["rev"]}"'
                # idade 0: no modo local o estado e sempre fresco
                extra = {"ETag": etag, "X-Claudinho-Idade": "0",
                         "X-Claudinho-Atualizado": str(int(time.time()))}
                if self.headers.get("If-None-Match") == etag:
                    return self.reply(304, b"", None, extra)
                return self.reply(200, to_bytes(estado), "application/json; charset=utf-8", extra)
            if url.path == "/saude":
                return self.reply(200, b"ok\n", "text/plain")
            if url.path == "/":
                txt = ("Claudinho no ar.\n\nO Kindle le /estado.json"
                       " (com o token, se configurado).\nTeste: /estado.json?demo=chamando\n")
                return self.reply(200, txt.encode(), "text/plain; charset=utf-8")
        except Exception as e:
            return self.reply(500, f"erro: {e}".encode(), "text/plain; charset=utf-8")
        self.reply(404, b"nao encontrado", "text/plain")

    def autorizado(self, q):
        auth = self.headers.get("Authorization") or ""
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else (q.get("token") or [""])[0]
        return bool(token) and hashlib.sha256(token.encode()).digest() == \
            hashlib.sha256(Servidor.token.encode()).digest()

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


def rodar_local(cfg, demo_mode):
    Servidor.token = cfg.get("token") or ""
    Servidor.demo = demo_mode
    porta = int(cfg.get("porta") or 8787)
    srv = ThreadingHTTPServer(("0.0.0.0", porta), Handler)
    log(f"Modo local. O Kindle le http://{ip_local()}:{porta}/estado.json")
    if demo_mode:
        log(f"Demo ligada: '{demo_mode}' (dados ficticios)")
    log("Ctrl+C para sair.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------ modo remoto

def enviar(cfg, estado):
    url = cfg["relay_url"].rstrip("/") + "/estado"
    req = urllib.request.Request(url, data=to_bytes(estado), method="PUT", headers={
        "Authorization": f"Bearer {cfg['token_pc']}",
        "Content-Type": "application/json",
        "User-Agent": "claudinho-pc/1",
    })
    with urllib.request.urlopen(req, timeout=10) as r:
        return r.status


def rodar_remoto(cfg, demo_mode):
    if not cfg.get("relay_url") or not cfg.get("token_pc"):
        sys.exit("Modo remoto sem relay configurado. Rode: python3 setup.py")
    log(f"Modo remoto. Enviando para {cfg['relay_url']}")
    if demo_mode:
        log(f"Demo ligada: '{demo_mode}' (dados ficticios)")
    log("Ctrl+C para sair.")
    parar = threading.Event()

    def sair(*_):
        parar.set()
    signal.signal(signal.SIGINT, sair)
    try:
        signal.signal(signal.SIGTERM, sair)
    except (AttributeError, ValueError):
        pass

    last_rev, last_modo, last_push, espera, falhou = None, None, 0.0, 0.0, False
    while not parar.is_set():
        now = time.time()
        estado = montar_estado(now, demo_mode)
        rev, modo = estado["rev"], estado["modo"]
        quer = False
        if rev != last_rev:
            if modo != last_modo:
                quer = now - last_push >= ENVIO_TROCA_MODO
            else:
                quer = now - last_push >= ENVIO_DETALHES
        elif now - last_push >= ENVIO_BATIMENTO:
            quer = True
        if quer and now >= espera:
            try:
                enviar(cfg, estado)
                if falhou or last_rev is None:
                    log("Relay recebendo o estado.")
                last_rev, last_modo, last_push, falhou = rev, modo, now, False
                espera = 0.0
            except urllib.error.HTTPError as e:
                log(f"Relay recusou ({e.code}). Confira a URL e o token com: python3 setup.py")
                espera, falhou = now + 60, True
            except Exception as e:
                if not falhou:
                    log(f"Sem conexao com o relay ({e}). Tentando de novo...")
                espera, falhou = now + 15, True
        parar.wait(2)

    # avisa o Kindle que o PC saiu, para ele nao ficar mostrando "cozinhando" pra sempre
    try:
        estado = montar_estado(time.time(), demo_mode)
        estado["pc_offline"] = True
        estado["rev"] += "-off"          # rev novo, senao o Kindle recebe 304 e nao ve o aviso
        enviar(cfg, estado)
        log("Avisei o Kindle que o PC saiu.")
    except Exception:
        pass


# ------------------------------------------------------------------ main

def main():
    args = sys.argv[1:]
    demo_mode = None
    if "--demo" in args:
        i = args.index("--demo")
        demo_mode = args[i + 1] if i + 1 < len(args) else "chamando"
        if demo_mode not in DEMOS:
            sys.exit(f"Demo desconhecida. Use uma destas: {', '.join(DEMOS)}")
    if "--estado" in args:
        print(json.dumps(montar_estado(demo_mode=demo_mode), ensure_ascii=False, indent=2))
        return
    cfg = load_config()
    if "--porta" in args:
        cfg["porta"] = int(args[args.index("--porta") + 1])
    os.makedirs(DATA, exist_ok=True)
    if not os.path.exists(CONFIG):
        log("Sem config.json ainda: rodando em modo local. Rode python3 setup.py para configurar.")
    if cfg.get("modo") == "remoto":
        rodar_remoto(cfg, demo_mode)
    else:
        rodar_local(cfg, demo_mode)


if __name__ == "__main__":
    main()
