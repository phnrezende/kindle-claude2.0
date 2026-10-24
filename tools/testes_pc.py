"""Testes do lado do PC: hooks, estado, tokens, setup e servidor.

Rodam numa copia temporaria do pc/ e do plugin, com um HOME falso, entao nao
mexem no seu ~/.claude nem no seu config.json. Usa a porta 8799.

    python3 tools/testes_pc.py
"""
import json, os, shutil, subprocess, sys, tempfile, time, urllib.request, urllib.error

# O teste le e escreve os arquivos do agente (settings.json, state.json...), que sao
# UTF-8. Ate o Python 3.14 o padrao no Windows e a pagina de codigo (cp1252), e um
# caminho com acento viraria lixo so do lado do teste. Entao o teste roda em modo
# UTF-8; os scripts testados continuam no padrao do sistema (rodam com -I, como no uso real).
if not sys.flags.utf8_mode:
    sys.exit(subprocess.run([sys.executable, "-X", "utf8", os.path.abspath(__file__)] + sys.argv[1:]).returncode)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
tmp = tempfile.mkdtemp()
# sem o config.json e os dados de quem roda os testes
shutil.copytree(os.path.join(REPO, "pc"), os.path.join(tmp, "pc"),
                ignore=shutil.ignore_patterns("config.json", "data", "__pycache__"))
shutil.copytree(os.path.join(REPO, "kindle"), os.path.join(tmp, "kindle"))
home = os.path.join(tmp, "home")
os.makedirs(os.path.join(home, ".claude"))
env = dict(os.environ, HOME=home, USERPROFILE=home)
env.pop("CLAUDE_CONFIG_DIR", None)          # nunca le a pasta de verdade de quem roda os testes
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

print("ferramentas em paralelo")
limpar()
P = {"session_id": "par", "cwd": "/x/par"}
hook({**P, "hook_event_name": "PreToolUse", "tool_name": "Read", "tool_use_id": "r1",
      "tool_input": {"file_path": "/x/par/a.py"}})
hook({**P, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "b1",
      "tool_input": {"description": "Build longo"}})
hook({**P, "hook_event_name": "PostToolUse", "tool_name": "Read", "tool_use_id": "r1"})
st = json.load(open(os.path.join(PC, "data", "state.json")))["sessions"]["par"]
ok(st["tool_running"] and st["tool_name"] == "Bash", "o Read acabou, o build continua rodando")
v = claudinho.session_view(st, time.time() + 300)
ok(v[1] == "cozinhando" and v[3] == "Bash", f"5 min depois: ainda o build na barra ({v[1]}, {v[3]!r})")
e = estado()
ok(e["ferramenta"] == "Bash" and e["antes"] == ["Read"], f"'antes' sem o build da barra ({e['antes']})")
hook({**P, "hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_use_id": "b1"})
st = json.load(open(os.path.join(PC, "data", "state.json")))["sessions"]["par"]
ok(st["tool_running"] is False and "rodando" not in st, "o build acabou: nada rodando")

print("privacidade de outras ferramentas")
limpar()
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "TaskCreate",
      "tool_input": {"subject": "Corrigir login", "description": "Cliente ACME reclamou do contrato 123"}})
e = estado()
ok(e["descricao"] == "Corrigir login" and "ACME" not in json.dumps(e), f"TaskCreate: so o titulo ({e['descricao']!r})")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Grep",
      "tool_input": {"pattern": "senha_admin", "path": "/Users/eu/clientes/acme"}})
