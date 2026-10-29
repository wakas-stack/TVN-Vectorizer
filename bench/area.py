"""Per-colour area of a traced image against the source's own coverage (anti-aliasing counted
in proportion): too much area for a dark outline colour means strokes come out too fat."""
import sys, io, re
sys.path[:0] = [".", "bench"]
import numpy as np, resvg_py, engine
from PIL import Image
path = sys.argv[1]
opts = eval(sys.argv[2]) if len(sys.argv) > 2 else {}
data = open(path, "rb").read()
r = engine.trace(data, opts)
pal = [engine.hex_to_rgb(c["hex"]) for c in r["colors"]]
im = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA")).astype(float)
W, H = im.shape[1], im.shape[0]
# source coverage: each pixel split between its two nearest palette colours in proportion
px = im[..., :3].reshape(-1, 3); a = im[..., 3].reshape(-1) / 255
P = np.array(pal, float)
d = ((px[:, None] - P[None]) ** 2).sum(-1)
two = np.argsort(d, 1)[:, :2]
pa, pb = P[two[:, 0]], P[two[:, 1]]
seg = pa - pb
t = np.clip(((px - pb) * seg).sum(1) / np.maximum((seg * seg).sum(1), 1e-6), 0, 1)
src = np.zeros(len(P))
np.add.at(src, two[:, 0], t * a); np.add.at(src, two[:, 1], (1 - t) * a)
# traced area: render without the gap filler and count the nearest palette colour
svg = re.sub(r'<g id="gap-filler".*?</g>', "", r["svg"], flags=re.S).replace(f'width="{W}" height="{H}"', f'width="{W*2}" height="{H*2}"')
g = np.asarray(Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg)))).convert("RGBA")).astype(float)
gp = g[..., :3].reshape(-1, 3); ga = g[..., 3].reshape(-1) > 128
lab = ((gp[ga][:, None] - P[None]) ** 2).sum(-1).argmin(1)
got = np.bincount(lab, minlength=len(P)) / 4
for i in np.argsort(-src)[:8]:
    print(f"{r['colors'][i]['hex']}  source {src[i]:8.0f}  traced {got[i]:8.0f}  {100 * (got[i] / max(src[i], 1) - 1):+6.1f}%")
