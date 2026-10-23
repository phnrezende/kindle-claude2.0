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

print("estado sem frases em portugues (v2)")
limpar()
hook({**base, "hook_event_name": "UserPromptSubmit"})
e = estado()
ok(e["v"] == 2 and e["modo"] == "cozinhando" and e["descricao"] == "", "pensando: descricao vazia, o Kindle escreve")
os.makedirs(os.path.join(PC, "data"), exist_ok=True)
zera = time.time() + 3600
with open(os.path.join(PC, "data", "statusline.json"), "w") as f:
    json.dump({"rate_limits": {"five_hour": {"used_percentage": 11.4, "resets_at": zera},
                               "seven_day": {"used_percentage": 19, "resets_at": zera}}}, f)
e = estado()
import datetime as _dt
quando = _dt.datetime.fromtimestamp(zera)
ok(e["sessao"] == {"pct": 11, "hora": quando.strftime("%H:%M")}, f"sessao: {e['sessao']}")
ok(e["semana"] == {"pct": 19, "hora": quando.strftime("%H:%M"), "dia": quando.isoweekday()}, f"semana: {e['semana']}")
ok("zera" not in json.dumps(e) and "fogo" not in json.dumps(e), "nenhuma frase pronta no estado")

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

print("ferramenta que falha, MCP e varias sessoes")
limpar()
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Bash",
      "tool_input": {"command": "npm test", "description": "Rodar os testes"}})
hook({**base, "hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "x"})
hook({**base, "hook_event_name": "PostToolUseFailure", "tool_name": "Bash", "error": "exit 1"})
e = estado()
ok(e["modo"] == "cozinhando" and e["ferramenta"] == "Bash", "PostToolUseFailure: volta a cozinhando, sem 'chamando'")
st = json.load(open(os.path.join(PC, "data", "state.json")))["sessions"]["a"]
ok(st["status"] == "working" and st["tool_running"] is False, "e a ferramenta deixa de estar rodando")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "mcp__linear__create_issue",
      "tool_input": {"title": "Bug", "description": "Cliente ACME reclamou do contrato"}})
e = estado()
ok(e["ferramenta"] == "mcp:linear" and e["descricao"] == "create_issue", f"MCP manda so a funcao ({e['descricao']!r})")
ok("ACME" not in json.dumps(e) and "Bug" not in json.dumps(e), "campos do MCP nao saem")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "mcp__servidor",
      "tool_input": {"description": "segredo"}})
ok("segredo" not in json.dumps(estado()), "MCP sem nome de funcao tambem nao le os campos")
limpar()
A, B = {"session_id": "A", "cwd": "/x/a"}, {"session_id": "B", "cwd": "/x/b"}
hook({**A, "hook_event_name": "PreToolUse", "tool_name": "Grep", "tool_input": {"pattern": "x"}})
hook({**A, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"description": "Rodar os testes"}})
hook({**A, "hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "x"})
hook({**B, "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/x/b/main.py"}})
e = estado()
ok(e["ferramenta"] == "Bash" and e["antes"] == ["Read", "Grep"],
   f"varias sessoes: 'antes' sem a ferramenta da barra ({e['antes']})")

print("limite que ja zerou")
with open(os.path.join(PC, "data", "statusline.json"), "w") as f:
    json.dump({"rate_limits": {"five_hour": {"used_percentage": 87, "resets_at": time.time() - 7200},
                               "seven_day": {"used_percentage": 64, "resets_at": time.time() + 86400}}}, f)
e = estado()
ok(e["sessao"] == {"pct": 0}, f"janela vencida vira 0% ({e['sessao']})")
ok(e["semana"]["pct"] == 64 and "hora" in e["semana"], "a que nao venceu continua igual")
os.remove(os.path.join(PC, "data", "statusline.json"))

print("statusLine")
SL = os.path.join(PC, "statusline.py")
def statusline(dados):
    return subprocess.run([sys.executable, "-I", SL], input=json.dumps(dados), capture_output=True,
                          text=True, env=env).stdout.strip()
arq_sl = os.path.join(PC, "data", "statusline.json")
futuro = time.time() + 3600
saida = statusline({"model": {"display_name": "Opus"}, "rate_limits": {
    "five_hour": {"used_percentage": 40, "resets_at": futuro}, "seven_day": {"used_percentage": 20, "resets_at": futuro}}})
ok(saida == "Opus | 5h 40% | week 20%", f"linha de status ({saida})")
statusline({"model": {"display_name": "Opus"}, "rate_limits": {"seven_day": {"used_percentage": 21, "resets_at": futuro}}})
rl = json.load(open(arq_sl))["rate_limits"]
ok(rl["five_hour"]["used_percentage"] == 40 and rl["seven_day"]["used_percentage"] == 21,
   "janela que sumiu do JSON fica guardada; a que veio e atualizada")
ok(statusline([1, 2]).startswith("Claude |") and statusline("lixo").startswith("Claude |"),
   "entrada estranha nao quebra a linha (e mantem os limites guardados)")
# varias sessoes ao mesmo tempo: o arquivo nunca fica pela metade
grande = json.dumps({"pad": "x" * 200000, "rate_limits": {"five_hour": {"used_percentage": 1, "resets_at": futuro}}})
ruins, parar = [0], [False]
def ler_sem_parar():
    while not parar[0]:
        try:
            with open(arq_sl) as f:
                json.load(f)
        except FileNotFoundError:
            pass
        except ValueError:
            ruins[0] += 1
import threading
t = threading.Thread(target=ler_sem_parar)
t.start()
for _ in range(8):
    ps = [subprocess.Popen([sys.executable, "-I", SL], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, env=env)
          for _ in range(6)]
    for p_ in ps:
        p_.stdin.write(grande.encode())
        p_.stdin.close()
    for p_ in ps:
        p_.wait()
parar[0] = True
t.join()
ok(ruins[0] == 0, f"6 sessoes gravando juntas: nenhuma leitura pela metade ({ruins[0]})")
sobras = [n for n in os.listdir(os.path.join(PC, "data")) if n.endswith(".tmp")]
ok(not sobras, "nenhum arquivo temporario sobrando")
os.remove(arq_sl)

print("arquivos fora do formato")
for ruim_state, ruim_status in [([1, 2], "x"), ({"sessions": [1], "tools": {"a": 1}}, {"rate_limits": []}),
                                ({"sessions": {"a": 5, "b": {"status": "working", "last_event": "ontem"}},
                                  "tools": [5, {"name": {}}]},
                                 {"rate_limits": {"five_hour": {"used_percentage": "muito", "resets_at": "amanha"},
                                                  "seven_day": 7}})]:
    with open(os.path.join(PC, "data", "state.json"), "w") as f:
        json.dump(ruim_state, f)
    with open(os.path.join(PC, "data", "statusline.json"), "w") as f:
        json.dump(ruim_status, f)
    out = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--state"],
                         capture_output=True, text=True, env=env)
    ok(out.returncode == 0 and json.loads(out.stdout)["v"] == 2, f"estado sai mesmo com {str(ruim_state)[:40]}")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_input": {"file_path": "/a/b.py"}})
