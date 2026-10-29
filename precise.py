"""Precise tracing: sub-pixel colour boundaries fitted with Bezier curves.

Every pixel is given to its two nearest palette colours in proportion (an anti-aliased edge
pixel is part one colour, part the other), so blend pixels never become colours of their
own. Each colour's outline is the line where it stops being the strongest colour, found with
marching squares to a fraction of a pixel; neighbouring colours share that line exactly, so
there are no gaps or overlaps. The outlines are then fitted with cubic Bezier curves
(Schneider's method), keeping corners sharp where the outline turns more than the corner
threshold.
"""

from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw
from shapely.geometry import Point, Polygon
from shapely.prepared import prep


# --------------------------------------------------------------------------
# colour shares

def _b121(a, axis):
    """One [1 2 1] / 4 pass along an axis (edges repeated)."""
    a = np.moveaxis(a, axis, -1)
    p = np.concatenate([a[..., :1], a, a[..., -1:]], -1)
    out = (p[..., :-2] + 2 * p[..., 1:-1] + p[..., 2:]) * 0.25
    return np.moveaxis(out, -1, axis)


def _blur(a, sigma):
    """Small Gaussian blur of the last two axes: each binomial pass adds a variance of 1/2."""
    passes = int(round(2 * sigma * sigma)) if sigma >= 0.35 else 0
    for _ in range(passes):
        a = _b121(_b121(a, -1), -2)
    return a


def _dilate(m, r):
    """Square dilation by r pixels of boolean masks on the last two axes."""
    out = m.copy()
    for k in range(1, r + 1):
        out[..., k:, :] |= m[..., :-k, :]; out[..., :-k, :] |= m[..., k:, :]
    m2 = out.copy()
    for k in range(1, r + 1):
        out[..., :, k:] |= m2[..., :, :-k]; out[..., :, :-k] |= m2[..., :, k:]
    return out


