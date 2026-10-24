#!/usr/bin/env python3
"""Claudinho agent (runs on the computer).

Gathers what the Claude Code hooks and statusLine saved, plus the token counts
from the session logs and the usage limits of your Claude account (the same as
/usage), into a small JSON (the "state") and serves it to the Kindle on your
home network at http://<ip>:<port>/estado.json.

    python3 claudinho.py                 run with config.json
    python3 claudinho.py --demo MODE     fake data (test without Claude Code)
    python3 claudinho.py --state         print the current state and exit
    python3 claudinho.py --port 8787     use another port
    python3 claudinho.py --log FILE      write the messages to FILE (setup.py autostart uses it)

Demo modes: cozinhando, cebola, pensando, chamando, prato, esperando,
descansando, varios

(Os comentarios do codigo seguem em portugues; o que aparece no terminal e
em ingles.)

So usa a biblioteca padrao do Python. A logica de sessoes e tokens veio do
server.py do kindle-claude (guithepc, licenca MIT).
"""
import glob
import hashlib
import hmac
import json
import math
import os
import re
import shutil
import socket
import socketserver
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


def pasta_claude():
    """Onde o Claude Code guarda configuracao e historicos: ~/.claude, ou a pasta
    de CLAUDE_CONFIG_DIR quando essa variavel esta definida."""
    return os.path.abspath(os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"))


PROJECTS = os.path.join(pasta_claude(), "projects")
VERSAO = 2                  # 2: so dados; as frases (e o idioma) ficam no Kindle

PRATO_SECONDS = 60          # quanto tempo o "prato pronto" fica depois de terminar
REST_AFTER = 30 * 60        # parado ha mais que isso = descansando
TOOL_LINGER = 45            # a ferramenta continua na barra esse tempo depois de usada
TOOL_STALE = 10 * 60        # ferramenta "rodando" ha mais que isso: considera encerrada
PARADO_APOS = 10 * 60       # "trabalhando" sem nenhum evento ha mais que isso: foi
                            # interrompido (Esc ou erro de API nao disparam o Stop)
TOKENS_A_CADA = 30          # segundos entre recontagens dos historicos

# limites de tamanho do que vai para o Kindle (o painel corta o resto de qualquer jeito)
MAX_FERRAMENTA = 40
MAX_DESCRICAO = 80
MAX_PROJETO = 40


LOG_STDERR = False          # com --state, o stdout fica so com o JSON


def log(*args):
    print(time.strftime("%H:%M:%S"), *args, flush=True, file=sys.stderr if LOG_STDERR else sys.stdout)


def read_json(path):
    # no Windows, abrir um arquivo no instante em que o hook ou a statusLine o troca
    # (os.replace) da PermissionError: tenta de novo, em vez de ler "vazio"
    for tentativa in range(20):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except PermissionError:
            if tentativa == 19:
                return {}
            time.sleep(0.025)
        except Exception:
            return {}
    return {}


def load_config():
    cfg = {"porta": 8787, "token": ""}
    cfg.update(read_json(CONFIG))
    return cfg


def num(v, padrao=0.0):
    """Numero de um campo dos arquivos; um valor estranho vira `padrao`.
    O state.json e o statusline.json sao gravados pelo hook e pelo Claude Code,
    mas um arquivo fora do formato nao pode derrubar toda resposta ao Kindle."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return padrao
    return n if math.isfinite(n) else padrao


def cortar(texto, n):
    """Uma linha so, sem espacos repetidos, com no maximo `n` caracteres."""
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[:n - 1].rstrip() + "…"


# ------------------------------------------------------------------ tokens

# por arquivo: ate onde ja foi lido e as mensagens encontradas. Os historicos
# so crescem, entao a cada recontagem le apenas o pedaco novo.
_tok_cache = {}
_tok_result = {"t": 0, "valor": (0, 0, None)}

# session_id -> quando o historico mostrou que a vez do Claude acabou sem aviso aos
# hooks: Esc (interrupcao) ou um pedido de permissao recusado. O Stop nao dispara
# nesses casos e, sem isso, o Kindle ficava "Te chamando!" por meia hora.
_marcas = {}
INTERROMPIDO = "[Request interrupted by user"     # inicio do texto que o Claude Code grava
_B_INTERROMPIDO = INTERROMPIDO.encode()
_B_DECISAO = b'"permissionDecision"'


def chave_arquivo(path):
    """O mesmo historico chega pelo glob e pelo transcript_path do hook: uma chave so."""
    return os.path.normcase(os.path.abspath(path))


def _quando(d):
    return datetime.fromisoformat(str(d["timestamp"]).replace("Z", "+00:00")).astimezone()


def _parou_sem_hook(d):
    """Esta linha do historico mostra um Esc ou uma recusa de permissao do usuario?
    So vale a conversa principal (um subagente tem isSidechain)."""
    if d.get("type") != "user" or d.get("isSidechain"):
        return False
    decisao = d.get("permissionDecision")
    if isinstance(decisao, dict) and decisao.get("decision") not in (None, "accept", "allow") \
            and str(decisao.get("source") or "").startswith("user"):
        return True
    conteudo = (d.get("message") or {}).get("content") if isinstance(d.get("message"), dict) else None
    if isinstance(conteudo, str):
        return conteudo.startswith(INTERROMPIDO)
    if isinstance(conteudo, list):
        return any(isinstance(b, dict) and b.get("type") == "text"
                   and str(b.get("text") or "").startswith(INTERROMPIDO) for b in conteudo)
    return False


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
        tem_uso = b'"usage"' in bruta
        # a decisao "accept" aparece em quase todo resultado de ferramenta: nem abre o JSON
        sinal = _B_INTERROMPIDO in bruta or (
            _B_DECISAO in bruta and b'"permissionDecision":{"decision":"accept"' not in bruta)
        if not (tem_uso or sinal):
            continue
        try:
            d = json.loads(bruta.decode("utf-8", errors="ignore"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        if sinal and isinstance(d.get("sessionId"), str):
            try:
                if _parou_sem_hook(d):
                    t = _quando(d).timestamp()
                    if t > _marcas.get(d["sessionId"], 0):
                        _marcas[d["sessionId"]] = t
            except Exception:
                pass
        if not tem_uso:
            continue
        try:
            msg = d.get("message") or {}
            usage = msg.get("usage")
            if not isinstance(usage, dict) or not usage:
                continue
            dt = _quando(d)
            tokens = sum(int(usage.get(k) or 0) for k in (
                "input_tokens", "output_tokens",
                "cache_creation_input_tokens", "cache_read_input_tokens"))
        except Exception:
            continue
        if dt < cutoff_dt:
            continue
        key = f'{msg.get("id")}|{d.get("requestId")}'
        if key == "None|None":
            key = f"{path}:{inicio}"
        cache["entries"][key] = (dt, tokens)
    cache["pos"] += fim + 1


def ler_historicos(sessions):
    """Le o pedaco novo do historico das sessoes trabalhando ou esperando (o
    transcript_path que o hook guardou), para ver logo um Esc ou uma recusa.
    Usa o mesmo cache da contagem de tokens, entao nada e lido duas vezes."""
    cutoff_dt = datetime.now().astimezone() - timedelta(days=8)
    for s in sessions.values():
        if not isinstance(s, dict) or s.get("status") not in ("working", "waiting"):
            continue
        path = s.get("transcript")
        if not isinstance(path, str) or not path.endswith(".jsonl"):
            continue
        cache = _tok_cache.setdefault(chave_arquivo(path), {"pos": 0, "entries": {}})
        try:
            _ler_novas(path, cache, cutoff_dt)
        except Exception:
            pass


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
        chave = chave_arquivo(path)
        vistos.add(chave)
        cache = _tok_cache.setdefault(chave, {"pos": 0, "entries": {}})
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


# ------------------------------------------------------------------ uso da conta

# O % da sessao de 5 h e da semana, direto da conta, como o /usage do Claude Code.
# A statusLine so roda no `claude` do terminal; o app de desktop nao a chama, entao
# quem usa o app ficaria sem o %. O login e o do `claude` do terminal
# (.credentials.json). O token de acesso dura poucas horas e so o `claude` o renova;
# vencido, o agente renova do mesmo jeito e grava o novo no arquivo, porque cada
# renovacao troca tambem o refresh token: sem gravar, o `claude` perderia o login.
CREDENCIAIS = os.path.join(pasta_claude(), ".credentials.json")
USO_URL = os.environ.get("CLAUDINHO_USO_URL") or "https://api.anthropic.com/api/oauth/usage"
TOKEN_URL = os.environ.get("CLAUDINHO_TOKEN_URL") or "https://platform.claude.com/v1/oauth/token"
CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"      # o do Claude Code
USO_A_CADA = 120            # segundos entre consultas
USO_ESPERA_FALHA = 600      # depois de uma falha (sem rede, endpoint fora)
USO_ESPERA_LOGIN = 1800     # sem login, ou login que nao renova: tenta de vez em quando
USO_LIGADO = True           # "uso_da_conta": false no config.json desliga

_uso = {"valor": None, "avisos": set()}
_credenciais_lock = threading.Lock()


class SemLogin(Exception):
    """Nao ha login do Claude Code, ou ele nao pode ser renovado."""


def _avisar_uso(chave, msg):
    if chave not in _uso["avisos"]:
        _uso["avisos"].add(chave)
        log(msg)


def _http_json(metodo, url, corpo=None, token=None):
    headers = {"Content-Type": "application/json", "User-Agent": "claudinho-kindle"}
    if token:
        headers["Authorization"] = "Bearer " + token
        headers["anthropic-beta"] = "oauth-2025-04-20"
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers=headers, method=metodo)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def _ler_credenciais():
    """(o arquivo inteiro, a parte claudeAiOauth) ou (None, None)."""
    try:
        with open(CREDENCIAIS, encoding="utf-8") as f:
            dados = json.load(f)
    except Exception:
        return None, None
    oauth = dados.get("claudeAiOauth") if isinstance(dados, dict) else None
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return None, None
    return dados, oauth


def _gravar_credenciais(dados):
    """Grava o .credentials.json de uma vez (arquivo temporario + troca), com as
    permissoes do original, depois de copiar o atual para .bak-claudinho."""
    backup = CREDENCIAIS + ".bak-claudinho"
    shutil.copy2(CREDENCIAIS, backup)
    tmp = CREDENCIAIS + ".tmp-claudinho"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(dados, f)
        shutil.copymode(CREDENCIAIS, tmp)
        os.replace(tmp, CREDENCIAIS)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def renovar_token(oauth):
    """Pede um token novo com o refresh token, como o Claude Code faz, e grava no
    .credentials.json so a parte claudeAiOauth (o resto do arquivo fica igual)."""
    with _credenciais_lock:
        dados, atual = _ler_credenciais()
        if not atual or not atual.get("refreshToken"):
            raise SemLogin("no refresh token")
        if atual.get("accessToken") != oauth.get("accessToken") and num(atual.get("expiresAt")) / 1000 > time.time() + 60:
            return atual                  # o `claude` renovou enquanto isso
        corpo = {"grant_type": "refresh_token", "refresh_token": atual["refreshToken"], "client_id": CLIENT_ID}
        if isinstance(atual.get("scopes"), list) and atual["scopes"]:
            corpo["scope"] = " ".join(str(s) for s in atual["scopes"])
        try:
            r = _http_json("POST", TOKEN_URL, corpo)
        except urllib.error.HTTPError as e:
            if e.code in (400, 401, 403):
                raise SemLogin(f"HTTP {e.code}")
            raise
        if not isinstance(r, dict) or not r.get("access_token") or not r.get("expires_in"):
            raise ValueError("unexpected token response")
        agora_ms = int(time.time() * 1000)
        novo = dict(atual)
        novo["accessToken"] = r["access_token"]
        novo["refreshToken"] = r.get("refresh_token") or atual["refreshToken"]
        novo["expiresAt"] = agora_ms + int(r["expires_in"]) * 1000
        if r.get("refresh_token_expires_in"):
            novo["refreshTokenExpiresAt"] = agora_ms + int(r["refresh_token_expires_in"]) * 1000
        if isinstance(r.get("scope"), str) and r["scope"].strip():
            novo["scopes"] = r["scope"].split()
        dados["claudeAiOauth"] = novo
        _gravar_credenciais(dados)
    log("Renewed the Claude Code login token (saved in .credentials.json; the old file is in"
        " .credentials.json.bak-claudinho).")
    return novo


def _epoch(v):
    """resets_at como numero (epoch) ou texto ISO ("2026-10-23T21:30:00.123+00:00")."""
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    if not isinstance(v, str) or not v:
        return None
    s = re.sub(r"(\.\d+)", "", v.strip()).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return None


def _converter_uso(r):
    """A resposta do /api/oauth/usage no formato do statusline.json."""
    rl = {}
    for janela in ("five_hour", "seven_day"):
        d = r.get(janela) if isinstance(r, dict) else None
        pct = num(d.get("utilization"), None) if isinstance(d, dict) else None
        if pct is not None:
            rl[janela] = {"used_percentage": pct, "resets_at": _epoch(d.get("resets_at"))}
    return rl


def consultar_uso():
    """O uso da conta agora, no formato do statusline.json. SemLogin sem o login do
    `claude` no .credentials.json (ou com um que nao renova)."""
    dados, oauth = _ler_credenciais()
    if not oauth:
        raise SemLogin("no .credentials.json")
    if num(oauth.get("expiresAt")) / 1000 < time.time() + 60:
        oauth = renovar_token(oauth)
    try:
        r = _http_json("GET", USO_URL, token=oauth["accessToken"])
    except urllib.error.HTTPError as e:
        if e.code != 401:
            raise
        oauth = renovar_token(oauth)      # vencido antes da hora: renova e tenta de novo
        r = _http_json("GET", USO_URL, token=oauth["accessToken"])
    return _converter_uso(r)


def atualizar_uso():
    """Consulta o uso uma vez e guarda. Devolve quantos segundos esperar ate a proxima."""
    try:
        valor = consultar_uso()
    except SemLogin as e:
        _avisar_uso("login:" + str(e), "No usage from your Claude account: the `claude` login in"
                    f" {CREDENCIAIS} is missing or can't be renewed ({e}). Run `claude` and /login,"
                    " or the % comes only from the statusLine.")
        return USO_ESPERA_LOGIN
    except urllib.error.HTTPError as e:
        _avisar_uso(f"http:{e.code}", f"Couldn't read the usage of your Claude account (HTTP {e.code}).")
        return USO_ESPERA_FALHA
    except Exception as e:
        _avisar_uso("erro:" + type(e).__name__, f"Couldn't read the usage of your Claude account ({e!r}).")
        return USO_ESPERA_FALHA
    if valor and _uso["valor"] is None:
        partes = [f"{'5 h' if k == 'five_hour' else 'week'} {round(v['used_percentage'])}%" for k, v in valor.items()]
        log("Usage from your Claude account: " + ", ".join(partes) + ".")
    _uso["valor"] = valor or None
    _uso["avisos"].clear()                  # voltou: avisa de novo na proxima falha
    return USO_A_CADA


def acompanhar_uso():
    while True:
        time.sleep(atualizar_uso())


# ------------------------------------------------------------------ sessoes

def session_view(s, now, parou=None):
    """(prioridade, modo, desde, ferramenta, descricao) de uma sessao.

    `parou`: quando o historico da sessao mostrou um Esc ou uma permissao recusada
    (ver _marcas). Nesses casos o Claude Code nao avisa os hooks."""
    last = num(s.get("last_event"))
    status = s.get("status")
    parou = num(parou)
    if status in ("waiting", "working") and parou > last:
        # a vez do Claude acabou depois do ultimo evento: ele espera voce
        return 1, "esperando", parou, "", ""
    if status == "waiting":
        since = num(s.get("waiting_since"), last) or last
        asked_tool = now - num(s.get("tool_started")) < 120
        if asked_tool and s.get("tool_name"):
            return 5, "chamando", since, s["tool_name"], s.get("tool_desc", "")
        return 5, "chamando", since, "", ""
    if status == "working":
        started = num(s.get("tool_started"))
        recent = now - started < TOOL_LINGER
        if (s.get("tool_running") and now - started < TOOL_STALE) or recent:
            return 4, "cozinhando", last, s.get("tool_name", ""), s.get("tool_desc", "")
        if now - last < PARADO_APOS:
            return 3, "cozinhando", last, "", ""
        # sem evento nenhum ha muito tempo: foi interrompido e o Stop nao veio
        return 1, "esperando", last, "", ""
    if status == "done":
        done_at = num(s.get("done_at"), last) or last
        if now - done_at < PRATO_SECONDS:
            return 2, "prato", done_at, "", ""
        return 1, "esperando", done_at, "", ""
    return 0, "descansando", last, "", ""


def derive(state, now, marcas=None):
    """Junta todas as sessoes numa so: mostra a mais urgente e conta as ativas.
    `marcas`: session_id -> quando o historico mostrou um Esc ou uma recusa."""
    marcas = marcas if isinstance(marcas, dict) else {}
    sessions = state.get("sessions") if isinstance(state.get("sessions"), dict) else {}
    sessions = {sid: s for sid, s in sessions.items() if isinstance(s, dict)}
    live = [(sid, s) for sid, s in sessions.items()
            if s.get("status") != "closed" and now - num(s.get("last_event")) < REST_AFTER]
    views = [(session_view(s, now, marcas.get(sid)), sid, s) for sid, s in live]
    active = sum(1 for v, _, _ in views if v[0] >= 3)
    if not views:
        last = max([num(s.get("last_event")) for s in sessions.values()] or
                   [num(state.get("last_event"))])
        return {"mode": "descansando", "since": last, "tool": "", "desc": "",
                "active": 0, "project": "", "session": None, "tool_id": None}
    (_, mode, since, tool, desc), sid, s = max(
        views, key=lambda v: (v[0][0], num(v[2].get("last_event"))))
    return {"mode": mode, "since": since, "tool": tool, "desc": desc,
            "active": active, "project": s.get("project", ""), "session": sid,
            "tool_id": s.get("tool_id") if tool else None}


DEMO_INICIO = time.time()


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
             "tools": [{"name": a, "desc": b, "session": "demo"} for a, b in zip(tools, descs)]}
    if mode in names:
        state["tools"][-1] = {"name": tool, "desc": tdesc, "session": "demo"}
    elif mode in ("pensando", "frigideira"):
        s["tool_running"] = False
        s["tool_started"] = now - 120
    elif mode == "chamando":
        # um pedido so, desde que o agente abriu (como no de verdade): o "desde" nao
        # muda a cada busca, e o Kindle avisa uma vez
        s.update(status="waiting", waiting_since=DEMO_INICIO - 40, last_event=now - 40, tool_started=now - 45,
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

def quando_zera(epoch, week):
    """Hora em que o limite zera, no fuso do PC, e o dia da semana (1 = segunda)
    para o limite semanal. O Kindle escreve a frase no idioma dele."""
    try:
        dt = datetime.fromtimestamp(float(epoch))
    except Exception:
        return {}
    r = {"hora": f"{dt:%H:%M}"}
    if week:
        r["dia"] = dt.isoweekday()
    return r


def ferramentas_antes(tools, info):
    """As ferramentas para a lista "antes:", sem a que ja esta na barra.

    A lista e de todas as sessoes; a da barra e a mais recente da sessao que
    aparece. Com varias sessoes, ela nem sempre e a ultima da lista."""
    if not info["tool"] or not tools:
        return tools
    tid = info.get("tool_id")
    if tid:
        # com ferramentas em paralelo, a da barra nem sempre e a ultima da sessao
        for i in range(len(tools) - 1, -1, -1):
            if tools[i].get("id") == tid:
                return tools[:i] + tools[i + 1:]
        if any("id" in t for t in tools):
            return tools           # a ferramenta da barra ja saiu da lista
    for i in range(len(tools) - 1, -1, -1):
        if tools[i].get("session") == info.get("session"):
            return tools[:i] + tools[i + 1:]
    if any("session" in t for t in tools):
        return tools               # a ferramenta da barra ja saiu da lista
    return tools[:-1]              # state.json antigo, sem a sessao de cada ferramenta


def como_kindle(n):
    """Arredonda para a precisao que o Kindle mostra (E.fmt_tokens): "2,5 mi",
    "32 mil", "512". Assim o rev so muda quando o numero na tela mudaria."""
    if not n:
        return n
    passo = 100_000 if n >= 100_000 else 1000 if n >= 1000 else 1
    return int((n + passo // 2) // passo * passo)


def montar_estado(now=None, demo_mode=None):
    now = now or time.time()
    marcas = None
    if demo_mode:
        state, status, (hoje, hora, media) = demo(demo_mode)
    else:
        state, status = read_json(STATE), read_json(STATUS)
        hoje, hora, media = token_stats_cached(now)
    state = state if isinstance(state, dict) else {}
    status = status if isinstance(status, dict) else {}
    if not demo_mode:
        sessoes = state.get("sessions")
        if isinstance(sessoes, dict):
            ler_historicos(sessoes)
        marcas = _marcas
    info = derive(state, now, marcas)

    tools = state.get("tools") if isinstance(state.get("tools"), list) else []
    tools = [t for t in tools if isinstance(t, dict)]
    antes = [cortar(t.get("name", "?"), MAX_FERRAMENTA)
             for t in reversed(ferramentas_antes(tools, info)[-4:])]

    rl = status.get("rate_limits") if isinstance(status.get("rate_limits"), dict) else {}
    if not demo_mode and _uso["valor"]:
        rl = {**rl, **_uso["valor"]}        # o da conta vale mais: atualiza mesmo sem a statusLine

    def limite(key, week):
        d = rl.get(key)
        pct = num(d.get("used_percentage"), None) if isinstance(d, dict) else None
        if pct is None:
            return {"pct": None}
        zera = num(d.get("resets_at"), None)
        if zera is not None and zera <= now:
            # a janela ja virou e o Claude Code nao rodou desde entao (o statusline.json
            # so muda com ele aberto): o uso da janela nova ainda e zero
            return {"pct": 0}
        return {"pct": int(round(pct)), **quando_zera(zera, week)}

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
                    return self.reply(401, b'{"error":"invalid token"}', "application/json")
                demo_mode = (q.get("demo") or [Servidor.demo])[0]
                if demo_mode is not None and demo_mode not in DEMOS:
                    return self.reply(400, b'{"error":"unknown demo"}', "application/json")
                estado = Servidor.estado(demo_mode)
                etag = f'"{estado["rev"]}"'
                extra = {"ETag": etag}
                if self.headers.get("If-None-Match") == etag:
                    return self.reply(304, b"", None, extra)
                return self.reply(200, to_bytes(estado), "application/json; charset=utf-8", extra)
            if url.path == "/saude":
                return self.reply(200, b"ok\n", "text/plain")
            if url.path == "/":
                txt = ("Claudinho is running.\n\nThe Kindle reads /estado.json"
                       " (with Authorization: Bearer TOKEN).\nTry: /estado.json?demo=chamando\n")
                return self.reply(200, txt.encode(), "text/plain; charset=utf-8")
        except Exception as e:
            log(f"Error answering {url.path}: {e!r}")
            return self.reply(500, b"internal error", "text/plain; charset=utf-8")
        self.reply(404, b"not found", "text/plain")

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


class ServidorHTTP(ThreadingHTTPServer):
    """O ThreadingHTTPServer sem o getfqdn() ao abrir: essa consulta de nome nao serve
    para nada aqui e pode levar segundos (no macOS, por exemplo)."""
    daemon_threads = True

    def server_bind(self):
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def rodar(cfg, demo_mode):
    Servidor.token = cfg.get("token") or ""
    Servidor.demo = demo_mode
    porta = int(cfg.get("porta") or 8787)
    # "host" no config.json limita a uma interface (o IP da rede de casa, por exemplo);
    # sem ele, responde em todas, como antes
    host = str(cfg.get("host") or "0.0.0.0")
    try:
        srv = ServidorHTTP((host, porta), Handler)
    except OSError as e:
        if host != "0.0.0.0":
            sys.exit(f"Could not listen on {host}:{porta} ({e}). Is this computer still on that network"
                     " with that IP? Fix \"host\" in config.json or remove it to listen everywhere.")
        sys.exit(f"Could not open port {porta} ({e}). Is another claudinho.py already running?"
                 " Use --port to pick another one.")
    if not demo_mode:
        # a primeira contagem le os historicos inteiros e pode levar alguns segundos;
        # feita aqui, ela nao atrasa a primeira resposta ao Kindle
        log("Counting tokens in the Claude Code history…")
        token_stats_cached(time.time())
        if USO_LIGADO:
            threading.Thread(target=acompanhar_uso, daemon=True).start()
    log(f"The Kindle reads http://{ip_local() if host == '0.0.0.0' else host}:{porta}/estado.json")
    if not Servidor.token:
        log("Warning: no token. Any device on the network can read the state. Run setup.py.")
    if demo_mode:
        log(f"Demo on: '{demo_mode}' (fake data)")
    log("Press Ctrl+C to quit.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


# ------------------------------------------------------------------ main

def opcao(args, *nomes):
    """(presente, valor) da primeira opcao de `nomes` que aparece em `args`."""
    for nome in nomes:
        if nome in args:
            i = args.index(nome)
            if i + 1 < len(args) and not args[i + 1].startswith("--"):
                return True, args[i + 1]
            return True, None
    return False, None


def main():
    args = sys.argv[1:]
    demo_mode = None
    tem, valor = opcao(args, "--demo")
    if tem:
        demo_mode = valor or "chamando"
        if demo_mode not in DEMOS:
            sys.exit(f"Unknown demo. Use one of: {', '.join(DEMOS)}")
    cfg = load_config()
    global USO_LIGADO, LOG_STDERR
    USO_LIGADO = cfg.get("uso_da_conta") is not False
    if "--state" in args or "--estado" in args:
        LOG_STDERR = True
        if USO_LIGADO and not demo_mode:
            atualizar_uso()
        if not sys.stdout.isatty():
            # redirecionado (arquivo, outro programa): UTF-8 em qualquer sistema; no
            # Windows o padrao seria a pagina de codigo, que nao tem todos os caracteres
            sys.stdout.reconfigure(encoding="utf-8")
        print(json.dumps(montar_estado(demo_mode=demo_mode), ensure_ascii=False, indent=2))
        return
    tem, porta = opcao(args, "--port", "--porta")
    if tem:
        if not porta or not porta.isdigit() or not 0 < int(porta) < 65536:
            sys.exit("Use --port with a number, for example: --port 8787")
        cfg["porta"] = int(porta)
    os.makedirs(DATA, exist_ok=True)
    tem, arquivo_log = opcao(args, "--log")
    if tem and arquivo_log:
        # aberto sem janela (pythonw, pelo atalho de "setup.py autostart"): as mensagens
        # e os erros vao para o arquivo; passando de 1 MB, o antigo vira .old
        try:
            if os.path.getsize(arquivo_log) > 1_000_000:
                os.replace(arquivo_log, arquivo_log + ".old")
        except OSError:
            pass
        sys.stdout = sys.stderr = open(arquivo_log, "a", encoding="utf-8", buffering=1)
    if not os.path.exists(CONFIG):
        log("No config.json yet. Run python3 setup.py to set things up.")
    elif cfg.get("modo") == "remoto":
        log("Remote mode was removed; serving on the local network."
            " Run python3 setup.py connection and copy the plugin to the Kindle again.")
    rodar(cfg, demo_mode)


if __name__ == "__main__":
    main()
