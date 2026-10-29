"""Draw the app icon, the EMB Pros mark (static/emb-pros-logo.svg: an embroidery hoop, a line of
running stitches inside it and the needle making the last one) on a Mac icon tile, into an
.iconset folder."""

import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ORANGE, INK, CLOTH = (255, 90, 31, 255), (29, 34, 48, 255), (255, 243, 236, 255)


def bezier(p0, p1, p2, p3, n=1500):
    out = []
    for i in range(n + 1):
        t = i / n
        u = 1 - t
        out.append(tuple(u ** 3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3)))
    return out


def draw(size: int) -> Image.Image:
    s = 4  # draw large, then scale down for smooth edges
    W = size * s
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    # the tile, as macOS draws app icons: a rounded square inset from the edge, a soft shadow under it
    pad, r = W * 0.098, W * 0.18
    shadow = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((pad, pad + W * 0.012, W - pad, W - pad + W * 0.012), r, fill=(0, 0, 0, 60))
    im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(W * 0.012)))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((pad, pad, W - pad, W - pad), r, fill=(255, 255, 255, 255), outline=(0, 0, 0, 22), width=max(1, int(W * 0.004)))
    # the mark, in its own 40-unit box (as the SVG), centred on the tile
    k = (W - 2 * pad) * 0.72 / 40
    ox, oy = W / 2 - 20.5 * k, W / 2 - 21 * k
    P = lambda x, y: (ox + x * k, oy + y * k)
    cx, cy = P(20, 21)
    R = 17.2 * k
    d.ellipse((cx - R, cy - R, cx + R, cy + R), fill=CLOTH)
    w = 3.6 * k
    d.ellipse((cx - R - w / 2, cy - R - w / 2, cx + R + w / 2, cy + R + w / 2), outline=ORANGE, width=round(w))
    r2 = 12.8 * k
    d.ellipse((cx - r2, cy - r2, cx + r2, cy + r2), outline=(255, 190, 160, 255), width=max(1, round(1.1 * k)))
    # running stitches along the curve: 3.2 on, 2.5 off
    pts = bezier(P(8, 27.5), P(11.5, 20.5), P(16, 31), P(21.5, 24.5))
    dist = [0.0]
    for a, b in zip(pts, pts[1:]):
        dist.append(dist[-1] + math.dist(a, b))
    on, off, sw = 3.2 * k, 2.5 * k, max(1, round(2.3 * k))
    start = 0.0
    while start < dist[-1]:
        seg = [p for p, t in zip(pts, dist) if start <= t <= start + on]
        for e in seg:       # a solid round-ended stitch: discs along it (the curve is sampled finely)
            d.ellipse((e[0] - sw / 2, e[1] - sw / 2, e[0] + sw / 2, e[1] + sw / 2), fill=INK)
        start += on + off
    # the needle, its eye near the top
    a, b = P(39.5, 0.8), P(23.6, 21.4)
    nw = max(1, round(2.6 * k))
    d.line([a, b], fill=INK, width=nw)
    for e in (a, b):
        d.ellipse((e[0] - nw / 2, e[1] - nw / 2, e[0] + nw / 2, e[1] + nw / 2), fill=INK)
    eye = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    ex, ey = P(37.4, 3.5)
    ImageDraw.Draw(eye).ellipse((ex - 1 * k, ey - 2.3 * k, ex + 1 * k, ey + 2.3 * k), fill=CLOTH)
    im.alpha_composite(eye.rotate(-38, center=(ex, ey)))
    return im.resize((size, size), Image.LANCZOS)


out = Path(sys.argv[1])
for base in (16, 32, 128, 256, 512):
    draw(base).save(out / f"icon_{base}x{base}.png")
    draw(base * 2).save(out / f"icon_{base}x{base}@2x.png")