def shares(rgb: np.ndarray, alpha: np.ndarray, palette: np.ndarray, lab_px: np.ndarray, lab_pal: np.ndarray):
    """(N, H, W) share of each palette colour in every pixel, and (H, W) transparency.

    A pixel lying on the RGB line between its two nearest colours is split between them in
    proportion; one that is not (a colour of its own) goes wholly to the nearest."""
    H, W = alpha.shape
    n = len(palette)
    flat = rgb.reshape(-1, 3).astype(np.float32)
    lab = lab_px.reshape(-1, 3)
    out = np.zeros((n, H * W), np.float32)
    # an edge pixel can only mix the colours around it: a colour counts near a pixel when it
    # fills a flat area, or matches exactly, within a few pixels (keeps compression fringes from
    # turning into a third colour, and thin lines that match their colour exactly)
    present = None
    if n > 1:
        c16 = rgb.astype(np.int16)
        step = np.zeros((H, W), np.int16)
        for dy, dx in ((0, 1), (1, 0)):
            d = np.abs(c16 - np.roll(np.roll(c16, dy, 0), dx, 1)).max(-1)
            step = np.maximum(step, np.maximum(d, np.roll(np.roll(d, -dy, 0), -dx, 1)))
        is_flat = (step < 16).ravel()
        near_all = np.empty(H * W, np.int32)
        exact = np.empty(H * W, bool)
        clear = np.empty(H * W, bool)
        for i in range(0, H * W, 400_000):
            d = ((lab[i:i + 400_000, None, :] - lab_pal[None]) ** 2).sum(-1)
            near_all[i:i + 400_000] = d.argmin(1)
            exact[i:i + 400_000] = d.min(1) < 16
            # clearly one colour: within 30 of it and under half as far as from any other (small,
            # blurred lettering far from any solid patch of its colour still counts as that colour)
            dd = np.partition(d, 1, axis=1)[:, :2] if n > 1 else np.stack([d[:, 0], d[:, 0] * 0 + 1e9], 1)
            clear[i:i + 400_000] = (dd[:, 0] < 900) & (dd[:, 0] < 0.25 * dd[:, 1])
        # a pixel between two other colours whose own colour is just their mix is their
        # anti-aliasing, not a colour of its own: the half-black, half-sand pixels along a black
        # outline match an engraved brown, but they do not make the brown present there
        lbl = near_all.reshape(H, W)
        first = np.full((H, W), -1, np.int32)
        second = np.full((H, W), -1, np.int32)
        # look up to 3 px away in eight directions, so a soft edge a few pixels wide is spanned
        for r in (1, 2, 3):
            for dy, dx in ((0, 1), (1, 0), (0, -1), (-1, 0), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                nb = np.roll(np.roll(lbl, dy * r, 0), dx * r, 1)
                other = nb != lbl
                second = np.where(other & (first >= 0) & (nb != first) & (second < 0), nb, second)
                first = np.where(other & (first < 0), nb, first)
        two = (second >= 0).ravel()
        wedged = np.zeros(H * W, bool)
        if two.any():
            idx2 = np.nonzero(two)[0]
            pc = palette[near_all[idx2]].astype(np.float32)
            pa = palette[first.ravel()[idx2]].astype(np.float32); pb = palette[second.ravel()[idx2]].astype(np.float32)
            seg = pa - pb
            t = np.clip(((pc - pb) * seg).sum(1) / np.maximum((seg * seg).sum(1), 1e-6), 0, 1)
            wedged[idx2] = (np.linalg.norm(pb + t[:, None] * seg - pc, axis=1) < 25) & (t > 0.08) & (t < 0.92)
        sure = (is_flat | exact | clear) & ~wedged
        present = np.zeros((n, H * W), bool)
        present[near_all[sure], np.nonzero(sure)[0]] = True
        base = present.reshape(n, H, W)
        present = _dilate(base, 3).reshape(n, H * W)  # a pixel's own colour: one within 3 px
        wide = _dilate(base, 8).reshape(n, H * W)     # what it may be blended with: within 8 px
        none = ~present.any(0)
        present[:, none] = wide[:, none]              # the middle of a wide soft edge
        none = ~present.any(0)
        present[:, none] = True                       # nothing sure anywhere near (gradients): any colour
        wide[:, none] = True
    pal = palette.astype(np.float32)
    step = 400_000
    for i in range(0, len(flat), step):
        d = ((lab[i:i + step, None, :] - lab_pal[None]) ** 2).sum(-1)
        if present is not None:
            dw = np.where(wide[:, i:i + step].T, d, d + 1e7)
            d = np.where(present[:, i:i + step].T, d, d + 1e7)
            # the pixel's own colour from those within 3 px; its blend partner may be a little further
            own = d.argmin(1)
            dw[np.arange(len(dw)), own] = np.inf
            d = np.where(np.arange(n)[None, :] == own[:, None], d, dw)
        if n == 1:
            out[0, i:i + step] = 1
            continue
        two = np.argpartition(d, 1, axis=1)[:, :2]
        da = np.take_along_axis(d, two, 1)
        swap = da[:, 0] > da[:, 1]
        a = np.where(swap, two[:, 1], two[:, 0]); b = np.where(swap, two[:, 0], two[:, 1])
        c = flat[i:i + step]
        pa, pb = pal[a], pal[b]
        seg = pa - pb
        t = np.clip(((c - pb) * seg).sum(1) / np.maximum((seg * seg).sum(1), 1e-6), 0, 1)
        off = np.linalg.norm(pb + t[:, None] * seg - c, axis=1)
        near = np.sqrt(np.minimum(da[:, 0], da[:, 1])) < 5           # already the colour itself
        banned = np.maximum(da[:, 0], da[:, 1]) >= 1e6                 # the second colour is not around here
        solo = near | banned | (off > 38)                             # not a blend of two colours here: all to the nearest
        t = np.where(solo, 1.0, t)
        idx = np.arange(len(c))
        out[a, i + idx] += t
        out[b, i + idx] += 1 - t
    out = out.reshape(n, H, W)
    al = alpha.astype(np.float32) / 255
    return out * al[None], 1 - al


# --------------------------------------------------------------------------
# marching squares

# edge pairs for each case (corners: tl=1, tr=2, br=4, bl=8); saddles 5 and 10 decided by the centre
_PAIRS = {1: [("L", "T")], 2: [("T", "R")], 3: [("L", "R")], 4: [("R", "B")], 6: [("T", "B")],
          7: [("L", "B")], 8: [("L", "B")], 9: [("T", "B")], 11: [("R", "B")], 12: [("L", "R")],
          13: [("T", "R")], 14: [("L", "T")]}


def contours(F: np.ndarray):
    """Closed loops (lists of (x, y), image pixel coordinates) where F crosses 0, F > 0 inside."""
    H, W = F.shape
    Fp = np.full((H + 2, W + 2), -1.0, np.float32)
    Fp[1:-1, 1:-1] = F
    Fp[Fp == 0] = 1e-6                     # no value exactly on the line
    Hp, Wp = Fp.shape
    ins = Fp > 0
    case = (ins[:-1, :-1] * 1 + ins[:-1, 1:] * 2 + ins[1:, 1:] * 4 + ins[1:, :-1] * 8).astype(np.int8)
    ys, xs = np.nonzero((case != 0) & (case != 15))
    if len(ys) == 0:
        return []
    cs = case[ys, xs]
    edge = {"T": ys * Wp + xs, "B": (ys + 1) * Wp + xs, "L": Hp * Wp + ys * Wp + xs, "R": Hp * Wp + ys * Wp + xs + 1}
    e1, e2 = [], []
    for c, pairs in _PAIRS.items():
        m = cs == c
        for a, b in pairs:
            e1.append(edge[a][m]); e2.append(edge[b][m])
    centre = (Fp[ys, xs] + Fp[ys, xs + 1] + Fp[ys + 1, xs] + Fp[ys + 1, xs + 1]) / 4 > 0
    for c, (pin, pout) in ((5, ((("T", "R"), ("L", "B")), (("L", "T"), ("R", "B")))),
                           (10, ((("L", "T"), ("R", "B")), (("T", "R"), ("L", "B"))))):
        for inside, pairs in ((True, pin), (False, pout)):
            m = (cs == c) & (centre == inside)
            for a, b in pairs:
                e1.append(edge[a][m]); e2.append(edge[b][m])
    e1 = np.concatenate(e1); e2 = np.concatenate(e2)
    nseg = len(e1)
    # where each edge is crossed
    used = np.unique(np.concatenate([e1, e2]))
    horiz = used < Hp * Wp
    hy, hx = np.divmod(used[horiz], Wp)
    vy, vx = np.divmod(used[~horiz] - Hp * Wp, Wp)
    px = np.empty(len(used), np.float64); py = np.empty(len(used), np.float64)
    a, b = Fp[hy, hx], Fp[hy, hx + 1]
    px[horiz] = hx + a / (a - b) - 0.5; py[horiz] = hy - 0.5
    a, b = Fp[vy, vx], Fp[vy + 1, vx]
    px[~horiz] = vx - 0.5; py[~horiz] = vy + a / (a - b) - 0.5
    k1 = np.searchsorted(used, e1); k2 = np.searchsorted(used, e2)
    # every crossed edge belongs to exactly two segments: link them into loops
    ends = np.concatenate([k1, k2])
    segs = np.concatenate([np.arange(nseg), np.arange(nseg)])
    order = np.argsort(ends, kind="stable")
    pair_of = np.empty(len(ends), np.int64)
    o = order.reshape(-1, 2)
    pair_of[o[:, 0]] = segs[o[:, 1]]
    pair_of[o[:, 1]] = segs[o[:, 0]]
    other1, other2 = pair_of[:nseg], pair_of[nseg:]   # the segment across each segment's first / second end
    seen = np.zeros(nseg, bool)
    loops = []
    k1l, k2l, o1l, o2l = k1.tolist(), k2.tolist(), other1.tolist(), other2.tolist()
    pxl, pyl = px.tolist(), py.tolist()
    for s0 in range(nseg):
        if seen[s0]:
            continue
        seen[s0] = True
        start, cur, nxt = k1l[s0], k2l[s0], o2l[s0]
        pts = [start, cur]
        while nxt != s0 and not seen[nxt]:
            s = nxt
            seen[s] = True
            if k1l[s] == cur:           # entered by its first end: leave by the second
                cur, nxt = k2l[s], o2l[s]
            else:
                cur, nxt = k1l[s], o1l[s]
            if cur == start:
                break
            pts.append(cur)
        if len(pts) >= 4:
            loops.append([(pxl[q], pyl[q]) for q in pts])
    return loops


# --------------------------------------------------------------------------
# Bezier fitting (Schneider, "An algorithm for automatically fitting digitized curves")

def _bez(b, t):
    t = t[:, None]; u = 1 - t
    return u ** 3 * b[0] + 3 * u * u * t * b[1] + 3 * u * t * t * b[2] + t ** 3 * b[3]


def _bez_d(b, t):
    t = t[:, None]; u = 1 - t
    return 3 * u * u * (b[1] - b[0]) + 6 * u * t * (b[2] - b[1]) + 3 * t * t * (b[3] - b[2])


def _bez_dd(b, t):
    t = t[:, None]
    return 6 * (1 - t) * (b[2] - 2 * b[1] + b[0]) + 6 * t * (b[3] - 2 * b[2] + b[1])


def _generate(P, u, t1, t2):
    p0, p3 = P[0], P[-1]
    uu = u[:, None]; v = 1 - uu
    A1 = t1[None] * (3 * v * v * uu)
    A2 = t2[None] * (3 * v * uu * uu)
    c00 = (A1 * A1).sum(); c01 = (A1 * A2).sum(); c11 = (A2 * A2).sum()
    tmp = P - (v ** 3 * p0 + 3 * v * v * uu * p0 + 3 * v * uu * uu * p3 + uu ** 3 * p3)
    x0 = (A1 * tmp).sum(); x1 = (A2 * tmp).sum()
    det = c00 * c11 - c01 * c01
    seg = float(np.linalg.norm(p3 - p0))
    if abs(det) > 1e-12:
        al1 = (x0 * c11 - x1 * c01) / det
        al2 = (c00 * x1 - c01 * x0) / det
    else:
        al1 = al2 = seg / 3
    eps = 1e-6 * seg
    if al1 < eps or al2 < eps or al1 > seg * 2 or al2 > seg * 2:
        al1 = al2 = seg / 3
    return np.array([p0, p0 + t1 * al1, p3 + t2 * al2, p3])


def _reparam(b, P, u):
    d = _bez(b, u) - P
    d1, d2 = _bez_d(b, u), _bez_dd(b, u)
    num = (d * d1).sum(1)
    den = (d1 * d1).sum(1) + (d * d2).sum(1)
    nu = np.where(np.abs(den) > 1e-12, u - num / np.where(np.abs(den) > 1e-12, den, 1), u)
    return np.clip(nu, 0, 1)


def _unit(v):
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else v


def _fit(P, t1, t2, err2, depth=0):
    n = len(P)
    if n == 2 or depth > 12:
        d = np.linalg.norm(P[-1] - P[0]) / 3
        return [np.array([P[0], P[0] + t1 * d, P[-1] + t2 * d, P[-1]])]
    cl = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(P, axis=0), axis=1))])
    u = cl / cl[-1] if cl[-1] > 0 else np.linspace(0, 1, n)
    b = _generate(P, u, t1, t2)
    e = ((_bez(b, u) - P) ** 2).sum(1)
    if e.max() < err2:
        return [b]
    if e.max() < err2 * 9:
        for _ in range(6):
            u = _reparam(b, P, u)
            b = _generate(P, u, t1, t2)
            e = ((_bez(b, u) - P) ** 2).sum(1)
            if e.max() < err2:
                return [b]
    split = int(np.clip(np.argmax(e), 1, n - 2))
    tc = _unit(P[max(0, split - 2)] - P[min(n - 1, split + 2)])
    return _fit(P[:split + 1], t1, tc, err2, depth + 1) + _fit(P[split:], -tc, t2, err2, depth + 1)


