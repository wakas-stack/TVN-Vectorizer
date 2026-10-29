"""Coverage check: a traced image must cover every opaque part of the source, with no hole.

    .venv/bin/python bench/holes.py              # every benchmark case and every bench/real/*.png

Each result is drawn without the gap filler (whose strokes would hide a hole) and compared with
the source's opaque area, shrunk by a pixel so anti-aliased outer edges do not count. Any
uncovered patch is a hole: a shape that was dropped or that no longer meets its neighbour.
Exits 1 when any image has one, so run it after every change to the tracer.
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

import numpy as np
import resvg_py
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "bench")]

import engine  # noqa: E402
from cases import CASES, RUNS, RUNS_BIG  # noqa: E402
from run import render  # noqa: E402

Z = 4   # drawn at 4x, so a hole a quarter of a pixel wide still shows


def holes(data: bytes, opts: dict | None = None):
    r = engine.trace(data, opts or {})
    W, H = r["width"], r["height"]
    svg = re.sub(r'<g id="gap-filler".*?</g>', "", r["svg"], flags=re.S)
    svg = svg.replace(f'width="{W}" height="{H}"', f'width="{W * Z}" height="{H * Z}"')
    got = np.asarray(Image.open(io.BytesIO(bytes(resvg_py.svg_to_bytes(svg_string=svg)))).convert("RGBA"))[..., 3]
    src = np.asarray(Image.open(io.BytesIO(data)).convert("RGBA"))[..., 3]
    want = np.asarray(Image.fromarray(src).resize((W * Z, H * Z), Image.NEAREST)) > 200
    want = ndimage.binary_erosion(want, iterations=Z)
    gap = want & (got < 128)
    lab, k = ndimage.label(gap)
    spots = []
    for sl in ndimage.find_objects(lab)[:5]:
        spots.append((round((sl[1].start + sl[1].stop) / 2 / Z), round((sl[0].start + sl[0].stop) / 2 / Z)))
    return int(gap.sum()), k, spots


def main():
    items = []
    for case, px, jpg in RUNS + RUNS_BIG:
        src = Image.fromarray(render(CASES[case], px).astype(np.uint8))
        if jpg:
            b = io.BytesIO(); src.save(b, "JPEG", quality=jpg); src = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
        b = io.BytesIO(); src.save(b, "PNG")
        items.append((f"{case}@{px}" + (f"q{jpg}" if jpg else ""), b.getvalue()))
    for p in sorted((ROOT / "bench" / "real").glob("*.png")):
        if "vectorizerai" in p.name or "-vai-" in p.name:     # captures of vectorizer.ai, not inputs
            continue
        items.append((p.name, p.read_bytes()))
    bad = 0
    for name, data in items:
        px, k, spots = holes(data)
        flag = "HOLE" if k else "ok"
        bad += bool(k)
        print(f"{flag:4} {name:28} uncovered={px / Z / Z:7.1f} px  pieces={k}" + (f"  near {spots}" if k else ""))
    print(f"{bad} image(s) with holes")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
