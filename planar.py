"""Planar map: every boundary between two colours traced and fitted once, shared by both shapes.

The label image (strongest colour in every cell of the supersampled grid) is cut along the cracks
between cells of different colours. The cracks form a network: junctions where three or more
colours meet (or where two touch only at a corner), joined by edges with one colour on each side,
plus closed loops with no junction at all. Each edge is smoothed and fitted with lines and curves
once; each colour's outlines are then put together from the fitted edges around it, so
neighbouring shapes meet exactly, with no gap or overlap, and corners at junctions stay put.
"""

from __future__ import annotations

from collections import defaultdict

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon
from shapely.prepared import prep

import precise


def clean_labels(lab: np.ndarray, min_cells: float, keep: set) -> np.ndarray:
    """Hand every patch smaller than min_cells (4-connected) to the colours around it: each of its
    cells takes the colour of the nearest cell outside any such patch."""
    small = np.zeros(lab.shape, bool)
    for j in np.unique(lab):
        if int(j) in keep:
            continue
        comp, k = ndimage.label(lab == j)
        if k == 0:
            continue
        sizes = np.bincount(comp.ravel())
        tiny = sizes < min_cells
        tiny[0] = False
        if tiny.any():
            small |= tiny[comp]
    if not small.any() or small.all():
        return lab
    iy, ix = ndimage.distance_transform_edt(small, return_distances=False, return_indices=True)
    out = lab.copy()
    out[small] = lab[iy[small], ix[small]]
    return out


def drop_slivers(lab: np.ndarray, f: int, palette: np.ndarray, width: float = 1.2) -> np.ndarray:
    """Hand on thin strips (narrower than `width` px) of a colour that is only the blend of the
    two colours either side of it: where dark green meets a light background, the anti-aliased
    edge pixels match a light green of the palette and would trace as a hairline of it. A thin
    strip of a colour that is not their blend (a black outline's tip, thin lettering) stays."""
    r = max(1, int(round(width / 2 * f)))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    disk = xx * xx + yy * yy <= r * r
    n = len(palette)
    drop = np.zeros(lab.shape, bool)
    for j in np.unique(lab):
        j = int(j)
        if j >= n:
            continue
        m = lab == j
        thin = m & ~ndimage.binary_opening(m, disk)
        if not thin.any():
            continue
        comp, k = ndimage.label(thin, np.ones((3, 3)))
        sizes = np.bincount(comp.ravel())
        objs = ndimage.find_objects(comp)
        for c in range(1, k + 1):
            if sizes[c] < (f * f):                 # a corner's tip: under a pixel in all
                continue
            sl = objs[c - 1]
            y0, y1 = max(0, sl[0].start - 2), min(lab.shape[0], sl[0].stop + 2)
            x0, x1 = max(0, sl[1].start - 2), min(lab.shape[1], sl[1].stop + 2)
            cm = comp[y0:y1, x0:x1] == c
            ring = ndimage.binary_dilation(cm, iterations=2) & ~m[y0:y1, x0:x1]
            nb = lab[y0:y1, x0:x1][ring]
            nb = nb[nb < n]
            if len(nb) < 2:
                continue
            cnt = np.bincount(nb, minlength=n)
            a, b = np.argsort(-cnt)[:2]
            if cnt[b] < 0.2 * cnt[a]:              # one colour around it: a stroke on it, keep
                continue
            if precise.is_blend(palette[j], palette[a], palette[b]):
                drop[y0:y1, x0:x1] |= cm
    if not drop.any():
        return lab
    iy, ix = ndimage.distance_transform_edt(drop, return_distances=False, return_indices=True)
    out = lab.copy()
    out[drop] = lab[iy[drop], ix[drop]]
    return out


def _smooth_open(P, passes):
    """[1 2 1] smoothing along a run with its two ends held."""
    if len(P) < 3 or passes <= 0:
        return P
    P = P.copy()
    for _ in range(passes):
        P[1:-1] = (P[:-2] + 2 * P[1:-1] + P[2:]) / 4
    return P


