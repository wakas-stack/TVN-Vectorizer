"""Render one region of a traced image large, under the source: crop.py img x y w h scale "opts" out.png"""
import sys, io
sys.path[:0] = [".", "bench"]
import resvg_py, engine
from PIL import Image
f, x, y, w, h, S = sys.argv[1], *map(int, sys.argv[2:7])
opts = eval(sys.argv[7]) if len(sys.argv) > 7 else {}
out = sys.argv[8] if len(sys.argv) > 8 else "bench/dbg/crop.png"
r = engine.trace(open(f, "rb").read(), opts)
W, H = r["width"], r["height"]
im = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=r["svg"].replace(f'width="{W}" height="{H}"', f'width="{W*S}" height="{H*S}"'))))).convert("RGB")
src = Image.open(f).convert("RGB").resize((W * S, H * S), Image.NEAREST)
b = (x * S, y * S, (x + w) * S, (y + h) * S)
o = Image.new("RGB", (w * S * 2 + 10, h * S), "white"); o.paste(src.crop(b), (0, 0)); o.paste(im.crop(b), (w * S + 10, 0)); o.save(out)
