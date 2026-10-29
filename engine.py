"""Raster-to-vector engine.

Pipeline: load -> (crop) -> palette detection -> trace: "precise" (precise.py: sub-pixel
colour boundaries fitted with Bezier curves; the default) or "classic" (upscale, snap pixels
to the palette, VTracer) -> rebuild shapes in original pixel space ->
fit whole shapes -> compute draw-order layers and parents -> write an SVG with
named groups (Inkscape/Illustrator layers), gap filler, draw style and size.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

import numpy as np
import vtracer
from PIL import Image, ImageFilter
from shapely import STRtree
from shapely.geometry import LineString, Polygon
from shapely.ops import linemerge, unary_union
from shapely.validation import make_valid

MAX_INPUT_PIXELS = 3_000_000      # larger inputs are downscaled to this
MAX_WORK_PIXELS = 4_000_000       # traced image size after upscaling
MAX_UPSCALE = 4
MAX_COLORS = 64
AUTO_MAX_COLORS = 32

DEFAULTS = {
    # palette
    "max_colors": 0,              # 0 = detect automatically
    "palette": None,              # [{"from": "#rrggbb", "to": "#rrggbb"}] to edit / merge colors
    "crop": None,                 # {"x":, "y":, "w":, "h":} in input pixels
    "remove_background": False,   # drop the border colour before tracing (CLI)
    "edits": None,                # {"remove": [ids], "recolor": {id: "#rrggbb"}} from the editor
    # tracing
    "tracer": "precise",          # precise | classic (VTracer)
    "detail": 50,                 # 0..100, higher keeps smaller features
    "corner_threshold": 45,       # degrees; smaller = more corners
    "smoothing": 50,              # 0..100, higher = smoother curves
    "fit_shapes": True,           # circles, ellipses, rectangles
    # output
    "shape_stacking": "cutouts",  # cutouts | stacked
    "group_by": "color",          # none | color | parent | layer
    "draw_style": "fill_shapes",  # fill_shapes | stroke_shapes | stroke_edges
    "gap_filler": True,
    "gap_clip": False,
    "gap_non_scaling": True,
    "gap_width": 1.5,
    "stroke_non_scaling": True,
    "stroke_override": False,
    "stroke_color": "#000000",
    "stroke_width": 1.0,
    "svg_version": "1.1",         # 1.0 | 1.1 | tiny1.2
    "fixed_size": True,
    "size_mode": "unchanged",     # unchanged | scale | width | height | fit | fill | stretch
    "scale": 1.0,
    "width": None,
    "height": None,
    "unit": "px",                 # px | in | cm | mm
    "dpi": 72,
}


# --------------------------------------------------------------------------
# colour helpers

def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_to_hex(c) -> str:
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in c[:3])


def _rgb_to_lab(rgb: np.ndarray) -> np.ndarray:
    c = rgb.astype(np.float64) / 255.0
    c = np.where(c > 0.04045, ((c + 0.055) / 1.055) ** 2.4, c / 12.92)
    m = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = c @ m.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def _nearest(lab_pixels: np.ndarray, lab_palette: np.ndarray) -> np.ndarray:
    out = np.empty(len(lab_pixels), dtype=np.int32)
    step = 250_000
    for i in range(0, len(lab_pixels), step):
        d = ((lab_pixels[i:i + step, None, :] - lab_palette[None, :, :]) ** 2).sum(-1)
        out[i:i + step] = d.argmin(1)
    return out


# --------------------------------------------------------------------------
# palette

def _grow(m: np.ndarray, r: int) -> np.ndarray:
    """Square dilation of a boolean mask by r pixels."""
    out = m.copy()
    for k in range(1, r + 1):
        out[k:] |= m[:-k]; out[:-k] |= m[k:]
    m2 = out.copy()
    for k in range(1, r + 1):
        out[:, k:] |= m2[:, :-k]; out[:, :-k] |= m2[:, k:]
    return out


def noise_level(rgb: np.ndarray) -> float:
    """Compression noise in flat areas, in Lab units: 0 for a clean PNG, about 1-3 for a JPEG.

    How far pixels lie from their 5 x 5 median away from edges, at the 99.5th percentile (a large
    JPEG's flat areas are clean and its noise rings round the edges), scaled to about 1-3."""
    if rgb.shape[0] < 8 or rgb.shape[1] < 8:
        return 0.0
    med = np.stack([np.asarray(Image.fromarray(np.ascontiguousarray(rgb[..., k])).filter(ImageFilter.MedianFilter(5)))
                    for k in range(3)], -1)
    c16 = rgb.astype(np.int16)
    step = np.zeros(rgb.shape[:2], np.int16)
    for dy, dx in ((0, 1), (1, 0)):
        d = np.abs(c16 - np.roll(np.roll(c16, dy, 0), dx, 1)).max(-1)
        step = np.maximum(step, np.maximum(d, np.roll(np.roll(d, -dy, 0), -dx, 1)))
    flat = np.asarray(Image.fromarray(((step < 40) * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(3))) > 0
    if flat.sum() < 64:
        return 0.0
    a, b = rgb[flat].astype(np.float64), med[flat].astype(np.float64)
    if len(a) > 100_000:
        k = np.random.default_rng(2).choice(len(a), 100_000, replace=False); a, b = a[k], b[k]
    return 0.4 * float(np.percentile(np.linalg.norm(_rgb_to_lab(a) - _rgb_to_lab(b), axis=1), 99.5))


def detect_palette(rgba: np.ndarray, max_colors: int = 0) -> list[tuple[int, int, int]]:
    """Return the palette colours, most common first.

    With max_colors 0 the number of colours is detected: small clusters that
    are anti-aliasing blends between two bigger colours are dropped, and
    clusters closer than a just-noticeable difference are merged.
    """
    opaque = rgba[..., 3] >= 128
    px = rgba[..., :3][opaque]
    if len(px) == 0:
        return [(0, 0, 0)]
    if len(px) > 200_000:
        px = px[np.random.default_rng(0).choice(len(px), 200_000, replace=False)]
    want = max_colors if max_colors else 64
    # pixels inside flat areas (not on an edge): a colour found there is a real colour, even
    # when it lies between two others like an anti-aliasing blend (an overlap, a darker tip)
    rgb = rgba[..., :3].astype(np.int16)
    step_ = np.zeros(rgba.shape[:2], np.int16)
    for dy, dx in ((0, 1), (1, 0)):
        d = np.abs(rgb - np.roll(np.roll(rgb, dy, 0), dx, 1)).max(-1)
        step_ = np.maximum(step_, np.maximum(d, np.roll(np.roll(d, -dy, 0), -dx, 1)))
    flat_mask = Image.fromarray(((step_ < 16) & opaque).astype(np.uint8) * 255).filter(ImageFilter.MinFilter(5))
    flat_px = rgba[..., :3][np.asarray(flat_mask) > 0]
    if len(flat_px) > 200_000:
        flat_px = flat_px[np.random.default_rng(1).choice(len(flat_px), 200_000, replace=False)]
    flat_lab = _rgb_to_lab(flat_px.astype(np.float64)) if len(flat_px) else np.zeros((0, 3))
    img = Image.fromarray(px.reshape(-1, 1, 3).astype(np.uint8), "RGB")
    q = img.quantize(colors=min(want, 256), method=Image.Quantize.MEDIANCUT, kmeans=3)
    pal = np.array(q.getpalette()[: 3 * 256]).reshape(-1, 3)
    counts = np.bincount(np.array(q).ravel(), minlength=len(pal))
    used = [(int(counts[i]), pal[i].astype(float)) for i in range(len(pal)) if counts[i] > 0]
    used.sort(key=lambda t: -t[0])
    if max_colors:
        return [tuple(int(v) for v in c) for _, c in used[:max_colors]]

    total = sum(n for n, _ in used)
    # compressed images drift around their true colours (JPEG blocks, chroma subsampling): merge
    # and blend tolerances widen with the noise measured in flat areas; clean images keep 9 / 22
    noise = noise_level(rgba[..., :3])
    merge_de = 9.0 + 3.0 * noise
    blend_tol = 22.0 + 8.0 * noise
    accepted: list[list] = []  # [count, rgb, lab]
    lab_img = None
    around = {}                # accepted colour index -> where it is, grown by 3 px

    def stroke(lab):
        """True when this colour draws strokes of its own (line art, lettering, an engraving)
        instead of lining the edge where two other colours meet, as an anti-aliasing blend does:
        its pixels hang together, and most see only one other palette colour around them."""
        nonlocal lab_img
        if lab_img is None:
            lab_img = _rgb_to_lab(rgba[..., :3].reshape(-1, 3)).astype(np.float32).reshape(*rgba.shape[:2], 3)
        m = (np.linalg.norm(lab_img - lab.astype(np.float32), axis=-1) < 8) & opaque
        if m.sum() < 150:
            return False
        nb = sum(np.roll(np.roll(m, dy, 0), dx, 1).astype(np.uint8) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dy or dx)
        if (nb[m] >= 3).mean() < 0.5:                       # scattered specks, not strokes
            return False
        seen = np.zeros(m.shape, np.uint8)
        for i, a in enumerate(accepted):
            if i not in around:
                around[i] = _grow((np.linalg.norm(lab_img - a[2].astype(np.float32), axis=-1) < 12) & opaque, 3)
            seen += around[i]
        if float((seen[m] >= 2).mean()) < 0.5:
            return True
        # the same colour may also blend along other colours' edges elsewhere (a dark brown between
        # a black outline and sand) and an engraving may have a lighter rim: so look at each clump
        # on its own, and straight across it. A stroke has one colour on both sides (sand | brown |
        # sand); a blend along an edge has a different colour on each side (yellow | halo | black)
        from scipy import ndimage
        comp, k = ndimage.label(m, np.ones((3, 3)))
        if k == 0:
            return False
        sizes = np.bincount(comp.ravel())
        nearest = np.argmin(np.stack([np.linalg.norm(lab_img - a[2].astype(np.float32), axis=-1) for a in accepted]), 0)
        H_, W_ = m.shape
        same = np.zeros(k + 1); seen_ = np.zeros(k + 1)
        for dy, dx in ((0, 3), (3, 0), (2, 2), (2, -2)):
            def shift(a, sy, sx, fill):
                out = np.full_like(a, fill)
                ys = slice(max(sy, 0), H_ + min(sy, 0)); yd = slice(max(-sy, 0), H_ + min(-sy, 0))
                xs = slice(max(sx, 0), W_ + min(sx, 0)); xd = slice(max(-sx, 0), W_ + min(-sx, 0))
                out[yd, xd] = a[ys, xs]
                return out
            fa, fb = shift(nearest, dy, dx, -1), shift(nearest, -dy, -dx, -2)
            ma, mb = shift(m, dy, dx, True), shift(m, -dy, -dx, True)
            oa, ob = shift(opaque, dy, dx, False), shift(opaque, -dy, -dx, False)
            across = m & ~ma & ~mb & oa & ob                    # both sides lie outside the clump
            seen_ += np.bincount(comp[across], minlength=k + 1)
            same += np.bincount(comp[across & (fa == fb)], minlength=k + 1)
        good = (sizes >= 20) & (seen_ >= 10) & (same >= 0.6 * np.maximum(seen_, 1))
        good[0] = False
        return int(sizes[good].sum()) >= 120
    for n, c in used:
        lab = _rgb_to_lab(c[None])[0]
        share = n / total
        near = [a for a in accepted if np.linalg.norm(a[2] - lab) < merge_de]
        if near:
            a = near[0]
            a[1] = (a[1] * a[0] + c * n) / (a[0] + n)
            a[0] += n
            a[2] = _rgb_to_lab(a[1][None])[0]
            continue
        # how much of the image's flat areas this colour fills: real colours have an inside,
        # anti-aliasing and compression fringes only line the edges
        solid = 0.0
        if len(flat_lab):
            dc = np.linalg.norm(flat_lab - lab, axis=1)
            near = dc < 8
            if accepted and near.any():     # flat pixels that are this colour, not an accepted one
                da = np.min([np.linalg.norm(flat_lab[near] - a[2], axis=1) for a in accepted], axis=0)
                near[np.nonzero(near)[0][da <= dc[near]]] = False
            solid = float(near.mean())
        line = None                     # worked out only when needed
        if share < 0.0015 and not (share > 0.0003 and (solid > 0.0008 or (line := stroke(lab)))):
            continue
        # a minor colour close to an accepted one that is neither solid anywhere nor draws lines of
        # its own only lines that colour's edges: JPEG ringing (darker or lighter than both sides)
        if (share < 0.05 and accepted and solid <= 0.0008
                and min(np.linalg.norm(a[2] - lab) for a in accepted) < 2 * merge_de + 2
                and not (line if line is not None else (line := stroke(lab)))):
            continue
        if share < 0.03 and len(accepted) >= 2:
            # drop anti-aliasing blends; they mix linearly in RGB between two accepted colours
            is_blend = False
            for i in range(len(accepted)):
                for j in range(i + 1, len(accepted)):
                    p, r = accepted[i][1], accepted[j][1]
                    seg = r - p
                    t = np.clip(np.dot(c - p, seg) / max(np.dot(seg, seg), 1e-9), 0, 1)
                    if 0.04 < t < 0.96 and np.linalg.norm(p + t * seg - c) < blend_tol:
                        is_blend = True
                        break
                if is_blend:
                    break
            if is_blend and (solid > 0.0008 or (line if line is not None else stroke(lab))):
                is_blend = False                # ...unless it fills flat areas or draws lines of its own
            if is_blend:
                continue
        accepted.append([n, c, lab])
        if len(accepted) >= AUTO_MAX_COLORS:
            break
    pal = [tuple(int(round(v)) for v in a[1]) for a in accepted] or [(0, 0, 0)]

    # continuous-tone images (photos, gradients): add colours until the average
    # colour error is small, so flat artwork keeps its small palette. Measured away from edges:
    # anti-aliased and compressed edges are blends the tracer shares out, not missing colours
    inner = rgba[..., :3][(step_ < 16) & opaque]
    sample = inner if len(inner) > 0.2 * len(px) else px
    sample = sample[:: max(1, len(sample) // 40_000)]
    lab_px = _rgb_to_lab(sample.astype(np.float64))
    def err(pl):
        lp = _rgb_to_lab(np.array(pl, dtype=np.float64))
        return float(np.sqrt(((lab_px[:, None, :] - lp[None]) ** 2).sum(-1).min(1)).mean())
    e = err(pal)
    n = len(pal)
    while e > 4.0 and n < AUTO_MAX_COLORS:
        n = min(AUTO_MAX_COLORS, max(n + 2, int(n * 1.4)))
        q = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT, kmeans=3)
        qp = np.array(q.getpalette()[: 3 * n]).reshape(-1, 3)
        qc = np.bincount(np.array(q).ravel(), minlength=len(qp))
        cand = [tuple(int(v) for v in qp[i]) for i in np.argsort(-qc) if qc[i] > 0]
        ce = err(cand)
        if ce < e:
            pal, e = cand, ce
    return pal


# --------------------------------------------------------------------------
# geometry

@dataclass
class Shape:
    sid: str
    color: str
    subpaths: list            # [[("M",(x,y)), ("L",(x,y)) | ("C",(x1,y1,x2,y2,x,y)), ...], ...]
    poly: object = None       # shapely geometry (even-odd of subpaths)
    shell: object = None      # filled outer outline, used for parent tests
    kind: str = "path"        # path | circle | ellipse | rect
    params: dict = field(default_factory=dict)
    layer: int = 0
    parent: int = -1


_TOKEN = re.compile(r"[MLCZmlcz]|-?\d*\.?\d+(?:[eE][-+]?\d+)?")


def parse_d(d: str, tx=0.0, ty=0.0, s=1.0):
    """Parse absolute M/L/C/Z path data (what VTracer and this engine write)."""
    toks = _TOKEN.findall(d)
    subs, cur, i, cmd = [], None, 0, None
    def num():
        nonlocal i
        v = float(toks[i]); i += 1
        return v
    while i < len(toks):
        t = toks[i]
        if t.isalpha():
            cmd = t.upper(); i += 1
            if cmd == "Z":
                if cur:
                    subs.append(cur); cur = None
                continue
        if cmd == "M":
            if cur:
                subs.append(cur)
            cur = [("M", ((num() + tx) * s, (num() + ty) * s))]
            cmd = "L"
        elif cmd == "L":
            cur.append(("L", ((num() + tx) * s, (num() + ty) * s)))
        elif cmd == "C":
            cur.append(("C", tuple((num() + (tx if k % 2 == 0 else ty)) * s for k in range(6))))
        else:
            i += 1
    if cur:
        subs.append(cur)
    return subs


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def subpaths_to_d(subs) -> str:
    out = []
    for sp in subs:
        for op, p in sp:
            out.append(op + " ".join(_fmt(v) for v in p))
        out.append("Z")
    return "".join(out)


def _flatten(sp, tol=0.35):
    pts = [sp[0][1]]
    for op, p in sp[1:]:
        if op == "L":
            pts.append(p)
        else:
            x0, y0 = pts[-1]
            x1, y1, x2, y2, x3, y3 = p
            length = math.dist((x0, y0), (x1, y1)) + math.dist((x1, y1), (x2, y2)) + math.dist((x2, y2), (x3, y3))
            n = max(2, min(32, int(length / (tol * 4)) + 2))
            for k in range(1, n + 1):
                t = k / n; u = 1 - t
                pts.append((u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                            u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
    return pts


def _poly_from_subpaths(subs):
    """Even-odd fill of the subpaths, and the same outline with its holes filled."""
    parts = []
    for sp in subs:
        pts = _flatten(sp)
        if len(pts) >= 3:
            parts.append(make_valid(Polygon(pts)))
    if not parts:
        return Polygon(), Polygon()
    # usual case: an outline with separate holes inside it, made in one step
    if len(parts) > 1 and all(isinstance(p, Polygon) for p in parts):
        quick = Polygon(parts[0].exterior, [p.exterior for p in parts[1:]])
        expect = parts[0].area - sum(p.area for p in parts[1:])
        if not quick.is_valid:              # holes touching the outline at a point: repaired in one step
            quick = make_valid(quick)
            if quick.geom_type == "GeometryCollection":     # keep the area, not stray lines or points
                quick = unary_union([g for g in quick.geoms if g.geom_type in ("Polygon", "MultiPolygon")])
        if abs(quick.area - expect) < 1e-3 * max(1.0, parts[0].area):
            return quick, Polygon(parts[0].exterior)
    geom = parts[0]
    for p in parts[1:]:
        geom = geom.symmetric_difference(p)
    return make_valid(geom), make_valid(unary_union(parts))


def _area_moments(poly: Polygon):
    """Area, centroid and central second moments of a simple polygon."""
    x, y = np.asarray(poly.exterior.coords).T
    x1, y1, x2, y2 = x[:-1], y[:-1], x[1:], y[1:]
    cr = x1 * y2 - x2 * y1
    a = cr.sum() / 2
    if abs(a) < 1e-9:
        return None
    cx = ((x1 + x2) * cr).sum() / (6 * a)
    cy = ((y1 + y2) * cr).sum() / (6 * a)
    ixx = ((y1**2 + y1 * y2 + y2**2) * cr).sum() / 12 - a * cy * cy
    iyy = ((x1**2 + x1 * x2 + x2**2) * cr).sum() / 12 - a * cx * cx
    ixy = ((x1 * y2 + 2 * x1 * y1 + 2 * x2 * y2 + x2 * y1) * cr).sum() / 24 - a * cx * cy
    return a, cx, cy, ixx, iyy, ixy


KAPPA = 0.5522847498


def primitive_subpath(kind, p, clockwise=True):
    """A closed subpath of lines and cubic Beziers for a fitted primitive.

    Coordinates are image pixels (y down); clockwise is as seen on screen.
    """
    cx, cy = p["cx"], p["cy"]
    t = math.radians(p.get("angle", 0.0)); c, s = math.cos(t), math.sin(t)
    def tr(x, y):
        return (cx + x * c - y * s, cy + x * s + y * c)
    segs = []  # list of (op, local points)
    if kind in ("circle", "ellipse"):
        rx, ry = (p["r"], p["r"]) if kind == "circle" else (p["rx"], p["ry"])
        q = [(rx, 0), (0, ry), (-rx, 0), (0, -ry)]
        start = q[0]
        for i in range(4):      # quarter arcs between axis points
            a, b = q[i], q[(i + 1) % 4]
            c1 = (a[0] + KAPPA * b[0], a[1] + KAPPA * b[1])
            c2 = (b[0] + KAPPA * a[0], b[1] + KAPPA * a[1])
            segs.append(("C", c1 + c2 + b))
    else:  # rect, optionally with rounded corners
        hw, hh = p["w"] / 2, p["h"] / 2
        r = min(p.get("r", 0.0), hw, hh)
        start = (-hw + r, -hh)
        corners = [((hw, -hh), (1, 0), (0, 1)), ((hw, hh), (0, 1), (-1, 0)), ((-hw, hh), (-1, 0), (0, -1)), ((-hw, -hh), (0, -1), (1, 0))]
        for (x, y), (dx0, dy0), (dx1, dy1) in corners:
            a = (x - dx0 * r, y - dy0 * r)       # where the straight side ends
            b = (x + dx1 * r, y + dy1 * r)       # where the next side starts
            segs.append(("L", a))
            if r > 0:
                segs.append(("C", (a[0] + dx0 * KAPPA * r, a[1] + dy0 * KAPPA * r,
                                   b[0] - dx1 * KAPPA * r, b[1] - dy1 * KAPPA * r) + b))
    sub = [("M", tr(*start))]
    for op, v in segs:
        if op == "L":
            sub.append(("L", tr(*v)))
        else:
            sub.append(("C", tr(v[0], v[1]) + tr(v[2], v[3]) + tr(v[4], v[5])))
    if not clockwise:
        sub = _reverse_subpath(sub)
    return sub


def _reverse_subpath(sub):
    pts = [sub[0][1]]
    for op, v in sub[1:]:
        pts.append(v[-2:])
    out = [("M", pts[-1])]
    for i in range(len(sub) - 1, 0, -1):
        op, v = sub[i]
        prev = pts[i - 1]
        out.append(("L", prev) if op == "L" else ("C", v[2:4] + v[0:2] + prev))
    return out


def _signed_area(pts):
    x = np.array([q[0] for q in pts]); y = np.array([q[1] for q in pts])
    return (x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2


def fit_loop(pts, max_dev=0.35):
    """Best circle / ellipse / rectangle / rounded rectangle for one closed loop, or None."""
    poly = make_valid(Polygon(pts))
    if not isinstance(poly, Polygon) or poly.is_empty:
        return None
    minx, miny, maxx, maxy = poly.bounds
    if min(maxx - minx, maxy - miny) < 4:
        return None
    perim = poly.length

    def dev(kind, prm):
        cand = Polygon(_flatten(primitive_subpath(kind, prm)))
        return poly.symmetric_difference(make_valid(cand)).area / max(perim, 1e-9)

    found = []
    rr = poly.minimum_rotated_rectangle
    if isinstance(rr, Polygon):
        c = np.asarray(rr.exterior.coords)[:4]
        e0, e1 = c[1] - c[0], c[2] - c[1]
        cx, cy = c.mean(0)
        ang0 = math.degrees(math.atan2(e0[1], e0[0]))
        n = round(ang0 / 90)
        ang = ang0 - 90 * n          # in [-45, 45]
        w, h = (np.linalg.norm(e1), np.linalg.norm(e0)) if n % 2 else (np.linalg.norm(e0), np.linalg.norm(e1))
        prm = {"cx": cx, "cy": cy, "w": w, "h": h, "angle": ang if abs(ang) > 0.3 else 0.0, "r": 0.0}
        found.append(("rect", prm, dev("rect", prm)))
        deficit = w * h - poly.area
        if deficit > 0:
            r = math.sqrt(deficit / (4 - math.pi))
            if 0.75 < r:
                # up to half the short side: a pill (a bar with round ends) is a rounded rectangle too
                prm2 = {**prm, "r": min(r, min(w, h) / 2)}
                found.append(("rect", prm2, dev("rect", prm2)))
    m = _area_moments(poly)
    if m:
        a, cx, cy, ixx, iyy, ixy = m      # ixx = integral of y^2, iyy = integral of x^2
        cov = np.array([[iyy, ixy], [ixy, ixx]]) / a  # x/y covariance of the area
        vals, vecs = np.linalg.eigh(cov)
        if vals.min() > 0:
            rx, ry = 2 * math.sqrt(vals[1]), 2 * math.sqrt(vals[0])
            ang = math.degrees(math.atan2(vecs[1, 1], vecs[0, 1]))
            ang = (ang + 90) % 180 - 90
            if abs(rx - ry) / max(rx, ry) < 0.02:
                prm = {"cx": cx, "cy": cy, "r": (rx + ry) / 2}
                found.append(("circle", prm, dev("circle", prm)))
            else:
                prm = {"cx": cx, "cy": cy, "rx": rx, "ry": ry, "angle": ang if abs(ang) > 0.3 else 0.0}
                found.append(("ellipse", prm, dev("ellipse", prm)))
    ok = [f for f in found if f[2] < max_dev]
    if not ok:
        return None
    kind, prm, _ = min(ok, key=lambda f: f[2])
    return kind, prm


def fit_whole_shape(sh: Shape, max_dev=0.35):
    """Fit circles, ellipses and (rounded) rectangles to the loops of a shape.

    A shape with a single fitted loop becomes a native SVG element; fitted
    loops of a shape with holes are rebuilt as exact curves inside its path.
    """
    changed = 0
    new_subs = []
    for sp in sh.subpaths:
        pts = _flatten(sp)
        f = fit_loop(pts, max_dev) if len(pts) >= 3 else None
        if f:
            kind, prm = f
            new_subs.append(primitive_subpath(kind, prm, clockwise=_signed_area(pts) > 0))
            changed += 1
            if len(sh.subpaths) == 1:
                sh.kind, sh.params = kind, prm
        else:
            new_subs.append(sp)
    if changed:
        sh.subpaths = new_subs
        sh.poly, sh.shell = _poly_from_subpaths(new_subs)
    return changed


def fit_shared_shapes(shapes, idx, max_dev=0.35):
    """fit_whole_shape for shapes that share their edges (the planar tracer).

    A loop fitted with a circle, ellipse or rectangle is shared with the shape on its other side
    (a ring's hole is the outline of the dot inside it): that loop gets the same primitive, so
    the two still meet exactly. When nothing on the other side matches it as one loop and the
    other side is not transparent, the loop is left as traced rather than open a gap."""
    loops = []
    for i, sh in enumerate(shapes):
        for k, sp in enumerate(sh.subpaths):
            pts = _flatten(sp)
            if len(pts) >= 3:
                xs = [q[0] for q in pts]; ys = [q[1] for q in pts]
                loops.append((i, k, pts, _signed_area(pts), (min(xs), min(ys), max(xs), max(ys))))
    if not loops:
        return 0
    B = np.array([lp[4] for lp in loops]); A = np.abs([lp[3] for lp in loops])
    H, W = idx.shape
    done = {}
    for n, (i, k, pts, ar, bb) in enumerate(loops):
        if (i, k) in done:
            continue
        f = fit_loop(pts, max_dev)
        if not f:
            continue
        same = np.nonzero((np.abs(B - np.array(bb)).max(1) < 1.0) & (np.abs(A - abs(ar)) < 0.02 * abs(ar) + 0.5))[0]
        partners = [m for m in same if loops[m][0] != i]
        if not partners:
            # alone is fine only against transparency: look just outside an outline, inside a hole
            poly = make_valid(Polygon(pts)).buffer(1.2 if ar > 0 else -1.2)
            if poly.is_empty:
                continue
            ring = np.asarray(getattr(poly, "exterior", None).coords if poly.geom_type == "Polygon" else [])
            if not len(ring):
                continue
            xs = np.clip(ring[:, 0].astype(int), 0, W - 1); ys = np.clip(ring[:, 1].astype(int), 0, H - 1)
            if (idx[ys, xs] != 255).mean() > 0.1:
                continue
        kind, prm = f
        for m in [n] + partners:
            done[(loops[m][0], loops[m][1])] = (kind, prm, loops[m][3] > 0)
    changed = 0
    for i, sh in enumerate(shapes):
        mine = {k: v for (j, k), v in done.items() if j == i}
        if not mine:
            continue
        sh.subpaths = [primitive_subpath(mine[k][0], mine[k][1], clockwise=mine[k][2]) if k in mine else sp
                       for k, sp in enumerate(sh.subpaths)]
        if len(sh.subpaths) == 1:
            sh.kind, sh.params = mine[0][0], mine[0][1]
        sh.poly, sh.shell = _poly_from_subpaths(sh.subpaths)
        changed += len(mine)
    return changed


def shape_outline_subpaths(sh: Shape):
    """Subpaths for a shape, also for fitted primitives (used by DXF and edges)."""
    return sh.subpaths


# --------------------------------------------------------------------------
# tracing

def _load(data: bytes) -> Image.Image:
    im = Image.open(io.BytesIO(data))
    if getattr(im, "is_animated", False):
        im.seek(0)
    return im.convert("RGBA")


MAX_AI_SIDE = 1000
_AI_CACHE: dict = {}        # (image hash, crop) -> upscaled image: palette edits re-trace without re-running it


def _ai_available() -> bool:
    try:
        import upscale
    except ImportError:
        return False
    return upscale.available()


def _ai_upscaled(im, data: bytes, crop) -> "Image.Image":
    import hashlib
    import upscale
    key = (hashlib.sha1(data).hexdigest(), repr(crop), im.size)
    if key not in _AI_CACHE:
        if len(_AI_CACHE) > 8:
            _AI_CACHE.pop(next(iter(_AI_CACHE)))
        _AI_CACHE[key] = upscale.upscale(im, 2)
    return _AI_CACHE[key].copy()


def _scale_sub(sub, f):
    return [(op, tuple(v * f for v in p)) for op, p in sub]


def _scale_shapes(shapes, f):
    from shapely import affinity
    for sh in shapes:
        sh.subpaths = [_scale_sub(sp, f) for sp in sh.subpaths]
        if sh.params:
            sh.params = {k: (v * f if k in ("cx", "cy", "r", "rx", "ry", "w", "h") else v) for k, v in sh.params.items()}
        sh.poly = affinity.scale(sh.poly, f, f, origin=(0, 0))
        if sh.shell is not None:
            sh.shell = affinity.scale(sh.shell, f, f, origin=(0, 0))


def trace(data: bytes, opts: dict, want_shapes: bool = False) -> dict:
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    im = _load(data)
    notes = []
    if o.get("crop"):
        c = o["crop"]
        x, y = max(0, int(c["x"])), max(0, int(c["y"]))
        w, h = int(c["w"]), int(c["h"])
        if w > 0 and h > 0:
            im = im.crop((x, y, min(im.width, x + w), min(im.height, y + h)))
    if im.width * im.height > MAX_INPUT_PIXELS:
        f = math.sqrt(MAX_INPUT_PIXELS / (im.width * im.height))
        im = im.resize((max(1, int(im.width * f)), max(1, int(im.height * f))), Image.LANCZOS)
        notes.append(f"Image downscaled to {im.width}x{im.height} (limit {MAX_INPUT_PIXELS // 1_000_000} MP).")
    # small images: redrawn twice as large by the AI upscaler (upscale.py), traced, and the shapes
    # scaled back, so 12 px lettering and hairline gaps come out as clean shapes
    ai = 1
    rgba_src = np.asarray(im).copy()          # the image's own colours: the palette comes from these
    if (o.get("ai_upscale", True) and o.get("tracer", "precise") != "classic"
            and max(im.size) <= MAX_AI_SIDE and _ai_available()):
        im = _ai_upscaled(im, data, o.get("crop"))
        ai = 2
        notes.append("Upscaled with AI before tracing (fine detail redrawn).")
    W, H = im.size
    rgba = np.asarray(im).copy()

    # palette: detected colours, optionally edited ("from" -> "to") or merged
    max_colors = int(o["max_colors"] or 0)
    max_colors = min(max(max_colors, 0), MAX_COLORS)
    if o.get("palette"):
        src = [hex_to_rgb(p["from"]) for p in o["palette"]]
        dst = [hex_to_rgb(p.get("to") or p["from"]) for p in o["palette"]]
    else:
        # the palette from the image's own pixels: the upscaler redraws shapes, not colours
        src = detect_palette(rgba_src, max_colors)
        dst = list(src)

    # colours sharing a target colour are merged before tracing, so shapes really merge
    targets = []
    tmap = {}
    for i, c in enumerate(dst):
        key = rgb_to_hex(c)
        if key not in tmap:
            tmap[key] = len(targets); targets.append(c)
    remap = np.array([tmap[rgb_to_hex(c)] for c in dst])
    precise_mode = o.get("tracer", "precise") != "classic"
    if precise_mode:
        import precise
        k = 1
        lab_pal = _rgb_to_lab(np.array(src, dtype=np.float64)).astype(np.float32)
        lab_px = _rgb_to_lab(rgba[..., :3].reshape(-1, 3)).astype(np.float32).reshape(H, W, 3)
        o["_noise"] = noise_level(rgba[..., :3])
        S_src, transparent = precise.shares(rgba[..., :3], rgba[..., 3], np.array(src, np.float32), lab_px, lab_pal)
        del lab_px
        S = np.zeros((len(targets), H, W), np.float32)
        for i, t in enumerate(remap):
            S[t] += S_src[i]
        del S_src
        idx = S.argmax(0).astype(np.int32)
        idx[transparent > S.max(0)] = 255
        counts = np.bincount(idx[idx != 255].ravel(), minlength=len(targets)) if (idx != 255).any() else np.zeros(len(targets), int)
        bg_index = None
        if o.get("remove_background"):
            border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
            border = border[border != 255]
            if len(border):
                bg_index = int(np.bincount(border).argmax())
        stacking = "stacked" if o["shape_stacking"] == "stacked" else "cutout"
        palette_hex = [rgb_to_hex(c) for c in targets]
        shapes: list[Shape] = []
        o["_palette"] = np.array(targets, np.float32)
        o["_seams"] = []                  # (fitted edge, colour, colour, closed): the exact shared edges
        o["_palette_hex"] = palette_hex
        for j, subs in precise.trace_colors(S, transparent, {bg_index} if bg_index is not None else set(), o):
            sh = Shape(sid=f"s{len(shapes) + 1}", color=palette_hex[j], subpaths=subs)
            sh.poly, sh.shell = _poly_from_subpaths(subs)
            if sh.poly.is_empty or sh.poly.area < 0.05:
                continue
            shapes.append(sh)
        if stacking == "stacked":     # holes filled by another colour are closed: that colour lies on top
            for sh in shapes:
                keep = [sh.subpaths[0]]
                for hole in sh.subpaths[1:]:
                    pt = _poly_from_subpaths([hole])[0].representative_point()
                    x, y = int(min(W - 1, max(0, pt.x))), int(min(H - 1, max(0, pt.y)))
                    if idx[y, x] == 255 or idx[y, x] == bg_index:
                        keep.append(hole)
                if len(keep) != len(sh.subpaths):
                    sh.subpaths = keep
                    sh.poly, sh.shell = _poly_from_subpaths(keep)
        del S
        if bg_index is not None:
            idx[idx == bg_index] = 255
    else:
        # upscale for sub-pixel smoothness, then snap every pixel to the palette
        k = 1
        while k < MAX_UPSCALE and W * H * (k + 1) ** 2 <= MAX_WORK_PIXELS and max(W, H) * k < 1600:
            k += 1
        work = im.resize((W * k, H * k), Image.LANCZOS) if k > 1 else im
        wa = np.asarray(work)
        alpha = wa[..., 3] >= 128
        lab_pal = _rgb_to_lab(np.array(src, dtype=np.float64))
        idx = _nearest(_rgb_to_lab(wa[..., :3].reshape(-1, 3)), lab_pal).reshape(wa.shape[:2])
        idx = remap[idx]
        idx[~alpha] = 255
        smooth = int(o["smoothing"])
        if k >= 2 and smooth > 0:
            size = 3 if smooth < 75 or k < 3 else 5
            idx = np.asarray(Image.fromarray(idx.astype(np.uint8), "L").filter(ImageFilter.ModeFilter(size))).astype(np.int32)
        counts = np.bincount(idx[idx != 255].ravel(), minlength=len(targets)) if (idx != 255).any() else np.zeros(len(targets), int)

        bg_index = None
        if o.get("remove_background"):
            border = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
            border = border[border != 255]
            if len(border):
                bg_index = int(np.bincount(border).argmax())
                idx[idx == bg_index] = 255

        out = np.zeros((*idx.shape, 4), dtype=np.uint8)
        tarr = np.array(targets, dtype=np.uint8)
        mask = idx != 255
        out[mask, :3] = tarr[idx[mask]]
        out[mask, 3] = 255
        buf = io.BytesIO()
        Image.fromarray(out, "RGBA").save(buf, "PNG")

        detail = int(o["detail"])
        speckle = max(1, int(round((8 - detail / 100 * 7) * k)))
        stacking = "stacked" if o["shape_stacking"] == "stacked" else "cutout"
        svg = vtracer.convert_raw_image_to_svg(
            buf.getvalue(), img_format="png", colormode="color", hierarchical=stacking, mode="spline",
            filter_speckle=speckle, color_precision=8, layer_difference=1,
            corner_threshold=int(o["corner_threshold"]), length_threshold=4.0 + smooth / 100 * 2,
            max_iterations=10, splice_threshold=45, path_precision=4)

        palette_hex = [rgb_to_hex(c) for c in targets]
        shapes: list[Shape] = []
        for m in re.finditer(r'<path d="([^"]+)" fill="([^"]+)"(?: transform="translate\(([-\d.e]+),([-\d.e]+)\)")?', svg):
            d, fill, tx, ty = m.group(1), m.group(2), float(m.group(3) or 0), float(m.group(4) or 0)
            subs = parse_d(d, tx, ty, 1.0 / k)
            if not subs:
                continue
            col = np.array(hex_to_rgb(fill), float)
            color = palette_hex[int(np.argmin(((np.array(targets, float) - col) ** 2).sum(1)))]
            sh = Shape(sid=f"s{len(shapes) + 1}", color=color, subpaths=subs)
            sh.poly, sh.shell = _poly_from_subpaths(subs)
            if sh.poly.is_empty or sh.poly.area < 0.05:
                continue
            shapes.append(sh)
    # background candidates: shapes of the main border colour that touch the border
    bg_candidates = []
    bcol = None
    border_px = np.concatenate([idx[0], idx[-1], idx[:, 0], idx[:, -1]])
    border_px = border_px[border_px != 255]
    if len(border_px):
        bcol = palette_hex[int(np.bincount(border_px).argmax())]
        for sh in shapes:
            x0, y0, x1, y1 = sh.poly.bounds
            if sh.color == bcol and (x0 < 1 or y0 < 1 or x1 > W - 1 or y1 > H - 1):
                bg_candidates.append(sh.sid)
        # the background colour seen through letters and shapes (the inside of B, O, A...) goes too
        if bg_candidates:
            bg_candidates += [sh.sid for sh in shapes if sh.color == bcol and sh.sid not in bg_candidates]

    edits = o.get("edits") or {}
    removed = set(edits.get("remove") or [])
    recolor = edits.get("recolor") or {}
    for sh in shapes:
        if sh.sid in recolor:
            sh.color = rgb_to_hex(hex_to_rgb(recolor[sh.sid]))
    removed_shapes = [sh for sh in shapes if sh.sid in removed]
    shapes = [sh for sh in shapes if sh.sid not in removed]

    fitted_loops = 0
    if o["fit_shapes"] and o["draw_style"] != "stroke_edges":
        if precise_mode and o.get("shared_edges", True):
            fitted_loops = fit_shared_shapes(shapes, idx)
        else:
            for sh in shapes:
                fitted_loops += fit_whole_shape(sh)

    if ai != 1:          # back to the image's own pixels
        _scale_shapes(shapes + removed_shapes, 1 / ai)
        o["_seams"] = [(_scale_sub(sub, 1 / ai), a, b, c) for sub, a, b, c in (o.get("_seams") or [])]
        W, H = W // ai, H // ai
        counts = np.asarray(counts) // (ai * ai)

    _assign_layers(shapes, stacking)
    _assign_parents(shapes)

    palette = [{"from": rgb_to_hex(src[i]), "to": rgb_to_hex(dst[i])} for i in range(len(src))]
    color_counts = {palette_hex[i]: int(counts[i]) for i in range(len(targets))}
    svg_out, stats = build_svg(shapes, W, H, o, notes, removed_shapes)
    stats["fitted"] = fitted_loops
    result = {
        "svg": svg_out, "width": W, "height": H, "upscale": k, "palette": palette,
        "colors": [{"hex": h, "pixels": color_counts.get(h, 0)} for h in palette_hex],
        "background": palette_hex[bg_index] if bg_index is not None else None,
        "background_shapes": bg_candidates,
        "border_color": bcol,
        "stats": stats, "notes": notes,
    }
    if want_shapes:   # Shape objects for the patch renderer (not JSON)
        result["shapes"] = shapes
    return result


def _assign_layers(shapes, stacking):
    """Draw-order layers: shapes in one layer never overlap, so they may be reordered."""
    if stacking == "cutout" or not shapes:
        for s in shapes:
            s.layer = 0
        return
    polys = [s.poly for s in shapes]
    tree = STRtree(polys)
    for i, s in enumerate(shapes):
        lay = 0
        for j in tree.query(polys[i]):
            if j < i and shapes[j].layer + 1 > lay:
                try:
                    if polys[i].intersection(polys[j]).area > 0.5:
                        lay = shapes[j].layer + 1
                except Exception:
                    lay = shapes[j].layer + 1
        s.layer = lay


def _assign_parents(shapes):
    if not shapes:
        return
    shells = [s.shell if not s.shell.is_empty else s.poly for s in shapes]
    tree = STRtree(shells)
    for i, s in enumerate(shapes):
        best = -1
        a = s.poly.area
        for j in tree.query(s.poly):
            if j == i:
                continue
            if shells[j].area <= a:
                continue
            try:
                if s.poly.intersection(shells[j]).area >= 0.98 * a:
                    if best < 0 or shells[j].area < shells[best].area:
                        best = int(j)
            except Exception:
                pass
        s.parent = best


# --------------------------------------------------------------------------
# SVG writing

def _shape_element(sh: Shape, style: str, extra: str = "") -> str:
    if sh.kind == "circle":
        p = sh.params
        geo = f'<circle cx="{_fmt(p["cx"])}" cy="{_fmt(p["cy"])}" r="{_fmt(p["r"])}"'
    elif sh.kind == "ellipse":
        p = sh.params
        tr = f' transform="rotate({_fmt(p["angle"])} {_fmt(p["cx"])} {_fmt(p["cy"])})"' if p["angle"] else ""
        geo = f'<ellipse cx="{_fmt(p["cx"])}" cy="{_fmt(p["cy"])}" rx="{_fmt(p["rx"])}" ry="{_fmt(p["ry"])}"{tr}'
    elif sh.kind == "rect":
        p = sh.params
        x, y = p["cx"] - p["w"] / 2, p["cy"] - p["h"] / 2
        tr = f' transform="rotate({_fmt(p["angle"])} {_fmt(p["cx"])} {_fmt(p["cy"])})"' if p["angle"] else ""
        rnd = f' rx="{_fmt(p["r"])}"' if p.get("r", 0) > 0 else ""
        geo = f'<rect x="{_fmt(x)}" y="{_fmt(y)}" width="{_fmt(p["w"])}" height="{_fmt(p["h"])}"{rnd}{tr}'
    else:
        geo = f'<path d="{subpaths_to_d(sh.subpaths)}"'
    return f"{geo} {style}{extra}/>"


def _units_to_px(v, unit, dpi):
    return {"px": 1.0, "in": dpi, "cm": dpi / 2.54, "mm": dpi / 25.4}.get(unit, 1.0) * float(v)


def output_size(W, H, o):
    """Width/height attributes (strings with units) and preserveAspectRatio."""
    mode, unit, dpi = o["size_mode"], o["unit"], float(o["dpi"] or 72)
    par = "xMidYMid meet"
    w, h = float(W), float(H)
    if mode == "scale":
        w, h = W * float(o["scale"] or 1), H * float(o["scale"] or 1)
        unit = "px"
    elif mode in ("width", "height", "fit", "fill", "stretch"):
        tw = _units_to_px(o["width"], unit, dpi) if o.get("width") else None
        th = _units_to_px(o["height"], unit, dpi) if o.get("height") else None
        if mode == "width" and tw:
            w, h = tw, tw * H / W
        elif mode == "height" and th:
            w, h = th * W / H, th
        elif tw and th:
            if mode == "fit":
                f = min(tw / W, th / H); w, h = W * f, H * f
            elif mode == "fill":
                f = max(tw / W, th / H); w, h = W * f, H * f
            else:
                w, h, par = tw, th, "none"
    if unit != "px" and mode != "scale":
        f = {"in": dpi, "cm": dpi / 2.54, "mm": dpi / 25.4}[unit]
        return f"{_fmt(w / f)}{unit}", f"{_fmt(h / f)}{unit}", par
    return _fmt(w), _fmt(h), par


def _avg(c1, c2):
    a, b = hex_to_rgb(c1), hex_to_rgb(c2)
    return rgb_to_hex([(x + y) / 2 for x, y in zip(a, b)])


def _edges(shapes, stacking, tol=0.6):
    """Each boundary between visible regions once, coloured by the average of its neighbours.

    Neighbouring shapes are traced separately, so their shared borders almost but
    not exactly coincide. Each region adds only the parts of its outline that no
    earlier region has drawn (within tol px), which keeps one clean line per edge.
    """
    regions = []
    if stacking == "stacked":
        polys = [s.poly for s in shapes]
        tree = STRtree(polys)
        for i, s in enumerate(shapes):
            above = [polys[j] for j in tree.query(polys[i]) if j > i]
            vis = s.poly.difference(unary_union(above)) if above else s.poly
            if not vis.is_empty and vis.area > 0.25:
                regions.append((make_valid(vis), s.color))
    else:
        regions = [(s.poly, s.color) for s in shapes]
    if not regions:
        return []
    regions = [(r, c) for r, c in regions if r.geom_type in ("Polygon", "MultiPolygon") and not r.is_empty]
    if not regions:
        return []
    bounds = [r.boundary.simplify(0.15) for r, _ in regions]   # a sub-pixel simplification keeps this quick
    btree = STRtree(bounds)
    halos = [b.buffer(tol, quad_segs=2) for b in bounds]   # outline +- tol
    out = []
    for i, (reg, col) in enumerate(regions):
        b = bounds[i]
        for j in btree.query(b.buffer(tol)):
            if j < i and not b.is_empty:
                b = b.difference(halos[j])   # line minus polygon is cheap; no union needed
        if b.is_empty:
            continue
        merged = linemerge(b) if b.geom_type in ("MultiLineString", "GeometryCollection") else b
        for ln in getattr(merged, "geoms", [merged]):
            if ln.geom_type != "LineString" or ln.length < max(1.0, tol):
                continue
            ln = ln.simplify(0.05)
            mid = ln.interpolate(0.5, normalized=True)
            nb = [regions[j][1] for j in btree.query(mid.buffer(tol)) if bounds[j].distance(mid) < tol]
            color = nb[0] if len(nb) == 1 else (_avg(nb[0], nb[1]) if nb else col)
            out.append((ln, color, len(nb)))
    return out


def build_svg(shapes, W, H, o, notes, removed_shapes=()):
    stacking = "stacked" if o["shape_stacking"] == "stacked" else "cutout"
    draw = o["draw_style"]
    group_by = o["group_by"]
    w_attr, h_attr, par = output_size(W, H, o)
    ver = o["svg_version"]
    head = {"1.0": 'version="1.0"', "1.1": 'version="1.1"', "tiny1.2": 'version="1.2" baseProfile="tiny"'}.get(ver, 'version="1.1"')
    size = f' width="{w_attr}" height="{h_attr}"' if o["fixed_size"] else ""
    if ver == "tiny1.2" and o["gap_clip"]:
        notes.append("SVG Tiny 1.2 has no clipping paths, so Clip Overflow was skipped.")
    clip_ok = ver != "tiny1.2"

    def nss(flag):
        return ' vector-effect="non-scaling-stroke"' if flag else ""

    def fill_style(sh):
        if draw == "stroke_shapes":
            col = o["stroke_color"] if o["stroke_override"] else sh.color
            return f'fill="none" stroke="{col}" stroke-width="{_fmt(float(o["stroke_width"]))}" stroke-linejoin="round"{nss(o["stroke_non_scaling"])}'
        return f'fill="{sh.color}"'

    def ident(sh):
        return f' id="{sh.sid}" class="shape" data-color="{sh.color}" data-layer="{sh.layer}"'

    def gap_el(sh):
        # stacked: the stroke lies on the shape below, so use the average of both colours
        col = _avg(sh.color, shapes[sh.parent].color) if stacking == "stacked" and sh.parent >= 0 else sh.color
        return _shape_element(sh, f'fill="none" stroke="{col}" stroke-width="{_fmt(float(o["gap_width"]))}" stroke-linejoin="round"{nss(o["gap_non_scaling"])}',
                              f' class="gap" data-for="{sh.sid}"')

    body, defs = [], []
    gap = o["gap_filler"] and draw == "fill_shapes"
    stats = {"shapes": len(shapes), "layers": (max((s.layer for s in shapes), default=-1) + 1),
             "fitted": sum(1 for s in shapes if s.kind != "path"), "groups": 0}

    def layer_attrs(gid, label):
        stats["groups"] += 1
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", gid).strip("-")
        return f'<g id="{safe}" inkscape:groupmode="layer" inkscape:label="{label}">'

    if draw == "stroke_edges":
        col_override = o["stroke_color"] if o["stroke_override"] else None
        edges = _edges(shapes, stacking)
        by_color: dict[str, list] = {}
        for ln, c, _ in edges:
            by_color.setdefault(col_override or c, []).append(ln)
        for c, lns in by_color.items():
            body.append(layer_attrs(f"edges-{c}", f"Edges {c}"))
            for ln in lns:
                pts = list(ln.coords)
                d = "M" + "L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in pts)
                body.append(f'<path d="{d}" fill="none" stroke="{c}" stroke-width="{_fmt(float(o["stroke_width"]))}" stroke-linecap="round" stroke-linejoin="round"{nss(o["stroke_non_scaling"])}/>')
            body.append("</g>")
        stats["edges"] = len(edges)
    else:
        order = sorted(range(len(shapes)), key=lambda i: (shapes[i].layer, i))
        if gap and stacking == "cutout":
            # strokes only along edges shared by two shapes, in the average of their colours
            body.append(layer_attrs("gap-filler", "Gap filler"))
            seams: dict[str, list[str]] = {}
            if o.get("_seams") and o.get("_palette_hex"):
                # the planar tracer's own fitted edges: the stroke lies exactly on the shared curve
                ph = o["_palette_hex"]
                for sub, a, b, closed in o["_seams"]:
                    d = "".join(op + " ".join(_fmt(v) for v in p) for op, p in sub) + ("Z" if closed else "")
                    seams.setdefault(_avg(ph[a], ph[b]), []).append(d)
            else:
                for ln, c, n in _edges(shapes, "cutout"):
                    if n >= 2:
                        seams.setdefault(c, []).append("M" + "L".join(f"{_fmt(x)} {_fmt(y)}" for x, y in ln.coords))
            for c, ds in seams.items():
                body.append(f'<path class="gap" d="{"".join(ds)}" fill="none" stroke="{c}" stroke-width="{_fmt(float(o["gap_width"]))}" stroke-linecap="round" stroke-linejoin="round"{nss(o["gap_non_scaling"])}/>')
            body.append("</g>")

        def gap_for_layer(L):
            if not gap or stacking != "stacked" or L == 0:
                return
            members = [i for i in order if shapes[i].layer == L and shapes[i].parent >= 0]
            clip = ""
            if o["gap_clip"] and clip_ok:
                cid = f"gapclip{L}"
                below = [shapes[i] for i in order if shapes[i].layer < L]
                defs.append(f'<clipPath id="{cid}">' + "".join(_shape_element(s, "") for s in below) + "</clipPath>")
                clip = f' clip-path="url(#{cid})"'
            body.append(f'<g id="gap-filler-{L}" inkscape:label="Gap filler {L}"{clip}>')
            body.extend(gap_el(shapes[i]) for i in members)
            body.append("</g>")

        if group_by == "parent":
            kids: dict[int, list[int]] = {}
            for i, s in enumerate(shapes):
                kids.setdefault(s.parent, []).append(i)
            seq = []
            def walk(p):
                for c in sorted(kids.get(p, [])):
                    seq.append(c)
                    walk(c)
            walk(-1)
            pos = {i: n for n, i in enumerate(seq)}
            valid = len(seq) == len(shapes)
            if valid and stacking == "stacked":
                polys = [s.poly for s in shapes]
                tree = STRtree(polys)
                for i in range(len(shapes)):
                    for j in tree.query(polys[i]):
                        if j < i and pos[j] > pos[i] and polys[i].intersection(polys[j]).area > 0.5:
                            valid = False; break
                    if not valid:
                        break
            if not valid:
                notes.append("Grouping by parent would change how the image looks, so shapes were grouped by layer instead.")
                group_by = "layer"
            else:
                def emit(p, depth):
                    ch = sorted(kids.get(p, []))
                    if not ch:
                        return
                    label = "Top level" if p < 0 else f"Inside {shapes[p].sid}"
                    body.append(layer_attrs(f"parent-{'root' if p < 0 else shapes[p].sid}", label) if depth == 0 else f'<g id="children-of-{shapes[p].sid}" inkscape:label="{label}">')
                    for c in ch:
                        if gap and stacking == "stacked" and shapes[c].layer > 0 and shapes[c].parent >= 0:
                            body.append(gap_el(shapes[c]))
                        body.append(_shape_element(shapes[c], fill_style(shapes[c]), ident(shapes[c])))
                        emit(c, depth + 1)
                    body.append("</g>")
                emit(-1, 0)

        if group_by in ("none", "color", "layer"):
            layers = sorted({s.layer for s in shapes})
            for L in layers:
                gap_for_layer(L)
                members = [i for i in order if shapes[i].layer == L]
                if group_by == "none":
                    body.extend(_shape_element(shapes[i], fill_style(shapes[i]), ident(shapes[i])) for i in members)
                elif group_by == "layer":
                    body.append(layer_attrs(f"layer-{L + 1}", f"Layer {L + 1}"))
                    body.extend(_shape_element(shapes[i], fill_style(shapes[i]), ident(shapes[i])) for i in members)
                    body.append("</g>")
                else:
                    by_color: dict[str, list[int]] = {}
                    for i in members:
                        by_color.setdefault(shapes[i].color, []).append(i)
                    for c, idxs in by_color.items():
                        gid = f"color-{c[1:]}" if stacking == "cutout" else f"layer-{L + 1}-color-{c[1:]}"
                        label = c if stacking == "cutout" else f"Layer {L + 1} {c}"
                        body.append(layer_attrs(gid, label))
                        body.extend(_shape_element(shapes[i], fill_style(shapes[i]), ident(shapes[i])) for i in idxs)
                        body.append("</g>")

    if removed_shapes:
        # kept so the editor can put them back; downloads strip data-removed elements
        body.append('<g id="removed-shapes" data-removed-group="1">')
        body.extend(_shape_element(s, f'fill="{s.color}"', f' id="{s.sid}" class="shape removed" data-color="{s.color}" data-removed="1"') for s in removed_shapes)
        body.append("</g>")

    svg = (f'<?xml version="1.0" encoding="UTF-8"?>\n'
           f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
           f'{head}{size} viewBox="0 0 {W} {H}" preserveAspectRatio="{par}">\n'
           + (f"<defs>{''.join(defs)}</defs>\n" if defs else "")
           + "\n".join(body) + "\n</svg>\n")
    return svg, stats
