"""Where do we differ from vectorizer.ai? Align a capture of its preview with our render and map
the disagreement.

    .venv/bin/python bench/vai_diff.py bench/real/koh-samui.png bench/real/koh-samui-vai-palm.png [opts]

Fits scale and offset of the capture to our render (least colour difference), then reports the
share of pixels that clearly disagree, overall and per region, and writes bench/dbg/vai-diff.png
(vectorizer.ai | ours | disagreement in red).
"""
import io, sys
sys.path[:0] = [".", "bench"]
import numpy as np, resvg_py, engine
from PIL import Image
from scipy import ndimage, optimize

src, cap = sys.argv[1], sys.argv[2]
opts = eval(sys.argv[3]) if len(sys.argv) > 3 else {}
r = engine.trace(open(src, "rb").read(), opts)
W, H = r["width"], r["height"]
K = 4
svg = r["svg"].replace(f'width="{W}" height="{H}"', f'width="{W * K}" height="{H * K}"')
rgba = np.asarray(Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg)))).convert("RGBA")).astype(np.float32)
alpha = rgba[..., 3]
ours = rgba[..., :3] * (alpha[..., None] / 255) + np.array([211, 224, 225], np.float32) * (1 - alpha[..., None] / 255)
src_a = np.asarray(Image.open(src).convert("RGBA").resize((W * K, H * K), Image.NEAREST))[..., 3].astype(np.float32)
vai = np.asarray(Image.open(cap).convert("RGB")).astype(np.float32)
vh, vw = vai.shape[:2]
# skip the viewer's own labels: the top 30 rows and a box round the "640 x 640 px" badge
mask = np.ones((vh, vw), bool); mask[:30] = False; mask[vh - 50:, vw // 2 - 150: vw // 2 + 150] = False
mask &= ~((vai[..., 0] < 140) & (vai[..., 1] < 140) & (vai[..., 2] > 150) & (np.abs(vai[..., 0] - vai[..., 1]) < 20))  # checkerboard grey-blue

def sample(params, step=4):
    s, x0, y0 = params
    yy, xx = np.mgrid[0:vh:step, 0:vw:step]
    ox = (x0 + xx / s) * K; oy = (y0 + yy / s) * K
    g = np.stack([ndimage.map_coordinates(ours[..., c], [oy, ox], order=1, mode="nearest") for c in range(3)], -1)
    inside = (ndimage.map_coordinates(src_a, [oy, ox], order=0, mode="nearest") > 250) & (ox >= 0) & (oy >= 0) & (ox < W * K) & (oy < H * K)
    return g, vai[::step, ::step], mask[::step, ::step] & inside

def cost(p):
    g, v, m = sample(p)
    return float(np.abs(g - v).mean(-1)[m].mean())

import os
p0 = np.array([float(v) for v in os.environ.get("VAI_P0", "3.77,95.6,186.6").split(",")])
best = min((cost(p0 + np.array([ds, dx, dy])), p0 + np.array([ds, dx, dy]))
           for ds in (-0.04, 0, 0.04) for dx in (-1.5, 0, 1.5) for dy in (-1.5, 0, 1.5))[1]
res = optimize.minimize(cost, best, method="Nelder-Mead", options={"xatol": 1e-3, "fatol": 1e-3, "maxiter": 200})
p = res.x
g, v, m = sample(p, 1)
d = np.abs(g - v).max(-1)
bad = (d > 60) & m
print(f"fit scale={p[0]:.4f} x0={p[1]:.2f} y0={p[2]:.2f}  mean diff={res.fun:.2f}")
print(f"pixels clearly different: {100 * bad.sum() / m.sum():.2f} %")
# where: 8 x 5 grid of the capture, worst cells with their image coordinates
gy, gx = 5, 8
cells = []
for i in range(gy):
    for j in range(gx):
        sl = (slice(i * vh // gy, (i + 1) * vh // gy), slice(j * vw // gx, (j + 1) * vw // gx))
        mm = m[sl]
        if mm.sum() > 1000:
            cells.append((100 * bad[sl].sum() / mm.sum(), p[1] + (sl[1].start + sl[1].stop) / 2 / p[0], p[2] + (sl[0].start + sl[0].stop) / 2 / p[0]))
for pct, x, y in sorted(cells, reverse=True)[:8]:
    print(f"  {pct:5.2f} %  around image ({x:.0f}, {y:.0f})")
vis = g.copy(); vis[bad] = [255, 0, 0]
Image.fromarray(np.concatenate([v, g, vis], 1).clip(0, 255).astype(np.uint8)).save("bench/dbg/vai-diff.png")
np.save("bench/dbg/vai-fit.npy", p)
