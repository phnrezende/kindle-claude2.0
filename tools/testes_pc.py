"""Testes do lado do PC: hooks, estado, tokens, setup e servidor.

Rodam numa copia temporaria do pc/ e do plugin, com um HOME falso, entao nao
mexem no seu ~/.claude nem no seu config.json. Usa a porta 8799.

    python3 tools/testes_pc.py
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.error

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
shutil.copytree(os.path.join(REPO, "pc"), os.path.join(tmp, "pc"))
shutil.copytree(os.path.join(REPO, "kindle"), os.path.join(tmp, "kindle"))
home = os.path.join(tmp, "home")
os.makedirs(os.path.join(home, ".claude"))
env = dict(os.environ, HOME=home, USERPROFILE=home)
PC = os.path.join(tmp, "pc")
falhas = 0


def ok(cond, msg):
    global falhas
    print(("  ok   " if cond else "  FALHOU ") + msg)
    falhas += 0 if cond else 1


def hook(ev):
    subprocess.run([sys.executable, "-I", os.path.join(PC, "hook.py")], input=json.dumps(ev), text=True, env=env)


def estado():
    out = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--estado"],
                         capture_output=True, text=True, env=env).stdout
    return json.loads(out)


def limpar():
    shutil.rmtree(os.path.join(PC, "data"), ignore_errors=True)


print("notification")
limpar()
base = {"session_id": "a", "cwd": "/x/proj"}
hook({**base, "hook_event_name": "UserPromptSubmit"})
hook({**base, "hook_event_name": "Stop"})
hook({**base, "hook_event_name": "Notification", "notification_type": "idle_prompt",
      "message": "Claude is waiting for your input"})
ok(estado()["modo"] == "prato", "idle_prompt nao vira 'chamando'")
hook({**base, "hook_event_name": "Notification", "notification_type": "auth_success", "message": "x"})
ok(estado()["modo"] == "prato", "auth_success ignorado")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Bash",
      "tool_input": {"command": "rm -rf build", "description": "Apagar a pasta build"}})
hook({**base, "hook_event_name": "Notification", "notification_type": "permission_prompt",
      "message": "Claude needs your permission to use Bash"})
e = estado()
ok(e["modo"] == "chamando" and e["ferramenta"] == "Bash" and e["descricao"] == "Apagar a pasta build",
   "permission_prompt vira 'chamando' com a ferramenta")
limpar()
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "ls"}})
hook({**base, "hook_event_name": "Notification", "message": "Claude needs your permission to use Bash"})
ok(estado()["modo"] == "chamando", "versao antiga sem notification_type: decide pela mensagem")
hook({**base, "hook_event_name": "PostToolUse", "tool_name": "Bash"})
hook({**base, "hook_event_name": "StopFailure"})
ok(estado()["modo"] == "prato", "StopFailure conta como terminou")

print("descricoes")
limpar()
casos = [
    ({"command": "export API_KEY=sk-secret && curl https://x"}, "export …"),
    ({"command": "FOO=1 sudo /usr/bin/npm test"}, "npm …"),
    ({"command": "x" * 50000}, None),
]
for inp, esperado in casos:
    hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": inp})
    d = estado()["descricao"]
    if esperado:
        ok(d == esperado, f"Bash sem descricao -> {d!r}")
    else:
        ok(len(d) <= 80, f"comando enorme cortado ({len(d)} caracteres)")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Task", "tool_input": {"prompt": "segredo do prompt"}})
ok("segredo" not in json.dumps(estado()), "prompt de subagente nao sai")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "WebSearch", "tool_input": {"query": "minha busca"}})
ok("minha busca" not in json.dumps(estado()), "texto da pesquisa nao sai")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "WebFetch",
      "tool_input": {"url": "https://exemplo.com/caminho?token=abc"}})
ok(estado()["descricao"] == "exemplo.com", "URL vira so o dominio")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Edit",
      "tool_input": {"file_path": "/home/eu/projeto/src/Main.java"}})
ok(estado()["descricao"] == "Main.java", "arquivo sem a pasta")
tam = len(json.dumps(estado(), ensure_ascii=False, separators=(",", ":")).encode())
ok(tam < 1200, f"estado pequeno ({tam} bytes)")

print("sessao interrompida")
sys.path.insert(0, PC)
import claudinho  # noqa
agora = time.time()
s = {"status": "working", "last_event": agora - 11 * 60, "tool_running": False, "tool_started": agora - 11 * 60}
ok(claudinho.session_view(s, agora)[1] == "esperando", "trabalhando sem eventos ha 11 min -> esperando")
s["last_event"] = agora - 60
ok(claudinho.session_view(s, agora)[1] == "cozinhando", "pensando ha 1 min continua cozinhando")
s.update(tool_running=True, tool_started=agora - 5 * 60, last_event=agora - 5 * 60)
ok(claudinho.session_view(s, agora)[1] == "cozinhando", "ferramenta longa (5 min) continua cozinhando")

print("arredondamento")
for n, esp in [(2_480_000, 2_500_000), (420_000, 400_000), (31_500, 32_000), (512, 512), (0, 0)]:
    ok(claudinho.como_kindle(n) == esp, f"{n} -> {claudinho.como_kindle(n)}")

print("tokens incrementais")
proj = os.path.join(home, ".claude", "projects", "p")
os.makedirs(proj)
claudinho.PROJECTS = os.path.join(home, ".claude", "projects")
arq = os.path.join(proj, "s.jsonl")
ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def linha(i, n):
    return json.dumps({"timestamp": ts, "requestId": f"r{i}",
                       "message": {"id": f"m{i}", "usage": {"input_tokens": n, "output_tokens": 0}}}) + "\n"


with open(arq, "w") as f:
    f.write(linha(1, 100) + linha(2, 200))
ok(claudinho.token_stats()[0] == 300, "primeira leitura soma 300")
with open(arq, "a") as f:
    f.write(linha(2, 200) + linha(3, 50) + '{"timestamp":"' + ts + '","usage"')   # repetida + linha pela metade
ok(claudinho.token_stats()[0] == 350, "le so o novo, sem repetir e sem a linha pela metade")
with open(arq, "a") as f:
    f.write(':1}\n')
ok(claudinho.token_stats()[0] == 350, "linha completada sem usage valido nao conta")
with open(arq, "w") as f:
    f.write(linha(9, 7))
ok(claudinho.token_stats()[0] == 7, "arquivo reescrito: recomeca")
os.remove(arq)
claudinho.token_stats()
ok(arq not in claudinho._tok_cache, "arquivo apagado sai do cache")

print("setup e servidor")
r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "--sem-perguntas", "--ip", "127.0.0.1",
                    "--porta", "8799"], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
ok(r.returncode == 0, "setup sem perguntas")
cfg = json.load(open(os.path.join(PC, "config.json")))
settings = json.load(open(os.path.join(home, ".claude", "settings.json")))
ok(set(cfg) == {"porta", "token"} and cfg["porta"] == 8799, "config.json so com porta e token")
ok("StopFailure" in settings["hooks"] and "statusLine" in settings, "hooks e statusLine instalados")
lua = open(os.path.join(tmp, "kindle", "claudinho.koplugin", "config.lua")).read()
ok("http://127.0.0.1:8799/estado.json" in lua and "modo" not in lua, "config.lua do plugin")
r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "--sem-perguntas", "--porta"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
ok(r.returncode != 0 and "Faltou o valor" in r.stderr, "setup: --porta sem valor da erro claro")
r = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--porta"],
                   capture_output=True, text=True, env=env)
ok(r.returncode != 0 and "--porta" in r.stderr and "Traceback" not in r.stderr, "agente: --porta sem valor")

srv = subprocess.Popen([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--demo", "chamando"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.5)
url = "http://127.0.0.1:8799/estado.json"


def get(u, headers=None):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers=headers or {}), timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


try:
    ok(get(url)[0] == 401, "sem token: 401")
    ok(get(url + "?token=" + cfg["token"])[0] == 401, "token na URL nao vale mais")
    st, h, corpo = get(url, {"Authorization": "Bearer " + cfg["token"]})
    ok(st == 200 and json.loads(corpo)["modo"] == "chamando", "com token: 200")
    ok(h.get("X-Claudinho-Idade") is None, "sem cabecalhos do relay")
    ok(get(url, {"Authorization": "Bearer " + cfg["token"], "If-None-Match": h["ETag"]})[0] == 304, "ETag: 304")
    ok(get(url + "?demo=xyz", {"Authorization": "Bearer " + cfg["token"]})[0] == 400, "demo desconhecida: 400")
finally:
    srv.terminate()
    srv.wait()

r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "remover"],
                   capture_output=True, text=True, env=env)
settings = json.load(open(os.path.join(home, ".claude", "settings.json")))
ok("hooks" not in settings and "statusLine" not in settings, "remover tira tudo")

shutil.rmtree(tmp)
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
