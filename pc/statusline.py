#!/usr/bin/env python3
"""statusLine do Claude Code: guarda os limites de uso (5h e semana) para o
Claudinho e imprime uma linha de status. Se voce ja tinha uma statusLine,
ela continua sendo usada, rodando no mesmo shell que o Claude Code usaria
(bash; no Windows, Git Bash ou PowerShell). Se ela falhar ou nao imprimir
nada, aparece a linha do Claudinho em vez de uma linha vazia.
Baseado no statusline.py do kindle-claude (MIT)."""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATUS = os.path.join(DATA, "statusline.json")
ORIG = os.path.join(DATA, "orig_statusline.txt")

sys.path.insert(0, BASE)
try:
    from shells import argumentos  # noqa: E402  (mesmo diretorio)
except Exception:                  # instalacao pela metade: a linha de status nao pode sumir
    def argumentos(cmd, sistema=None):
        return ["cmd", "/c", cmd] if os.name == "nt" else ["/bin/sh", "-c", cmd]


def linha_antiga(cmd, raw):
    """Roda a sua statusLine antiga. None se ela falhar sem imprimir nada."""
    try:
        r = subprocess.run(argumentos(cmd), input=raw, capture_output=True, timeout=5,
                           text=True, encoding="utf-8", errors="replace")
    except Exception:
        return None
    if not (r.stdout or "").strip():
        return None
    return r.stdout


def main():
    try:
        # o Claude Code manda UTF-8; no Windows o stdin de texto usaria outra codificacao
        raw = sys.stdin.buffer.read().decode("utf-8", "replace")
    except Exception:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}

    try:
        os.makedirs(DATA, exist_ok=True)
        try:
            with open(STATUS, encoding="utf-8") as f:
                old = json.load(f)
        except Exception:
            old = {}
        if not isinstance(old, dict):
            old = {}
        # rate_limits so aparece depois da primeira resposta, e o Claude Code tira cada
        # janela (5 h, semana) do JSON quando ela vence. Guarda cada uma separadamente:
        # vencida, o agente mostra 0% em vez de "--".
        novo = data.get("rate_limits") if isinstance(data.get("rate_limits"), dict) else {}
        antigo = old.get("rate_limits") if isinstance(old.get("rate_limits"), dict) else {}
        juntos = dict(antigo)
        juntos.update(novo)
        if juntos:
            data["rate_limits"] = juntos
        data["saved_at"] = time.time()
        # um nome por processo: varias sessoes rodam a statusLine ao mesmo tempo
        tmp = f"{STATUS}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, STATUS)
    except Exception:
        pass

    if os.path.exists(ORIG):
        try:
            with open(ORIG, encoding="utf-8") as f:
                cmd = f.read().strip()
        except Exception:
            cmd = ""
        if cmd:
            out = linha_antiga(cmd, raw)
            if out is not None:
                try:
                    # os mesmos bytes que a sua statusLine imprimiu (UTF-8), em qualquer sistema
                    sys.stdout.buffer.write(out.encode("utf-8", "replace"))
                    sys.stdout.flush()
                except Exception:
                    sys.stdout.write(out)
                return

    def campo(d, *chaves):
        for c in chaves:
            d = d.get(c) if isinstance(d, dict) else None
        return d

    parts = [str(campo(data, "model", "display_name") or "Claude")]
    agora = time.time()
    for rotulo, janela in (("5h", "five_hour"), ("week", "seven_day")):
        pct = campo(data, "rate_limits", janela, "used_percentage")
        zera = campo(data, "rate_limits", janela, "resets_at")
        try:
            # uma janela guardada de antes que ja venceu nao aparece na linha
            if pct is not None and (zera is None or float(zera) > agora):
                parts.append(f"{rotulo} {float(pct):.0f}%")
        except (TypeError, ValueError):
            pass
    print(" | ".join(parts))


if __name__ == "__main__":
    main()
