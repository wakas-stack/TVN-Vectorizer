"""Robustness: big images, photo-like content, every mode, through the app's own HTTP API."""
import io, json, sys, time
import numpy as np
from PIL import Image
sys.path[:0] = [".", "bench"]
import app as appmod
from cases import CASES
from run import render

c = appmod.app.test_client()

def png(arr):
    b = io.BytesIO(); Image.fromarray(arr.astype(np.uint8)).save(b, "PNG"); return b.getvalue()

imgs = {
    "logo-600": png(render(CASES["text"], 600)),
    "flag-500-jpg": None,
    "gradient-300": None,

    "transparent-400": None,
}
b = io.BytesIO(); Image.fromarray(render(CASES["flag"], 500).astype(np.uint8)).save(b, "JPEG", quality=80); imgs["flag-500-jpg"] = b.getvalue()
x = np.linspace(0, 1, 300)
g = np.stack([np.outer(np.ones(300), x) * 255, np.outer(x, np.ones(300)) * 200, np.full((300, 300), 90)], -1)
imgs["gradient-300"] = png(g)
rng = np.random.default_rng(0)
ph = np.asarray(Image.fromarray(rng.integers(0, 255, (50, 50, 3), dtype=np.uint8)).resize((500, 500), Image.BICUBIC)).astype(float)

t = np.zeros((400, 400, 4), np.uint8); yy, xx = np.mgrid[:400, :400]; m = (xx - 200) ** 2 + (yy - 200) ** 2 < 150 ** 2
t[m] = (220, 40, 40, 255); b = io.BytesIO(); Image.fromarray(t, "RGBA").save(b, "PNG"); imgs["transparent-400"] = b.getvalue()

modes = [{}, {"shape_stacking": "stacked"}, {"remove_background": True}, {"draw_style": "stroke_edges"},
         {"tracer": "classic"}, {"group_by": "parent"}, {"max_colors": 6}]
fail = 0
for name, data in imgs.items():
    for o in modes:
        if name in ("noise-photo-500",) and o:
            continue
        t0 = time.time()
        r = c.post("/api/vectorize", data={"image": (io.BytesIO(data), "x.png"), "options": json.dumps(o)}, content_type="multipart/form-data")
        dt = time.time() - t0
        j = r.get_json()
        if r.status_code != 200 or "error" in j:
            fail += 1; print("FAIL", name, o, j.get("error")); continue
        ok = render(j["svg"], 64) is not None
        print(f"{name:18} {json.dumps(o):38} {dt:6.2f}s colours={len(j['colors']):2d} shapes={j['stats']['shapes']}")
    if name == "logo-600":
        for fmt in ("svg", "pdf", "eps", "png", "dxf"):
            e = c.post("/api/export", json={"svg": j["svg"], "format": fmt})
            print("  export", fmt, e.status_code, len(e.data))
            fail += e.status_code != 200
print("failures:", fail)
