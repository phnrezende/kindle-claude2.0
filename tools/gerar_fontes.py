#!/usr/bin/env python3
"""Gera as fontes estaticas do plugin a partir das fontes variaveis do kindle-claude.

O KOReader abre fontes variaveis so no peso padrao, entao cada peso usado no
painel vira um arquivo. Precisa do fontTools (pip install fonttools).

    python3 tools/gerar_fontes.py CAMINHO/InterTight.ttf CAMINHO/JetBrainsMono.ttf
"""
import os
import sys

from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "kindle", "claudinho.koplugin", "fonts")

PESOS = {
    "InterTight": [(800, "ExtraBold"), (900, "Black")],
    "JetBrainsMono": [(400, "Regular"), (700, "Bold")],
}


def main():
    os.makedirs(OUT, exist_ok=True)
    for path in sys.argv[1:]:
        familia = os.path.splitext(os.path.basename(path))[0]
        for peso, nome in PESOS[familia]:
            fonte = TTFont(path)
            estatica = instancer.instantiateVariableFont(fonte, {"wght": peso}, updateFontNames=True)
            destino = os.path.join(OUT, f"{familia}-{nome}.ttf")
            estatica.save(destino)
            print(destino, os.path.getsize(destino) // 1024, "KB")


if __name__ == "__main__":
    main()
