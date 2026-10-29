"""Trace a real image and save a zoomed crop of the result next to the input.

    .venv/bin/python bench/real.py bench/real/koh-samui.png 380,120,140 "{}" tag
"""
import io, sys, time
sys.path[:0] = [".", "bench"]
import numpy as np, engine
from PIL import Image
from run import render

path, crop = sys.argv[1], [int(v) for v in sys.argv[2].split(",")]
opts = eval(sys.argv[3]) if len(sys.argv) > 3 else {}
tag = sys.argv[4] if len(sys.argv) > 4 else "x"
data = open(path, "rb").read()
t = time.time(); r = engine.trace(data, opts); dt = time.time() - t
open(f"bench/dbg/real-{tag}.svg", "w").write(r["svg"])
im = Image.open(path).convert("RGBA")
W, H = im.size
Z = int(sys.argv[5]) if len(sys.argv) > 5 else 4
x, y, s = crop
full = render(r["svg"].replace(f'width="{W}" height="{H}"', ""), W * Z)
got = full[y * Z:(y + s) * Z, x * Z:(x + s) * Z].astype(np.uint8)
bg = Image.new("RGBA", im.size, "white"); bg.alpha_composite(im)
inp = np.asarray(bg.convert("RGB").crop((x, y, x + s, y + s)).resize((s * Z, s * Z), Image.NEAREST))
Image.fromarray(np.concatenate([inp, got], 1)).save(f"bench/dbg/real-{tag}.png")
print(f"{dt:.1f}s colours={len(r['colors'])} shapes={r['stats']['shapes']} nodes~{r['svg'].count('C') + r['svg'].count('L')}")
