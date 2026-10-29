"""Shape-level differences from vectorizer.ai (thin edge disagreements filtered out), largest
first, with tiles (vectorizer.ai left, ours right) in bench/dbg/vai-blobs.png. Run vai_diff.py
first: it saves the alignment."""
import sys
import os
sys.argv = sys.argv[:1] + os.environ.get("VAI_PAIR", "bench/real/koh-samui.png,bench/real/koh-samui-vai-palm.png").split(",") + sys.argv[1:]
exec(open("bench/vai_diff.py").read().split("p0 = np.array")[0])
p = np.load("bench/dbg/vai-fit.npy")
g, v, m = sample(p, 1)
d = (np.abs(g - v).max(-1) > 60) & m
blob = ndimage.binary_opening(d, np.ones((5, 5)))
lab, k = ndimage.label(blob)
sizes = np.bincount(lab.ravel())[1:]
print(f"shape differences: {k}, {100 * blob.sum() / m.sum():.2f}% of region; edge disagreement {100 * d.sum() / m.sum():.2f}%")
objs = ndimage.find_objects(lab)
tiles = []
for i in np.argsort(-sizes)[:8]:
    sl = objs[i]; cy = (sl[0].start + sl[0].stop) // 2; cx = (sl[1].start + sl[1].stop) // 2
    print(f"  {sizes[i] / p[0] ** 2:6.1f} img-px²  at ({p[1] + cx / p[0]:.0f},{p[2] + cy / p[0]:.0f})")
    y0 = min(max(0, cy - 60), v.shape[0] - 120); x0 = min(max(0, cx - 60), v.shape[1] - 120)
    tiles.append(np.concatenate([v[y0:y0 + 120, x0:x0 + 120], g[y0:y0 + 120, x0:x0 + 120]], 1))
if tiles:
    Image.fromarray(np.concatenate(tiles, 0).clip(0, 255).astype(np.uint8)).resize((480, 240 * len(tiles)), Image.NEAREST).save("bench/dbg/vai-blobs.png")
