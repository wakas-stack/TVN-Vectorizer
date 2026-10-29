"""Patch mockups: show a logo as an embroidered, woven, dye-sublimated, leather, PVC rubber,
silicone, suede or HTV (heat transfer vinyl) patch.

The logo is traced into colour regions (engine.trace). Raised thread, borders and
pressed leather are built from those vector regions: shrinking a region step by step
(shapely buffers) gives a smooth distance-from-edge field, which becomes the height
of the material. The height is lit, textured and coloured with NumPy.
"""

from __future__ import annotations

import io
import math
import os
import re
from collections import OrderedDict
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from shapely import affinity, minimum_bounding_circle, minimum_bounding_radius
from shapely.geometry import LineString, MultiPolygon, Polygon, box
from shapely.ops import substring, unary_union
from shapely.validation import make_valid

import engine

# memory each logo may keep for drawing it again (masks, height maps at each size): the newest kept
CACHE_BYTES = int(os.environ.get("EMB_CACHE_MB", "512")) * 2 ** 20


def _nbytes(v):
    if isinstance(v, np.ndarray):
        return v.nbytes
    if isinstance(v, (tuple, list)):
        return sum(_nbytes(x) for x in v)
    return 0


STYLES = ("embroidery", "woven", "sublimated", "leather", "pvc", "silicone", "suede", "htv")
SEAMED = ("leather", "suede")          # a stitched seam on the patch (not a textile border)

DEFAULTS = {
    "style": "embroidery",
    "roles": {},              # {"#rrggbb": "base" | "thread" | "hidden"}; colours not listed use the analysis default
    "recolor": {},            # {"#rrggbb": "#rrggbb"} colour changes
    "shape": "outline",       # outline | logo | circle | rounded | rectangle
    "fabric_color": None,     # fabric when no logo colour is the fabric (None = contrast with the thread)
    "border": "merrow",       # merrow | satin | laser | none   (leather, suede: seam | none; pvc, silicone: rim | none)
    "border_color": None,     # None = same as the fabric
    "border_width": 0.035,    # fraction of the patch size
    "border_thickness": 1.0,  # how thick the border stands (merrow, satin, rim) or how dark (laser), 0.3..2.5
    "relief": 0.7,            # 0..1 raised thread / pressing depth
    "density": 1.0,           # thread density, 0.5..2
    "angle": 45,              # stitch direction, degrees
    "light": 135,             # light comes from this direction, degrees (135 = top left)
    "gloss": 0.5,             # 0..1 thread sheen
    "full_embroidery": False, # stitch the fabric too (100% embroidered)
    "leather_color": "#a8693a",
    "leather_finish": "deboss",  # deboss | emboss | engrave
    "leather_texture": None,  # id of a photo texture in static/leatherette (None = drawn leather)
    "engrave_color": None,    # colour a laser engraving reveals (None = burnt brown)
    "logo_scale": 1.0,        # size of the logo inside the patch shape, 0.5..1.5
    "outline": "none",        # shape "logo": none | filled (an even band around the logo, like a sticker)
    "outline_width": 0.03,    # band width, fraction of the logo size
    "outline_color": None,    # band colour (None = contrast with the logo)
    "seam_color": "#000000",
    "seam_style": "stitch",   # leather seam: stitch (dashes) | dotted | solid
    "seam_width": 0.006,      # seam thread thickness, fraction of the patch size
    "background": "#ffffff",      # transparent | #rrggbb
    "shadow": False,
}


# ---------------------------------------------------------------------------
# small array helpers

def _box_blur(a, r, axis):
    if r < 1:
        return a
    pad = [(0, 0)] * a.ndim
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float64)
    n, hi, lo = c.shape[axis], [slice(None)] * a.ndim, [slice(None)] * a.ndim
    hi[axis], lo[axis] = slice(2 * r + 1, n), slice(0, n - 2 * r - 1)
    d = c[tuple(hi)] - c[tuple(lo)]       # the two ends read in place (no copies): less memory
    del c
    d /= 2 * r + 1
    return d.astype(np.float32)


