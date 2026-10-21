#!/usr/bin/env python3
"""Pré-rend les glyphes des titres du carrousel (Noto Sans Bold, licence OFL).

La TV n'a ni Pillow ni moteur de polices côté Python : jellyfeed y colle ces
glyphes tout faits. Produit, par taille, app/root/font-<taille>.bin (couverture
0-255, une ligne après l'autre, compressée zlib) et app/root/font-<taille>.json
(métriques).

    python3 tools/make-font.py [chemin/NotoSans-Bold.ttf]
"""
import json
import os
import sys
import zlib

from PIL import Image, ImageDraw, ImageFont

FONT = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"
SIZES = (64, 34)  # titre, sous-titre (épisode)
CHARS = ("".join(chr(c) for c in range(32, 127)) + "".join(chr(c) for c in range(160, 256))
         + "ŒœŠšŽžŸ‘’‚“”„–—…•·€™")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "root")

for size in SIZES:
    font = ImageFont.truetype(FONT, size)
    ascent, descent = font.getmetrics()
    height = ascent + descent
    glyphs, x = {}, 0
    for ch in CHARS:
        left, _, right, _ = font.getbbox(ch)
        w = max(right, 0) - min(left, 0)
        glyphs[ch] = [x, w, round(font.getlength(ch)), min(left, 0)]
        x += w + 2
    atlas = Image.new("L", (x, height), 0)
    draw = ImageDraw.Draw(atlas)
    for ch, (gx, w, adv, left) in glyphs.items():
        draw.text((gx - left, 0), ch, font=font, fill=255)
    with open(os.path.join(OUT, "font-%d.bin" % size), "wb") as f:
        f.write(zlib.compress(atlas.tobytes(), 9))
    with open(os.path.join(OUT, "font-%d.json" % size), "w") as f:
        json.dump({"width": x, "height": height, "ascent": ascent, "glyphs": glyphs}, f, ensure_ascii=False,
                  separators=(",", ":"))
    print("font-%d : %d glyphes, %d×%d" % (size, len(glyphs), x, height))
