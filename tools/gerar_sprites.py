#!/usr/bin/env python3
"""Converte design/sprites.json (grades 36x24 do Claudinho chef) em sprites.lua.

    python3 tools/gerar_sprites.py

No sprite: '#' e traco, '+' e cinza, '.' e vazio. Confere que todos os
quadros tem o mesmo tamanho.
"""
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "design", "sprites.json")
OUT = os.path.join(ROOT, "kindle", "claudinho.koplugin", "claudinho", "sprites.lua")


def main():
    with open(SRC, encoding="utf-8") as f:
        sprites = json.load(f)
    nomes = sorted(sprites)
    alt = len(sprites[nomes[0]])
    larg = len(sprites[nomes[0]][0])
    for nome in nomes:
        grade = sprites[nome]
        assert len(grade) == alt and all(len(l) == larg for l in grade), nome
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("-- Gerado por tools/gerar_sprites.py a partir de design/sprites.json.\n")
        f.write("-- Claudinho chef: pixel art do kindle-claude (guithepc, licenca MIT).\n")
        f.write("return {\n")
        f.write(f"    largura = {larg},\n    altura = {alt},\n")
        f.write("    quadros = {\n")
        for nome in nomes:
            f.write(f"        {nome} = {{\n")
            for linha in sprites[nome]:
                f.write(f'            "{linha}",\n')
            f.write("        },\n")
        f.write("    },\n}\n")
    print(OUT, f"{len(nomes)} quadros de {larg}x{alt}")


if __name__ == "__main__":
    main()
