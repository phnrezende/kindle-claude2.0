#!/usr/bin/env python3
"""statusLine do Claude Code: guarda os limites de uso (5h e semana) para o
Claudinho e imprime uma linha de status. Se voce ja tinha uma statusLine,
ela continua sendo usada. Baseado no statusline.py do kindle-claude (MIT)."""
import json
import os
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
STATUS = os.path.join(DATA, "statusline.json")
ORIG = os.path.join(DATA, "orig_statusline.txt")


def main():
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
        cmd = open(ORIG, encoding="utf-8").read().strip()
        if cmd:
            try:
                out = subprocess.run(cmd, shell=True, input=raw, text=True,
                                     capture_output=True, timeout=5).stdout
                sys.stdout.write(out)
                return
            except Exception:
                pass

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
