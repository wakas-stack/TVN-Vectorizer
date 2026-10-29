"""Accuracy benchmark: vectorize ground-truth logos and score the result against the truth.

    .venv/bin/python bench/run.py                 # all runs, prints a table, writes bench/out/
    .venv/bin/python bench/run.py star text       # only these cases
    .venv/bin/python bench/run.py --tracer classic

Scores (rendered at REF x REF px, lower is better except IoU):
  bad%   pixels whose colour is clearly wrong (any channel off by more than 48): misplaced edges,
         lost or extra parts
  edge   mean colour error (0-255) in a 3 px band around the true edges: how closely outlines follow
  nodes  path segments written (fewer = cleaner, easier to edit)
"""

from __future__ import annotations

import argparse
import io
import re
import sys
import time
from pathlib import Path

import numpy as np
import resvg_py
from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "bench"))

import engine  # noqa: E402
from cases import CASES, RUNS, RUNS_BIG  # noqa: E402

REF = 512
OPTS: dict = {}


def render(svg: str, size: int) -> np.ndarray:
    png = resvg_py.svg_to_bytes(svg_string=svg, width=size, height=size, background="#ffffff")
    return np.asarray(Image.open(io.BytesIO(bytes(png))).convert("RGB")).astype(np.int16)


def count_nodes(svg: str) -> int:
    n = 0
    for d in re.findall(r' d="([^"]+)"', svg.split('id="removed-shapes"')[0]):
        if 'class="gap"' in d:
            continue
        n += len(re.findall(r"[MLCQAHVS]", d))
    n += 4 * len(re.findall(r"<(circle|ellipse)\b", svg)) + 4 * len(re.findall(r"<rect\b", svg))
    return n


def strip_gap(svg: str) -> str:
    return re.sub(r'<path class="gap"[^>]*/>', "", svg)


def score(truth: np.ndarray, got: np.ndarray):
    diff = np.abs(truth - got).max(-1)
    bad = float((diff > 48).mean() * 100)
    g = np.zeros(truth.shape[:2], bool)
    g[:, 1:] |= np.abs(truth[:, 1:] - truth[:, :-1]).max(-1) > 24
    g[1:, :] |= np.abs(truth[1:] - truth[:-1]).max(-1) > 24
    band = np.asarray(Image.fromarray(g.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(7))) > 0
    edge = float(np.abs(truth - got).mean(-1)[band].mean())
    return bad, edge


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*")
    ap.add_argument("--tracer", default="precise")
    ap.add_argument("--tag", default="")
    ap.add_argument("--opts", default="{}")
    ap.add_argument("--big", action="store_true", help="the 480 px runs instead")
    a = ap.parse_args(argv)
    OPTS.update(eval(a.opts))
    out = ROOT / "bench" / "out"
    out.mkdir(exist_ok=True)
    rows = []
    tiles = []
    for case, px, jpg in (RUNS_BIG if a.big else RUNS):
        if a.only and case not in a.only:
            continue
        svg = CASES[case]
        src = Image.fromarray(render(svg, px).astype(np.uint8))
        if jpg:
            b = io.BytesIO(); src.save(b, "JPEG", quality=jpg); src = Image.open(io.BytesIO(b.getvalue())).convert("RGB")
        b = io.BytesIO(); src.save(b, "PNG")
        t0 = time.time()
        r = engine.trace(b.getvalue(), {"tracer": a.tracer, **OPTS})
        dt = time.time() - t0
        truth = render(svg, REF)
        got = render(r["svg"], REF)
        bad, edge = score(truth, got)
        nodes = count_nodes(r["svg"])
        name = f"{case}@{px}" + (f"q{jpg}" if jpg else "")
        rows.append((name, bad, edge, nodes, len(r["colors"]), dt))
        up = np.asarray(src.resize((REF, REF), Image.NEAREST))
        tiles.append(np.concatenate([truth.astype(np.uint8), up, got.astype(np.uint8)], 1))
    print(f"{'run':16} {'bad%':>6} {'edge':>6} {'nodes':>6} {'cols':>4} {'sec':>5}")
    for n, bad, edge, nodes, nc, dt in rows:
        print(f"{n:16} {bad:6.2f} {edge:6.2f} {nodes:6d} {nc:4d} {dt:5.2f}")
    if rows:
        m = np.array([r[1:4] for r in rows], float).mean(0)
        print(f"{'MEAN':16} {m[0]:6.2f} {m[1]:6.2f} {m[2]:6.0f}")
        sheet = Image.fromarray(np.concatenate(tiles, 0))
        sheet.thumbnail((3 * 400, 10_000))
        sheet.save(out / f"sheet{('-' + a.tag) if a.tag else ''}.png")


if __name__ == "__main__":
    main()
