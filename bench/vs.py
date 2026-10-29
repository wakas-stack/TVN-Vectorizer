"""Stack a vectorizer.ai preview capture over our render of the same region.

    .venv/bin/python bench/vs.py bench/real/koh-samui.png bench/real/koh-samui-vai-palm.png 3.77 95.6 186.6 out.png "{}"
"""
import sys, io
sys.path[:0] = [".", "bench"]
import resvg_py, engine
from PIL import Image
src, cap, S, x0, y0, out = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4]), float(sys.argv[5]), sys.argv[6]
opts = eval(sys.argv[7]) if len(sys.argv) > 7 else {}
r = engine.trace(open(src, "rb").read(), opts)
W, H = r["width"], r["height"]
svg = r["svg"].replace(f'width="{W}" height="{H}"', f'width="{int(W * S)}" height="{int(H * S)}"')
im = Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg, background="#d3e0e1")))).convert("RGB")
vai = Image.open(cap).convert("RGB")
ours = im.crop((int(x0 * S), int(y0 * S), int(x0 * S) + vai.width, int(y0 * S) + vai.height))
o = Image.new("RGB", (vai.width, vai.height * 2 + 10), "white"); o.paste(vai, (0, 0)); o.paste(ours, (0, vai.height + 10)); o.save(out)
print("done", r["stats"]["shapes"], "shapes")