def _end_tangent(P, k=3):
    return _unit(P[min(k, len(P) - 1)] - P[0])


def _turn(Ps, m):
    """Turning angle (degrees) at every point of a closed polyline, between the chords m points back
    and m points ahead."""
    v1 = Ps - np.roll(Ps, m, 0); v2 = np.roll(Ps, -m, 0) - Ps
    cosang = (v1 * v2).sum(1) / np.maximum(np.linalg.norm(v1, axis=1) * np.linalg.norm(v2, axis=1), 1e-9)
    return np.degrees(np.arccos(np.clip(cosang, -1, 1)))


def _intersect(p, d, q, e):
    """Where the line through p along d meets the line through q along e, or None when parallel."""
    den = d[0] * e[1] - d[1] * e[0]
    if abs(den) < 0.15:                      # closer than about 9 degrees: no clear meeting point
        return None
    t = ((q[0] - p[0]) * e[1] - (q[1] - p[1]) * e[0]) / den
    return p + t * d


def _direction(Q):
    """Main direction of a short run of points, from first to last (least squares)."""
    c = Q - Q.mean(0)
    _, _, vt = np.linalg.svd(c, full_matrices=False)
    d = vt[0]
    return d if np.dot(d, Q[-1] - Q[0]) >= 0 else -d