ok(estado()["descricao"] == "senha_admin", "Grep com pasta: o padrao, nao a pasta")
hook({**base, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": "sudo -u postgres psql"}})
ok(estado()["descricao"] == "psql …", "sudo -u usuario: o programa, nao a opcao")

print("Esc e permissao recusada (o historico avisa; os hooks, nao)")
from datetime import datetime as _datetime, timezone as _tz
limpar()
proj_esc = os.path.join(home, ".claude", "projects", "esc")
os.makedirs(proj_esc, exist_ok=True)
hist = os.path.join(proj_esc, "s-esc.jsonl")
open(hist, "w").close()
ESC = {"session_id": "s-esc", "cwd": "/x/esc", "transcript_path": hist}


def no_historico(conteudo, sidechain=False, **extra):
    d = {"type": "user", "sessionId": "s-esc", "isSidechain": sidechain,
         "timestamp": _datetime.now(_tz.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
         "message": {"role": "user", "content": conteudo}}
    d.update(extra)
    with open(hist, "a") as f:
        f.write(json.dumps(d) + "\n")


INTERROMPIDO = [{"type": "text", "text": "[Request interrupted by user for tool use]"}]
hook({**ESC, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "t1",
      "tool_input": {"description": "Apagar a pasta build"}})
hook({**ESC, "hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "x"})
ok(estado()["modo"] == "chamando", "pedindo permissao: chamando")
no_historico(INTERROMPIDO, sidechain=True)
ok(estado()["modo"] == "chamando", "interrupcao num subagente nao conta")
no_historico([{"type": "tool_result", "tool_use_id": "t0", "content": "[Request interrupted by user for tool use]"}],
             permissionDecision={"decision": "accept", "source": "config"})
ok(estado()["modo"] == "chamando", "o texto dentro do resultado de outra ferramenta nao conta")
no_historico(INTERROMPIDO)
e = estado()
ok(e["modo"] == "esperando" and e["ferramenta"] == "", f"Esc no pedido de permissao: esperando ({e['modo']})")
hook({**ESC, "hook_event_name": "UserPromptSubmit"})
ok(estado()["modo"] == "cozinhando", "um prompt novo depois do Esc: cozinhando de novo")
hook({**ESC, "hook_event_name": "PreToolUse", "tool_name": "Edit", "tool_use_id": "t2",
      "tool_input": {"file_path": "/x/esc/a.py"}})
hook({**ESC, "hook_event_name": "Notification", "notification_type": "permission_prompt", "message": "x"})
no_historico([{"type": "tool_result", "tool_use_id": "t2", "content": "rejected", "is_error": True}],
             permissionDecision={"decision": "reject", "source": "user_reject"})
ok(estado()["modo"] == "esperando", "recusa registrada so na decisao de permissao: esperando")
hook({**ESC, "hook_event_name": "UserPromptSubmit"})
hook({**ESC, "hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_use_id": "t3",
      "tool_input": {"description": "Rodar os testes"}})
no_historico("[Request interrupted by user]")
ok(estado()["modo"] == "esperando", "Esc enquanto trabalha (sem pedido de permissao): esperando")
os.remove(hist)

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
        except (FileNotFoundError, PermissionError):
            pass        # Windows: o arquivo no meio da troca (o agente tenta de novo, ver read_json)
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

print("statusLine antiga")
orig = os.path.join(PC, "data", "orig_statusline.txt")
entrada = {"model": {"display_name": "Opus"}, "rate_limits": {"five_hour": {"used_percentage": 7, "resets_at": futuro}}}
for antiga, esperado, msg in [
        ("echo minha linha", "minha linha", "a sua statusLine continua aparecendo"),
        ("exit 3", "Opus | 5h 7%", "a antiga falhou: aparece a do Claudinho, nao uma linha vazia"),
        ("comando-que-nao-existe-claudinho", "Opus | 5h 7%", "comando inexistente: a do Claudinho"),
        ('[[ -n "$HOME" ]] && echo coisa do bash', "coisa do bash", "roda no bash, como o Claude Code"),
        ("cat >/dev/null; printf 'acentuação ✓'", "acentuação ✓", "acentos passam intactos")]:
    with open(orig, "w", encoding="utf-8") as f:
        f.write(antiga)
    saida = statusline(entrada)
    ok(saida == esperado, f"{msg} ({saida!r})")
os.remove(orig)
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
r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "--no-prompt", "--ip", "127.0.0.1"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
st = json.load(open(settings_path))
ok("Replaced" not in r.stdout and len(st["hooks"]["Stop"]) == 1,
   "rodar o setup de novo nao chama os hooks desta pasta de 'antigos' nem repete")
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
ok("Address: http://127.0.0.1:8799/estado.json" in r.stdout and f"Token:   {cfg['token']}" in r.stdout,
   "mostra o endereco e o token para o menu do Kindle (plugin do zip dos Releases)")
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
url = "http://127.0.0.1:8799/estado.json"


# direto, sem o proxy do sistema (no macOS do GitHub, ate 127.0.0.1 ia para um proxy)
_direto = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def espera_saude(porta, segundos=30):
    """Espera o agente responder (em vez de dormir um tempo fixo)."""
    fim = time.time() + segundos
    while time.time() < fim:
        try:
            if get(f"http://127.0.0.1:{porta}/saude")[0] == 200:
                return True
        except Exception:
            pass
        time.sleep(0.3)
    return False


def get(u, headers=None):
    try:
        with _direto.open(urllib.request.Request(u, headers=headers or {}), timeout=5) as resp:
            return resp.status, resp.headers, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, b""


try:
    ok(espera_saude(8799), "o agente abre e responde")
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
espera_saude(8797)
srv.terminate()
saida = srv.communicate()[0]
ok(saida.find("Counting tokens") >= 0 and saida.find("Counting tokens") < saida.find("The Kindle reads"),
   "conta os tokens antes de abrir a porta")

r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "remover"],
                   capture_output=True, text=True, env=env)
settings = json.load(open(os.path.join(home, ".claude", "settings.json")))
ok("hooks" not in settings and "statusLine" not in settings, "remover tira tudo")

print("setup: statusLine com opcoes, Windows e PowerShell")
SETUP = [sys.executable, "-I", os.path.join(PC, "setup.py")]
json.dump({"statusLine": {"type": "command", "command": "echo minha", "padding": 2, "refreshInterval": 5}},
          open(settings_path, "w"))
subprocess.run(SETUP + ["--no-prompt", "--ip", "127.0.0.1"], capture_output=True, text=True, env=env,
               stdin=subprocess.DEVNULL)
sl = json.load(open(settings_path))["statusLine"]
ok(sl.get("padding") == 2 and sl.get("refreshInterval") == 5 and "statusline.py" in sl["command"],
   "a statusLine do Claudinho fica com o padding e o refreshInterval que voce tinha")
subprocess.run(SETUP + ["remove"], capture_output=True, text=True, env=env)
sl = json.load(open(settings_path))["statusLine"]
ok(sl == {"type": "command", "command": "echo minha", "padding": 2, "refreshInterval": 5},
   f"remover devolve a sua statusLine inteira ({sl})")
r = subprocess.run(SETUP + ["--no-prompt", "--ip", "127.0.0.1", "--shell", "powershell"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
st = json.load(open(settings_path))
hs = [h for lst in st["hooks"].values() for e in lst for h in e["hooks"]]
ok(all(h["command"].startswith('& "') and h.get("shell") == "powershell" for h in hs),
   "--shell powershell: comandos com & e o campo shell")
ok(st["statusLine"]["command"].startswith('& "'), "--shell powershell: a statusLine tambem")
r = subprocess.run(SETUP + ["--no-prompt", "--ip", "127.0.0.1"], capture_output=True, text=True, env=env,
                   stdin=subprocess.DEVNULL)
st = json.load(open(settings_path))
ok(len(st["hooks"]["Stop"]) == 1 and not st["hooks"]["Stop"][0]["hooks"][0]["command"].startswith("&")
   and "Replaced" not in r.stdout, "voltando ao bash, os comandos do PowerShell sao trocados, sem repetir")
r = subprocess.run(SETUP + ["--no-prompt", "--ip", "127.0.0.1", "--shell", "zsh"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
ok(r.returncode != 0 and "--shell" in r.stderr, "--shell com valor errado da erro claro")
subprocess.run(SETUP + ["remove"], capture_output=True, text=True, env=env)
os.remove(settings_path)

if os.name == "nt":
    print("Windows: os comandos gravados rodam de verdade, no PowerShell e no Git Bash")
    import shells as _shells
    # uma pasta com espaco e acento, como C:\Users\Joao Silva\...
    pasta = os.path.join(tmp, "Pasta com espaço")
    PC_W = os.path.join(pasta, "pc")
    shutil.copytree(PC, PC_W, ignore=shutil.ignore_patterns("config.json", "data", "__pycache__"))

    def rodar_gravados(shell, argv):
        """Roda cada comando gravado no settings.json como o Claude Code rodaria."""
        st = json.load(open(settings_path))
        hook_cmd = st["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        pre_cmd = st["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        shutil.rmtree(os.path.join(PC_W, "data"), ignore_errors=True)
        sid = "sessao-" + shell
        for cmd, ev in ((hook_cmd, {"hook_event_name": "UserPromptSubmit", "session_id": sid,
                                    "cwd": r"C:\projetos\meu app", "prompt": "oi"}),
                        (pre_cmd, {"hook_event_name": "PreToolUse", "session_id": sid,
                                   "cwd": r"C:\projetos\meu app", "tool_name": "Bash", "tool_use_id": "t1",
                                   "tool_input": {"command": "npm test", "description": "Rodar os testes"}})):
            subprocess.run(argv(cmd), input=json.dumps(ev), text=True, capture_output=True, env=env, timeout=60)
        estado_w = json.load(open(os.path.join(PC_W, "data", "state.json"), encoding="utf-8"))
        s = estado_w.get("sessions", {}).get(sid, {})
        ok(s.get("status") == "working" and s.get("tool_name") == "Bash",
           f"{shell}: os hooks gravados rodam e gravam o estado ({s.get('status')}, {s.get('tool_name')})")
        sl_cmd = st["statusLine"]["command"]
        r = subprocess.run(argv(sl_cmd), text=True, capture_output=True, env=env, timeout=60,
                           input=json.dumps({"model": {"display_name": "Opus"}, "rate_limits": {
                               "five_hour": {"used_percentage": 40, "resets_at": time.time() + 3600}}}))
        guardado = json.load(open(os.path.join(PC_W, "data", "statusline.json")))["rate_limits"]
        ok("5h 40%" in r.stdout and guardado["five_hour"]["used_percentage"] == 40,
           f"{shell}: a statusLine gravada roda e guarda o % ({r.stdout.strip()!r})")

    setup_w = [sys.executable, "-I", os.path.join(PC_W, "setup.py"), "--no-prompt", "--ip", "127.0.0.1"]
    subprocess.run(setup_w + ["--shell", "powershell"], capture_output=True, text=True, env=env,
                   stdin=subprocess.DEVNULL)
    rodar_gravados("PowerShell", lambda c: ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", c])
    bash_w = _shells.git_bash()
    if bash_w:
        subprocess.run(setup_w + ["--shell", "bash"], capture_output=True, text=True, env=env,
                       stdin=subprocess.DEVNULL)
        rodar_gravados("Git Bash", lambda c: [bash_w, "-c", c])
    else:
        print("  (sem Git Bash neste Windows: so o PowerShell foi rodado)")
    subprocess.run([sys.executable, "-I", os.path.join(PC_W, "setup.py"), "remove"], capture_output=True,
                   text=True, env=env)
    os.remove(settings_path)
import setup as _setup  # noqa: E402
_setup.PY = r"C:\Program Files\Python312\python.exe"
alvo = r"C:\Users\Joao Silva\kindle-claude2.0\pc\hook.py"
ok(_setup.comando(alvo, "powershell", "nt") ==
   '& "C:/Program Files/Python312/python.exe" "C:/Users/Joao Silva/kindle-claude2.0/pc/hook.py" --claudinho',
   "Windows + PowerShell: & e barras normais")
ok(_setup.comando(alvo, "bash", "nt") ==
   '"C:/Program Files/Python312/python.exe" "C:/Users/Joao Silva/kindle-claude2.0/pc/hook.py" --claudinho',
   "Windows + Git Bash: barras normais, sem &")
ok(_setup.comando_nosso(_setup.comando(alvo, "powershell", "nt"), "hook.py"), "o comando do PowerShell e reconhecido")

print("setup: token novo, host e CLAUDE_CONFIG_DIR")
r = subprocess.run(SETUP + ["connection", "--no-prompt", "--ip", "127.0.0.1", "--port", "8799"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
antes = json.load(open(os.path.join(PC, "config.json")))["token"]
ok(antes == cfg["token"], "sem --new-token o token continua o mesmo")
r = subprocess.run(SETUP + ["connection", "--no-prompt", "--ip", "127.0.0.1", "--new-token"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
novo = json.load(open(os.path.join(PC, "config.json")))
ok(novo["token"] != antes and novo["token"] in open(os.path.join(tmp, "kindle", "claudinho.koplugin", "config.lua")).read()
   and "New token" in r.stdout, "--new-token troca o token no PC e no config.lua")
novo["host"] = "127.0.0.1"
novo.update(modo="remoto", relay_url="https://x.workers.dev", token_pc="pc")   # sobra da versao com relay
json.dump(novo, open(os.path.join(PC, "config.json"), "w"))
r = subprocess.run(SETUP + ["connection", "--no-prompt", "--ip", "127.0.0.1", "--port", "8796"],
                   capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
novo = json.load(open(os.path.join(PC, "config.json")))
ok(novo.get("host") == "127.0.0.1" and novo["porta"] == 8796, "o setup mantem o \"host\" que voce pos no config.json")
ok(not {"modo", "relay_url", "token_pc"} & set(novo) and "Remote mode was removed" in r.stdout,
   "e tira as chaves do modo remoto, avisando")
srv = subprocess.Popen([sys.executable, "-I", os.path.join(PC, "claudinho.py")], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    ok(espera_saude(8796), "com \"host\", responde nesse endereco")
finally:
    srv.terminate()
    saida = srv.communicate()[0]
ok("http://127.0.0.1:8796/estado.json" in saida, "e diz esse endereco ao abrir")


print("agente com --log (como o atalho de 'setup.py autostart' o abre)")
log_teste = os.path.join(tmp, "agente.log")
srv = subprocess.Popen([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--log", log_teste], env=env,
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
try:
    respondeu = espera_saude(8796)
finally:
    srv.terminate()
    tela = srv.communicate()[0]
escrito = open(log_teste, encoding="utf-8").read() if os.path.exists(log_teste) else ""
ok(respondeu and "The Kindle reads http://127.0.0.1:8796" in escrito and "The Kindle reads" not in tela,
   "--log: responde, e as mensagens vao para o arquivo, nao para a tela")

if os.name == "nt":
    print("Windows: 'setup.py autostart' cria o atalho, e ele abre o agente sem janela")
    inicializar = os.path.join(tmp, "Startup")
    env_auto = dict(env, CLAUDINHO_STARTUP_DIR=inicializar)
    r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "autostart"], capture_output=True,
                       text=True, env=env_auto)
    lnk = os.path.join(inicializar, "Claudinho (Kindle).lnk")
    ok(r.returncode == 0 and os.path.exists(lnk), "atalho criado na pasta Inicializar")
    ler = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:CL_LNK); "
           "$s.TargetPath; $s.Arguments; $s.WindowStyle")
    alvo, argumentos, janela = (subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", ler],
                                               capture_output=True, text=True, env=dict(env, CL_LNK=lnk))
                                .stdout.strip().splitlines() + ["", "", ""])[:3]
    ok(alvo.lower().endswith("pythonw.exe") and "claudinho.py" in argumentos and "--log" in argumentos,
       f"o atalho abre o claudinho.py com o pythonw e o --log ({os.path.basename(alvo)})")
    log_auto = os.path.join(PC, "data", "agente.log")
    if os.path.exists(log_auto):
        os.remove(log_auto)
    # abre pelo atalho, como o Windows faz no login
    subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", "Start-Process -FilePath $env:CL_LNK"],
                   env=dict(env, CL_LNK=lnk))
    respondeu = espera_saude(8796)
    lista = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                            "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like ('*' + $env:CL_PC + '*') }"
                            " | ForEach-Object { $_.ProcessId.ToString() + ' ' + $_.Name }"],
                           capture_output=True, text=True, env=dict(env, CL_PC=os.path.join(PC, "claudinho.py")))
    procs = [l.split(" ", 1) for l in lista.stdout.split("\n") if l.strip()]
    for pid, _ in procs:
        subprocess.run(["taskkill", "/F", "/PID", pid], capture_output=True)
    escrito = open(log_auto, encoding="utf-8").read() if os.path.exists(log_auto) else ""
    ok(respondeu and any(n.strip().lower() == "pythonw.exe" for _, n in procs) and "The Kindle reads" in escrito,
       f"aberto pelo atalho: responde, roda no pythonw (sem janela) e escreve o log ({[n.strip() for _, n in procs]})")
    r = subprocess.run([sys.executable, "-I", os.path.join(PC, "setup.py"), "autostart", "remove"],
                       capture_output=True, text=True, env=env_auto)
    ok(not os.path.exists(lnk) and "Removed" in r.stdout, "'autostart remove' tira o atalho")
outra = os.path.join(tmp, "outra-config")
os.makedirs(os.path.join(outra, "projects", "q"))
with open(os.path.join(outra, "projects", "q", "s.jsonl"), "w") as f:
    f.write(linha(70, 4321))
env_outra = dict(env, CLAUDE_CONFIG_DIR=outra)
r = subprocess.run(SETUP + ["--no-prompt", "--ip", "127.0.0.1"], capture_output=True, text=True, env=env_outra,
                   stdin=subprocess.DEVNULL)
ok(os.path.exists(os.path.join(outra, "settings.json")) and not os.path.exists(settings_path),
   "com CLAUDE_CONFIG_DIR, os hooks vao para o settings.json de la")
out = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--estado"],
                     capture_output=True, text=True, env=env_outra).stdout
ok(json.loads(out)["tokens"]["hoje"] == 4000, "e os tokens sao contados nos historicos de la")

print("uso da conta (o mesmo do /usage), com o login do `claude`")
import http.server
import threading
from datetime import datetime as _dt, timedelta, timezone


class Anthropic(http.server.BaseHTTPRequestHandler):
    """O /api/oauth/usage e o /v1/oauth/token de mentira."""
    valido, refresh, uso, pedidos = None, None, None, []

    def log_message(self, *a):
        pass

    def responder(self, codigo, obj):
        corpo = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        Anthropic.pedidos.append(("GET", self.headers.get("anthropic-beta")))
        if self.headers.get("Authorization") != f"Bearer {Anthropic.valido}":
            return self.responder(401, {"error": {"type": "authentication_error"}})
        self.responder(200, Anthropic.uso)

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Anthropic.pedidos.append(("POST", corpo))
        if corpo.get("refresh_token") != Anthropic.refresh:
            return self.responder(400, {"error": "invalid_grant"})
        Anthropic.valido, Anthropic.refresh = "acesso-novo", "refresh-novo"
        self.responder(200, {"access_token": "acesso-novo", "refresh_token": "refresh-novo", "expires_in": 28800,
                             "scope": "user:inference user:profile"})


falso = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Anthropic)
threading.Thread(target=falso.serve_forever, daemon=True).start()
base_falsa = f"http://127.0.0.1:{falso.server_port}"
env_uso = dict(env, CLAUDINHO_USO_URL=base_falsa + "/api/oauth/usage",
               CLAUDINHO_TOKEN_URL=base_falsa + "/v1/oauth/token")
cred = os.path.join(home, ".claude", ".credentials.json")
zera5 = _dt.now(timezone.utc).replace(microsecond=123456) + timedelta(hours=2)
Anthropic.uso = {"five_hour": {"utilization": 19.0, "resets_at": zera5.isoformat()},
                 "seven_day": {"utilization": 45.4, "resets_at": (zera5 + timedelta(days=3)).isoformat()},
                 "seven_day_opus": None}


def credenciais(acesso, vence_em, refresh="refresh-velho"):
    json.dump({"claudeAiOauth": {"accessToken": acesso, "refreshToken": refresh,
                                 "expiresAt": int((time.time() + vence_em) * 1000),
                                 "scopes": ["user:inference", "user:profile"], "subscriptionType": "pro"},
               "mcpOAuth": {"plugin:x": {"accessToken": "nao-mexer"}}}, open(cred, "w"))
    if os.name != "nt":
        os.chmod(cred, 0o600)
    Anthropic.pedidos = []


def estado_uso():
    r = subprocess.run([sys.executable, "-I", os.path.join(PC, "claudinho.py"), "--estado"],
                       capture_output=True, text=True, env=env_uso)
    return json.loads(r.stdout), r.stderr


limpar()
credenciais("acesso-ok", 3600)
Anthropic.valido, Anthropic.refresh = "acesso-ok", "refresh-velho"
e, _ = estado_uso()
ok(e["sessao"]["pct"] == 19 and e["semana"]["pct"] == 45, f"o % vem da conta, sem statusLine ({e['sessao']}, {e['semana']})")
ok(e["sessao"].get("hora") == _dt.fromtimestamp(int(zera5.timestamp())).strftime("%H:%M"),
   "e a hora em que zera, no fuso do PC")
ok(Anthropic.pedidos == [("GET", "oauth-2025-04-20")], "token valido: so consulta, nao renova")
ok(json.load(open(cred))["claudeAiOauth"]["accessToken"] == "acesso-ok", "token valido: o arquivo fica igual")

credenciais("acesso-velho", -3600)
Anthropic.valido, Anthropic.refresh = None, "refresh-velho"
e, _ = estado_uso()
c = json.load(open(cred))
post = [p[1] for p in Anthropic.pedidos if p[0] == "POST"]
ok(e["sessao"]["pct"] == 19, "token vencido: renova e le o uso")
ok(post and post[0] == {"grant_type": "refresh_token", "refresh_token": "refresh-velho",
                        "client_id": "9d1c250a-e61b-44d9-88ed-5944d1962f5e", "scope": "user:inference user:profile"},
   "renova como o Claude Code (refresh token, client_id e escopos)")
o = c["claudeAiOauth"]
ok(o["accessToken"] == "acesso-novo" and o["refreshToken"] == "refresh-novo"
   and abs(o["expiresAt"] / 1000 - (time.time() + 28800)) < 60, "grava o token novo, o refresh novo e o vencimento")
ok(o["subscriptionType"] == "pro" and c["mcpOAuth"] == {"plugin:x": {"accessToken": "nao-mexer"}},
   "o resto do arquivo fica igual")
ok(json.load(open(cred + ".bak-claudinho"))["claudeAiOauth"]["accessToken"] == "acesso-velho",
   "backup do arquivo de antes")
ok(not os.path.exists(cred + ".tmp-claudinho"), "nenhum arquivo temporario sobrando")
if os.name != "nt":
    ok(os.stat(cred).st_mode & 0o777 == 0o600, "o arquivo continua so seu (600)")

credenciais("acesso-revogado", 3600)
Anthropic.valido, Anthropic.refresh = None, "refresh-velho"
e, _ = estado_uso()
ok(e["sessao"]["pct"] == 19 and [p[0] for p in Anthropic.pedidos] == ["GET", "POST", "GET"],
   "token recusado antes de vencer: renova e tenta de novo")

os.makedirs(os.path.join(PC, "data"), exist_ok=True)
json.dump({"rate_limits": {"five_hour": {"used_percentage": 7, "resets_at": time.time() + 3600}}}, open(arq_sl, "w"))
credenciais("acesso-velho", -60, refresh="refresh-errado")
Anthropic.valido, Anthropic.refresh = None, "refresh-velho"
e, erro = estado_uso()
ok(e["sessao"]["pct"] == 7 and "/login" in erro, "renovacao recusada: usa a statusLine e diz para fazer /login")
ok(json.load(open(cred))["claudeAiOauth"]["accessToken"] == "acesso-velho", "renovacao recusada: nao mexe no arquivo")

os.remove(cred)
Anthropic.pedidos = []
e, _ = estado_uso()
ok(e["sessao"]["pct"] == 7 and Anthropic.pedidos == [], "sem login do `claude`: so a statusLine, sem consultar nada")

credenciais("acesso-ok", 3600)
Anthropic.valido = "acesso-ok"
cfg_antes = open(os.path.join(PC, "config.json")).read()
json.dump(dict(json.loads(cfg_antes), uso_da_conta=False), open(os.path.join(PC, "config.json"), "w"))
e, _ = estado_uso()
ok(e["sessao"]["pct"] == 7 and Anthropic.pedidos == [], "\"uso_da_conta\": false no config.json desliga")
open(os.path.join(PC, "config.json"), "w").write(cfg_antes)
falso.shutdown()

shutil.rmtree(tmp)
print("TUDO CERTO" if not falhas else f"{falhas} FALHA(S)")
sys.exit(1 if falhas else 0)
