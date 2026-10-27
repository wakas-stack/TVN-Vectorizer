"""Build static/leatherette/: leather textures and the colour list for the Faux/Leather patch.

    .venv/bin/python make_leatherette.py <folder of photos>

The photos are the blank-sheet images (the 2nd image of each listing) of Lone Star Adhesive's
Heritage Collection Durra-Bull Premium Leatherette sheets, used with the owner's permission.
Each one is cropped to the leather, its large-scale lighting is evened out (the patch renderer
adds its own), and it is saved as a small JPEG. catalog.json lists every sheet: top colour,
the core colour a laser engraving reveals, its texture and its average colour.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

from patch import blur

HERE = Path(__file__).resolve().parent
OUT = HERE / "static" / "leatherette"
CORES = {"Black": "#1c1c1c", "Silver": "#b9bcc0", "Gold": "#c8a24a", "Copper": "#b5714a"}

# texture id -> words in the photo's file name; crop (x0, x1) as fractions of the width
TEXTURES = {
    "buckskin": ("buckskin", (0.17, 0.83)), "walnut": ("walnut", (0.17, 0.83)),
    "rawhide": ("rawhide", (0.17, 0.83)), "bright-white": ("bright-white", (0.17, 0.83)),
    "flint": ("flint", (0.17, 0.83)), "charcoal": ("charcoal", (0.17, 0.83)),
    "black": ("black-black", (0.17, 0.83)), "sand": ("sand-black", (0.17, 0.83)),
    "glow": ("glow-in-the-dark", (0.53, 0.83)),          # daylight half; the other half glows
    "primrose": ("primrose", (0.17, 0.83)), "olive": ("olive", (0.17, 0.83)),
    "ruby": ("ruby", (0.17, 0.83)), "indigo": ("indigo", (0.17, 0.83)),
    "orange": ("orange", (0.17, 0.83)), "yellow": ("yellow", (0.17, 0.83)),
    "violet": ("violet", (0.17, 0.83)), "maroon": ("maroon", (0.17, 0.83)),
    "eggshell": ("eggshell", (0.17, 0.83)), "seafoam": ("seafoam", (0.17, 0.83)),
    "kelly-green": ("kelly-green", (0.17, 0.83)), "sky-blue": ("sky-blue", (0.17, 0.83)),
}

# (top colour, core colour, texture id, colour when there is no photo), in the store's order
SHEETS = [
    ("Buckskin", "Black", "buckskin", None), ("Walnut", "Black", "walnut", None),
    ("Rawhide", "Black", "rawhide", None), ("Bright White", "Black", "bright-white", None),
    ("Flint", "Black", "flint", None), ("Charcoal", "Black", "charcoal", None),
    ("Black", "Black", "black", None), ("Sand", "Black", "sand", None),
    ("Black", "Silver", "black", None), ("Glow-in-the-Dark", "Black", "glow", None),
    ("Primrose", "Black", "primrose", None), ("Olive", "Black", "olive", None),
    ("Ruby", "Black", "ruby", None), ("Indigo", "Black", "indigo", None),
    ("Saddle Tan", "Black", None, "#c29a68"),            # no blank photo in its listing
    ("Black", "Gold", "black", None), ("Orange", "Black", "orange", None),
    ("Black", "Copper", "black", None), ("Yellow", "Black", "yellow", None),
    ("Violet", "Black", "violet", None), ("Maroon", "Black", "maroon", None),
    ("Eggshell", "Black", "eggshell", None), ("Seafoam Green", "Black", "seafoam", None),
    ("Kelly Green", "Black", "kelly-green", None), ("Sky Blue", "Black", "sky-blue", None),
    ("Indigo", "Silver", "indigo", None), ("Walnut", "Silver", "walnut", None),
    ("Walnut", "Gold", "walnut", None), ("Indigo", "Gold", "indigo", None),
]


def texture(path: Path, xr) -> np.ndarray:
    im = Image.open(path).convert("RGB")
    w, h = im.size
    im = im.crop((int(w * xr[0]), int(h * 0.04), int(w * xr[1]), int(h * 0.86)))   # some photos darken at the bottom edge
    im = im.resize((640, round(640 * im.height / im.width)), Image.LANCZOS)
    a = np.asarray(im, np.float32) / 255
    # even lighting per channel (the photos shift hue as well as brightness), keep the grain
    for ch in range(3):
        low = blur(a[..., ch], im.width * 0.15)
        a[..., ch] *= a[..., ch].mean() / np.maximum(low, 1e-3)
    return np.clip(a, 0, 1)


def main():
    src = Path(sys.argv[1])
    OUT.mkdir(parents=True, exist_ok=True)
    avg = {}
    for tid, (words, xr) in TEXTURES.items():
        path = next(p for p in sorted(src.glob("*.png")) if words in p.name)
        a = texture(path, xr)
        Image.fromarray((a * 255 + 0.5).astype(np.uint8)).save(OUT / f"{tid}.jpg", quality=86, optimize=True)
        avg[tid] = "#" + "".join(f"{round(v * 255):02x}" for v in a.reshape(-1, 3).mean(0))
    sheets = []
    for top, core, tid, color in SHEETS:
        sid = f"{top}-{core}".lower().replace(" ", "-")
        sheets.append({"id": sid, "name": f"{top} / {core}", "core": core, "core_hex": CORES[core],
                       "texture": tid, "color": color or avg[tid]})
    (OUT / "catalog.json").write_text(json.dumps({
        "collection": "Heritage Collection Durra-Bull Premium Leatherette (Lone Star Adhesive)",
        "source": "https://lonestaradhesive.com/collections/heritage-leatherette",
        "sheets": sheets}, indent=1))
    size = sum(p.stat().st_size for p in OUT.iterdir())
    print(f"{len(sheets)} sheets, {len(TEXTURES)} textures, {size // 1024} KB in {OUT}")


if __name__ == "__main__":
    main()