def blur(a, sigma):
    """Gaussian-like blur (three box passes), any float array."""
    if sigma < 0.5:
        return a
    r = max(1, int(round(math.sqrt(12 * sigma * sigma / 3 + 1) - 1) // 2))
    for _ in range(3):
        a = _box_blur(_box_blur(a, r, 0), r, 1)
    return a


def value_noise(h, w, cell, seed):
    """Smooth random field in [0, 1] with features about `cell` px wide."""
    rng = np.random.default_rng(seed)
    gh, gw = max(2, int(h / cell) + 3), max(2, int(w / cell) + 3)
    small = Image.fromarray(rng.random((gh, gw), dtype=np.float32), "F")
    big = small.resize((int(gw * cell), int(gh * cell)), Image.BICUBIC)
    return np.asarray(big, dtype=np.float32)[:h, :w]


def _rgb(hexs):
    return np.array(engine.hex_to_rgb(hexs), np.float32) / 255.0


def _polys(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    out = []
    for g in getattr(geom, "geoms", []):     # GeometryCollection: keep the areas
        out += _polys(g)
    return out


def _fill_holes(geom):
    return unary_union([Polygon(p.exterior) for p in _polys(geom)])


# ---------------------------------------------------------------------------
# analysis: trace once, then render many times

class Analysis:
    def __init__(self, data: bytes):
        # no AI upscale: a mockup or a DST needs the logo's shapes, not its finest detail, and
        # the upscaler would add some 40 s (and its memory) to every new logo
        r = engine.trace(data, {"shape_stacking": "cutouts", "fit_shapes": True, "gap_filler": False,
                                "group_by": "none", "ai_upscale": False}, want_shapes=True)
        self.width, self.height = r["width"], r["height"]
        # background: shapes of the image's border colour that touch the image border or
        # the outside of the logo (the tracer sometimes leaves strips of background behind)
        bg = set(r["background_shapes"])
        bcol = r.get("border_color")
        outside = _fill_holes(unary_union([sh.poly for sh in r["shapes"]])).boundary if r["shapes"] else None
        tol = max(1.5, 0.004 * max(self.width, self.height))
        # a thin band wrapping the outside of the logo (a sticker-style outline) is kept as its
        # own entry, "<hex>/outline", hidden by default: on a patch the border takes its place
        thin = 0.016 * max(self.width, self.height)
        by_color: dict[str, list] = {}
        for sh in r["shapes"]:
            by_color.setdefault(sh.color, []).append(sh.poly)
        others = {c: unary_union([g for k, v in by_color.items() if k != c for g in v]).buffer(tol) for c in by_color}

        def is_outline(sh):
            # thin, on the outside, and at least a third of its edge runs along another colour
            # (a keyline around a badge); thin script letters touch only empty background
            if sh.poly.area / max(1.0, sh.poly.length) >= thin or others[sh.color].is_empty:
                return False
            return sh.poly.boundary.intersection(others[sh.color]).length >= 0.33 * sh.poly.length

        groups: dict[str, list] = {}
        self.background = []
        for sh in r["shapes"]:
            touches_out = outside is not None and sh.poly.distance(outside) < tol
            if sh.sid in bg or (sh.color == bcol and touches_out):
                self.background.append(sh.poly)
                groups.setdefault(sh.color + "/background", []).append(sh.poly)
            elif touches_out and is_outline(sh):
                groups.setdefault(sh.color + "/outline", []).append(sh.poly)
            else:
                groups.setdefault(sh.color, []).append(sh.poly)
        self.regions = {c: make_valid(unary_union(g)) for c, g in groups.items()}
        self.regions = {c: g for c, g in self.regions.items() if not g.is_empty and g.area > 1}
        areas = {c: g.area for c, g in self.regions.items()}
        extra = lambda c: c.endswith(("/outline", "/background"))
        order = sorted(areas, key=lambda c: (extra(c), -areas[c]))
        total = max(1.0, sum(a for c, a in areas.items() if not extra(c)))
        self.colors = [{"id": c, "hex": c.split("/")[0], "kind": c.split("/")[1] if "/" in c else "colour",
                        "area": round(areas[c] / total, 4)} for c in order]
        # largest colour is the fabric, the rest is thread; outlines and background start hidden.
        # A one-colour logo has no fabric of its own: it is all thread, shown as the logo only.
        self.default_roles = {}
        single = sum(1 for c in order if not extra(c)) == 1
        for c in order:
            if extra(c):
                self.default_roles[c] = "hidden"
            elif single:
                self.default_roles[c] = "thread"
            else:
                self.default_roles[c] = "base" if "base" not in self.default_roles.values() else "thread"
        self.suggested_shape = "logo" if single else "outline"
        self._cache: OrderedDict = OrderedDict()
        self._bytes = 0

    def info(self):
        return {"width": self.width, "height": self.height, "colors": self.colors,
                "roles": self.default_roles, "background_removed": bool(self.background),
                "suggested_shape": self.suggested_shape}

    def cached(self, key, fn):
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        val = fn()
        self._cache[key] = val
        self._bytes += _nbytes(val)
        # at most 48 things, and at most CACHE_BYTES of arrays: the oldest go first
        while len(self._cache) > 1 and (len(self._cache) > 48 or self._bytes > CACHE_BYTES):
            self._bytes -= _nbytes(self._cache.popitem(last=False)[1])
        return val


# ---------------------------------------------------------------------------
# geometry -> pixels

class Canvas:
    """Maps logo pixels to output pixels and rasterises geometry."""

    def __init__(self, patch, size):
        x0, y0, x1, y1 = patch.bounds
        self.margin = int(size * 0.06)
        self.s = (size - 2 * self.margin) / max(x1 - x0, y1 - y0)
        self.x0, self.y0 = x0, y0
        self.w = int(math.ceil((x1 - x0) * self.s)) + 2 * self.margin
        self.h = int(math.ceil((y1 - y0) * self.s)) + 2 * self.margin
        self.extent = max(x1 - x0, y1 - y0) * self.s        # patch size in output px

    def raster(self, geom, ss=2):
        im = Image.new("L", (self.w * ss, self.h * ss), 0)
        d = ImageDraw.Draw(im)
        f = self.s * ss
        ox, oy = self.margin * ss - self.x0 * f, self.margin * ss - self.y0 * f
        for p in sorted(_polys(geom), key=lambda p: -p.area):   # containers before islands in their holes
            d.polygon([(x * f + ox, y * f + oy) for x, y in p.exterior.coords], fill=255)
            for ring in p.interiors:
                d.polygon([(x * f + ox, y * f + oy) for x, y in ring.coords], fill=0)
        if ss > 1:
            im = im.resize((self.w, self.h), Image.BOX)
        return np.asarray(im, np.float32) / 255.0

    def depth(self, geom, width_px, steps=10):
        """0 at the edge of geom, rising to 1 at width_px inside (smooth)."""
        acc = np.zeros((self.h, self.w), np.float32)
        step = width_px / self.s / steps
        for k in range(steps):
            g = geom.buffer(-(k + 0.5) * step, quad_segs=6) if k else geom
            if g.is_empty:
                break
            acc += self.raster(g, ss=1 if k else 2)
        return blur(acc / steps, max(0.6, width_px / steps * 0.7))


# ---------------------------------------------------------------------------
# leatherette photo textures (static/leatherette, made by make_leatherette.py)

TEXTURE_DIR = Path(__file__).resolve().parent / "static" / "leatherette"


@lru_cache(maxsize=8)
def _texture_file(tid: str) -> np.ndarray:
    if not re.fullmatch(r"[a-z0-9-]{1,40}", tid or ""):
        raise ValueError("Unknown leather texture.")
    path = TEXTURE_DIR / f"{tid}.jpg"
    if not path.is_file():
        raise ValueError(f"Leather texture '{tid}' is missing.")
    return np.asarray(Image.open(path).convert("RGB"), np.float32) / 255


def _leather_texture(tid: str, h: int, w: int) -> np.ndarray:
    """The texture scaled to cover a w x h patch, centred."""
    tex = _texture_file(tid)
    th, tw = tex.shape[:2]
    f = max(w / tw, h / th)
    im = Image.fromarray((tex * 255).astype(np.uint8)).resize((max(w, round(tw * f)), max(h, round(th * f))), Image.BICUBIC)
    x0, y0 = (im.width - w) // 2, (im.height - h) // 2
    return np.asarray(im.crop((x0, y0, x0 + w, y0 + h)), np.float32) / 255


# ---------------------------------------------------------------------------
# rendering

def _patch_shape(an: Analysis, kept, o):
    """Outline of the patch in logo pixels."""
    D = max(an.width, an.height)
    shape = o["shape"]
    if shape == "logo":                       # exactly the logo's shapes, no backing
        if o.get("outline") == "filled":     # ...or with an even filled band around them
            return make_valid(kept.buffer(D * float(np.clip(float(o["outline_width"]), 0.005, 0.12)), quad_segs=12))
        return make_valid(kept.buffer(D * 0.0008))
    sil = _fill_holes(kept.buffer(D * 0.008).buffer(-D * 0.008))
    if len(_polys(sil)) > 1:
        # separate pieces: an even margin around the artwork, like a sticker contour
        for r in (0.02, 0.035, 0.05, 0.07, 0.1):
            sil = _fill_holes(kept.buffer(D * r, quad_segs=16))
            if len(_polys(sil)) == 1:
                break
        else:
            sil = kept.convex_hull.buffer(D * 0.03)
    bw = float(o["border_width"]) * D
    pad = bw * 0.55 if o["border"] not in ("none", "laser") else D * 0.004
    if shape == "circle":   # a true circle (the bounding circle itself is a coarse polygon)
        return minimum_bounding_circle(sil).centroid.buffer(minimum_bounding_radius(sil) + pad, quad_segs=64)
    if shape in ("rounded", "rectangle"):
        x0, y0, x1, y1 = sil.bounds
        g = box(x0, y0, x1, y1).buffer(pad + D * 0.02, join_style="mitre")
        if shape == "rounded":
            r = 0.12 * min(x1 - x0, y1 - y0)
            g = g.buffer(-r, join_style="mitre").buffer(r, quad_segs=16)
        return g
    return sil.buffer(pad, quad_segs=16)


def _seam_line(patch, inset, pitch):
    """The line the seam follows, `inset` inside the patch (logo units). Spikes narrower than
    about a stitch (where the outline has a tight notch) are rounded off, so no stitch
    runs into one and shows as a stray tick."""
    r = pitch * 0.5
    return patch.buffer(-(inset + r), quad_segs=16).buffer(r, quad_segs=16)


def _seam(cv: Canvas, patch, inset, style, width_px, pitch_px, ss=2):
    """Seam line (0..1) along a line `inset` (logo units) inside the patch: square dashes with
    gaps as long as the dashes, dots, or a plain line.

    Dashes are spaced evenly by length along the line, so they keep their size on straight
    sides and round corners alike."""
    thread = Image.new("L", (cv.w * ss, cv.h * ss), 0)
    dt = ImageDraw.Draw(thread)
    f = cv.s * ss
    ox, oy = cv.margin * ss - cv.x0 * f, cv.margin * ss - cv.y0 * f
    px = lambda pt: (pt.x * f + ox, pt.y * f + oy)
    wid = max(1.0, width_px * ss)

    def dot(d, c, r, v=255):
        d.ellipse((c[0] - r, c[1] - r, c[0] + r, c[1] + r), fill=v)

    for poly in _polys(_seam_line(patch, inset, pitch_px / cv.s)):
        ring = LineString(poly.exterior.coords)
        if ring.length * f < 4 * pitch_px * ss:    # a sliver left where the outline narrows: no room for a seam
            continue
        if style == "solid":
            dt.line([(x * f + ox, y * f + oy) for x, y in ring.coords], fill=255, width=round(wid), joint="curve")
            continue
        cycle = pitch_px * 2 if style == "stitch" else pitch_px     # stitch: dash, then a gap as long
        n = max(6, round(ring.length * f / (cycle * ss)))
        step = ring.length / n                     # a whole number of stitches round the line
        for i in range(n):
            d0 = i * step
            if style == "dotted":
                dot(dt, px(ring.interpolate(d0 + step / 2)), wid / 2)
            else:   # stitch: a square-ended dash on the first half of the step
                dash = substring(ring, d0 + step * 0.25, d0 + step * 0.75)   # follows corners
                dt.line([(x * f + ox, y * f + oy) for x, y in dash.coords], fill=255, width=round(wid), joint="curve")
    return np.asarray(thread.resize((cv.w, cv.h), Image.BOX), np.float32) / 255


def _light(az_deg, el_deg=42):
    az, el = math.radians(az_deg), math.radians(el_deg)
    return np.array([math.cos(az) * math.cos(el), -math.sin(az) * math.cos(el), math.sin(el)], np.float32)


def _shade(H, L, ambient=0.32, ks=0.0, shin=18.0):
    gy, gx = np.gradient(H)
    nz = 1.0 / np.sqrt(gx * gx + gy * gy + 1.0)
    nx, ny = -gx * nz, -gy * nz
    ndl = nx * L[0] + ny * L[1] + nz * L[2]
    diffuse = np.clip(ndl, 0, None) / L[2]
    shade = ambient + (1 - ambient) * diffuse
    hv = L + np.array([0, 0, 1], np.float32)
    hv /= np.linalg.norm(hv)
    spec = ks * np.clip(nx * hv[0] + ny * hv[1] + nz * hv[2], 0, 1) ** shin if ks else 0.0
    return shade.astype(np.float32), spec


def _cast_shadow(H, L, length):
    """Darkness where higher material blocks the light."""
    d = np.array([-L[0], -L[1]])
    d /= max(1e-6, np.hypot(*d))
    out = np.zeros_like(H)
    for f in (0.5, 1.0, 1.6):
        dx, dy = int(round(-d[0] * length * f)), int(round(-d[1] * length * f))
        shifted = np.roll(np.roll(H, dy, 0), dx, 1)
        out = np.maximum(out, (shifted - H) / max(1e-6, length * f) * (L[2] / math.hypot(L[0], L[1])))
    return blur(np.clip(out, 0, 1), max(1.0, length * 0.35))


def _across(D, sigma):
    """Direction across a stroke (radians, mod pi) at each pixel, from a distance-to-edge field:
    the smoothed orientation of its gradient (structure tensor), so it turns with the shape."""
    gy, gx = np.gradient(D)
    jxx, jyy, jxy = blur(gx * gx, sigma), blur(gy * gy, sigma), blur(gx * gy, sigma)
    return (0.5 * np.arctan2(2 * jxy, jxx - jyy)).astype(np.float32)


def _strands(theta, length, width, seed, steps=10):
    """Satin thread strands (0..1): noise about one thread wide, averaged along each pixel's
    stitch direction over `length` px (line integral convolution), then sharpened."""
    h, w = theta.shape
    n = value_noise(h, w, width, seed)
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)
    c, s = np.cos(theta), np.sin(theta)
    acc = np.zeros((h, w), np.float32)
    for k in range(-steps, steps + 1):
        t = k * length / (2 * steps)
        xs = np.clip((X + c * t + 0.5).astype(np.int32), 0, w - 1)
        ys = np.clip((Y + s * t + 0.5).astype(np.int32), 0, h - 1)
        acc += n[ys, xs]
    z = acc - blur(acc, width * 3)
    z /= float(z.std()) + 1e-6
    return (0.5 + 0.5 * np.tanh(1.3 * z)).astype(np.float32)


def _stripes(theta, period, seed, k=18):
    """Satin threads (0..1): regular parallel threads `period` px apart, each running along
    theta (radians, mod pi). Noise is band-passed to one thread per period across each of k
    fixed directions (FFT), and every pixel takes the result for its own direction."""
    h, w = theta.shape
    rng = np.random.default_rng(seed)
    F = np.fft.rfft2(rng.standard_normal((h, w)).astype(np.float32))
    fy = np.fft.fftfreq(h)[:, None].astype(np.float32)
    fx = np.fft.rfftfreq(w)[None, :].astype(np.float32)
    f0 = 1.0 / period
    out = np.zeros((h, w), np.float32)
    wsum = np.zeros((h, w), np.float32)
    for j in range(k):
        a = math.pi * j / k
        nx, ny = -math.sin(a), math.cos(a)                     # across the threads
        across = np.abs(fx * nx + fy * ny)
        along = fx * math.cos(a) + fy * math.sin(a)
        G = np.exp(-((across - f0) ** 2) / (2 * (0.2 * f0) ** 2) - along ** 2 / (2 * (0.025 * f0) ** 2))
        r = np.fft.irfft2(F * G, s=(h, w)).astype(np.float32)
        r /= np.sqrt(blur(r * r, period * 2)) + 1e-6           # even contrast everywhere
        wt = np.clip(np.cos(2 * (theta - a)), 0, None) ** 6     # how close this direction is
        out += wt * r
        wsum += wt
    z = out / (wsum + 1e-6)
    return (0.5 + 0.5 * np.tanh(2.0 * z)).astype(np.float32)


def _tatami(X, Y, angle, row, stitch):
    """Tatami fill (0..1): rows of stitches `row` apart along `angle`, each `stitch` long, the
    needle points moved on a third of a stitch every row (the brick pattern of a real fill)."""
    a = math.radians(angle)
    u = (X * math.cos(a) + Y * math.sin(a)) / stitch          # along the stitches
    v = (-X * math.sin(a) + Y * math.cos(a)) / row            # across the rows
    r = np.floor(v)
    tube = np.sqrt(np.clip(1 - (2 * (v - r) - 1) ** 2, 0, 1)) ** 0.6   # rows lie tight, each a rounded thread
    us = u + r * 0.34
    pos = np.mod(us, 1.0)
    e = (2 * pos - 1) ** 2
    shape = (1 - 0.9 * e ** 3) * (0.8 + 0.3 * (1 - e))         # dark at the needle points, bright mid-stitch
    k = np.floor(us)
    tone = 0.78 + 0.4 * np.modf(np.abs(np.sin(k * 78.233 + r * 12.9898)) * 43758.5453)[0]   # every stitch lies a little differently
    return (tube * shape * tone).astype(np.float32)


def _stitch_texture(X, Y, angle, spacing, stitch_len, seed):
    """Thread ridges (0..1) at `angle`, broken into staggered stitches."""
    a = math.radians(angle)
    t = (X * math.cos(a) + Y * math.sin(a)) / spacing
    u = (-X * math.sin(a) + Y * math.cos(a)) / stitch_len
    row = np.floor(t)
    jitter = np.modf(np.sin(row * 12.9898 + seed) * 43758.5453)[0]
    ridge = (0.5 - 0.5 * np.cos(2 * np.pi * t)) ** 0.7
    pos = np.modf(u + jitter * 3.7)[0]
    pos = np.where(pos < 0, pos + 1, pos)
    gap = np.clip(1 - np.minimum(pos, 1 - pos) / 0.07, 0, 1)
    return (ridge * (1 - 0.55 * gap)).astype(np.float32)


def render(an: Analysis, opts: dict, size: int = 1000) -> Image.Image:
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    style = o["style"] if o["style"] in STYLES else "embroidery"
    size = int(max(300, min(3000, size)))
    roles = {**an.default_roles, **{k.lower(): v for k, v in (o["roles"] or {}).items()}}
    recolor = {k.lower(): v for k, v in (o["recolor"] or {}).items()}
    col = lambda c: recolor.get(c) or recolor.get(c.split("/")[0]) or c.split("/")[0]   # region id -> colour
    relief = float(np.clip(o["relief"], 0, 1))
    L = _light(float(o["light"]))
    if o["shape"] == "logo":
        o["border"] = "none"

    kept_colors = [c["id"] for c in an.colors if roles.get(c["id"]) != "hidden"]
    if not kept_colors:
        raise ValueError("Every colour is hidden; give at least one colour a role.")
    outlined = o["shape"] == "logo" and o["outline"] == "filled"
    gkey = (style, o["shape"], o["border"], round(float(o["border_width"]), 4), tuple(sorted(roles.items())), size,
            outlined, round(float(o["outline_width"]), 4))
    kept = unary_union([an.regions[c] for c in kept_colors])
    patch = an.cached(("patch",) + gkey, lambda: _patch_shape(an, kept, o))
    # the logo can be made smaller or larger inside the patch shape (not when the logo is the shape)
    sc = 1.0 if o["shape"] == "logo" else float(np.clip(float(o["logo_scale"] or 1), 0.3, 2.0))
    px0, py0, px1, py1 = patch.bounds
    regions = an.regions
    if outlined:
        lum = sum(engine.hex_to_rgb(col(kept_colors[0]))) / 765
        outline_col = o["outline_color"] or ("#efece4" if lum < 0.5 else "#1f1f23")
        if style == "embroidery":   # the band is stitched too: a thread colour of its own, under the logo
            regions = {**an.regions, "outline/band": an.cached(("band",) + gkey, lambda: patch.difference(kept))}
            recolor["outline/band"] = outline_col
            roles["outline/band"] = "thread"
            kept_colors = ["outline/band"] + kept_colors
    region = (lambda c: regions[c]) if sc == 1 else \
        (lambda c: affinity.scale(regions[c], sc, sc, origin=((px0 + px1) / 2, (py0 + py1) / 2)))
    mkey = gkey + (round(sc, 3),)
    cv = Canvas(patch, size)
    E = cv.extent
    h, w = cv.h, cv.w
    Y, X = np.mgrid[0:h, 0:w].astype(np.float32)

    base_colors = [c for c in kept_colors if roles[c] == "base"]
    thread_colors = [c for c in kept_colors if roles[c] == "thread"]
    if outlined:
        fabric = outline_col
    elif o.get("fabric_color"):        # the backing's colour chosen on the page: over the logo's own
        fabric = o["fabric_color"]
    elif base_colors:
        fabric = col(base_colors[0])
    elif o["shape"] == "logo" and thread_colors:   # nothing behind the logo: no fabric colour at its edges
        fabric = col(thread_colors[0])
    else:   # no fabric colour in the logo: contrast with the thread
        lum = sum(engine.hex_to_rgb(col(thread_colors[0]))) / 765 if thread_colors else 0
        fabric = "#efece4" if lum < 0.5 else "#1f1f23"
    bw_px = float(o["border_width"]) * E

    P = an.cached(("P",) + gkey, lambda: cv.raster(patch))
    edge = an.cached(("edge",) + gkey, lambda: cv.depth(patch, max(2.0, bw_px if o["border"] != "none" else E * 0.03)))
    masks = {c: an.cached(("m", c) + mkey, lambda c=c: cv.raster(region(c).intersection(patch))) for c in kept_colors}

    # albedo of the fabric: main fabric colour, other "base" colours printed on it
    textile = style in ("embroidery", "woven", "sublimated")      # thread and fabric: never a flat black
    lift = (lambda c: 0.055 + 0.945 * c) if textile else (lambda c: c)
    albedo = np.empty((h, w, 3), np.float32)
    albedo[:] = lift(_rgb(fabric))
    printed = base_colors[1:] + (thread_colors if style == "sublimated" else [])
    for c in printed:
        albedo += masks[c][..., None] * (lift(_rgb(col(c))) - albedo)
    Hm = np.zeros((h, w), np.float32)
    gloss = np.zeros((h, w), np.float32)
    seed = 7

    if style == "embroidery":
        sp = E / (380 * float(np.clip(o["density"], 0.4, 2.5)))
        # twill fabric, or flat fill stitches when the patch is 100% embroidered; only where no
        # thread lies on top, so its texture does not show through the stitches
        fab = 1 - np.clip(sum((masks[c] for c in thread_colors), np.zeros((h, w), np.float32)), 0, 1)
        if o["full_embroidery"]:
            tex = _stitch_texture(X, Y, float(o["angle"]) + 90, sp * 1.1, sp * 7, seed)
            Hm += fab * tex * sp * 0.45
            albedo *= (1 - fab * (0.14 - 0.2 * tex))[..., None]
            gloss += fab * 0.6 * tex
        else:
            a = math.radians(62)
            tw = 0.5 - 0.5 * np.cos(2 * np.pi * (X * math.cos(a) + Y * math.sin(a)) / (sp * 1.7))
            fine = 0.5 - 0.5 * np.cos(2 * np.pi * (X * math.cos(a + 1.9) + Y * math.sin(a + 1.9)) / (sp * 0.9))
            n = value_noise(h, w, sp * 2.5, seed)
            Hm += fab * (tw * 0.6 + fine * 0.25) * sp * 0.45
            albedo *= (1 - fab * (0.2 - 0.26 * tw - 0.1 * n))[..., None]
            gloss += fab * 0.55 * tw * (0.6 + 0.4 * n)
        # each colour is digitized like a real design: narrow strokes become satin columns, with
        # every stitch one thread straight across the stroke; wide areas become a tatami fill
        tsp = E / (300 * float(np.clip(o["density"], 0.4, 2.5)))      # one thread, about 0.4 mm
        satin_px = 0.08 * E                                             # widest satin column
        rad = satin_px / 2
        puff = (0.002 + 0.01 * relief) * E
        light_dir = (math.cos(math.radians(float(o["light"]))), -math.sin(math.radians(float(o["light"]))))
        thread_lift = lambda c: c + 0.14 * (1 - c.max())   # dark thread is never flat black; bright thread keeps its colour
        for i, c in enumerate(thread_colors):
            m = masks[c]
            if not m.any():
                continue
            g = region(c).intersection(patch)

            def split(g=g):
                r = rad / cv.s
                # opening with a square: wide parts keep straight sides where satin bars join them
                wide = g.buffer(-r, join_style="mitre", mitre_limit=2).buffer(r * 1.05, join_style="mitre", mitre_limit=2).intersection(g)
                satin = g.difference(wide)
                # slivers the opening leaves at the corners of wide areas stay fill
                near = wide.buffer(r * 0.05) if not wide.is_empty else None
                small = [p for p in _polys(satin) if near is not None and p.area < (r * r * 0.8) and p.intersects(near)]
                if small:
                    wide = unary_union([wide] + small)
                    satin = satin.difference(unary_union(small))
                return cv.raster(satin), cv.raster(wide) if not wide.is_empty else np.zeros((h, w), np.float32)
            ms, mf = an.cached(("split", c, round(rad, 1)) + mkey, split)
            ms, mf = ms * m, mf * m
            D = an.cached(("d", c, round(rad, 1)) + mkey, lambda g=g: cv.depth(g, rad))
            tdir = np.full((h, w), math.radians(float(o["angle"])), np.float32)
            tex = np.zeros((h, w), np.float32)
            if ms.max() > 0.01:
                ys, xs = np.nonzero(ms > 0.01)
                pad = int(rad * 1.5) + 4
                y0, y1, x0, x1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1), max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
                th = _across(D[y0:y1, x0:x1], max(1.5, rad * 0.45))
                tdir[y0:y1, x0:x1] = np.where(ms[y0:y1, x0:x1] > 0.01, th, tdir[y0:y1, x0:x1])
                strands = _stripes(th, tsp, seed + i)
                tex[y0:y1, x0:x1] += ms[y0:y1, x0:x1] * strands
                col_prof = np.sin(np.pi / 2 * np.clip(D, 0, 1)) ** 0.7          # a satin column is rounded
                Hm += ms * (col_prof * puff + tex * tsp * 0.35)
            if mf.max() > 0.01:
                tat = _tatami(X, Y, float(o["angle"]), tsp, tsp * 6)
                tex += mf * tat
                Hm += mf * (np.sqrt(np.clip(D * 1.6, 0, 1)) * puff * 0.5 + tat * tsp * 0.35)
            # each stitch catches the light in short dashes, not along a whole thread
            breaks = 0.5 + 0.5 * value_noise(h, w, tsp * 1.3, seed + 40 + i)
            tex = tex * (0.45 + 0.55 * breaks)
            # thread shines most where it runs across the light; columns darken towards their edges
            ct = np.cos(tdir) * light_dir[0] + np.sin(tdir) * light_dir[1]
            aniso = 1 - ct * ct
            edge_dark = 0.5 + 0.5 * np.clip(D * 1.5, 0, 1) ** 0.6
            base = thread_lift(_rgb(col(c)))
            # the thread's own colour, and a white sheen on top (so dark thread shines and bright
            # thread keeps its colour)
            th = base * ((0.62 + 0.55 * tex) * edge_dark)[..., None] + (tex * tex * (0.07 + 0.16 * aniso) * edge_dark)[..., None]
            albedo += m[..., None] * (th - albedo)
            gloss = gloss * (1 - m) + m * tex * (0.35 + 0.65 * aniso)
        sheen = 0.18 + 0.42 * float(o["gloss"])
        ambient = 0.3
    elif style == "woven":
        sp = E / (360 * float(np.clip(o["density"], 0.4, 2.5)))
        warp = 0.5 - 0.5 * np.cos(2 * np.pi * X / sp)
        weft = 0.5 - 0.5 * np.cos(2 * np.pi * Y / sp)
        over = (np.floor(X / sp) + np.floor(Y / sp)) % 2
        weave = np.where(over > 0, warp, weft) * 0.75 + 0.25 * warp * weft
        Hm += weave * sp * 0.6
        albedo *= (0.78 + 0.3 * weave)[..., None]
        for c in thread_colors:
            m = masks[c]
            albedo += m[..., None] * (lift(_rgb(col(c))) * (0.8 + 0.26 * weave)[..., None] - albedo)
            Hm += m * blur(m, sp * 0.6) * (0.0015 + 0.003 * relief) * E
        gloss += 0.7 * weave
        sheen = 0.14 + 0.3 * float(o["gloss"])
        ambient = 0.36
    elif style == "sublimated":
        sp = E / (600 * float(np.clip(o["density"], 0.4, 2.5)))
        a = math.radians(60)
        tw = 0.5 - 0.5 * np.cos(2 * np.pi * (X * math.cos(a) + Y * math.sin(a)) / sp)
        n = value_noise(h, w, sp * 3, seed)
        Hm += (tw * 0.6 + n * 0.4) * sp * 0.3 + value_noise(h, w, E / 25, seed + 3) * E * 0.002
        albedo *= (0.96 + 0.05 * tw)[..., None]
        gloss += 0.5 + 0.3 * tw
        sheen = 0.12 + 0.35 * float(o["gloss"])
        ambient = 0.5
    elif style in ("pvc", "silicone"):
        # moulded PVC rubber or silicone: solid colours, the patch a smooth plate with rounded edges and
        # each logo colour a raised layer on it, sloping down at its edges (so a fine groove runs where
        # two colours meet). PVC is semi-gloss with crisp moulded steps; silicone is softer, domed,
        # satin-matte, and a little translucent at its edges
        pvc = style == "pvc"
        layer = (0.004 + 0.012 * relief) * E if pvc else (0.003 + 0.011 * relief) * E
        rad = (0.005 if pvc else 0.011) * E
        plate = np.sin(np.pi / 2 * np.clip(edge * 1.4, 0, 1)) * layer * 0.9
        Hm += plate                    # moulded: smooth, no texture of its own
        for c in thread_colors:
            m = masks[c]
            if not m.any():
                continue
            d = an.cached(("d", c, round(rad, 1)) + mkey, lambda c=c: cv.depth(region(c).intersection(patch), rad))
            dd = np.clip(blur(d, max(1.0, E * 0.0015)), 0, 1)        # the edge-distance steps smoothed out
            prof = np.sqrt(np.clip(1 - (1 - dd) ** 2, 0, 1)) if pvc else dd * dd * (3 - 2 * dd)     # silicone: soft shoulders
            Hm += m * prof * layer
            albedo += m[..., None] * (_rgb(col(c)) - albedo)
            if not pvc:      # light passes through the thin silicone at its edges
                albedo += (m * (1 - dd) ** 3 * 0.08)[..., None] * (1 - albedo)
        gloss += 0.75 if pvc else 0.45
        sheen = (0.1 + 0.4 * float(o["gloss"])) if pvc else (0.05 + 0.22 * float(o["gloss"]))
        ambient = 0.42
    elif style == "htv":
        # heat transfer vinyl: thin cut vinyl pressed onto the garment; flat solid colours with a
        # crisp, very slightly raised edge and a satin sheen; the fabric's weave shows faintly through
        sp = E / 520
        a = math.radians(62)
        tw = 0.5 - 0.5 * np.cos(2 * np.pi * (X * math.cos(a) + Y * math.sin(a)) / sp)
        Hm += tw * sp * 0.22
        thick = (0.0005 + 0.001 * relief) * E
        for c in thread_colors:
            m = masks[c]
            if not m.any():
                continue
            Hm += np.clip(blur(m, max(0.8, E * 0.0012)) * 1.15, 0, 1) * m * thick - m * tw * sp * 0.16   # the vinyl smooths the weave over
            albedo += m[..., None] * (_rgb(col(c)) - albedo)
        vinyl = np.clip(sum((masks[c] for c in thread_colors), np.zeros((h, w), np.float32)), 0, 1)
        gloss += vinyl * 0.6 + (1 - vinyl) * (0.45 - 0.15 * tw)      # the vinyl's sheen is even; the fabric's follows the weave
        sheen = 0.08 + 0.32 * float(o["gloss"])
        ambient = 0.45
    elif style == "suede":
        # suede: a soft matte nap, its fibres catching the light unevenly in soft patches; no shine.
        # The logo is debossed, embossed or laser engraved into it, as on leather
        leather = _rgb(o["leather_color"])
        nap = value_noise(h, w, E / 700, seed)
        fibre = value_noise(h, w, E / 260, seed + 1)
        brushed = value_noise(h, w, E / 30, seed + 2)
        Hm += (nap * 0.6 + fibre * 0.4) * E * 0.0005
        albedo[:] = leather * (0.84 + 0.1 * fibre + 0.12 * brushed + 0.05 * nap)[..., None]
        Hm += np.sqrt(np.clip(1 - (1 - np.clip(edge * 1.6, 0, 1)) ** 2, 0, 1)) * E * 0.01
        depth = (0.003 + 0.011 * relief) * E
        rad = 0.008 * E
        for c in (thread_colors if o["shape"] != "logo" or outlined else []):
            m = masks[c]
            d = an.cached(("d", c, round(rad, 1)) + mkey, lambda c=c: cv.depth(region(c).intersection(patch), rad))
            prof = np.sqrt(np.clip(1 - (1 - d) ** 2, 0, 1)) * m
            finish = o["leather_finish"]
            if finish == "emboss":
                Hm += prof * depth
                albedo *= (1 + 0.05 * prof)[..., None]
            elif finish == "engrave":      # the laser burns the nap away: darker and smooth
                burn = _rgb(o["engrave_color"]) if o["engrave_color"] else leather * 0.42
                albedo += m[..., None] * (burn - albedo) * 0.9
                Hm -= m * E * 0.0006
                gloss += m * 0.2
            else:                          # pressed: the nap flattened, darker and a little smoother
                Hm -= prof * depth
                albedo *= (1 - 0.32 * prof)[..., None]
                gloss += prof * 0.25
        gloss += 0.05
        sheen = 0.02 + 0.08 * float(o["gloss"])
        ambient = 0.4
    else:  # leather
        leather = _rgb(o["leather_color"])
        grain1 = value_noise(h, w, E / 160, seed)
        grain2 = value_noise(h, w, E / 55, seed + 1)
        pores = value_noise(h, w, E / 420, seed + 2)
        cells = np.abs(grain1 - 0.5) * 2              # pebbled ridges
        photo = _leather_texture(o["leather_texture"], h, w) if o["leather_texture"] else None
        if photo is not None:   # leatherette photo: its colour and grain, lit by the patch's own light
            lum = photo.mean(-1)
            Hm += (lum - blur(lum, max(1.0, E / 120))) * E * 0.0015   # the photo is the grain; only a light relief
            albedo[:] = photo
        else:
            Hm += (cells ** 1.5 * 0.9 + grain2 * 0.5 + pores * 0.2) * E * 0.0016
            tone = 0.86 + 0.16 * grain2 + 0.06 * (cells - 0.5) - 0.06 * (pores > 0.8)
            albedo[:] = leather * tone[..., None]
        # rounded, thick edge
        Hm += np.sqrt(np.clip(1 - (1 - np.clip(edge * 1.6, 0, 1)) ** 2, 0, 1)) * E * 0.012
        finish = o["leather_finish"]
        depth = (0.003 + 0.012 * relief) * E
        rad = 0.008 * E
        for c in (thread_colors if o["shape"] != "logo" or outlined else []):   # logo only: the logo is the leather piece
            m = masks[c]
            d = an.cached(("d", c, round(rad, 1)) + mkey, lambda c=c: cv.depth(region(c).intersection(patch), rad))
            prof = np.sqrt(np.clip(1 - (1 - d) ** 2, 0, 1)) * m
            if finish == "emboss":
                Hm += prof * depth
                albedo *= (1 + 0.06 * prof)[..., None]
            elif finish == "engrave":
                if o["engrave_color"]:   # two-layer leatherette: the laser uncovers the core colour
                    burn = _rgb(o["engrave_color"])
                    char = 0.92 + 0.16 * value_noise(h, w, E / 300, seed + 5)
                    albedo += m[..., None] * (burn * char[..., None] - albedo) * 0.97
                    gloss += m * 0.35
                else:
                    burn = np.array([0.18, 0.09, 0.05], np.float32)
                    char = 0.8 + 0.4 * value_noise(h, w, E / 300, seed + 5)
                    albedo += m[..., None] * (burn * char[..., None] - albedo) * 0.88
                Hm -= m * E * 0.0008
            else:  # deboss: pressed in and darkened by the heat press
                Hm -= prof * depth
                albedo *= (1 - 0.38 * prof)[..., None]
        gloss += 0.4 + 0.6 * (1 - cells)
        sheen = 0.08 + 0.3 * float(o["gloss"])
        ambient = 0.36

    # ---------------------------------------------------------------- border
    border = o["border"]
    thick = float(np.clip(float(o["border_thickness"] or 1), 0.3, 2.5))
    bcol = _rgb(o["border_color"] or (o["seam_color"] if style in SEAMED else fabric))
    flat_seam = None
    if style in SEAMED:
        if border != "none":
            # seam line inset from the edge; flat, painted on after the lighting (no relief or shadow)
            sw_px = float(np.clip(float(o["seam_width"]), 0.001, 0.03)) * E
            sstyle = o["seam_style"] if o["seam_style"] in ("stitch", "dotted", "solid") else "stitch"
            inset = max(bw_px * 0.62, sw_px * 1.5) / cv.s
            # dash 4 times as long as it is thick; dots about 2.2 thicknesses apart
            pitch = max(sw_px * 2.2, E * 0.012) if sstyle == "dotted" else max(sw_px * 4.0, E * 0.021)
            flat_seam = an.cached(("seam", sstyle, round(sw_px, 2)) + gkey,
                                  lambda: _seam(cv, patch, inset, sstyle, sw_px, pitch))
    elif border in ("merrow", "satin"):
        ring = (edge < 0.999).astype(np.float32) * P
        t = np.clip(edge, 0, 1)
        tube = np.sqrt(np.clip(1 - (2 * t - 1) ** 2, 0, 1)) * bw_px * (0.5 if border == "merrow" else 0.25) * thick
        cx, cy = w / 2, h / 2
        ang = np.arctan2(Y - cy, X - cx)
        rmean = math.sqrt(P.sum() / math.pi)
        rope_p = max(2.0, bw_px * 0.32)
        rope = 0.5 - 0.5 * np.cos(2 * np.pi * (ang * rmean / rope_p + t * bw_px / rope_p * (0.9 if border == "merrow" else 0.2)))
        rope = rope ** 0.7
        Hm = Hm * (1 - ring) + ring * np.maximum(Hm, tube + rope * rope_p * 0.3 * thick)
        albedo += ring[..., None] * (lift(bcol) * (0.8 + 0.3 * rope)[..., None] - albedo)
        gloss = gloss * (1 - ring) + ring * (0.4 + 0.6 * rope)
    elif border == "rim" and style in ("pvc", "silicone"):
        # a moulded rim round the edge, a little higher than the logo layers
        ring = (edge < 0.999).astype(np.float32) * P
        rim = np.sin(np.pi * np.clip(edge, 0, 1)) * (0.004 + 0.012 * relief) * E * (1.25 if style == "pvc" else 1.0) * thick
        Hm = Hm * (1 - ring) + ring * np.maximum(Hm, rim + Hm * 0.5)
        albedo += ring[..., None] * (bcol - albedo)
    elif border == "laser":
        lip = np.clip(1 - edge / (0.08 * thick ** 1.5), 0, 1) * P          # 1x: as it always was
        albedo *= (1 - min(0.8, 0.35 * thick) * lip)[..., None]

    # the textures and fields the styles and borders were built from are done with: let them go
    # (memory: a large picture holds dozens of these at once)
    X = Y = tex = tdir = D = ms = mf = tw = fine = n = weave = warp = weft = over = None
    grain1 = grain2 = pores = cells = photo = nap = fibre = brushed = prof = d = m = None
    ring = t = tube = ang = rope = lip = rim = th = aniso = edge_dark = breaks = ct = fab = None

    # ---------------------------------------------------------------- light
    Hm *= P
    # shape (puff, border, pressing) gets shading and shadows; thread texture only adds
    # detail around the true colour, so fine ridges do not darken the whole surface; each
    # field is let go as soon as it has been used
    Hmac = blur(Hm, max(1.0, E / 260))
    shade, _ = _shade(Hmac, L, ambient)
    fine, _ = _shade(Hm, L, ambient)
    detail = np.clip(fine - blur(fine, max(1.5, E / 150)) + 1.0, 0.55, 1.45)
    fine = None
    _, spec = _shade(Hm, L, ambient, ks=1.0, shin=14.0)
    Hm = None
    occl = _cast_shadow(Hmac, L, max(1.5, float(Hmac.max()) * 1.3))
    ao = np.clip((blur(Hmac, max(1.0, E * 0.006)) - Hmac) / max(1e-6, E * 0.004), 0, 1)
    Hmac = None
    shade *= detail * (1 - 0.55 * occl) * (1 - 0.35 * ao)
    detail = occl = ao = None
    shine = sheen * gloss
    shine *= spec
    gloss = spec = None
    rgb = albedo * shade[..., None]
    albedo = shade = None
    rgb += shine[..., None]
    shine = None
    np.clip(rgb, 0, 1, out=rgb)
    if flat_seam is not None:
        rgb += flat_seam[..., None] * (bcol - rgb)

    # ---------------------------------------------------------------- compose
    alpha = P
    out = np.zeros((h, w, 4), np.float32)
    if o["shadow"]:
        if style == "embroidery" and o["shape"] == "logo":   # stitched straight onto the garment: a tight shadow
            sh = blur(np.roll(np.roll(P, int(E * 0.003), 0), int(E * 0.0015), 1), E * 0.003) * 0.35
        else:
            sh = blur(np.roll(np.roll(P, int(E * 0.012), 0), int(E * 0.006), 1), E * 0.014) * 0.45
        out[..., 3] = sh
    a = alpha[..., None]
    out[..., :3] = rgb * a
    rgb = None
    out[..., 3] = alpha + out[..., 3] * (1 - alpha)
    # un-premultiply
    nz = out[..., 3:] > 1e-6
    out[..., :3] = np.where(nz, out[..., :3] / np.maximum(out[..., 3:], 1e-6), 0)
    nz = None
    np.clip(out, 0, 1, out=out)
    out *= 255
    out += 0.5
    img = Image.fromarray(out.astype(np.uint8), "RGBA")
    out = None
    if o["background"] and o["background"] != "transparent":
        bg = Image.new("RGBA", img.size, tuple(engine.hex_to_rgb(o["background"])) + (255,))
        img = Image.alpha_composite(bg, img)
    return img


def render_png(an: Analysis, opts: dict, size: int = 1000) -> bytes:
    buf = io.BytesIO()
    render(an, opts, size).save(buf, "PNG", optimize=False, compress_level=3)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Faux/Leather production file: layered vector PDF

def leather_pdf(an: Analysis, opts: dict, width_in: float = 4.0) -> bytes:
    """The leather patch as a vector PDF with three layers (optional content groups, shown as
    layers in Illustrator and Acrobat): Shape (white, thin black outline), Logo (solid black)
    and Stitch lines (the seam: dashes, dots or a plain line, spaced exactly as in the mockup).
    The longest side of the patch is `width_in` inches."""
    import zlib
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    roles = {**an.default_roles, **{k.lower(): v for k, v in (o["roles"] or {}).items()}}
    kept_colors = [c["id"] for c in an.colors if roles.get(c["id"]) != "hidden"]
    if not kept_colors:
        raise ValueError("Every colour is hidden; give at least one colour a role.")
    logo_only = o["shape"] == "logo"
    outlined = logo_only and o["outline"] == "filled"
    if logo_only:
        o["border"] = "none"
    kept = unary_union([an.regions[c] for c in kept_colors])
    patch = _patch_shape(an, kept, o)
    x0, y0, x1, y1 = patch.bounds
    Dp = max(x1 - x0, y1 - y0)                       # the patch size, as the mockup measures it

    # logo: every "Logo" colour as one black shape (scaled inside the patch like the mockup)
    sc = 1.0 if logo_only else float(np.clip(float(o["logo_scale"] or 1), 0.3, 2.0))
    logo = unary_union([an.regions[c] for c in kept_colors if roles[c] == "thread"] or [Polygon()])
    if sc != 1:
        logo = affinity.scale(logo, sc, sc, origin=((x0 + x1) / 2, (y0 + y1) / 2))
    logo = make_valid(logo.intersection(patch))

    # page: the patch with a small margin, y up
    k = width_in * 72 / Dp
    m = 0.04 * Dp
    W, H = (x1 - x0 + 2 * m) * k, (y1 - y0 + 2 * m) * k
    num = lambda v: f"{v:.3f}".rstrip("0").rstrip(".")
    pt = lambda x, y: f"{num((x - x0 + m) * k)} {num(H - (y - y0 + m) * k)}"

    def ring_ops(coords, close=True):
        coords = list(coords)
        ops = [f"{pt(*coords[0])} m"] + [f"{pt(*p)} l" for p in coords[1:]]
        return ops + (["h"] if close else [])

    def poly_ops(geom):
        ops = []
        for p in _polys(geom):
            ops += ring_ops(p.exterior.coords)
            for r in p.interiors:
                ops += ring_ops(r.coords)
        return ops

    body, groups = [], []
    if not logo_only or outlined:          # the patch outline; with "logo only" the logo is the piece
        groups.append("Shape")
        # white, with a hairline outline (0.072 pt = 0.001 in, the usual cut-line width)
        body += ["/OC /L1 BDC q", "1 1 1 rg 0 0 0 RG 0.072 w 1 j"] + poly_ops(patch) + ["b*", "Q EMC"]
    groups.append("Logo")
    body += [f"/OC /L{len(groups)} BDC q", "0 0 0 rg"] + poly_ops(logo) + ["f*", "Q EMC"]
    if o["border"] != "none":
        sw = float(np.clip(float(o["seam_width"]), 0.001, 0.03)) * Dp
        sstyle = o["seam_style"] if o["seam_style"] in ("stitch", "dotted", "solid") else "stitch"
        inset = max(float(o["border_width"]) * Dp * 0.62, sw * 1.5)
        pitch = max(sw * 2.2, Dp * 0.012) if sstyle == "dotted" else max(sw * 4.0, Dp * 0.021)
        cycle = pitch * 2 if sstyle == "stitch" else pitch
        groups.append("Stitch lines")
        body += [f"/OC /L{len(groups)} BDC q", f"0 0 0 RG {num(sw * k)} w"]
        for p in _polys(_seam_line(patch, inset, pitch)):
            ring = p.exterior
            if ring.length < 4 * pitch:           # a sliver left where the outline narrows: no room for a seam
                continue
            step = ring.length / max(6, round(ring.length / cycle))     # whole stitches round the line
            if sstyle == "stitch":      # square dashes, gaps as long, the first starting a quarter in
                body += ["0 J", f"[{num(step / 2 * k)} {num(step / 2 * k)}] {num(step * 0.75 * k)} d"]
            elif sstyle == "dotted":    # round dots, one in the middle of every step
                body += ["1 J", f"[0 {num(step * k)}] {num(step / 2 * k)} d"]
            else:
                body += ["0 J", "[] 0 d"]
            body += ring_ops(ring.coords, close=False) + ["S"]
        body += ["Q EMC"]

    stream = zlib.compress("\n".join(body).encode("latin-1"))
    n = len(groups)
    ocg_ids = [6 + i for i in range(n)]
    refs = " ".join(f"{i} 0 R" for i in ocg_ids)
    props = " ".join(f"/L{j + 1} {i} 0 R" for j, i in enumerate(ocg_ids))
    objs = [
        f"<< /Type /Catalog /Pages 2 0 R /OCProperties << /OCGs [{refs}] /D << /Order [{refs}] /ON [{refs}] >> >> >>".encode(),
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {W:.3f} {H:.3f}] /Contents 4 0 R /Resources << /Properties << {props} >> >> >>".encode(),
        f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Producer (EMB Pros) /Title (Leather patch) >>",
    ] + [f"<< /Type /OCG /Name ({g}) >>".encode() for g in groups]
    out = bytearray(b"%PDF-1.5\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, ob in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + ob + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{x:010d} 00000 n \n".encode() for x in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
