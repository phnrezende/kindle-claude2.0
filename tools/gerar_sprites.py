#!/usr/bin/env python3
"""Converte design/sprites.json (grades 36x24 do Claudinho chef) em sprites.lua.

    python3 tools/gerar_sprites.py

No sprite: '#' e traco, '+' e cinza, '.' e vazio. Tambem calcula o recorte
(a menor caixa que contem todos os quadros), usado pelo overlay da leitura
para nao desperdicar espaco.
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
    x0, y0, x1, y1 = larg, alt, -1, -1
    for nome in nomes:
        grade = sprites[nome]
        assert len(grade) == alt and all(len(l) == larg for l in grade), nome
        for y, linha in enumerate(grade):
            for x, ch in enumerate(linha):
                if ch != ".":
                    x0, y0, x1, y1 = min(x0, x), min(y0, y), max(x1, x), max(y1, y)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("-- Gerado por tools/gerar_sprites.py a partir de design/sprites.json.\n")
        f.write("-- Claudinho chef: pixel art do kindle-claude (guithepc, licenca MIT).\n")
        f.write("return {\n")
        f.write(f"    largura = {larg},\n    altura = {alt},\n")
        f.write(f"    recorte = {{ x = {x0}, y = {y0}, w = {x1 - x0 + 1}, h = {y1 - y0 + 1} }},\n")
        f.write("    quadros = {\n")
        for nome in nomes:
            f.write(f"        {nome} = {{\n")
            for linha in sprites[nome]:
                f.write(f'            "{linha}",\n')
            f.write("        },\n")
        f.write("    },\n}\n")
    print(OUT, f"recorte x={x0} y={y0} w={x1 - x0 + 1} h={y1 - y0 + 1}")


if __name__ == "__main__":
    main()
