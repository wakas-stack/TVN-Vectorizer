"""AI upscaling before tracing: Real-ESRGAN (x4plus anime 6B, made for illustration and flat
colour art) run locally with onnxruntime.

A small, blurred logo does not hold the shape of its smallest parts (12 px lettering, the gap
between two strokes): no tracing of its pixels can recover them. The network redraws the image
four times larger with crisp edges, as it learned drawings look; the tracer then works on that.
The weights are the official release (github.com/xinntao/Real-ESRGAN, v0.2.2.4), converted to
ONNX; nothing leaves this computer. Without the model file or onnxruntime, tracing goes on as
before.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

MODEL = Path(__file__).resolve().parent / "models" / "realesrgan_anime6b_x4.onnx"
MAX_SIDE = 1000           # larger images already hold their detail, and would take long
TILE, PAD = 192, 12       # run in tiles (bounded memory), overlapping so seams do not show

_session = None


def available() -> bool:
    if not MODEL.exists():
        return False
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        return False
    return True


def _sess():
    global _session
    if _session is None:
        import onnxruntime as ort
        so = ort.SessionOptions()
        so.intra_op_num_threads = os.cpu_count() or 4
        _session = ort.InferenceSession(str(MODEL), so, providers=["CPUExecutionProvider"])
    return _session


def _x4(rgb: np.ndarray) -> np.ndarray:
    """(H, W, 3) uint8 -> (4H, 4W, 3) float32 0..1, tile by tile."""
    H, W = rgb.shape[:2]
    x = rgb.astype(np.float32).transpose(2, 0, 1) / 255
    out = np.zeros((3, H * 4, W * 4), np.float32)
    s = _sess()
    for y0 in range(0, H, TILE):
        for x0 in range(0, W, TILE):
            y1, x1 = min(H, y0 + TILE), min(W, x0 + TILE)
            ya, xa = max(0, y0 - PAD), max(0, x0 - PAD)
            yb, xb = min(H, y1 + PAD), min(W, x1 + PAD)
            y = s.run(None, {"input": x[None, :, ya:yb, xa:xb]})[0][0]
            out[:, y0 * 4:y1 * 4, x0 * 4:x1 * 4] = y[:, (y0 - ya) * 4:(y1 - ya) * 4, (x0 - xa) * 4:(x1 - xa) * 4]
    return out.transpose(1, 2, 0).clip(0, 1)


def upscale(im: Image.Image, scale: int = 2) -> Image.Image:
    """The RGBA image `scale` times larger: colours redrawn by the network (made 4x, then
    reduced), transparency enlarged smoothly."""
    im = im.convert("RGBA")
    W, H = im.size
    a = np.asarray(im)
    alpha = a[..., 3]
    rgb = a[..., :3]
    if alpha.min() < 255:                      # what lies under transparency: the nearest opaque colour
        bg = np.asarray(Image.fromarray(rgb).filter(__import__("PIL.ImageFilter", fromlist=["x"]).MedianFilter(3)))
        rgb = np.where(alpha[..., None] > 0, rgb, bg)
    big = Image.fromarray((_x4(rgb) * 255).round().astype(np.uint8))
    big = big.resize((W * scale, H * scale), Image.LANCZOS)
    al = Image.fromarray(alpha).resize((W * scale, H * scale), Image.LANCZOS)
    big.putalpha(al)
    return big