def _smooth_closed(P, passes):
    for _ in range(passes):
        P = (np.roll(P, 1, 0) + 2 * P + np.roll(P, -1, 0)) / 4
    return P


def _reverse(sub):
    """The same subpath run backwards (open: no closing)."""
    pts = [sub[0][1]]
    for op, v in sub[1:]:
        pts.append(tuple(v[-2:]))
    out = [("M", pts[-1])]
    for i in range(len(sub) - 1, 0, -1):
        op, v = sub[i]
        prev = pts[i - 1]
        out.append(("L", prev) if op == "L" else ("C", tuple(v[2:4]) + tuple(v[0:2]) + tuple(prev)))
    return out


def trace(lab: np.ndarray, f: int, n: int, skip: set, err: float, corner: float, min_area: float,
          smooth_px: float = 0.6, line_tol=None, jmove: float = 2.0, jtrim: float = 1.6, reach: float = 2.5,
          arm_px: float = 2.0, far: float = 0.0, seams_out: list | None = None, small_lines: float = -1.0):
    """Shapes for every colour 0..n-1 not in skip from the supersampled label image lab
    (label n = transparent): [(colour, [subpaths])], each outline followed by its holes.
    Coordinates are original pixels (the grid is f cells per pixel)."""
    Hh, Wh = lab.shape
    Lp = np.full((Hh + 2, Wh + 2), -1, np.int32)
    Lp[1:-1, 1:-1] = lab
    W1 = Wh + 1
    # cracks: horizontal at lattice row r (0..Hh) between the cells above and below, from column c
    # to c + 1; vertical at lattice column c (0..Wh) between the cells left and right, row r to r + 1
    hm = Lp[:-1, 1:-1] != Lp[1:, 1:-1]                       # (Hh + 1, Wh)
    vm = Lp[1:-1, :-1] != Lp[1:-1, 1:]                       # (Hh, Wh + 1)
    hr, hc = np.nonzero(hm)
    vr, vc = np.nonzero(vm)
    a = np.concatenate([hr * W1 + hc, vr * W1 + vc])
    b = np.concatenate([hr * W1 + hc + 1, (vr + 1) * W1 + vc])
    nh = len(hr)
    ncr = len(a)
    if ncr == 0:
        return []
    deg = np.bincount(np.concatenate([a, b]), minlength=(Hh + 1) * W1)
    # the colour on each side of a crack, as walked from a to b: "left" is the cell at (-dy, dx)
    # from the crack's middle (below a crack walked to +x, left of one walked to +y)
    side_ab = np.concatenate([Lp[hr + 1, hc + 1], Lp[vr + 1, vc]])      # walked a -> b
    side_ba = np.concatenate([Lp[hr, hc + 1], Lp[vr + 1, vc + 1]])      # walked b -> a

    inc = defaultdict(list)
    al, bl = a.tolist(), b.tolist()
    for k in range(ncr):
        inc[al[k]].append(k); inc[bl[k]].append(k)
    used = np.zeros(ncr, bool)

    # saddles: two cells of one colour touching only at a corner, the other colour in the other
    # two. Not a junction: the colour with fewer cells (usually a thin stroke) runs on through it
    partner = {}
    sr, sc = np.nonzero(deg.reshape(Hh + 1, W1) == 4)
    if len(sr):
        TL, TR, BL, BR = Lp[sr, sc], Lp[sr, sc + 1], Lp[sr + 1, sc], Lp[sr + 1, sc + 1]
        sad = (TL == BR) & (TR == BL) & (TL != TR)
        if sad.any():
            hid = np.full(hm.shape, -1, np.int64); hid[hr, hc] = np.arange(nh)
            vid = np.full(vm.shape, -1, np.int64); vid[vr, vc] = nh + np.arange(len(vr))
            cnt = np.bincount(lab.ravel() + 1, minlength=n + 3)
            for r, c, x, y in zip(sr[sad].tolist(), sc[sad].tolist(), TL[sad].tolist(), TR[sad].tolist()):
                up, down, left, right = vid[r - 1, c], vid[r, c], hid[r, c - 1], hid[r, c]
                v = r * W1 + c
                if cnt[x + 1] <= cnt[y + 1]:          # TL-BR colour runs through
                    pairs = ((up, right), (left, down))
                else:
                    pairs = ((up, left), (right, down))
                for p, q in pairs:
                    partner[(v, int(p))] = int(q); partner[(v, int(q))] = int(p)
                deg[v] = 2
    degl = deg.tolist()

    def walk(v0, k0):
        """Follow cracks from vertex v0 along crack k0 until a junction (or round to k0 again)."""
        verts = [v0]
        k, v = k0, v0
        first_fwd = al[k0] == v0
        while True:
            used[k] = True
            v = bl[k] if al[k] == v else al[k]
            verts.append(v)
            if degl[v] != 2:
                break
            if (v, k) in partner:
                k = partner[(v, k)]
            else:
                k1, k2 = inc[v]
                k = k2 if k1 == k else k1
            if k == k0 or used[k]:
                break
        side = int(side_ab[k0] if first_fwd else side_ba[k0])
        other = int(side_ba[k0] if first_fwd else side_ab[k0])
        return verts, side, other

    edges = []          # (vertex ids, colour on the left, colour on the right, closed)
    for v in np.nonzero(deg > 2)[0].tolist():
        for k in inc[v]:
            if not used[k]:
                verts, s1, s2 = walk(v, k)
                edges.append((verts, s1, s2, False))
    for k in range(ncr):
        if not used[k]:
            verts, s1, s2 = walk(al[k], k)
            edges.append((verts, s1, s2, True))

    # every edge smoothed, in original pixel coordinates
    passes = max(1, int(round(2 * (smooth_px * f) ** 2)))   # Gaussian of smooth_px: removes the 1/f steps and jitter
    light = max(1, int(round(2 * (0.6 * f) ** 2)))           # 0.6 px: where corners are looked for
    runs, lights, raws, scales = [], [], [], []
    for verts, s1, s2, closed in edges:
        vv = np.asarray(verts)
        P = np.stack([vv % W1, vv // W1], 1).astype(np.float64) / f
        sm = _smooth_closed if closed else _smooth_open
        P = P[:-1] if closed else P
        raws.append(P)
        Pl = sm(P, min(light, passes))
        lights.append(Pl)
        ps, q = passes, 1.0
        if closed:
            # a small shape (a letter of small print) keeps its detail: smoothing, and how far the
            # fit may stray, grow with its size, the full amount from about 50 px across
            diag = float(np.linalg.norm(P.max(0) - P.min(0)))
            eff = min(smooth_px, max(0.6, diag / 40))
            q = eff / max(smooth_px, 1e-6)
            ps = min(passes, max(light, int(round(2 * (eff * f) ** 2))))
        scales.append(q)
        runs.append(sm(Pl, ps - min(light, ps)) if ps > light else Pl)

    # junctions: the colours blur together over a pixel or two where three meet, so each junction
    # is moved to where its edges, followed straight on from outside that blur, meet best
    ends = defaultdict(list)                     # junction -> [(point, direction into it)]
    for (verts, _, _, closed), P in zip(edges, runs):
        if closed or len(P) < 4:
            continue
        L = np.linalg.norm(np.diff(P, axis=0), axis=1)
        cl = np.concatenate([[0], np.cumsum(L)])
        if cl[-1] < 3.0:
            continue
        for v, Q in ((verts[0], P[(cl > 1.5) & (cl < 3.5)][::-1]), (verts[-1], P[(cl > cl[-1] - 3.5) & (cl < cl[-1] - 1.5)])):
            if len(Q) >= 2:
                ends[v].append((Q[-1], precise._direction(Q)))
    Wo, Ho = Wh / f, Hh / f
    jpos = {}
    for v, lst in ends.items():
        raw = np.array([v % W1, v // W1], np.float64) / f
        if len(lst) < 2:
            continue
        A = np.zeros((2, 2)); b = np.zeros(2)
        for q, d in lst:
            M = np.eye(2) - np.outer(d, d)
            A += M; b += M @ q
        if np.linalg.eigvalsh(A)[0] < 0.25:      # all the edges run the same way: nothing to meet
            continue
        x = np.linalg.solve(A, b)
        if np.linalg.norm(x - raw) > jmove:
            continue
        for k, lim in ((0, Wo), (1, Ho)):        # junctions on the image border stay on it
            if raw[k] <= 0 or raw[k] >= lim:
                x[k] = raw[k]
        jpos[v] = x

    # T-junctions: where a colour border ends on an outline (the sky's edge behind a letter), two of
    # the three edges carry straight on through the junction. They are one line that happens to
    # change neighbour there, so they are smoothed as one and the junction sits on that line:
    # the outline keeps no kink where the background changes behind it
    at = defaultdict(list)                        # junction -> [(edge, ends at start?)]
    for e, (verts, _, _, closed) in enumerate(edges):
        if not closed:
            at[verts[0]].append((e, True)); at[verts[-1]].append((e, False))
    win = max(4, int(round(4 * smooth_px * f)))
    for v, lst in at.items():
        if len(lst) != 3:
            continue
        raw = np.array([v % W1, v // W1], np.float64) / f
        if raw[0] <= 0 or raw[1] <= 0 or raw[0] >= Wo or raw[1] >= Ho:
            continue
        outs = []                                 # each edge oriented away from the junction
        for e, start in lst:
            P = raws[e] if start else raws[e][::-1]
            if len(P) < 3 * f:
                outs.append(None); continue
            k = min(len(P) - 1, int(3 * f))
            outs.append(precise._unit(P[k] - P[0]))
        best, pair = -0.85, None                  # straighter than about 150 degrees
        for i in range(3):
            for j in range(i + 1, 3):
                if outs[i] is not None and outs[j] is not None and float(np.dot(outs[i], outs[j])) < best:
                    best, pair = float(np.dot(outs[i], outs[j])), (i, j)
        if pair is None:
            continue
        (e1, s1_), (e2, s2_) = lst[pair[0]], lst[pair[1]]
        if e1 == e2:
            continue
        A = raws[e1][::-1] if s1_ else raws[e1]   # runs into the junction
        B = raws[e2] if s2_ else raws[e2][::-1]   # runs out of it
        C = np.vstack([A, B[1:]])
        iv = len(A) - 1
        Cl = _smooth_open(C, min(light, passes))
        Cs = _smooth_open(Cl, passes - min(light, passes)) if passes > light else Cl
        w1 = min(win, iv); w2 = min(win, len(C) - 1 - iv)
        for e, start, seg_s, seg_l in ((e1, s1_, Cs[iv - w1:iv + 1], Cl[iv - w1:iv + 1]),
                                       (e2, s2_, Cs[iv:iv + w2 + 1][::-1], Cl[iv:iv + w2 + 1][::-1])):
            # seg runs towards the junction; write it over that end of the edge
            if start:
                runs[e][:len(seg_s)] = seg_s[::-1]; lights[e][:len(seg_l)] = seg_l[::-1]
            else:
                runs[e][-len(seg_s):] = seg_s; lights[e][-len(seg_l):] = seg_l
        jpos[v] = Cs[iv].copy()

    # fit every edge once; smoothing rounds corners off over about 1.5 sigma, left out of the sides
    ct = max(0.9, 1.5 * smooth_px)
    arm = arm_px
    fitted = []
    for (verts, s1, s2, closed), P, Pl, q in zip(edges, runs, lights, scales):
        if closed:
            e_l = max(0.2, err * q)
            lt_l = None if line_tol is None else max(0.3, line_tol * (q if small_lines < 0 else small_lines))
            sub = precise.fit_chain(P, True, e_l, corner, line_tol=lt_l, corner_trim=max(0.9, ct * q), arm=arm, detect=Pl,
                                    reach=reach, far=far)
        else:
            P, Pl = P.copy(), Pl.copy()
            for k, v in ((0, verts[0]), (-1, verts[-1])):
                if v in jpos:
                    P[k] = Pl[k] = jpos[v]
            sub = precise.fit_chain(P, False, err, corner, end_trim=jtrim, line_tol=line_tol,
                                       corner_trim=ct, arm=arm, detect=Pl, reach=reach, far=far)
        fitted.append(sub)

    # the fitted edges between two drawn colours, for a gap filler that lies exactly on them
    if seams_out is not None:
        for (verts, s1, s2, closed), sub in zip(edges, fitted):
            if 0 <= s1 < n and 0 <= s2 < n and s1 not in skip and s2 not in skip:
                seams_out.append((sub, s1, s2, closed))

    # each colour's outlines from the edges around it, walked with the colour on the left
    by_color = defaultdict(list)
    for e, (verts, s1, s2, closed) in enumerate(edges):
        for col, fwd in ((s1, True), (s2, False)):
            if 0 <= col < n and col not in skip:
                by_color[col].append((e, fwd))
    out = []
    for col, lst in by_color.items():
        rings = []
        starts = defaultdict(list)
        for e, fwd in lst:
            verts, _, _, closed = edges[e]
            if closed:
                sub = fitted[e] if fwd else _reverse(fitted[e])
                rings.append(sub)
            else:
                starts[verts[0] if fwd else verts[-1]].append((e, fwd))
        done = set()
        for e0, f0 in [x for v in starts.values() for x in v]:
            if (e0, f0) in done:
                continue
            first = edges[e0][0][0] if f0 else edges[e0][0][-1]
            ring = []
            e, fw = e0, f0
            while (e, fw) not in done:
                done.add((e, fw))
                sub = fitted[e] if fw else _reverse(fitted[e])
                ring.extend(sub if not ring else sub[1:])
                end = edges[e][0][-1] if fw else edges[e][0][0]
                if end == first:
                    break
                nxt = [x for x in starts.get(end, []) if x not in done]
                if not nxt:
                    break
                e, fw = nxt[0]
            rings.append(ring)
        # outlines turn one way and holes the other; each hole goes in the smallest outline round it
        outer, holes = [], []
        for r in rings:
            pts = precise_points(r)
            if len(pts) < 3:
                continue
            ar = precise._area(pts)
            if abs(ar) < 1e-3:                    # specks went with the labels: dropping one here would leave a hole
                continue
            (outer if ar > 0 else holes).append((r, pts, abs(ar)))
        shells = []
        for r, pts, ar in outer:
            poly = Polygon(pts)
            shells.append((r, ar, prep(poly if poly.is_valid else poly.buffer(0)), [r]))
        for r, pts, ar in holes:
            hp = Polygon(pts)
            hp = hp if hp.is_valid else hp.buffer(0)
            if hp.is_empty:
                continue
            pt = hp.representative_point()
            best = None
            for s in shells:
                if s[1] > ar and s[2].contains(pt) and (best is None or s[1] < best[1]):
                    best = s
            if best is not None:
                best[3].append(r)
        for r, ar, _, subs in sorted(shells, key=lambda s: -s[1]):
            out.append((col, subs))
    return out


def precise_points(sub):
    """The corner and end points of a subpath, with a few points along each curve."""
    pts = [sub[0][1]]
    for op, v in sub[1:]:
        if op == "L":
            pts.append(tuple(v))
        else:
            x0, y0 = pts[-1]
            x1, y1, x2, y2, x3, y3 = v
            for t in (0.25, 0.5, 0.75, 1.0):
                u = 1 - t
                pts.append((u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                            u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
    return pts
