"""Draw the app icon (a vector pen node over colour layers) into an .iconset folder."""

import sys
from pathlib import Path

from PIL import Image, ImageDraw


def draw(size: int) -> Image.Image:
    s = 4  # draw large, then scale down for smooth edges
    W = size * s
    im = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad, r = int(W * 0.09), int(W * 0.2)
    d.rounded_rectangle((pad, pad, W - pad, W - pad), r, fill=(24, 27, 36, 255))
    # three stacked colour layers
    for i, col in enumerate([(30, 90, 200), (225, 45, 45), (245, 190, 30)]):
        o = int(W * (0.26 + 0.09 * i))
        d.rounded_rectangle((o, o, o + int(W * 0.34), o + int(W * 0.34)), int(W * 0.05), fill=col + (255,))
    # bezier handle: line with square anchor and round control points
    a, b = (int(W * 0.24), int(W * 0.76)), (int(W * 0.76), int(W * 0.24))
    d.line([a, b], fill=(255, 255, 255, 255), width=max(2, int(W * 0.018)))
    k = int(W * 0.045)
    d.rectangle((W // 2 - k, W // 2 - k, W // 2 + k, W // 2 + k), fill=(255, 255, 255, 255))
    for p in (a, b):
        d.ellipse((p[0] - k, p[1] - k, p[0] + k, p[1] + k), fill=(255, 90, 31, 255))
    return im.resize((size, size), Image.LANCZOS)


out = Path(sys.argv[1])
for base in (16, 32, 128, 256, 512):
    draw(base).save(out / f"icon_{base}x{base}.png")
    draw(base * 2).save(out / f"icon_{base}x{base}@2x.png")