def fit_loop(pts, err=0.5, corner_deg=60, density=1):
    """A closed subpath [("M", p), ("L" | "C", ...), ...] through a dense loop (see fit_chain)."""
    return fit_chain(pts, True, err, corner_deg)


def fit_chain(pts, closed, err=0.5, corner_deg=60, end_trim=0.9, line_tol=None, corner_trim=0.9, arm=2.0, reach=2.5,
              detect=None, far=0.0):
    """[("M", p), ("L" | "C", ...), ...] through a dense run of outline points.

    Corners are found where the outline turns sharply over about 2 px and keeps turning as
    sharply over 1 px (a circle's turn halves). Pixels round a corner off, so each corner is
    rebuilt where the straight-on directions of its two sides meet. Each side is then a straight
    line when it is one, else cubic Beziers (Schneider). An open run (an edge between two
    junctions) keeps its two end points exactly, so the edges meeting there still meet.

    detect: the same run less smoothed (point for point). Corners are found on it, where they
    are still sharp and two close corners (the end of a thin stroke) are still two; the sides
    are fitted to pts, smoothed enough that noise is gone."""
    P = np.asarray(pts, np.float64)
    n = len(P)
    if n < 2:
        return [("M", tuple(P[0]))]
    if closed and n < 6:
        return [("M", tuple(P[0]))] + [("L", tuple(p)) for p in P[1:]]
    if closed:
        Ps = (np.roll(P, 1, 0) + 2 * P + np.roll(P, -1, 0)) / 4      # light smoothing
        total = float(np.linalg.norm(Ps - np.roll(Ps, 1, 0), axis=1).sum())
    else:
        Ps = P.copy()
        if n > 2:
            Ps[1:-1] = (P[:-2] + 2 * P[1:-1] + P[2:]) / 4
        total = float(np.linalg.norm(np.diff(Ps, axis=0), axis=1).sum())
    ppx = n / max(total, 1e-9)                                   # points per pixel of outline
    D = Ps if detect is None else np.asarray(detect, np.float64)
    # a corner turns as sharply over half the arm as over the arm; a curve turns half as much
    m2 = max(1, int(round(arm * ppx)))
    m1 = max(1, int(round(arm / 2 * ppx)))
    err2 = err * err

    if not closed and (total < 1.5 or n < 4):
        return [("M", tuple(P[0])), ("L", tuple(P[-1]))]

    corners = []
    # and still turns over twice the arm: a wiggle of noise along a curve turns sharply over a
    # pixel or two but not over four; a real corner does
    m4 = 2 * m2
    if closed and n > 4 * m2:
        t2, t1 = _turn(D, m2), _turn(D, m1)
        is_c = (t2 > corner_deg) & (t1 > 0.62 * t2)
        if n > 4 * m4:
            is_c &= _turn(D, m4) > far * corner_deg
        for s in range(1, m2 + 1):                                # the sharpest point around
            is_c &= (t2 >= np.roll(t2, s)) & (t2 > np.roll(t2, -s))
        corners = list(np.nonzero(is_c)[0])
    elif not closed and n > 2 * m2 + 2:
        t2, t1 = _turn(D, m2), _turn(D, m1)
        valid = np.zeros(n, bool); valid[m2:n - m2] = True
        is_c = valid & (t2 > corner_deg) & (t1 > 0.62 * t2)
        if n > 2 * m4 + 2:
            t4 = _turn(D, m4)
            is_c &= (t4 > far * corner_deg) | ~np.isin(np.arange(n), np.arange(m4, n - m4))
        for s in range(1, m2 + 1):
            is_c &= (t2 >= np.roll(t2, s)) & (t2 > np.roll(t2, -s))
        corners = list(np.nonzero(is_c)[0])

    if closed and not corners:
        # a smooth loop: two halves joined smoothly
        h = n // 2
        ta = _unit(Ps[1] - Ps[-1]); tb = _unit(Ps[h + 1] - Ps[h - 1])
        A = Ps[:h + 1]; B = np.vstack([Ps[h:], Ps[:1]])
        beziers = _fit(A, ta, -tb, err2) + _fit(B, tb, -ta, err2)
        sub = [("M", (float(beziers[0][0][0]), float(beziers[0][0][1])))]
        for b in beziers:
            sub.append(("C", tuple(float(v) for v in (b[1][0], b[1][1], b[2][0], b[2][1], b[3][0], b[3][1]))))
        return sub

    # the sides between corners (and the two ends of an open run), without the rounded-off part
    if closed:
        nc = len(corners)
        ext = np.vstack([Ps, Ps, Ps]); extD = np.vstack([D, D, D])
        bounds = [(corners[i], corners[(i + 1) % nc] + (n if i + 1 >= nc else 0)) for i in range(nc)]
    else:
        ext, extD = Ps, D
        cs = [0] + corners + [n - 1]
        bounds = [(cs[i], cs[i + 1]) for i in range(len(cs) - 1)]
    lt = line_tol if line_tol is not None else max(0.3, 0.6 * err)
    sides = []
    last = len(bounds) - 1
    for i, (a, b) in enumerate(bounds):
        span = b - a
        ta = end_trim if (not closed and i == 0) else corner_trim  # junctions smear more than corners
        tb = end_trim if (not closed and i == last) else corner_trim
        # a short side (the end of a thin stroke) is taken from the less smoothed run: smoothing
        # pulls it in
        src = extD if span < 2.5 * corner_trim * ppx else ext
        Q = src[a + min(int(round(ta * ppx)), max(0, span // 4)):b - min(int(round(tb * ppx)), max(0, span // 4)) + 1]
        if len(Q) < 2:
            Q = ext[[a, b]]
        k = max(2, min(len(Q), int(round(1.5 * ppx)) + 1))
        d0, d1 = _direction(Q[:k]), _direction(Q[-k:])
        # a side that one straight line follows all along (within line_tol) is that line, and its
        # corners are where the whole lines meet, not where a pixel or two at each end points
        c = Q.mean(0)
        dl = _direction(Q) if len(Q) > 2 else _unit(Q[-1] - Q[0])
        straight = len(Q) >= 2 and float(np.abs((Q[:, 0] - c[0]) * dl[1] - (Q[:, 1] - c[1]) * dl[0]).max()) < lt
        if straight:
            d0 = d1 = dl
        sides.append((Q, d0, d1, straight, c))
    # each corner where the side before it and the side after it meet; the end of a thin stroke
    # (the outline turns right round between two nearly parallel sides) is cut square instead,
    # as two corners on a cap line across the stroke, rather than drawn out to a far-off point
    def corner(prev, nxt, raw):
        Qp, _, dp, sp, cp = prev
        Qn, dn, _, sn, cn = nxt
        p_pt, n_pt = (cp if sp else Qp[-1]), (cn if sn else Qn[0])
        if float(np.dot(dp, dn)) < -0.9:
            perp = np.array([-dp[1], dp[0]])
            c1 = _intersect(p_pt, dp, raw, perp); c2 = _intersect(n_pt, dn, raw, perp)
            if (c1 is not None and c2 is not None and np.linalg.norm(c1 - raw) < reach
                    and np.linalg.norm(c2 - raw) < reach and np.linalg.norm(c1 - c2) < 3.5):
                return c1, c2
            return raw, raw
        x = _intersect(p_pt, dp, n_pt, dn)
        if x is None or np.linalg.norm(x - raw) > reach:
            x = raw
        return x, x

    if closed:
        cps = [corner(sides[i - 1], sides[i], D[corners[i]]) for i in range(nc)]
        ends = [(cps[i][1], cps[(i + 1) % nc][0]) for i in range(nc)]
        caps = [cps[(i + 1) % nc] for i in range(nc)]
    else:
        cps = [(P[0], P[0])] + [corner(sides[i - 1], sides[i], D[cs[i]]) for i in range(1, len(sides))] + [(P[-1], P[-1])]
        ends = [(cps[i][1], cps[i + 1][0]) for i in range(len(sides))]
        caps = [cps[i + 1] for i in range(len(sides))]
    sub = [("M", (float(ends[0][0][0]), float(ends[0][0][1])))]
    for (A, B), (Q, d0, d1, straight, _), cap in zip(ends, sides, caps):
        if straight:
            sub.append(("L", (float(B[0]), float(B[1]))))
        else:
            pts_i = np.vstack([A[None], Q, B[None]])
            chord = B - A
            cl = np.linalg.norm(chord)
            if cl > 1e-9:
                dev = np.abs((pts_i[:, 0] - A[0]) * chord[1] - (pts_i[:, 1] - A[1]) * chord[0]) / cl
            else:
                dev = np.linalg.norm(pts_i - A, axis=1)
            if dev.max() < lt:                                   # a straight side
                sub.append(("L", (float(B[0]), float(B[1]))))
            else:
                for bz in _fit(pts_i, d0, -d1, err2):
                    sub.append(("C", tuple(float(v) for v in (bz[1][0], bz[1][1], bz[2][0], bz[2][1], bz[3][0], bz[3][1]))))
        if cap[0] is not cap[1] and np.linalg.norm(cap[1] - cap[0]) > 1e-6:   # across a square stroke end
            sub.append(("L", (float(cap[1][0]), float(cap[1][1]))))
    if closed and len(sub) > 1 and sub[-1][0] == "L" and np.linalg.norm(np.subtract(sub[-1][1], sub[0][1])) < 1e-6:
        sub.pop()                                                # back at the start: Z closes it
    return sub


# --------------------------------------------------------------------------
# colour regions -> shapes

def _area(pts):
    p = np.asarray(pts)
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float((x * np.roll(y, -1) - np.roll(x, -1) * y).sum())


def _length(pts):
    p = np.asarray(pts)
    return float(np.linalg.norm(p - np.roll(p, 1, 0), axis=1).sum())


def is_blend(c, a, b, tol=40.0):
    """True when colour c lies between colours a and b, as their anti-aliased mix does."""
    c, a, b = (np.asarray(v, np.float64) for v in (c, a, b))
    seg = a - b
    t = float(np.dot(c - b, seg) / max(float(np.dot(seg, seg)), 1e-6))
    return 0.05 < t < 0.95 and float(np.linalg.norm(b + t * seg - c)) < tol


def _on_edge(lp, label, j, palette=None):
    """True when a small loop sits on the edge between two other colours (a speck left by
    their anti-aliasing), not inside one colour like a dot or a hole: look just outside it.
    With the palette, only when its colour is their mix: a small patch of a colour of its own
    between two others (sky in the notch of a letter) is kept."""
    ring = np.asarray(Polygon(lp).buffer(1.5, quad_segs=2).exterior.coords)
    H, W = label.shape
    xs = np.clip(ring[:, 0].astype(int), 0, W - 1); ys = np.clip(ring[:, 1].astype(int), 0, H - 1)
    around = label[ys, xs]
    others = around[around != j]
    if len(others) < 0.5 * len(around):
        return False
    cnt = np.bincount(others)
    order = np.argsort(-cnt)
    if len(order) < 2 or cnt[order[1]] < 0.2 * len(around):
        return False
    a, b = int(order[0]), int(order[1])
    if palette is None or j >= len(palette) or a >= len(palette) or b >= len(palette):
        return True
    return is_blend(palette[j], palette[a], palette[b])


def _up(a: np.ndarray, f: int) -> np.ndarray:
    """A share map enlarged f times with a smooth (bicubic) interpolation."""
    if f == 1:
        return a
    H, W = a.shape
    return np.asarray(Image.fromarray(np.ascontiguousarray(a, np.float32), "F").resize((W * f, H * f), Image.BICUBIC))


def supersample(H: int, W: int, n: int) -> int:
    """How many times larger than the image the outlines are traced: dense sub-pixel points for
    small images, about 4 million cells at most (but always at least twice the image size)."""
    return int(max(2, min(8, math.floor(math.sqrt(4_000_000 / max(1, H * W))))))


def trace_colors(S: np.ndarray, transparent: np.ndarray, skip: set, opts: dict):
    """Shapes for every colour index not in `skip`: [(index, [subpaths])], outer outline first
    and its holes after it (even-odd). S is (N, H, W) colour shares."""
    smooth = float(opts.get("smoothing", 50))
    detail = float(opts.get("detail", 50))
    corner = float(opts.get("corner_threshold", 60))
    # blur only when asked for more smoothing (it softens 1-2 px strokes): none at the default 50
    S = _blur(np.concatenate([S, transparent[None]]), max(0.0, smooth - 50) / 50 * 0.9)
    n = len(S) - 1
    H, W = S.shape[1:]
    label = S.argmax(0)                                     # the strongest colour in every pixel
    # how smooth the outlines are: a small image keeps every pixel's worth of detail; a bigger
    # one is drawn with smoother edges and straighter lines, as its wobbles of a pixel are noise
    # (resizing, compression), not shape. The Smoothing slider (50 = this) scales it all
    big = min(1.0, max(0.0, (max(H, W) - 128) / 400))
    k = 0.5 + 0.5 * smooth / 50
    err = float(opts["fit_tolerance"]) if opts.get("fit_tolerance") else (0.2 + 0.2 * big) * k   # px a curve may stray
    edge_smooth = float(opts["edge_smooth"]) if opts.get("edge_smooth") else (0.6 + 0.8 * big) * k
    line_tol = float(opts["line_tol"]) if opts.get("line_tol") else (0.3 + 0.3 * big) * k
    # specks smaller than this are dropped; compression noise leaves more of them, so a noisy
    # (JPEG) image drops larger ones while a clean image keeps small dots and letter parts
    min_area = (1.5 + (100 - detail) / 100 * 2.5) ** 2 * (1 + 0.6 * float(opts.get("_noise", 0.0)))

    def keep(lp, j):
        a = abs(_area(lp))
        if a < min_area:                                    # a speck
            return False
        if a / max(1e-6, _length(lp)) <= float(opts.get("sliver", 0.45)):   # a hairline sliver along another colour's edge
            return False
        return a >= 40 or not _on_edge(lp, label, j, opts.get("_palette"))   # a speck between two other colours

    def field(j):
        return S[j] - np.delete(S, j, axis=0).max(0)        # > 0 where j is the strongest colour

    # first pass: the specks each colour would leave. Their area is handed to the colours around
    # them (that colour's share there is cleared), so dropping one never leaves a gap
    gone = np.zeros((n, H, W), bool)
    for j in range(n):
        if j in skip:
            continue
        drop = [lp for lp in contours(field(j)) if _area(lp) < 0 and not keep(lp, j)]   # outlines (holes fill themselves)
        if drop:
            im = Image.new("L", (W, H), 0)
            dr = ImageDraw.Draw(im)
            for lp in drop:
                dr.polygon([(x - 0.5, y - 0.5) for x, y in lp], fill=255, outline=255)
            gone[j] = np.asarray(im) > 0
    if gone.any():
        gone = _dilate(gone, 1)
        S = S.copy()
        S[:n][gone] = 0
        label = S.argmax(0)

    # the outlines are traced on the shares enlarged f times, so they follow the edges between
    # pixels closely and small shapes get enough points to find their corners
    # thin strokes: anti-aliasing spreads a stroke under a pixel wide over its neighbours, so its
    # colour may never be the strongest anywhere. Undoing some of that blur (an unsharp mask on the
    # shares) lifts it back above its surroundings; a plain edge's halfway line does not move
    sharpen = float(opts.get("sharpen", 0.5))
    if sharpen > 0:
        sw = float(opts.get("sharpen_width", 0.7))
        Sb = _blur(S, sw) if sw > 0.75 else _b121(_b121(S, -1), -2)
        S = S + sharpen * (S - Sb)
    # transparency wins only where a pixel is at least half transparent: in an opaque pixel whose
    # colours were all cleared above (specks handed on), its sliver of share would punch a hole
    S[n] = np.where(S[n] >= 0.5, S[n], S[n] - 1.0)
    f = supersample(H, W, n + 1)
    top1 = np.full((H * f, W * f), -np.inf, np.float32)
    top2 = top1.copy()
    lab = np.zeros(top1.shape, np.int16)
    for j in range(n + 1):
        u = _up(S[j], f)
        better = u > top1
        top2 = np.where(better, top1, np.maximum(top2, u))
        top1 = np.where(better, u, top1)
        lab[better] = j


    if opts.get("shared_edges", True):
        # one fitted line for every boundary between two colours, shared by both shapes
        import planar
        if opts.get("clean_labels", True):
            lab = planar.clean_labels(lab, min_area * f * f, set())
        if opts.get("_palette") is not None and opts.get("drop_slivers", True):
            lab = planar.drop_slivers(lab, f, opts["_palette"])
        return planar.trace(lab, f, n, skip, err, corner, min_area, edge_smooth, line_tol,
                            float(opts.get("jmove", 1.2)), float(opts.get("jtrim", 1.0)),
                            reach=float(opts.get("reach", 4.0)), arm_px=float(opts.get("corner_arm", 2.0)),
                            far=float(opts.get("corner_far", 0.0)), seams_out=opts.get("_seams"),
                            small_lines=float(opts.get("small_lines", 1.6)))

    out = []
    for j in range(n):
        if j in skip:
            continue
        u = _up(S[j], f)
        F = u - np.where(lab == j, top2, top1)
        del u
        if (F > 0).sum() < min_area * f * f:
            continue
        loops = [[(x / f, y / f) for x, y in lp] for lp in contours(F)]
        loops = [lp for lp in loops if keep(lp, j)]
        if not loops:
            continue
        polys = [Polygon(lp) for lp in loops]
        prepared = [prep(p if p.is_valid else p.buffer(0)) for p in polys]
        areas = [abs(p.area) for p in polys]
        # nesting: a loop inside an even number of loops is an outline, odd is a hole
        container = []
        depth = []
        for i, lp in enumerate(loops):
            pt = Point(lp[0])
            inside = [m for m in range(len(loops)) if m != i and areas[m] > areas[i] and prepared[m].contains(pt)]
            depth.append(len(inside))
            container.append(min(inside, key=lambda m: areas[m]) if inside else -1)
        fitted = {}
        for i in range(len(loops)):
            if depth[i] % 2 == 0:
                subs = [fit_loop(loops[i], err, corner, f)]
                for h in range(len(loops)):
                    if container[h] == i and depth[h] % 2 == 1:
                        subs.append(fit_loop(loops[h], err, corner, f))
                fitted[i] = subs
        for i in sorted(fitted, key=lambda i: -areas[i]):
            out.append((j, fitted[i]))
    return out
