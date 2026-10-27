"""Build static/cmyk-fogra39.json: a CMYK -> Lab table from the Coated FOGRA39 ICC profile.

    .venv/bin/python make_cmyk_table.py [path/to/CoatedFOGRA39.icc]

The table holds, on a 17-step grid per ink (the match pages interpolate between grid points):
- lab: Lab, D50, relative colorimetric - what Adobe apps use by default; the Pantone page
  matches against it
- rgb: the screen colour (sRGB, relative colorimetric with black point compensation, as Adobe
  apps and macOS show CMYK); the hex shown and the Thread page use it
The profile's paper white is saved too.
"""

from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageCms

HERE = Path(__file__).resolve().parent
DEFAULT = "/Library/Application Support/Adobe/Color/Profiles/Recommended/CoatedFOGRA39.icc"
N = 17                                   # grid points per ink: 0, 6.25, ... 100 %


def cmyk_to_lab8(profile, cmyk_bytes: np.ndarray) -> np.ndarray:
    """CMYK bytes (n, 4) -> 8-bit Lab (n, 3) through the profile, relative colorimetric."""
    img = Image.frombytes("CMYK", (len(cmyk_bytes), 1), cmyk_bytes.astype(np.uint8).tobytes())
    t = ImageCms.buildTransform(profile, ImageCms.createProfile("LAB", 5000), "CMYK", "LAB",
                                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC)
    lab = np.frombuffer(ImageCms.applyTransform(img, t).tobytes(), np.uint8).reshape(-1, 3).copy()
    lab[:, 1:] = (lab[:, 1:].view(np.int8).astype(np.int16) + 128).astype(np.uint8)   # Pillow's a, b are signed bytes
    return lab


def cmyk_to_srgb(profile, cmyk_bytes: np.ndarray) -> np.ndarray:
    """CMYK bytes (n, 4) -> sRGB bytes (n, 3), relative colorimetric with black point compensation."""
    img = Image.frombytes("CMYK", (len(cmyk_bytes), 1), cmyk_bytes.astype(np.uint8).tobytes())
    t = ImageCms.buildTransform(profile, ImageCms.createProfile("sRGB"), "CMYK", "RGB",
                                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                                flags=ImageCms.Flags.BLACKPOINTCOMPENSATION)
    return np.frombuffer(ImageCms.applyTransform(img, t).tobytes(), np.uint8).reshape(-1, 3)


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    profile = ImageCms.getOpenProfile(path)
    steps = np.round(np.arange(N) * 255 / (N - 1))
    c, m, y, k = np.meshgrid(steps, steps, steps, steps, indexing="ij")    # C slowest, K fastest
    grid = np.stack([c, m, y, k], -1).reshape(-1, 4)
    lab = cmyk_to_lab8(profile, grid)
    rgb = cmyk_to_srgb(profile, grid)
    white = profile.profile.media_white_point[0]
    out = {
        "name": profile.profile.profile_description,
        "note": "lab: D50 relative colorimetric, L = v*100/255, a = v-128, b = v-128; rgb: sRGB with black point compensation",
        "grid": N,
        "order": "C,M,Y,K (C slowest)",
        "white": [round(v, 6) for v in white],
        "lab": base64.b64encode(lab.tobytes()).decode(),
        "rgb": base64.b64encode(rgb.tobytes()).decode(),
    }
    dest = HERE / "static" / "cmyk-fogra39.json"
    dest.write_text(json.dumps(out, separators=(",", ":")))
    print(f"{dest} {dest.stat().st_size // 1024} KB, {len(grid)} points, white {out['white']}")


if __name__ == "__main__":
    main()
