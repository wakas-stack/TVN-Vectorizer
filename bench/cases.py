"""Ground-truth test logos: each case is an SVG drawn at 100 x 100 user units.

The benchmark rasterizes the SVG small (as an uploaded logo would be), vectorizes that
bitmap, then renders both the true SVG and the result large and compares them.
"""

from __future__ import annotations

import math


def _wrap(body: str, bg: str = "#ffffff") -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="100" height="100">'
            f'<rect width="100" height="100" fill="{bg}"/>{body}</svg>')


def _star(cx, cy, r1, r2, n=5, rot=-90):
    pts = []
    for k in range(2 * n):
        r = r1 if k % 2 == 0 else r2
        a = math.radians(rot + k * 180 / n)
        pts.append(f"{cx + r * math.cos(a):.3f},{cy + r * math.sin(a):.3f}")
    return " ".join(pts)


CASES = {
    # whole shapes: circle, ring, rounded rectangle, rotated square
    "shapes": _wrap(
        '<circle cx="27" cy="27" r="19" fill="#e12d2d"/>'
        '<circle cx="73" cy="27" r="18" fill="#1e5ac8"/><circle cx="73" cy="27" r="9" fill="#ffffff"/>'
        '<rect x="8" y="56" width="40" height="34" rx="7" fill="#f5be1e"/>'
        '<rect x="60" y="58" width="26" height="26" fill="#2a9d4b" transform="rotate(30 73 71)"/>'),
    # sharp corners and straight edges
    "star": _wrap(f'<polygon points="{_star(50, 52, 46, 19)}" fill="#202024"/>'
                  f'<polygon points="{_star(50, 52, 22, 9)}" fill="#f2b705"/>'),
    # smooth free-form curves
    "blob": _wrap('<path d="M20 50 C20 15 55 5 70 25 C85 45 95 60 75 80 C55 100 20 85 20 50 Z" fill="#7b2cbf"/>'
                  '<path d="M38 50 C38 38 52 30 60 42 C68 54 58 66 48 64 C40 62 38 58 38 50 Z" fill="#ffd6ff"/>'),
    # lettering
    "text": _wrap('<text x="50" y="44" font-family="Helvetica, Arial" font-weight="bold" font-size="30" '
                  'text-anchor="middle" fill="#111111">ABC</text>'
                  '<text x="50" y="82" font-family="Georgia, Times" font-size="26" text-anchor="middle" '
                  'fill="#c1121f">Rsg&amp;</text>'),
    # thin line art
    "lines": _wrap('<g fill="none" stroke="#0b3954" stroke-width="2.2" stroke-linecap="round">'
                   '<path d="M10 85 Q50 5 90 85"/><circle cx="50" cy="60" r="14"/>'
                   '<path d="M15 20 L85 20"/><path d="M20 90 L80 30"/></g>'),
    # several touching colours (shared edges, no outline)
    "flag": _wrap('<path d="M0 0 H100 V100 Z" fill="#003049"/>'
                  '<circle cx="50" cy="50" r="30" fill="#fcbf49"/>'
                  '<path d="M50 20 A30 30 0 0 1 50 80 Z" fill="#d62828"/>', bg="#eae2b7"),
}

# (case, pixel size, jpeg quality or None)
RUNS = [(c, 64, None) for c in CASES] + [(c, 128, None) for c in CASES] + [(c, 128, 70) for c in CASES]

# larger uploads (what most real logos are): clean and as a JPEG
RUNS_BIG = [(c, 480, None) for c in ("shapes", "star", "text", "lines", "flag")] + [(c, 480, 80) for c in ("star", "text", "flag")]