ok(estado()["ferramenta"] == "Read", "o hook conserta um state.json fora do formato")
hook({"session_id": 5, "cwd": 7, "hook_event_name": "PreToolUse", "tool_name": 3, "tool_input": "x"})
ok(json.load(open(os.path.join(PC, "data", "state.json")))["sessions"].get("5") is not None,
   "evento com tipos estranhos e gravado (session_id e cwd que nao sao texto)")
os.remove(os.path.join(PC, "data", "statusline.json"))

print("setup: hooks de uma pasta antiga")
settings_path = os.path.join(home, ".claude", "settings.json")
morto = '"/usr/bin/python3" "/pasta/que/nao/existe/pc/hook.py"'
json.dump({"hooks": {
    "PreToolUse": [{"matcher": "*", "hooks": [{"type": "command", "command": morto}]},
                   {"matcher": "Bash", "hooks": [{"type": "command", "command": "node /meu/hook.js"}]}],
    "Stop": [{"hooks": [{"type": "command", "command": morto}]}]},
    "statusLine": {"type": "command", "command": '"/usr/bin/python3" "/pasta/que/nao/existe/pc/statusline.py"'}},
    open(settings_path, "w"))
r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "--no-prompt", "--ip", "127.0.0.1"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
st = json.load(open(settings_path))
cmds = [h["command"] for lst in st["hooks"].values() for e in lst for h in e["hooks"]]
ok(not any("nao/existe" in c for c in cmds), "hooks da pasta antiga foram trocados")
ok("node /meu/hook.js" in cmds, "o hook do usuario continua la")
ok(all(c.endswith("--claudinho") for c in cmds if "hook.py" in c), "os novos tem a marca")
ok(len([c for c in st["hooks"]["Stop"] for c in c["hooks"]]) == 1, "sem hook repetido")
ok("PostToolUseFailure" in st["hooks"], "PostToolUseFailure registrado")
ok("Replaced 2 Claudinho hook" in r.stdout, "o setup avisa que trocou os antigos")
ok(not os.path.exists(os.path.join(PC, "data", "orig_statusline.txt")),
   "statusLine antiga do Claudinho (morta) nao vira a 'sua statusLine'")
os.remove(settings_path)

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
ok(r.returncode != 0 and "Missing value" in r.stderr, "setup: --porta sem valor da erro claro")
for flag in ("--port", "--porta"):
    r = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), flag],
                       capture_output=True, text=True, env=env)
    ok(r.returncode != 0 and "--port" in r.stderr and "Traceback" not in r.stderr, f"agente: {flag} sem valor")
ok("Done." in subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "--no-prompt", "--no-hooks",
                              "--ip", "127.0.0.1", "--port", "8799"], capture_output=True, text=True, env=env,
                             stdin=subprocess.DEVNULL).stdout, "setup em ingles, com as opcoes novas")

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

srv = subprocess.Popen([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--port", "8797"],
                       env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
time.sleep(1.5)
srv.terminate()
saida = srv.communicate()[0]
ok(saida.find("Counting tokens") >= 0 and saida.find("Counting tokens") < saida.find("The Kindle reads"),
   "conta os tokens antes de abrir a porta")

r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "remover"],
                   capture_output=True, text=True, env=env)
settings = json.load(open(os.path.join(home, ".claude", "settings.json")))
ok("hooks" not in settings and "statusLine" not in settings, "remover tira tudo")

shutil.rmtree(tmp)
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
