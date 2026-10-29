"""Timing on bigger and harder images."""
import sys, io, time
sys.path[:0] = [".", "bench"]
import numpy as np, engine
from PIL import Image
from cases import CASES
from run import render

def png(a):
    b = io.BytesIO(); Image.fromarray(a.astype(np.uint8)).save(b, "PNG"); return b.getvalue()

x = np.linspace(0, 1, 300)
cases = {
    "text-400": png(render(CASES["text"], 400)),
    "gradient-300": png(np.stack([np.outer(np.ones(300), x) * 255, np.outer(x, np.ones(300)) * 200, np.full((300, 300), 90)], -1)),
    "flag-1200": png(render(CASES["flag"], 1200)),
    "text-1500": png(render(CASES["text"], 1500)),
}
rng = np.random.default_rng(0)
ph = np.asarray(Image.fromarray(rng.integers(0, 255, (40, 40, 3), dtype=np.uint8)).resize((500, 500), Image.BICUBIC)).astype(float)
cases["photo-500"] = png(np.clip(ph + rng.normal(0, 6, ph.shape), 0, 255))
engine.trace(png(render(CASES["star"], 64)), {})   # warm-up: imports and first-call costs
for name in sys.argv[1:] or cases:
    t = time.time(); r = engine.trace(cases[name], {}); print(f"{name:14} {time.time() - t:6.1f}s  colours={len(r['colors'])} shapes={r['stats']['shapes']}", flush=True)
