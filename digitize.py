"""Cap embroidery: auto-digitize a traced logo into stitches and write a Tajima .DST file.

Flat embroidery for the front panel of a cap. The logo's colour regions (patch.Analysis)
are scaled to the chosen size in millimetres and stitched one colour at a time:

  - underlay first, to hold the cap's thick fabric: an edge run just inside each part,
    then a light tatami across the top stitches (wide parts) or a sparse zigzag (narrow);
  - narrow parts (lines, letters) get satin: stitches straight across, at the angle that
    keeps them shortest, never longer than SATIN_MAX (long satin goes loose on a curve);
  - every other part gets tatami fill: vertical stitches up to FILL_LEN, staggered;
  - the top stitches are widened by the pull compensation, so colours overlap and no
    fabric shows between them.

Cap sequencing: inside each colour the parts go from the centre outwards (right and
left) and from the bottom up; a fill is split at the centre line and each half is swept
from the centre outwards, each row sewn upwards first. Moves between parts run along the
edge or straight across inside the colour when they can; otherwise the thread is
trimmed and the frame jumps.

Options for caps (Gunold's and Madeira's cap advice):
  - tack-down underlay: a light grid over the whole design, sewn first, to hold a stiff or
    slippery cap to its backing;
  - fewer stitches: sparser underlay and fill, for thick caps ("less is more");
  - crown height: the design should leave about 1/2 in clear at the top and bottom;
  - tilt: side logos are turned 10-15 degrees to counter the slope of the cap's side;
  - 3D puff (as Wilcom's 3D WTS cap file): the puff colours are sewn last; a centre run down
    each stroke holds the cap, the machine stops for the foam, then each stroke is one dense
    satin (0.15 mm) that follows it, up to 12 mm across, with no underlay; straight strokes
    are sewn level or upright, as lettering is.

DST (Tajima): 0.1 mm units, y up, 3-byte records; a trim is written as three jumps.
"""

from __future__ import annotations

import math
import re

import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon, box
from shapely.ops import nearest_points, substring, unary_union

import engine

STITCH, JUMP, TRIM, COLOR, END = 0, 1, 2, 3, 4

DEFAULTS = {
    "width_mm": 114.3,       # the box the logo is fitted into (4.5 x 2.25 in: a cap's front panel)
    "height_mm": 57.15,
    "density": 0.4,          # mm between rows of top stitches
    "pull_comp": 0.2,        # mm the top stitches are widened by
    "colors": None,          # [{"id": region id, "hex": thread colour, "skip": bool}] in sewing order
    "name": "cap",
    "origin": "center",      # where the machine starts and ends: "center" of the design, or "bottom" centre
    "order": "center",       # where the sewing begins: "center" (centre out, the cap rule) or "bottom" (bottom up, centre out)
    "tackdown": False,       # a light grid under the whole design, sewn first (stiff or slippery caps)
    "light": False,          # fewer stitches: sparser underlay and fill
    "crown_mm": None,        # the cap's crown height: the design keeps 1/2 in clear at top and bottom
    "tilt": 0.0,             # degrees, counter-clockwise: side logos are turned 10-15 degrees
    "kind": "flat",          # "flat" or "puff"
    "puff": None,            # with "puff": the region ids sewn as 3D puff (None: every colour)
}
SATIN_MAX = 5.0      # mm: the longest satin stitch on a cap
FILL_LEN = 3.5       # mm: tatami stitch length
RUN_LEN = 2.0        # mm: running stitches (edge underlay, travel)
UNDER_ROW = 2.0      # mm between tatami underlay rows
UNDER_LEN = 3.0
EDGE_INSET = 0.4     # mm: the edge run sits this far inside
MIN_STITCH = 0.3     # mm: shorter stitches are dropped
HOP = 3.0            # mm: the longest travel allowed over finished stitches, rather than a trim
SEAM_OFF = 2.0       # mm: the first stitches of a part on the centre line start this far beside it
MIN_PART = 0.5       # mm2: smaller bits are not sewn
THIN = 0.8           # mm: narrower parts are hard to sew; they are counted in the notes
TACK_ROW = 3.0       # mm between the rows of the tack-down underlay
TACK_LEN = 4.0
TACK_INSET = 0.8     # mm: the tack-down stays this far inside the design, under the top stitches
PUFF_DENSITY = 0.15  # mm between puff satin stitches on each side (Wilcom's 3D WTS cap file: 0.15)
PUFF_MAX = 12.0      # mm: the longest puff satin stitch (that file: up to 11.5 mm); wider parts are sewn flat
END_CAP = 1.2        # mm: how deep the end caps of a puff column reach in
SPLIT_MAX = 12.0     # mm: strokes wider than SATIN_MAX, up to this, are split satin (each long
                     # stitch split, the splits staggered, like Wilcom's auto split); wider: fill
SPLIT_LEN = 4.0      # mm: the longest stitch of a split satin
JUMP_STEP = 63       # 0.1 mm: the longest jump record written, as Wilcom (moves go in equal steps)


# ---------------------------------------------------------------------------
# geometry

def _parts(geom):
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    out = []
    for g in getattr(geom, "geoms", []):
        out += _parts(g)
    return out


def _width(p: Polygon) -> float:
    """About how wide a part is: 2 x area / perimeter (a strip's width, a disc's radius)."""
    return 2 * p.area / max(p.length, 1e-9)


def _scan(poly, angle, spacing):
    """Rows of segments across `poly`: stitches run at `angle` (degrees, 0 = along x), rows
    `spacing` apart. In the turned frame (u along the stitches, v across): [(v, [(u0, u1)])]."""
    rot = affinity.rotate(poly, -angle, origin=(0, 0))
    x0, y0, x1, y1 = rot.bounds
    n = max(1, int((y1 - y0) / spacing))
    vs = y0 + ((y1 - y0) - (n - 1) * spacing) / 2 + spacing * np.arange(n)
    lines = shapely.linestrings([[[x0 - 1, v], [x1 + 1, v]] for v in vs])
    out = []
    for v, g in zip(vs, shapely.intersection(lines, rot)):
        segs = []
        for part in getattr(g, "geoms", [g]):
            if part.is_empty or part.geom_type != "LineString":
                continue
            xs = [c[0] for c in part.coords]
            if max(xs) - min(xs) > 0.05:
                segs.append((min(xs), max(xs)))
        out.append((float(v), sorted(segs)))
    return out


def _cells(rows):
    """Split the rows into cells that can each be sewn back and forth without a break: a
    cell ends where the shape splits (around a hole, into two arms) or two parts join.
    rows in sewing order. Each cell: [(row index, v, u0, u1)]."""
    cells, prev = [], []           # prev: (u0, u1, cell index) of the row before
    for r, (v, segs) in enumerate(rows):
        cur = []
        for u0, u1 in segs:
            over = [p for p in prev if p[0] < u1 and p[1] > u0]
            k = None
            if len(over) == 1:
                p0 = over[0]
                if sum(1 for a, b in segs if a < p0[1] and b > p0[0]) == 1:
                    k = p0[2]
            if k is None:
                k = len(cells); cells.append([])
            cells[k].append((r, v, u0, u1))
            cur.append((u0, u1, k))
        prev = cur
    return cells


def _order_cells(cells, start):
    """Cells in a sewing order: each next one the nearest to where the last ended, among
    those whose first row comes soonest. Returns [(cell, starts at the low end)]."""
    left, out, at = list(range(len(cells))), [], start
    while left:
        first = min(cells[i][0][0] for i in left)
        pool = [i for i in left if cells[i][0][0] <= first + 6] or left

        def cost(i):
            r, v, u0, u1 = cells[i][0]
            return min((math.dist(at, (u0, v)), True), (math.dist(at, (u1, v)), False))
        i = min(pool, key=lambda i: cost(i)[0])
        low = cost(i)[1]
        out.append((cells[i], low))
        left.remove(i)
        r, v, u0, u1 = cells[i][-1]
        at = (u0, v) if (low if len(cells[i]) % 2 == 0 else not low) else (u1, v)
    return out


def _turn(pts, angle):
    a = math.radians(angle)
    c, s = math.cos(a), math.sin(a)
    return [(u * c - v * s, u * s + v * c) for u, v in pts]


def _split(a, b, length, phase):
    """Points from a to b (along u), stitches about `length` long, on a grid shifted by
    `phase` (tatami: neighbouring rows are staggered so the needle holes do not line up)."""
    if abs(b - a) <= length * 1.15:
        return [a, b]
    step = length if b > a else -length
    k0 = math.floor((a - phase) / length) + (1 if b > a else 0)
    out, u = [a], phase + k0 * length
    while (b - u) * (1 if b > a else -1) > MIN_STITCH:
        if abs(u - out[-1]) > MIN_STITCH:
            out.append(u)
        u += step
    out.append(b)
    return out


# ---------------------------------------------------------------------------
# stitch types (each returns runs: lists of (x, y) in mm, sewn in order; between runs the
# needle travels)

def _rows_order(rows, angle, toward):
    """Rows in the order that starts nearest `toward` (a point, design coordinates)."""
    if len(rows) > 1:
        first = _turn([(0, rows[0][0])], angle)[0]
        last = _turn([(0, rows[-1][0])], angle)[0]
        # distance across the rows only: the v direction turned back is (-sin, cos)
        a = math.radians(angle)
        nx, ny = -math.sin(a), math.cos(a)
        d0 = abs((first[0] - toward[0]) * nx + (first[1] - toward[1]) * ny)
        d1 = abs((last[0] - toward[0]) * nx + (last[1] - toward[1]) * ny)
        if d1 < d0:
            rows = rows[::-1]
    return rows


def _start(rows, angle, toward, up):
    """Where in the turned frame the first row starts: its low or high end."""
    if not rows or not rows[0][1]:
        return (0.0, 0.0)
    v, segs = rows[0]
    return ((segs[0][0] if up else segs[-1][1]), v)


def _cell_area(cell, spacing, angle):
    """The area a cell's stitches cover, in design coordinates."""
    ring = [(u0, v) for _, v, u0, _ in cell] + [(u1, v) for _, v, _, u1 in reversed(cell)]
    if len(cell) == 1:
        _, v, u0, u1 = cell[0]
        ring = [(u0, v - spacing / 2), (u1, v - spacing / 2), (u1, v + spacing / 2), (u0, v + spacing / 2)]
    g = shapely.make_valid(Polygon(_turn(ring, angle))).buffer(spacing / 2)
    return g


def tatami(poly, angle, spacing, length, toward):
    """Tatami fill: [(points, area they cover)], cell by cell."""
    rows = _rows_order(_scan(poly, angle, spacing), angle, toward)
    up = math.sin(math.radians(angle)) >= -1e-9     # u grows upwards: the first row is sewn upwards
    inside = affinity.rotate(poly, -angle, origin=(0, 0)).buffer(0.05)
    runs = []
    for cell, low in _order_cells(_cells(rows), _start(rows, angle, toward, up)):
        pts, fwd = [], low
        for r, v, u0, u1 in cell:
            phase = (r % 3) * length / 3
            us = _split(u0, u1, length, phase) if fwd else _split(u1, u0, length, phase)
            if pts and not inside.covers(LineString([pts[-1], (us[0], v)])):
                # this row starts past the end of the last one (a T's bar onto its stem): the step
                # across would leave the shape, so go back along the last row first, or along this one
                a, b = pts[-1], (us[0], v)
                for mid in ((b[0], a[1]), (a[0], b[1])):
                    if inside.covers(LineString([a, mid, b])):
                        if mid[1] == a[1]:
                            pts += [(u, a[1]) for u in _split(a[0], mid[0], length, 0)[1:]]
                        else:
                            pts += [(u, v) for u in _split(mid[0], b[0], length, 0)[:-1]]
                        break
            pts += [(u, v) for u in us]
            fwd = not fwd
        runs.append((_turn(pts, angle), _cell_area(cell, spacing, angle)))
    return runs


def satin(poly, angle, spacing, toward):
    """Zigzag across the part: each stitch goes from one side to the other, `spacing` apart
    on each side."""
    rows = _rows_order(_scan(poly, angle, spacing / 2), angle, toward)
    runs = []
    for cell, low in _order_cells(_cells(rows), _start(rows, angle, toward, True)):
        if len(cell) == 1:
            r, v, u0, u1 = cell[0]
            pts = [(u0, v), (u1, v)] if low else [(u1, v), (u0, v)]
        else:
            pts = [((u0 if (i % 2 == 0) == low else u1), v) for i, (r, v, u0, u1) in enumerate(cell)]
        runs.append((_turn(pts, angle), _cell_area(cell, spacing / 2, angle)))
    return runs


def _run_along(line: LineString, length=RUN_LEN):
    n = max(1, math.ceil(line.length / length))
    return [line.interpolate(i / n, normalized=True).coords[0] for i in range(n + 1)]


def edge_run(poly, start):
    """A running stitch around the inside of each ring of the part, starting at the point
    of the outer ring nearest `start`."""
    runs = []
    inner = poly.buffer(-EDGE_INSET, join_style=2)
    for p in _parts(inner):
        if p.area < 1.0:
            continue
        for ring in [p.exterior] + list(p.interiors):
            d = ring.project(Point(start))
            L = ring.length
            line = LineString(list(substring(ring, d, L).coords) + list(substring(ring, 0, d).coords)[1:])
            runs.append((_run_along(line), None))
    return runs


def ring_satin(ring_poly, spacing, center_x):
    """Satin round a thin ring (a border, a circle, an O): stitches across from the outside edge
    to the inside, following the ring. Two halves, each from the bottom up to the top, the right
    one first; the centre is the design's centre line when the ring crosses it, else the ring's
    own. [(points, area they cover)]."""
    outer, inner = ring_poly.exterior, ring_poly.interiors[0]
    x0, y0, x1, y1 = ring_poly.bounds
    cx = center_x if x0 < center_x < x1 else (x0 + x1) / 2
    L = outer.length
    sb, st = outer.project(Point(cx, y0 - 1)), outer.project(Point(cx, y1 + 1))
    right = outer.interpolate((sb + 1.0) % L).x > outer.interpolate(sb).x   # forward along the ring goes right
    if cx == center_x:      # start just beside the centre seam; the left half crosses it once at speed
        sb = (sb + SEAM_OFF) % L if right else (sb - SEAM_OFF) % L
    mid = (L + inner.length) / 2
    step = spacing / 2 * L / mid                  # crossings `spacing` / 2 apart on the middle of the ring
    runs = []
    for fwd in (right, not right):
        a = (sb - spacing) % L if fwd else (sb + spacing) % L      # the halves overlap a little at both ends
        b = (st + spacing) % L if fwd else (st - spacing) % L
        span = (b - a) % L if fwd else (a - b) % L
        n = max(2, int(span / step))
        pts = []
        for k in range(n + 1):
            o_ = outer.interpolate((a + (span * k / n if fwd else -span * k / n)) % L)
            q = o_ if k % 2 == 0 else inner.interpolate(inner.project(o_))
            pts.append((q.x, q.y))
        half = ring_poly.intersection(box(cx, y0 - 1, x1 + 1, y1 + 1) if fwd == right else box(x0 - 1, y0 - 1, cx, y1 + 1))
        runs.append((pts, half))
    return runs


def _is_ring(p: Polygon, widest=SATIN_MAX) -> bool:
    """A thin ring a satin can follow: one hole, about even width, under `widest` wide, and nothing
    standing out of it (the ear of a g: an inside corner on its outside edge)."""
    if len(p.interiors) != 1:
        return False
    hole = Polygon(p.interiors[0])
    w = _width(p)
    return 0.5 <= w <= widest and hole.area > 0.15 * Polygon(p.exterior).area and not _reflex(Polygon(p.exterior), 35.0)


def _halves(g, center_x, lap):
    """g split at the centre line, right half first, so each is sewn from the centre outwards;
    the halves overlap by `lap`, so no seam shows."""
    x0, y0, x1, y1 = g.bounds
    if not x0 < center_x < x1:
        return [g]
    return [g.intersection(box(center_x - lap / 2, y0 - 1, x1 + 1, y1 + 1)),
            g.intersection(box(x0 - 1, y0 - 1, center_x + lap / 2, y1 + 1))]


def _nearest(runs, at):
    """Runs in the order that keeps each move short, each turned to start at its nearer end."""
    left, out = list(runs), []
    while left:
        k = min(range(len(left)), key=lambda i: min(math.dist(at, left[i][0][0]), math.dist(at, left[i][0][-1])))
        pts, area = left.pop(k)
        if math.dist(at, pts[-1]) < math.dist(at, pts[0]):
            pts = pts[::-1]
        out.append((pts, area))
        at = pts[-1]
    return out


def tack_down(area, center_x):
    """Tack-down underlay: a light tatami over the whole design, under every colour, rows
    TACK_ROW apart; each half from the centre line outwards, parts from the bottom up."""
    inner = area.buffer(-TACK_INSET, join_style=2)
    runs = []
    for half in _halves(inner, center_x, 0.2):
        parts = [p for p in _parts(half) if p.area > 25]      # not worth it on small bits: each costs a trim
        for i in cap_order(parts):
            runs += tatami(parts[i], 0.0, TACK_ROW, TACK_LEN, (center_x, parts[i].bounds[1]))
    return runs


def end_caps(poly, angle, spacing, outline=None):
    """The ends of a puff column: where the edge runs along the satin stitches, the satin does
    not cut the foam. A short satin across that edge, END_CAP deep, closes it. [(points, area)].
    outline: the edge of the whole part; a column's edges inside it (where it meets the next
    column) get no end cap."""
    a = math.radians(angle)
    sx, sy = math.cos(a), math.sin(a)
    depth = min(END_CAP, 0.4 * _width(poly))
    inner = poly.buffer(-depth, join_style=2)
    if inner.is_empty or depth < 0.3:
        return []
    edge = inner.boundary
    runs = []
    for ring in [poly.exterior] + list(poly.interiors):
        L = ring.length
        n = max(8, int(L / (spacing / 2)))
        step = L / n
        flags = []
        for k in range(n):
            p, q = ring.interpolate((k * step - 0.3) % L), ring.interpolate((k * step + 0.3) % L)
            tx, ty = q.x - p.x, q.y - p.y
            t = math.hypot(tx, ty)
            flags.append(t > 1e-9 and abs(tx * sx + ty * sy) / t > math.cos(math.radians(30))
                         and (outline is None or outline.distance(ring.interpolate(k * step)) < 0.1))
        if all(flags) or not any(flags):
            continue
        k0 = flags.index(False)
        groups, cur = [], []
        for i in [(k0 + j) % n for j in range(n)]:
            if flags[i]:
                cur.append(i)
            elif cur:
                groups.append(cur); cur = []
        if cur:
            groups.append(cur)
        for g in groups:
            if len(g) * step < 1.0:
                continue
            pts = []
            for j, i in enumerate(g):
                o_ = ring.interpolate(i * step)
                q = o_ if j % 2 == 0 else nearest_points(edge, o_)[0]
                if q.distance(o_) > 2.5 * depth:      # a corner: the inside is not across from here
                    break
                pts.append((q.x, q.y))
            if len(pts) >= 3:
                runs.append((pts, LineString(pts).buffer(0.3).intersection(poly)))
    return runs


def _reflex(poly, min_turn=25.0, span=None):
    """The inside corners of a part (where a T's bar meets its stem): [(point, edge in, edge out)].
    The turn is measured over `span` mm of outline each side (0.4 mm, more on a wide stroke), so
    the jags of a traced outline do not count; only the sharpest point of each corner is kept."""
    span = span or max(0.4, 0.25 * _width(poly))
    poly = shapely.geometry.polygon.orient(poly, 1.0)       # the inside is on the left of every ring
    out = []
    for ring in [poly.exterior] + list(poly.interiors):
        R = ring.length
        n = max(8, int(R / 0.1))
        d = np.arange(n) * R / n
        P = shapely.get_coordinates(shapely.line_interpolate_point(ring, d))
        k = max(1, int(round(span / (R / n))))

        def turning(k):
            u = P - np.roll(P, k, axis=0)
            v = np.roll(P, -k, axis=0) - P
            return u, v, np.degrees(np.arctan2(u[:, 0] * v[:, 1] - u[:, 1] * v[:, 0], (u * v).sum(axis=1)))
        u, v, turn = turning(k)
        _u, _v, wide = turning(2 * k)
        # a corner turns about as much over a short stretch as over twice it; a smooth bend (the
        # inside of a C) turns twice as much: that is not a corner
        corner = np.abs(turn) >= 0.7 * np.abs(wide)
        for i in range(n):
            if corner[i] and turn[i] < -min_turn and turn[i] <= turn[(i - 1) % n] and turn[i] < turn[(i + 1) % n]:
                out.append((turn[i], tuple(P[i]), tuple(u[i]), tuple(v[i])))
    return [(b, u, v) for _, b, u, v in sorted(out)[:12]]       # the sharpest first


def _cut(poly, at, d):
    """poly cut by a straight line from the corner `at` in direction d to the far edge, or None."""
    n = math.hypot(*d)
    if n < 1e-9:
        return None
    dx, dy = d[0] / n, d[1] / n
    ray = LineString([(at[0] + dx * 0.05, at[1] + dy * 0.05), (at[0] + dx * 2 * SPLIT_MAX, at[1] + dy * 2 * SPLIT_MAX)])
    hits = [q for g in getattr(ray.intersection(poly.boundary), "geoms", [ray.intersection(poly.boundary)])
            if not g.is_empty for q in g.coords]
    if not hits:
        return None
    q = min(hits, key=lambda q: math.dist(q, at))
    seg = LineString([at, q])
    if seg.length < 0.3 or not poly.buffer(0.02).covers(seg):
        return None
    line = LineString([(at[0] - dx * 0.05, at[1] - dy * 0.05), (q[0] + dx * 0.05, q[1] + dy * 0.05)])
    pieces = [p for p in _parts(shapely.make_valid(shapely.ops.split(poly, line))) if p.area > 0.05]
    if not pieces or min(p.area for p in pieces) < 0.3:
        return None
    if len(pieces) < 2:     # one piece: fine when the cut opened a hole (an e's eye, cut open, is a stroke)
        opened = line.buffer(0.03)
        piece = shapely.make_valid(poly.difference(opened))
        pieces = [p for p in _parts(piece) if p.area > 0.05]
        if len(pieces) != 1 or len(pieces[0].interiors) >= len(poly.interiors):
            return None
    return pieces, seg.length


def _smooth(g):
    """The outline without the jags of tracing (small notches filled, small bumps taken off), so
    they are not taken for corners. The part as it is when smoothing would change it much."""
    r = min(0.15, 0.15 * _width(g))
    for s in (g.simplify(0.08).buffer(r, join_style=1).buffer(-2 * r, join_style=1).buffer(r, join_style=1),
              g.simplify(0.08).buffer(-r, join_style=1).buffer(r, join_style=1)):      # without filling notches
        parts = _parts(shapely.make_valid(s.simplify(0.04)))
        if not parts:
            continue
        s = max(parts, key=lambda p: p.area)
        if len(s.interiors) == len(g.interiors) and abs(s.area - g.area) < 0.1 * g.area:   # same shape, no gap closed
            return s
    return g


def columns(poly, ok, depth=0, _memo=None):
    """A part cut into pieces that each pass ok(piece) (a column a satin can cover): cut from its
    inside corners, straight across the stroke, the way a digitizer splits a T into its bar and
    stem. Pieces that cannot be made to pass are returned as they are."""
    memo = {} if _memo is None else _memo

    def good(p):
        k = p.wkb
        if k not in memo:
            memo[k] = ok(p)
        return memo[k]
    if good(poly) or depth >= 6:
        return [poly]
    best = None
    corners = _reflex(poly)
    tries = [(at, d) for at, u, v in corners for d in (u, (-v[0], -v[1]), (1, 0), (-1, 0), (0, 1), (0, -1))]
    # and from one inside corner to another (the two corners of a T, the inside of a bend)
    tries += [(a, (b[0] - a[0], b[1] - a[1])) for i, (a, _u, _v) in enumerate(corners[:6])
              for b, _u2, _v2 in corners[i + 1:6] if 0.3 < math.dist(a, b) <= SPLIT_MAX]
    # a hole that is not an even ring (the eye of an e, the bowl of an a): cut the ring open from
    # the hole's bottom, top or sides straight out to the edge
    for hole in sorted(poly.interiors, key=lambda r: -Polygon(r).area)[:3]:     # the largest few
        hx = np.array(hole.coords)
        for k, d_ in ((np.argmin(hx[:, 1]), (0, -1)), (np.argmax(hx[:, 1]), (0, 1)),
                      (np.argmin(hx[:, 0]), (-1, 0)), (np.argmax(hx[:, 0]), (1, 0))):
            tries.append((tuple(hx[k]), d_))
    # the cuts, shortest first: the first that leaves every piece passing is the best (the shortest
    # such cut), so the rest need not be tested (testing a piece can mean tracing its stroke)
    cuts = sorted((r for r in (_cut(poly, at, d) for at, d in tries) if r), key=lambda r: r[1])
    for pieces, length in cuts:
        bad = sum(p.area for p in pieces if not good(p))     # area that still does not pass
        if bad < poly.area - 0.2 and (best is None or (bad, length) < best[0]):
            best = ((bad, length), pieces)
        if bad == 0:
            break
    if not best:
        return [poly]
    return [q for p in best[1] for q in columns(p, ok, depth + 1, memo)]


def _best_satin_angle(poly):
    """The angle that makes the stitches across the part shortest, and that length."""
    best = (90.0, math.inf)
    rect = poly.minimum_rotated_rectangle
    cs = list(rect.exterior.coords) if isinstance(rect, Polygon) else []
    cands = [0.0, 45.0, 90.0, 135.0]
    if len(cs) >= 4:
        (ax, ay), (bx, by), (cx, cy) = cs[0], cs[1], cs[2]
        long_a = math.degrees(math.atan2(by - ay, bx - ax)) if math.dist(cs[0], cs[1]) >= math.dist(cs[1], cs[2]) \
            else math.degrees(math.atan2(cy - by, cx - bx))
        cands.insert(0, (long_a + 90) % 180)
    for a in cands:
        longest = max((u1 - u0 for _, segs in _scan(poly, a, 0.5) for u0, u1 in segs), default=0)
        if longest < best[1] - 1e-6:
            best = (a, longest)
    return best


# ---------------------------------------------------------------------------
# turning satin: stitches across a stroke that bends (an S, a C, the bowl of an R), at right
# angles to it all along, the way a digitizer lays a satin column on its two rails

_STEPS = [((1, 0), 1.0), ((-1, 0), 1.0), ((0, 1), 1.0), ((0, -1), 1.0),
          ((1, 1), math.sqrt(2)), ((1, -1), math.sqrt(2)), ((-1, 1), math.sqrt(2)), ((-1, -1), math.sqrt(2))]


def _raster(poly, res):
    """The part as a grid of cells `res` mm wide: (mask, x of column 0, y of row 0)."""
    x0, y0, x1, y1 = poly.bounds
    x0, y1 = x0 - 2 * res, y1 + 2 * res
    im = Image.new("1", (int((x1 - x0) / res) + 5, int((y1 - y0) / res) + 5), 0)
    g = ImageDraw.Draw(im)
    px = lambda c: ((c[0] - x0) / res, (y1 - c[1]) / res)
    g.polygon([px(c) for c in poly.exterior.coords], fill=1)
    for r in poly.interiors:
        g.polygon([px(c) for c in r.coords], fill=0)
    return np.asarray(im, bool).copy(), x0, y1


def _geodesic(mask, seed):
    """How far (in cells) each cell inside the mask is from `seed`, going round inside it."""
    H, W = mask.shape
    d = np.full(mask.shape, np.inf)
    d[seed] = 0.0
    for _ in range(4 * (H + W)):
        changed = False
        for (di, dj), w in _STEPS:
            rows, cols = slice(max(di, 0), H + min(di, 0)), slice(max(dj, 0), W + min(dj, 0))
            dst = d[rows, cols]
            cand = d[max(-di, 0):H + min(-di, 0), max(-dj, 0):W + min(-dj, 0)] + w
            better = mask[rows, cols] & (cand < dst - 1e-9)
            if better.any():
                dst[better] = cand[better]
                changed = True
        if not changed:
            break
    return d


class Stroke:
    """A part that is one stroke (no hole, no branch), as a digitizer sees it: a centre line from
    one end (A) to the other (B), and every satin stitch across it at right angles, from edge to
    edge. `ok` is False when the part is not one stroke a satin can follow."""

    def __init__(self, poly, coarse=False):
        """coarse: traced on a grid about a third as fine (a quick yes or no while cutting a part)."""
        self.ok, self.poly = False, poly
        if poly.interiors or poly.area < 0.2:
            return
        w = 2 * poly.area / poly.length                 # about how wide the stroke is
        cells, most = (1500, 0.45) if coarse else (5000, 0.25)
        res = min(max(math.sqrt(poly.area / cells), 0.04), most, max(w / 5, 0.04))
        mask, x0, y1 = _raster(poly, res)
        if mask.sum() < 8:
            return
        inner = mask.copy()
        inner[1:] &= mask[:-1]; inner[:-1] &= mask[1:]; inner[:, 1:] &= mask[:, :-1]; inner[:, :-1] &= mask[:, 1:]
        edge = mask & ~inner

        def far(dist):
            v = np.where(edge & np.isfinite(dist), dist, -1.0)
            return np.unravel_index(np.argmax(v), v.shape)
        rp = poly.representative_point()
        ii, jj = np.nonzero(mask)
        k = np.argmin((ii - (y1 - rp.y) / res) ** 2 + (jj - (rp.x - x0) / res) ** 2)
        A = far(_geodesic(mask, (ii[k], jj[k])))        # one end: the farthest from the middle
        dA = _geodesic(mask, A)
        B = far(dA)                                     # the other: the farthest from A
        dB = _geodesic(mask, B)
        L = float(dA[B]) * res
        if not math.isfinite(L) or L < max(0.6, w):
            return
        # the centre line: the middle of the cells at each step along the stroke
        reach = np.isfinite(dA[ii, jj]) & np.isfinite(dB[ii, jj])
        ii, jj = ii[reach], jj[reach]
        phi = (dA[ii, jj] - dB[ii, jj]) * res / 2 + L / 2
        band = max(2 * res, 0.15)
        bins = np.clip((phi / band).astype(int), 0, int(L / band))
        cnt = np.bincount(bins)
        keep = cnt > 0
        cx = (np.bincount(bins, x0 + jj * res)[keep] / cnt[keep])
        cy = (np.bincount(bins, y1 - ii * res)[keep] / cnt[keep])
        c = np.column_stack([cx, cy])
        if len(c) < 4:
            return
        win = max(1, int(w / 2 / band))                 # smoothed over half a stroke width
        ker = np.ones(2 * win + 1) / (2 * win + 1)
        c = np.column_stack([np.convolve(np.pad(c[:, i], win, mode="edge"), ker, "valid") for i in (0, 1)])
        # the ends: the line is unsure within half a width of them; go on straight from there
        seg = np.hypot(*np.diff(c, axis=0).T)
        s = np.concatenate([[0], np.cumsum(seg)])
        lo, hi = np.searchsorted(s, 0.5 * w), np.searchsorted(s, s[-1] - 0.5 * w)
        if hi - lo < 2:
            lo, hi = 0, len(c) - 1
        c = c[lo:hi + 1]
        t0, t1 = c[0] - c[min(2, len(c) - 1)], c[-1] - c[max(len(c) - 3, 0)]
        t0, t1 = t0 / max(np.hypot(*t0), 1e-9), t1 / max(np.hypot(*t1), 1e-9)
        ext = 0.5 * w + 1.0
        c = np.vstack([c[0] + t0 * ext, c, c[-1] + t1 * ext])
        line = LineString(c)
        if line.length < 0.5:
            return
        self.line = line
        # near each end (a serif, a flag, a foot) the stitches keep the angle the stroke has where it
        # is still regular, as Wilcom's lettering ends: parallel, not fanned out over the widening
        self.freeze = min(ext + 0.6 * w, line.length / 3)
        self.loose = poly.buffer(0.15)
        R = poly.exterior.length
        self.edge = shapely.get_coordinates(shapely.line_interpolate_point(poly.exterior, np.arange(0, R, 0.05)))
        Q1, Q2 = self.rungs(0.25, fill=False)       # the stroke as it is, for the test below
        if len(Q1) < 3:
            return
        wd = np.hypot(*(Q1 - Q2).T)
        self.width = float(np.percentile(wd, 95))
        cover = wd.sum() * 0.25 / poly.area             # the stitches cover the part, no more
        self.ok = 0.8 <= cover <= 1.2 and 0.3 < self.width <= SPLIT_MAX

    def rungs(self, step, inset=0.0, fill=True):
        """Each satin stitch's two ends, every `step` mm along the centre line from A to B:
        (Q1, Q2), Q1 on one side, Q2 on the other. inset: each end moved this far in."""
        line, poly = self.line, self.poly
        n = max(2, int(round(line.length / step)))
        d = np.linspace(0, line.length, n + 1)
        c = shapely.get_coordinates(shapely.line_interpolate_point(line, d))
        dd = np.clip(d, self.freeze, line.length - self.freeze)      # the ends: the angle held
        frozen = dd != d
        a = shapely.get_coordinates(shapely.line_interpolate_point(line, np.clip(dd - 0.3, 0, line.length)))
        b = shapely.get_coordinates(shapely.line_interpolate_point(line, np.clip(dd + 0.3, 0, line.length)))
        t = b - a
        t /= np.maximum(np.hypot(*t.T), 1e-9)[:, None]
        nrm = np.column_stack([-t[:, 1], t[:, 0]])
        reach = SPLIT_MAX + 2
        cuts = shapely.intersection(shapely.linestrings(np.stack([c - nrm * reach, c + nrm * reach], axis=1)), poly)
        Q1, Q2, held = [], [], []
        for k, g in enumerate(cuts):
            segs = [q for q in getattr(g, "geoms", [g]) if q.geom_type == "LineString" and not q.is_empty]
            if not segs:
                continue
            pt = Point(c[k])
            q = min(segs, key=lambda q: q.distance(pt))
            if q.distance(pt) > 0.3:
                continue
            e = np.array(q.coords)[[0, -1]]
            side = (e - c[k]) @ nrm[k]
            p1, p2 = (e[1], e[0]) if side[0] < side[1] else (e[0], e[1])
            Q1.append(p1); Q2.append(p2); held.append(frozen[k])
        Q1, Q2 = np.array(Q1).reshape(-1, 2), np.array(Q2).reshape(-1, 2)
        if len(Q1):
            # on a tight bend the line across can run along the stroke (far longer than the stroke
            # is wide): there, each end is the nearest point of the edge on its side
            mid = (Q1 + Q2) / 2
            nm = Q2 - Q1
            ln = np.hypot(*nm.T)
            typical = float(np.median(ln))
            for k in np.nonzero((ln > max(2.0 * typical, typical + 1.5)) & ~np.array(held, bool))[0]:
                v = self.edge - mid[k]
                dist = np.hypot(*v.T)
                side = v @ (nm[k] / max(ln[k], 1e-9))
                for sgn, Q in ((-1, Q1), (1, Q2)):
                    cone = sgn * side > 0.34 * dist
                    if cone.any():
                        Q[k] = self.edge[np.argmin(np.where(cone, dist, np.inf))]
            # a stitch that would leave the stroke (across a gap to another part of it) is left out
            inside = shapely.covered_by(shapely.linestrings(np.stack([Q1, Q2], axis=1)), self.loose)
            Q1, Q2 = Q1[inside], Q2[inside]
            if fill:
                Q1, Q2 = self._fill_gaps(Q1, Q2, step)
        if inset and len(Q1):
            dv = Q2 - Q1
            ln = np.maximum(np.hypot(*dv.T), 1e-9)[:, None]
            m = np.minimum(inset, ln / 3)
            Q1, Q2 = Q1 + dv / ln * m, Q2 - dv / ln * m
        return Q1, Q2

    def _fill_gaps(self, Q1, Q2, step):
        """Where one edge of the satin jumps (the stitches turn sharply: round a tight bend, where the
        angle is held at an end), stitches are added that walk that edge, so no wedge of the stroke
        is left bare: Wilcom's short stitches fanning round a turn."""
        if len(Q1) < 2:
            return Q1, Q2
        ring = self.poly.exterior
        R = ring.length
        lim = max(2.5 * step, 0.35)
        o1, o2 = [Q1[0]], [Q2[0]]
        for k in range(1, len(Q1)):
            a1, b1, a2, b2 = Q1[k - 1], Q1[k], Q2[k - 1], Q2[k]
            g = max(math.dist(a1, b1), math.dist(a2, b2))
            if g > lim:
                m = min(40, math.ceil(g / step))
                walk = []
                for A, B in ((a1, b1), (a2, b2)):       # each edge walked along the outline, the short way
                    pa, pb = ring.project(Point(A)), ring.project(Point(B))
                    d = (pb - pa) % R
                    if d > R / 2:
                        d -= R
                    if abs(d) > 4 * math.dist(A, B) + 1:        # not along this outline: straight
                        walk.append([A + (B - A) * j / m for j in range(1, m)])
                    else:
                        walk.append([np.array(ring.interpolate((pa + d * j / m) % R).coords[0]) for j in range(1, m)])
                for p1, p2 in zip(*walk):
                    if math.dist(p1, p2) > 0.2 and shapely.covered_by(LineString([p1, p2]), self.loose):
                        o1.append(p1); o2.append(p2)
            o1.append(b1); o2.append(b2)
        return np.array(o1).reshape(-1, 2), np.array(o2).reshape(-1, 2)

    def ends(self):
        Q1, Q2 = self.rungs(0.5)
        return tuple((Q1[0] + Q2[0]) / 2), tuple((Q1[-1] + Q2[-1]) / 2)


_STROKES = {}      # Stroke of a piece, by its shape: tracing one is the slow part, and the same
                   # piece is tested while cutting, then sewn; emptied at the start of each design


def _stroke(p, coarse=False):
    k = (p.wkb, coarse)
    if k not in _STROKES:
        if len(_STROKES) > 2000:
            _STROKES.clear()
        _STROKES[k] = Stroke(p, coarse)
    return _STROKES[k]


def turning_satin(st: Stroke, spacing, reverse=False, underlay=True, inset=0.4, light=False, longest=SATIN_MAX,
                  back=False):
    """Runs for one stroke: underlay (a centre run there and back on a narrow stroke; an edge walk
    up one side and down the other on a wide one), then the satin from A to B (or B to A),
    each stitch longer than `longest` split in two or more, the splits staggered.
    back: the underlay goes out to the far end only (a centre run; on a wide stroke the edge walk
    and a zigzag out) and the satin comes back, so the needle ends where it came in (an arm sewn
    from where it joins the rest: the next piece starts there, with no trim)."""
    def order(Q):
        return Q[::-1] if reverse else Q
    runs = []
    if underlay:
        if st.width <= 2.0:
            Q1, Q2 = st.rungs(1.6 if light else 1.2)
            mid = order((Q1 + Q2) / 2)
            runs.append(([tuple(p) for p in mid] + ([] if back else [tuple(p) for p in mid[::-1][1:]]), None))
        else:
            Q1, Q2 = st.rungs(2.0 if light else 1.6, inset)
            Q1, Q2 = order(Q1), order(Q2)
            runs.append(([tuple(p) for p in Q1] + [tuple(p) for p in Q2[::-1]], None))
            if st.width > SATIN_MAX or back:     # a wide one: a zigzag across as well
                Z1, Z2 = st.rungs(3.0 if light else 2.2, inset)
                Z1, Z2 = order(Z1), order(Z2)
                runs.append(([tuple(Z1[k] if k % 2 == 0 else Z2[k]) for k in range(len(Z1))], None))
    Q1, Q2 = st.rungs(spacing / 2)
    Q1, Q2 = (Q1, Q2) if reverse == back else (Q1[::-1], Q2[::-1])
    zz = [Q1[k] if k % 2 == 0 else Q2[k] for k in range(len(Q1))]      # one side, then the other
    runs.append((_split_long(zz, longest), st.poly))
    return runs


def _split_long(zz, longest):
    """A satin's points with each stitch longer than `longest` split in two or more, the splits
    shifted row by row (Wilcom's auto split), so no line of needle holes runs down the column."""
    pts = [tuple(zz[0])]
    for k in range(1, len(zz)):
        a, b = zz[k - 1], zz[k]
        d = math.dist(a, b)
        if d > longest:
            m = math.ceil(d / SPLIT_LEN)
            shift = ((k % 3) - 1) * 0.3
            for j in range(1, m):
                t = (j + shift) / m
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        pts.append(tuple(b))
    return pts


def _level_angle(p, st):
    """The one angle a straight stroke is sewn at, as Wilcom sews lettering: level across a stem or
    a leg, upright across a bar, square across a diagonal; the serifs and feet at its ends at the
    same angle. None when the stroke's middle bends, a row would cross it twice, or the stitches
    would run much longer than the stroke is wide."""
    L = st.line.length
    m0, m1 = st.freeze, L - st.freeze
    if m1 - m0 < max(0.5, 0.5 * st.width) or (st.width > 3.0 and L < 2.5 * st.width):     # a blob, not a stroke
        return None
    mid = shapely.ops.substring(st.line, m0, m1)
    c = shapely.get_coordinates(mid)
    chord = LineString([c[0], c[-1]])
    if chord.length < 0.5 or max(chord.distance(Point(q)) for q in c) > 0.12 * chord.length:
        return None
    ang = math.degrees(math.atan2(c[-1][1] - c[0][1], c[-1][0] - c[0][0])) % 180
    fixed = 90.0 if ang < 25 or ang > 155 else 0.0 if 65 < ang < 115 else (ang + 90) % 180
    rows = [segs for _, segs in _scan(p, fixed, 0.3) if segs]
    if any(len(segs) > 1 for segs in rows):
        return None
    longest = max((u1 - u0 for segs in rows for u0, u1 in segs), default=0)
    limit = min(SATIN_MAX, 2.0 * st.width) if st.width <= 3.0 else min(SPLIT_MAX, 1.8 * st.width)
    return fixed if longest <= limit else None


def _hole_tips(ring, min_prom=0.18):
    """The points of a spiky hole (a star's points, a gear's teeth): where its outline reaches
    farthest from its centre, each standing out by min_prom of the mean reach. [(x, y)], or []."""
    c = Polygon(ring).centroid
    L = ring.length
    n = max(60, int(L / 0.1))
    pts = shapely.get_coordinates(shapely.line_interpolate_point(ring, np.linspace(0, L, n, endpoint=False)))
    r = np.hypot(pts[:, 0] - c.x, pts[:, 1] - c.y)
    mean = float(r.mean())
    if mean <= 0:
        return []
    win = max(2, n // 40)
    tips = []
    for i in range(n):
        near = np.take(r, range(i - win, i + win + 1), mode="wrap")
        if r[i] < near.max():
            continue
        far = np.take(r, range(i - n // 10, i + n // 10 + 1), mode="wrap")       # the valleys each side
        if r[i] - far.min() >= min_prom * mean and all(math.dist(pts[i], t) > 0.5 for t in tips):
            tips.append(tuple(pts[i]))
    return tips


def _wedges(poly):
    """A part with one spiky hole (a circle with a star in it) cut as Wilcom digitizes it: from
    each point of the hole straight out to the edge, into wedges, each sewn as a satin at one
    angle, straight out from the hole's centre. [(piece, angle)], or None when the part is not
    like that or a wedge would not sew so."""
    if len(poly.interiors) != 1:
        return None
    hole = poly.interiors[0]
    tips = _hole_tips(hole)
    if not 3 <= len(tips) <= 12:
        return None
    c = Polygon(hole).centroid
    reach = math.dist(poly.bounds[:2], poly.bounds[2:]) + 1
    cuts = []
    for x, y in tips:
        dx, dy = x - c.x, y - c.y
        k = math.hypot(dx, dy) or 1
        dx, dy = dx / k, dy / k
        # from just inside the hole, out past the outer edge
        cuts.append(LineString([(x - dx * 0.3, y - dy * 0.3), (x + dx * reach, y + dy * reach)]))
    pieces = [q for q in _parts(shapely.make_valid(shapely.ops.split(poly, shapely.MultiLineString(cuts))))
              if q.area > 0.3]
    if len(pieces) != len(tips):
        return None
    # each wedge: stitches straight out from the hole's centre, through the wedge's middle
    out = []
    for q in pieces:
        m = q.centroid
        ang = math.degrees(math.atan2(m.y - c.y, m.x - c.x)) % 180
        rows = [segs for _, segs in _scan(q, ang, 0.3) if segs]
        if any(len(sg) > 1 for sg in rows) or max((u1 - u0 for sg in rows for u0, u1 in sg), default=0) > SPLIT_MAX:
            return None
        out.append((q, ang))
    return out


def _stroke_ok(p):
    """Can a satin follow this piece as it is: a ring, or one stroke (no hole, no branch, nowhere
    wider than SPLIT_MAX)? Inside corners only at its ends (a serif, a foot, a flag: a stem and its
    foot are one column, as Wilcom sews them) still make one stroke; its ends are sewn level."""
    if _is_ring(p, SATIN_MAX):
        return True
    if p.interiors or not p.buffer(-SPLIT_MAX / 2).is_empty:
        return False
    corners = _reflex(p, 35.0)
    if not corners:
        return True
    if len(corners) > 4:
        return False
    # quick tests first, on the tightest box around it: it is long, and its corners are near the
    # box's ends (a T's corners are in its middle)
    box = np.array(p.minimum_rotated_rectangle.exterior.coords)[:4]
    e1, e2 = box[1] - box[0], box[2] - box[1]
    long_, short = (e1, e2) if np.hypot(*e1) >= np.hypot(*e2) else (e2, e1)
    Lb, Wb = np.hypot(*long_), np.hypot(*short)
    if Wb <= 0 or Lb < 1.7 * Wb:
        return False
    axis, mid = long_ / Lb, box.mean(axis=0)
    if any(Lb / 2 - abs(float(np.dot(np.array(c) - mid, axis))) > 1.2 * Wb for c, _u, _v in corners):
        return False
    st = _stroke(p, coarse=True)
    if not st.ok or st.line.length < 2.5 * st.width:      # a stroke is long; a star's arms are not
        return False
    L, reach = st.line.length, st.freeze + 0.3 * st.width
    if not all(min(st.line.project(Point(c)), L - st.line.project(Point(c))) <= reach for c, _u, _v in corners):
        return False
    # and between its ends the stroke keeps an even width (a star's arms, joined, do not)
    Q1, Q2 = st.rungs(0.3, fill=False)
    if len(Q1) < 4:
        return False
    mid = (Q1 + Q2) / 2
    along = np.array([st.line.project(Point(q)) for q in mid])
    w = np.hypot(*(Q2 - Q1).T)[(along > st.freeze) & (along < L - st.freeze)]
    return len(w) >= 3 and np.percentile(w, 90) <= 1.6 * np.percentile(w, 10)


# ---------------------------------------------------------------------------
# one colour

class Router:
    """Ways for the thread to travel inside an area: shortest paths on a grid of RES mm."""
    RES = 0.4

    def __init__(self, area):
        self.loose = area.buffer(0.1)
        x0, y0, x1, y1 = area.bounds if not area.is_empty else (0, 0, 1, 1)
        self.x0, self.y1 = x0 - 1, y1 + 1
        w, h = int((x1 - x0 + 2) / self.RES) + 1, int((y1 - y0 + 2) / self.RES) + 1
        self.im = Image.new("1", (w, h), 0)
        self._draw(area, 1)
        self.base = self.mask.copy()        # before anything is blocked

    def _draw(self, area, value):
        g = ImageDraw.Draw(self.im)
        for part in sorted(_parts(area), key=lambda q: -q.area):     # outer parts first, their holes cut out
            g.polygon([self._px(c) for c in part.exterior.coords], fill=value)
            for ring in part.interiors:
                g.polygon([self._px(c) for c in ring.coords], fill=1 - value)
        self.mask = np.asarray(self.im, bool)

    def block(self, area):
        """Stitches now cover this area: travel no longer runs over it."""
        self._draw(area.buffer(0.1), 0)       # and its edge: no creeping round finished stitches

    def clear(self, a, b):
        """The straight way from a to b stays inside (its ends may sit on the edge)."""
        d = math.dist(a, b)
        n = max(2, int(d / (self.RES / 2)))
        h, w = self.mask.shape
        for k in range(n + 1):
            t = k / n
            if d * min(t, 1 - t) < 0.5:
                continue
            x, y = self._px((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
            i, j = int(round(y)), int(round(x))
            if not (0 <= i < h and 0 <= j < w and self.mask[i, j]):
                return False
        return True

    def _px(self, c):
        return ((c[0] - self.x0) / self.RES, (self.y1 - c[1]) / self.RES)

    @staticmethod
    def _cell(x, y, m):
        """The nearest grid cell inside, within a few cells of (x, y) (grid units)."""
        i, j = int(round(y)), int(round(x))
        for r in range(3):
            a0, a1 = max(0, i - r), min(m.shape[0], i + r + 1)
            b0, b1 = max(0, j - r), min(m.shape[1], j + r + 1)
            if a0 >= a1 or b0 >= b1:
                continue
            ii, jj = np.mgrid[a0:a1, b0:b1]
            ii, jj = ii.ravel(), jj.ravel()
            hit = m[ii, jj]
            if hit.any():
                k = np.argmin(np.where(hit, (ii - y) ** 2 + (jj - x) ** 2, np.inf))
                return int(ii[k]), int(jj[k])
        return None

    def path(self, a, b, longest, over=False):
        """Points from a to b inside the area, or None when there is no way shorter than `longest` mm.
        over: the way may cross finished stitches (of this colour)."""
        pad = longest / 2 + 1
        (ax, ay), (bx, by) = self._px(a), self._px(b)
        r = pad / self.RES
        i0, j0 = max(0, int(min(ay, by) - r)), max(0, int(min(ax, bx) - r))
        i1 = min(self.mask.shape[0], int(max(ay, by) + r) + 2)
        j1 = min(self.mask.shape[1], int(max(ax, bx) + r) + 2)
        m = (self.base if over else self.mask)[i0:i1, j0:j1].copy()
        if m.size == 0:
            return None
        # the needle may step out of finished stitches near either end (within this area only)
        base = self.base[i0:i1, j0:j1]
        ii, jj = np.mgrid[0:m.shape[0], 0:m.shape[1]]
        for px, py in ((ax - j0, ay - i0), (bx - j0, by - i0)):
            m |= base & ((ii - py) ** 2 + (jj - px) ** 2 <= (0.6 / self.RES) ** 2)
        ca, cb = self._cell(ax - j0, ay - i0, m), self._cell(bx - j0, by - i0, m)
        if ca is None or cb is None:
            return None
        dist = np.full(m.shape, -1, np.int32)
        dist[ca] = 0
        front = np.zeros(m.shape, bool); front[ca] = True
        k = 0
        while dist[cb] < 0:          # grow outwards from a, one cell a step (8 neighbours)
            k += 1
            if k * self.RES > longest:
                return None
            g = front.copy()
            g[1:] |= front[:-1]; g[:-1] |= front[1:]
            h = g.copy()
            g[:, 1:] |= h[:, :-1]; g[:, :-1] |= h[:, 1:]
            g &= m & (dist < 0)
            if not g.any():
                return None
            dist[g] = k
            front = g
        cells, (i, j) = [cb], cb
        while dist[i, j] > 0:        # and back from b
            d = dist[i, j]
            for di, dj in ((-1, 0), (1, 0), (0, -1), (0, 1), (-1, -1), (-1, 1), (1, -1), (1, 1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < m.shape[0] and 0 <= jj < m.shape[1] and dist[ii, jj] == d - 1:
                    i, j = ii, jj
                    break
            cells.append((i, j))
        pts = [(self.x0 + (jj + j0) * self.RES, self.y1 - (ii + i0) * self.RES) for ii, jj in reversed(cells)]
        line = LineString([a] + pts[1:-1] + [b]) if len(pts) > 2 else LineString([a, b])
        smooth = line.simplify(0.15)
        if self.loose.covers(smooth):
            return list(smooth.coords)
        # the grid can bridge a gap narrower than a cell or two (two letters close together):
        # a way that leaves the area there would lay thread on the bare cap
        return list(line.coords) if self.loose.buffer(0.2).covers(line) else None


class Sewing:
    """Stitches as (x mm, y mm, command), and the needle's position."""

    def __init__(self):
        self.out = []
        self.at = (0.0, 0.0)
        self.tied = False          # the thread is locked at the needle
        self.trims = 0
        self.objects = 0           # top-stitch objects sewn (a satin, a fill, a column): Wilcom's "Objects"

    def stitch(self, p):
        if math.dist(p, self.at) < MIN_STITCH and self.out:
            return
        self.out.append((p[0], p[1], STITCH)); self.at = p

    def tie(self, toward):
        """Lock stitches: two tiny stitches back and forth along the next stitch."""
        p = self.at
        d = math.dist(p, toward)
        if d < 1e-6:
            return
        q = (p[0] + (toward[0] - p[0]) * 0.6 / max(d, 0.6), p[1] + (toward[1] - p[1]) * 0.6 / max(d, 0.6))
        for r in (q, p):
            self.out.append((r[0], r[1], STITCH))

    def trim(self):
        if self.out and self.out[-1][2] == STITCH:
            p, b = self.at, self.out[-2] if len(self.out) > 1 else None
            if b:               # tie off: two small stitches back along the last stitch and two forward
                d = math.dist(p, b[:2])         # (as a Wilcom file does: about 0.7 mm each)
                if d > 1e-6:
                    s = min(0.7, d / 2)
                    q1 = (p[0] + (b[0] - p[0]) * s / d, p[1] + (b[1] - p[1]) * s / d)
                    q2 = (p[0] + (b[0] - p[0]) * 2 * s / d, p[1] + (b[1] - p[1]) * 2 * s / d)
                    self.out += [(q[0], q[1], STITCH) for q in (q1, q2, q1, p)]
            self.out.append((p[0], p[1], TRIM)); self.trims += 1

    def jump(self, p):
        self.out.append((p[0], p[1], JUMP)); self.at = p
        self.tied = False

    def go(self, p):
        """Move the needle to p: sew there inside this colour, or under colours sewn later
        (they cover it), straight or the shortest way round; else trim and jump."""
        if not self.out:
            self.jump(p); return
        d = math.dist(self.at, p)
        if d < MIN_STITCH:
            return
        if d <= 0.6 or self.router.clear(self.at, p):
            way = [self.at, p]
        else:
            way = self.router.path(self.at, p, 2.5 * d + 8)
            if not way and d <= HOP:      # a short hop over finished stitches of this colour sinks into them
                way = self.router.path(self.at, p, 1.5 * d + 1, over=True)
        if way:
            for q in _run_along(LineString(way))[1:]:
                self.stitch(q)
            return
        self.trim()
        self.jump(p)

    def runs(self, runs, top=False):
        """Sew runs [(points, area they cover)]; the top layer's areas are closed to travel once sewn."""
        self.objects += bool(top and runs)
        for run, area in runs:
            if len(run) < 2:
                continue
            self.go(run[0])
            if not self.tied:
                self.tie(run[1]); self.tied = True
            for q in run[1:]:
                self.stitch(q)
            if top:
                self.router.block(area)


def _anchor(part, o, center_x):
    """Where a part's sewing begins: at its bottom, beside the centre seam (sewn from the bottom
    up), or at its point nearest the centre of the design (sewn from the centre outwards)."""
    if o["order"] == "center":
        q = nearest_points(part, Point(center_x + SEAM_OFF, 0.0))[0]
        return (q.x, q.y)
    return (center_x + SEAM_OFF, part.bounds[1])


def _chain(sw, plans, start, order):
    """A part's pieces in sewing order: first the lowest nearest the centre line (or the nearest
    the centre of the design), then each time the one nearest where the needle is.
    The piece that joins the others (a star's middle, a stem with arms off it) comes after them:
    while it is not sewn the needle runs under it from one to the next, where sewn first it would
    part them, and each would need a trim."""
    left = list(plans)
    touch = {id(a[0]): [b for b in plans if b is not a and a[0].distance(b[0]) < 0.3] for a in plans}

    def parts_them(item):       # sewing it now leaves the pieces still to sew in two or more groups
        rest = [it for it in left if it is not item]
        if len(rest) < 2:
            return False
        seen, todo = {id(rest[0])}, [rest[0]]
        while todo:
            for b in touch[id(todo.pop()[0])]:
                if id(b) not in seen and any(b is r for r in rest):
                    seen.add(id(b)); todo.append(b)
        return len(seen) < len(rest)

    def free():
        return [it for it in left if not parts_them(it)] or left

    def gap(item, at):
        p, kind = item
        if isinstance(kind, Stroke):
            return min(math.dist(at, q) for q in kind.ends())
        return p.distance(Point(at))
    if order == "center":
        first = min(free(), key=lambda it: it[0].distance(Point(start)))
    else:
        first = min(free(), key=lambda it: (math.floor(it[0].bounds[1]), abs(it[0].centroid.x - start[0])))
    left.remove(first)
    yield first
    while left:
        nxt = min(free(), key=lambda it: gap(it, sw.at))
        left.remove(nxt)
        yield nxt


def _sew_piece(sw: Sewing, p, kind, o, center_x, start=None, rest=None):
    """One piece of a part: a ring satin, a turning satin (Stroke), or, for a piece that is
    neither, a straight satin when one fits, else fill. Returns "satin" or "fill".
    rest: the pieces of the part still to sew; the piece ends at the end they join (an arm is
    sewn out and back to where it joins the rest; a piece on the way to them, through)."""
    at = start or sw.at
    light, pull = o["light"], o["pull_comp"]

    def joins(q):        # a piece still to sew touches here
        return bool(rest) and any(r.distance(Point(q)) < 0.5 for r in rest)
    if kind == "ring":
        sw.runs(edge_run(p, at))
        under = p.buffer(-0.5 - pull, join_style=2)
        if _width(p) > 1.6 and isinstance(under, Polygon) and _is_ring(under):
            sw.runs(ring_satin(under, 2.5 if light else 2.0, center_x))
        sw.runs(ring_satin(p, o["density"], center_x), top=True)
        return "satin"
    if isinstance(kind, float):     # a wedge: a satin at one angle, long stitches split
        sw.runs(edge_run(p, at))
        q0 = nearest_points(p, Point(at))[0]
        entry = (q0.x, q0.y)
        far = tuple(max(shapely.get_coordinates(p.exterior), key=lambda q: math.dist(q, entry)))
        through = joins(far) and not joins(entry)
        if not through:         # the satin comes back over its underlay, from the far end
            for q in _parts(p.buffer(-0.5 - pull, join_style=2)):
                sw.runs(satin(q, kind, 2.5 if light else 2.0, at))
        if rest is None:
            top = satin(p, kind, o["density"], sw.at)
        else:                   # the way round that ends nearest where the next piece begins
            want = far if through else entry
            top = min((satin(p, kind, o["density"], t) for t in (entry, far)),
                      key=lambda r: math.dist(r[-1][0][-1], want) if r else math.inf)
        sw.runs([(_split_long(pts, SATIN_MAX), area) for pts, area in top], top=True)
        return "satin"
    if isinstance(kind, Stroke):
        a, b = kind.ends()
        rev = math.dist(at, b) < math.dist(at, a)
        near_, far = (b, a) if rev else (a, b)
        runs = turning_satin(kind, o["density"], reverse=rev, inset=0.4 + pull, light=light,
                             back=joins(near_) and not joins(far))
        sw.runs(runs[:-1])
        # a straight stroke (a letter's stem, leg or bar, with its serifs and feet) is sewn as
        # lettering is: a satin at one angle, level across stems and legs, upright on bars
        # (Wilcom's lettering), long stitches split
        fixed = _level_angle(p, kind)
        if fixed is not None:
            sw.runs([(_split_long(pts, SATIN_MAX), area) for pts, area in satin(p, fixed, o["density"], sw.at)], top=True)
            return "satin"
        sw.runs(runs[-1:], top=True)
        return "satin"
    angle, longest = _best_satin_angle(p)
    if longest <= SATIN_MAX:
        under = p.buffer(-0.5 - pull, join_style=2)
        for q in _parts(under):
            sw.runs(satin(q, angle, 2.5 if light else 2.0, at))
        sw.runs(satin(p, angle, o["density"], at), top=True)
        return "satin"
    sw.runs(edge_run(p, at))
    for q in _parts(p.buffer(-0.6 - pull, join_style=2)):
        if q.area > 2:
            sw.runs(tatami(q, 0.0, 3.0 if light else UNDER_ROW, UNDER_LEN, at))
    density, length = (o["density"] * 1.1, 4.0) if light else (o["density"], FILL_LEN)
    sw.runs(tatami(p, 90.0, density, length, at), top=True)
    return "fill"


def _sew_part(sw: Sewing, part: Polygon, top: Polygon, o, center_x):
    """Underlay and top stitches of one part (top: the part widened by the pull compensation)."""
    w = _width(part)
    light = o["light"]              # fewer stitches: sparser underlay, longer and sparser fill
    bottom = (part.centroid.x, part.bounds[1])
    # the first stitches start just beside the centre seam, not in it (it is a valley on the cap)
    near = _anchor(part, o, center_x)

    if _is_ring(top) and _is_ring(part):
        sw.runs(edge_run(part, near))
        under = part.buffer(-0.5, join_style=2)
        if w > 1.6 and isinstance(under, Polygon) and _is_ring(under):
            sw.runs(ring_satin(under, 2.5 if light else 2.0, center_x))
        sw.runs(ring_satin(top, o["density"], center_x), top=True)
        return "satin"
    # strokes: the part cut at its inside corners into columns (a T into its bar and stem), each
    # sewn as a satin that follows it, the pieces one after the other, the nearest next
    plans, pieces = [], []
    sm = _smooth(top)
    wedges = _wedges(sm)
    if wedges:      # a circle with a star in it: wedges, each a satin straight out from the star (Wilcom)
        done = set()
        for k, (p, ang) in enumerate(_chain(sw, wedges, near, o["order"])):
            done.add(id(p))
            _sew_piece(sw, p, ang, o, center_x, near if k == 0 else None, [q for q, _ in wedges if id(q) not in done])
        return "satin"
    for p in columns(sm, _stroke_ok):
        p = max(_parts(shapely.make_valid(p)), key=lambda q: q.area)
        # a piece across the centre line (a stripe, a bar) is sewn in two halves, each from the
        # centre outwards, as the cap rule asks
        if not _is_ring(p, SATIN_MAX) and p.bounds[0] < center_x - 3 < center_x + 3 < p.bounds[2]:
            hs = [q for h in _halves(p, center_x, o["density"]) for q in _parts(shapely.make_valid(h)) if q.area > 0.3]
            if len(hs) == 2 and all(_stroke(q).ok for q in hs):     # only where the halves are still strokes
                pieces += hs
                continue
        pieces.append(p)
    if o["order"] == "center" and pieces:
        # sewing starts at the centre: the stroke nearest it is cut there, and both halves are
        # sewn from the cut outwards
        k = min(range(len(pieces)), key=lambda i: pieces[i].distance(Point(near)))
        st = _stroke(pieces[k])
        if st.ok:
            at = st.line.project(Point(near))
            c = st.line.interpolate(at)
            a, b = st.line.interpolate(max(at - 0.3, 0)), st.line.interpolate(min(at + 0.3, st.line.length))
            t = np.array([b.x - a.x, b.y - a.y]) / max(math.dist(a.coords[0], b.coords[0]), 1e-9)
            nv = np.array([-t[1], t[0]]) * (SPLIT_MAX + 2)
            cut = LineString([(c.x - nv[0], c.y - nv[1]), (c.x + nv[0], c.y + nv[1])])
            hs = [q for q in _parts(shapely.make_valid(shapely.ops.split(pieces[k], cut))) if q.area > 0.3]
            sts = [_stroke(q) for q in hs]
            # only where both halves are still straight strokes (a bar, a stripe): a curve cut there
            # leaves a stub that fans, so it is sewn whole from its end nearest the centre
            if len(hs) == 2 and all(t.ok and _level_angle(q, t) is not None for q, t in zip(hs, sts)):
                pieces[k:k + 1] = hs
    for p in pieces:
        if _is_ring(p, SATIN_MAX):
            plans.append((p, "ring"))
        else:
            st = _stroke(p)
            if st.ok and st.line.length < 3.5 * st.width:
                # a short piece (a serif on its own, the ear of a g, a star's point): a satin at one
                # angle when that is no longer than across the stroke; turning, it would fan out
                angle, longest = _best_satin_angle(p)
                if longest <= min(1.1 * st.width, SATIN_MAX):
                    plans.append((p, float(angle)))
                    continue
            plans.append((p, st if st.ok else None))
    if any(kind is not None for _, kind in plans):
        kinds, done = [], set()
        for k, (p, kind) in enumerate(_chain(sw, plans, near, o["order"])):
            done.add(id(p))
            rest = [q for q, _ in plans if id(q) not in done]
            kinds.append(_sew_piece(sw, p, kind, o, center_x, near if k == 0 else None, rest))
        return "satin" if kinds.count("satin") >= kinds.count("fill") else "fill"
    angle, longest = _best_satin_angle(top)
    if longest <= SATIN_MAX:
        a0 = (angle + 90) % 180
        column = 45 <= a0 <= 135        # a column runs up from the bottom, a bar out from the centre
        start = bottom if column else near
        sw.runs(edge_run(part, start))
        if w > 1.2:
            under = part.buffer(-0.5, join_style=2)
            for p in _parts(under):
                sw.runs(satin(p, angle, 2.5 if light else 2.0, start))
        for h in ([top] if column else _halves(top, center_x, o["density"])):
            for p in _parts(h):
                sw.runs(satin(p, angle, o["density"], (center_x, p.bounds[1]) if not column else start), top=True)
        return "satin"
    # fill: vertical stitches, each half swept from the centre line outwards
    halves = _halves(top, center_x, o["density"])
    sw.runs(edge_run(part, near))
    under = part.buffer(-0.6, join_style=2)
    for half in halves:
        for p in _parts(half.intersection(under) if not under.is_empty else half):
            if p.area > 2:
                sw.runs(tatami(p, 0.0, 3.0 if light else UNDER_ROW, UNDER_LEN, (center_x, p.bounds[1])))
    density, length = (o["density"] * 1.1, 4.0) if light else (o["density"], FILL_LEN)
    for half in halves:
        for p in _parts(half):
            sw.runs(tatami(p, 90.0, density, length, (center_x, p.bounds[1])), top=True)
    return "fill"


def _puff_plan(top: Polygon):
    """How a part is sewn in 3D puff: "ring", or its pieces [(piece, Stroke or satin angle)], or
    None (a piece too wide for a puff satin: the part is sewn flat). A piece at least twice as
    long as it is wide follows its stroke; a shorter one (a dot, a wedge) is sewn at one angle."""
    if _is_ring(top, PUFF_MAX):
        return "ring"
    plan = []
    sm = _smooth(top)
    wedges = _wedges(sm)
    if wedges:      # a circle with a star in it: wedges, each at one angle (none over SPLIT_MAX = PUFF_MAX)
        return wedges
    for p in columns(sm, _stroke_ok):
        p = max(_parts(shapely.make_valid(p)), key=lambda q: q.area)
        st = _stroke(p)
        if st.ok and st.width <= PUFF_MAX and st.line.length >= 2 * st.width:     # a stroke, not a blob
            plan.append((p, st))
            continue
        angle, longest = _best_satin_angle(p)
        if p.interiors or longest > PUFF_MAX:
            return None
        plan.append((p, angle))
    return plan


def _puff_centre_run(p, kind, at):
    """The run under a puff piece, sewn before the foam: down its centre line (Wilcom's 3D file
    sews this), or round its edge where it has none."""
    st = kind if isinstance(kind, Stroke) else Stroke(p)
    if not st.ok:
        return edge_run(p, at)
    Q1, Q2 = st.rungs(1.5)
    if len(Q1) < 2:
        return edge_run(p, at)
    mid = (Q1 + Q2) / 2
    if math.dist(at, mid[-1]) < math.dist(at, mid[0]):
        mid = mid[::-1]
    return [([tuple(q) for q in mid], None)]


def _puff_pieces(sw: Sewing, top: Polygon, plan, o, center_x, first=False):
    """A puff part's pieces in sewing order (each next one the nearest to where the needle is
    when it gets there); first: the first part of a pass, which starts where the design starts (both passes do, as in Wilcom's 3D file)."""
    return _chain(sw, plan, _anchor(top, o, center_x) if first else sw.at, o["order"])


def _level(p, kind: Stroke):
    """The angle a straight puff stroke is sewn at, as lettering is (level across a stem or a leg,
    upright across a bar), or None: it is curved, or the stitches would run too long."""
    a, b = kind.ends()
    chord = LineString([a, b])
    if chord.length < 0.5 or max(chord.distance(Point(q)) for q in shapely.get_coordinates(kind.line)[1:-1]) > 0.1 * chord.length:
        return None
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
    fixed = 90.0 if ang < 30 or ang > 150 else 0.0
    rows = [segs for _, segs in _scan(p, fixed, 0.3) if segs]
    if any(len(segs) > 1 for segs in rows):     # a row that crosses the stroke twice: not straight
        return None
    longest = max((u1 - u0 for segs in rows for u0, u1 in segs), default=0)
    return fixed if longest <= min(PUFF_MAX, 1.3 * kind.width) else None


def _sew_puff(sw: Sewing, top: Polygon, plan, o, center_x, first=False):
    """A puff part, over the foam: dense satin with no underlay (it would flatten the foam). Each
    piece is one satin: a straight stroke level or upright (as lettering), a curved one turning
    with it, as Wilcom's 3D WTS cap file sews them; other pieces at their best angle, with end
    caps across the ends that run along the stitches."""
    if plan == "ring":
        sw.runs(ring_satin(top, PUFF_DENSITY, center_x), top=True)
        return
    outline = top.boundary
    for p, kind in _puff_pieces(sw, top, plan, o, center_x, first):
        if len(plan) > 1:       # pieces overlap a little where they meet: no gap in the foam's cover
            p = max(_parts(shapely.make_valid(p.buffer(0.2, join_style=2).intersection(top))), key=lambda q: q.area)
        if isinstance(kind, Stroke):
            fixed = _level(p, kind)
            if fixed is not None:
                sw.runs(satin(p, fixed, PUFF_DENSITY, sw.at), top=True)
                continue
            a, b = kind.ends()
            sw.runs(turning_satin(kind, PUFF_DENSITY, reverse=math.dist(sw.at, b) < math.dist(sw.at, a),
                                  underlay=False, longest=PUFF_MAX), top=True)
            continue
        sw.runs(satin(p, kind, PUFF_DENSITY, sw.at), top=True)
        sw.runs(_nearest(end_caps(p, kind, PUFF_DENSITY, outline), sw.at), top=True)


# ---------------------------------------------------------------------------
# the whole design

SMALL = 6.35         # mm (0.25 in): smaller text and detail is noted


def _core(p):
    """Where most of a part is, up and down: the heights below which 20, 50 and 80 % of its area lie
    (a y's or a g's tail reaching into the next line moves them little)."""
    x0, y0, x1, y1 = p.bounds
    ys = np.linspace(y0, y1, 120)
    X, Y = np.meshgrid(np.linspace(x0, x1, 120), ys)
    rows = shapely.contains_xy(p, X, Y).sum(axis=1).astype(float)
    if rows.sum() == 0:
        return y0, (y0 + y1) / 2, y1
    c = np.cumsum(rows) / rows.sum()
    return tuple(float(np.interp(t, c, ys)) for t in (0.2, 0.5, 0.8))


def text_lines(parts):
    """The design's parts in lines, as text is read: two parts are on one line when the middle of
    either (half its area above, half below) lies within where most of the other is. Returns each
    part's line, numbered in sewing order: first the line of the part nearest the centre of the
    design, then the others, the nearest to it first."""
    n = len(parts)
    cores = [_core(p) for p in parts]
    group = list(range(n))

    def find(i):
        while group[i] != i:
            group[i] = group[group[i]]; i = group[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            (a0, am, a1), (b0, bm, b1) = cores[i], cores[j]
            if a0 <= bm <= a1 or b0 <= am <= b1:
                group[find(i)] = find(j)
    rows = {}
    for i in range(n):
        rows.setdefault(find(i), []).append(i)
    mid = {r: float(np.median([cores[i][1] for i in m])) for r, m in rows.items()}
    first = find(min(range(n), key=lambda i: parts[i].distance(Point(0, 0)))) if n else None
    seq = sorted(rows, key=lambda r: (r != first, abs(mid[r] - mid[first]), mid[r]))
    rank = {r: k for k, r in enumerate(seq)}
    return [rank[find(i)] for i in range(n)]


def cap_order(parts, order="bottom", lines=None):
    """The order a cap is sewn in: rows of parts (parts side by side, like a line of text)
    from the bottom up; in each row the part nearest the centre first, then outwards to the
    right, then outwards to the left. order "center": line by line (lines: each part's line, in
    sewing order, from text_lines), the line nearest the centre of the design first; in each line
    the part nearest the centre line first, then outwards to the right, then to the left."""
    if order == "center":
        lines = lines if lines is not None else text_lines(parts)
        out = []
        for ln in sorted(set(lines)):
            row = [i for i in range(len(parts)) if lines[i] == ln]
            cx = lambda i: (parts[i].bounds[0] + parts[i].bounds[2]) / 2
            ym = float(np.median([_core(parts[i])[1] for i in row]))
            mid = min(row, key=lambda i: (round(parts[i].distance(Point(0, ym)), 1), abs(cx(i))))
            right = sorted((i for i in row if i != mid and cx(i) >= cx(mid)), key=cx)
            left = sorted((i for i in row if i != mid and cx(i) < cx(mid)), key=lambda i: -cx(i))
            out += [mid] + right + left
        return out
    n = len(parts)
    box_ = [p.bounds for p in parts]
    # rows: parts that overlap up and down by at least half the smaller one's height
    group = list(range(n))

    def find(i):
        while group[i] != i:
            group[i] = group[group[i]]; i = group[i]
        return i
    for i in range(n):
        for j in range(i + 1, n):
            lo, hi = max(box_[i][1], box_[j][1]), min(box_[i][3], box_[j][3])
            hmin = min(box_[i][3] - box_[i][1], box_[j][3] - box_[j][1])
            if hi - lo >= 0.5 * hmin:
                group[find(i)] = find(j)
    rows = {}
    for i in range(n):
        rows.setdefault(find(i), []).append(i)
    order = []
    for row in sorted(rows.values(), key=lambda r: min(box_[i][1] for i in r)):
        cx = lambda i: (box_[i][0] + box_[i][2]) / 2
        mid = min(row, key=lambda i: abs(cx(i)))
        right = sorted((i for i in row if i != mid and cx(i) >= cx(mid)), key=cx)
        left = sorted((i for i in row if i != mid and cx(i) < cx(mid)), key=lambda i: -cx(i))
        order += [mid] + right + left
    return order

def digitize(an, opts: dict):
    """an: patch.Analysis. Returns (stitches [(x, y, cmd)], colours [{hex, id}], info)."""
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    _STROKES.clear()
    o["density"] = min(max(float(o["density"]), 0.3), 0.8)
    o["pull_comp"] = min(max(float(o["pull_comp"]), 0.0), 0.6)
    o["tilt"] = min(max(float(o["tilt"] or 0), -30.0), 30.0)
    W, H = float(o["width_mm"]), float(o["height_mm"])
    if not (W > 2 and H > 2):
        raise ValueError("The size must be more than 2 mm each way.")
    if W > 400 or H > 400:
        raise ValueError("The size is over 400 mm.")
    plan = o["colors"] or [{"id": c["id"], "hex": c["hex"], "skip": an.default_roles.get(c["id"]) == "hidden"}
                           for c in an.colors]
    plan = [c for c in plan if not c.get("skip") and c["id"] in an.regions]
    # shapes and pen drawings added on the page: colours of their own, sewn after the logo's
    shapes = _shape_regions(o.get("shapes"))
    plan += [{"id": cid, "hex": h} for cid, (h, _ps) in shapes.items()]
    if not plan:
        raise ValueError("Every colour is set to not be stitched.")
    puffed = set()
    if o["kind"] == "puff":     # puff colours are sewn last: the foam goes on over the finished flat work
        puffed = {c["id"] for c in plan} if o["puff"] is None else set(o["puff"]) & {c["id"] for c in plan}
        plan = [c for c in plan if c["id"] not in puffed] + [c for c in plan if c["id"] in puffed]
    # pieces: each colour's separate shapes, keyed "colour id:n" in a fixed order, as edited on the
    # page (moved, resized, turned, deleted; in image pixels, about the piece's centre)
    edits = o.get("edits") or {}
    pieces = {k: _edited(k, g, edits) for k, g in an.regions.items()}
    for cid, (_h, ps) in shapes.items():
        pieces[cid] = [(key, q) for key, q in ((key, _apply_edit(key, p, edits)) for key, p in ps) if q is not None]
    # a colour with no edits keeps its shape exactly as traced (rebuilt from its pieces it would differ a hair)
    edited = {k: (unary_union([p for _, p in ps]) if ps else Polygon())
              if k not in an.regions or any(e.startswith(k + ":") for e in edits) else an.regions[k]
              for k, ps in pieces.items()}
    # pieces given another thread on the page ({color: "#rrggbb"}): sewn with that thread, with a
    # colour of the logo that has it, else as a colour of their own right after the one they left
    added = {}
    for c in plan:
        own = [(key, p) for key, p in pieces.get(c["id"], []) if key.startswith(c["id"] + ":")]
        moved = [(key, p) for key, p in own if (edits.get(key) or {}).get("color")]
        if not moved:
            continue
        pieces[c["id"]] = [kp for kp in pieces[c["id"]] if kp not in moved]
        for key, p in moved:
            h = str(edits[key]["color"]).lower()
            same = next((d["id"] for d in plan if d["hex"].lower() == h and not d["id"].endswith("/background")), None)
            if same is None:
                same = "piece" + h
                if same not in added:
                    added[same] = {"after": c["id"], "hex": h}
                    pieces[same] = []
            pieces[same].append((key, p))
    for cid, x in added.items():
        at = next(i for i, d in enumerate(plan) if d["id"] == x["after"])
        plan.insert(at + 1, {"id": cid, "hex": x["hex"]})
        if x["after"] in puffed:
            puffed.add(cid)
    for k, ps in pieces.items():
        if k in added or any((edits.get(key) or {}).get("color") for key, _p in ps) or \
                any((edits.get(key) or {}).get("color") and key.startswith(k + ":") for key in edits):
            edited[k] = unary_union([p for _, p in ps]) if ps else Polygon()
    # arranged on the page (Bring to Front, Send to Back...): the pieces sewn in that order
    if o.get("arrange"):
        plan, pieces, edited = _arranged(plan, pieces, edited, [str(k) for k in o["arrange"]], puffed)
    regions = {c["id"]: edited[c["id"]] for c in plan}
    bg = [c["id"] for c in plan if c["id"].split("~")[0].endswith("/background")]
    if bg:      # the background colour is sewn only inside the logo (white stripes, a white star), not around it
        logo = unary_union([g for k, g in edited.items() if not k.endswith("/background")])
        r = 0.03 * max(an.width, an.height)
        env = Polygon() if logo.is_empty else unary_union([Polygon(p.exterior) for p in _parts(logo.buffer(r).buffer(-r))])
        for k in bg:
            regions[k] = shapely.make_valid(regions[k].intersection(env))
    geoms = [g for g in regions.values() if not g.is_empty]
    if not geoms:
        raise ValueError("Nothing to stitch: only the background is chosen.")
    bx0, by0, bx1, by1 = unary_union(geoms).bounds
    cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2

    def place(g):        # image pixels (y down) -> around the logo's centre (y up), turned by the tilt
        g = affinity.scale(affinity.translate(g, -cx, -cy), 1, -1, origin=(0, 0))
        return affinity.rotate(g, o["tilt"], origin=(0, 0)) if o["tilt"] else g
    placed = [place(regions[c["id"]]) for c in plan]
    ux0, uy0, ux1, uy1 = unary_union([g for g in placed if not g.is_empty]).bounds
    s = min(W / max(ux1 - ux0, 1e-9), H / max(uy1 - uy0, 1e-9))      # fitted into the box, turned
    if o.get("mm_per_px"):      # while editing: the scale stays, the design grows or shrinks with the edits
        s = float(o["mm_per_px"])
    mx, my = (ux0 + ux1) / 2, (uy0 + uy1) / 2
    mm = [shapely.make_valid(affinity.scale(affinity.translate(g, -mx, -my), s, s, origin=(0, 0)).simplify(0.04))
          for g in placed]

    sw = Sewing()
    colors, kinds, thin, tiny, small = [], {"satin": 0, "fill": 0}, 0, 0, 0
    stops, too_wide, tacked = [], 0, 0
    # the lines of the whole design (every colour's parts), so each colour sews them in the same order
    every = [(n, p) for n, g in enumerate(mm) for p in _parts(g) if p.area >= MIN_PART]
    line_of = dict(zip(((n, p.wkb) for n, p in every), text_lines([p for _, p in every])))
    for n, c in enumerate(plan):
        g = mm[n]
        parts = [p for p in _parts(g) if p.area >= MIN_PART]
        tiny += len(_parts(g)) - len(parts)
        if not parts:
            continue
        if colors:
            sw.trim()
            sw.out.append((sw.at[0], sw.at[1], COLOR)); sw.tied = False
        colors.append({"id": c["id"], "hex": c["hex"]})
        if o["tackdown"] and len(colors) == 1:      # under everything, in the first colour's thread
            whole = unary_union(mm)
            sw.router = Router(whole.buffer(o["pull_comp"] + 0.05))
            tack = tack_down(whole, 0.0)
            tacked = len(tack)
            sw.runs(tack)
        tops = [p.buffer(o["pull_comp"], join_style=1) if o["pull_comp"] else p for p in parts]
        later = unary_union(mm[n + 1:]).buffer(-0.4) if n + 1 < len(mm) else Polygon()
        order = cap_order(parts, o["order"], [line_of[(n, p.wkb)] for p in parts])
        small += sum(1 for p in parts if max(p.bounds[2] - p.bounds[0], p.bounds[3] - p.bounds[1]) < SMALL)
        thin += sum(1 for p in parts if _width(p) < THIN / 2)
        plans = {i: _puff_plan(tops[i]) for i in order} if c["id"] in puffed else {}
        puffs = [i for i in order if plans.get(i)]
        flat = [i for i in order if i not in puffs]
        too_wide += len(flat) if c["id"] in puffed else 0

        def router(left):
            # travel runs only where stitches still come: the parts of this colour not sewn yet
            # and the colours sewn later (they cover it), never over finished work
            sw.router = Router(unary_union([tops[j] for j in left] + [later]).buffer(0.05))
        for k, i in enumerate(flat):
            router(flat[k:] + puffs)
            kinds[_sew_part(sw, parts[i], tops[i], o, 0.0)] += 1
        if puffs:
            for k, i in enumerate(puffs):       # a centre run holds the cap before the foam goes on
                router(puffs)
                if plans[i] == "ring":
                    sw.runs(edge_run(parts[i], sw.at))
                    continue
                for p, kind in _puff_pieces(sw, tops[i], plans[i], o, 0.0, k == 0):
                    sw.runs(_puff_centre_run(p, kind, sw.at))
            sw.trim()                           # the machine stops: lay the foam, same thread
            sw.out.append((sw.at[0], sw.at[1], COLOR)); sw.tied = False
            colors.append({"id": c["id"], "hex": c["hex"], "stop": "foam"})
            stops.append(len(colors))
            for k, i in enumerate(puffs):
                router(puffs[k:])
                _sew_puff(sw, tops[i], plans[i], o, 0.0, k == 0)
                kinds["satin"] += 1
    if not sw.out:
        raise ValueError("Nothing to stitch at this size.")
    sw.trim()
    lift = 0.0
    if o["origin"] == "bottom":     # the needle starts at the bottom centre: everything sews above it
        lift = -min(p[1] for p in sw.out if p[2] == STITCH)
        sw.out = [(x, y + lift, c) for x, y, c in sw.out]
    sw.jump((0.0, 0.0))             # back to where the design started
    sw.out.append((0.0, 0.0, END))

    xs = [p[0] for p in sw.out if p[2] == STITCH]
    ys = [p[1] for p in sw.out if p[2] == STITCH]
    count = sum(1 for p in sw.out if p[2] == STITCH)
    notes = []
    w_mm, h_mm = max(xs) - min(xs), max(ys) - min(ys)
    crown = float(o["crown_mm"] or 0)
    if crown and h_mm > crown - 25.4 + 1:
        notes.append(f"The design is {h_mm / 25.4:.2f} in tall: on a {crown / 25.4:.2f} in crown keep it under "
                     f"{max(crown - 25.4, 0) / 25.4:.2f} in, about 1/2 in clear at the top and bottom.")
    elif h_mm > 57.2 + 1:
        notes.append(f"The design is {h_mm / 25.4:.2f} in tall: a cap's front panel usually takes 2.25 in at most.")
    if w_mm > 127 + 1:
        notes.append(f"The design is {w_mm / 25.4:.2f} in wide: a cap's front panel usually takes 4.5 to 5 in.")
    if small:
        notes.append(f"{small} part{'s are' if small > 1 else ' is'} under 0.25 in (small text or detail): "
                     "auto-digitizing may not sew it cleanly; check the preview, or have it digitized by hand.")
    if thin:
        notes.append(f"{thin} part{'s are' if thin > 1 else ' is'} under {THIN} mm wide and may not sew cleanly: "
                     "make the design larger or simplify those details.")
    if tiny:
        notes.append(f"{tiny} speck{'s' if tiny > 1 else ''} under {MIN_PART} mm² left out.")
    if stops:
        notes.append("The machine stops to lay the foam before " + ", ".join(f"colour {k}" for k in stops)
                     + ": set the same needle as the colour before it.")
    if too_wide:
        notes.append(f"{too_wide} puff part{'s are' if too_wide > 1 else ' is'} too wide for puff satin "
                     f"(over {PUFF_MAX:g} mm across): sewn flat before the foam. Tear the foam away there.")
    if o["tackdown"] and not tacked:
        notes.append("No tack-down underlay: no area of the design is large enough (about 5 × 5 mm) to hold it.")
    if o["kind"] == "puff" and not stops:
        notes.append("No colour is sewn as 3D puff: tick Puff on a colour.")
    info = {"stitches": count, "colors": len(colors), "stops": len(stops), "trims": sw.trims,
            "width_mm": round(w_mm, 1), "height_mm": round(h_mm, 1),
            "minutes": round(count / 650, 1), "satin_parts": kinds["satin"], "fill_parts": kinds["fill"],
            "aspect": round((ux1 - ux0) / max(uy1 - uy0, 1e-9), 6), "objects": sw.objects,   # the logo's own width / height (as fitted)
            "notes": notes}
    info["details"] = design_details(info)
    info["mm_per_px"] = s
    info["size_mm"] = [round((ux1 - ux0) * s, 2), round((uy1 - uy0) * s, 2)]     # the logo's own size, as placed
    # each piece's outline where it is sewn (0.1 mm, as the stitches), for selecting it on the page
    info["pieces"] = []
    for n, c in enumerate(plan):
        for key, p in pieces[c["id"]]:
            q = shapely.make_valid(affinity.scale(affinity.translate(place(p), -mx, -my), s, s, origin=(0, 0)))
            if c["id"] in bg:
                q = shapely.make_valid(q.intersection(mm[n]))
            for part in _parts(q):
                if part.area >= MIN_PART:
                    part = part.simplify(0.15)
                    pts = lambda ring: [[round(x * 10), round((y + lift) * 10)] for x, y in ring.coords]
                    info["pieces"].append({"key": key, "color": c["id"], "hex": c["hex"], "pts": pts(part.exterior),
                                           "holes": [pts(h) for h in part.interiors if Polygon(h).area >= MIN_PART]})
    # how image pixels are placed (for shapes drawn on the page): px -> centre (cx, cy), y up, turned
    # by tilt, less (mx, my), times s mm per px, plus lift
    info["frame"] = {"cx": cx, "cy": cy, "mx": mx, "my": my, "s": s, "tilt": o["tilt"], "lift": lift}
    return sw.out, colors, info


def sew_shape(geom, opts):
    """A shape drawn on an opened DST (geometry in mm), digitized as the logo's parts are: its
    stitches [(x, y, command)] in mm, from its first stitch to the last, trimmed."""
    o = {**DEFAULTS, **{k: v for k, v in (opts or {}).items() if v is not None}}
    o["density"] = min(max(float(o["density"]), 0.3), 0.8)
    o["pull_comp"] = min(max(float(o["pull_comp"]), 0.0), 0.6)
    _STROKES.clear()
    parts = [p for p in _parts(shapely.make_valid(geom)) if p.area >= MIN_PART]
    if not parts:
        raise ValueError("The shape is too small to sew.")
    sw = Sewing()
    tops = [p.buffer(o["pull_comp"], join_style=1) if o["pull_comp"] else p for p in parts]
    sw.router = Router(unary_union(tops).buffer(0.05))
    for i in cap_order(parts, o["order"]):
        _sew_part(sw, parts[i], tops[i], o, 0.0)
    sw.trim()
    first = next(i for i, p in enumerate(sw.out) if p[2] == STITCH)
    return sw.out[first:]


def _apply_edit(key, p, edits):
    """A piece (polygon in image pixels) as its edit leaves it, or None when it is deleted. The edit:
    dx, dy, and m [a, b, c, d] (x' = a x + b y, y' = c x + d y about its centre), or an older edit's
    scale and rotate."""
    e = edits.get(key)
    if not e:
        return p
    if e.get("deleted"):
        return None
    c = p.centroid
    m = e.get("m")
    if isinstance(m, (list, tuple)) and len(m) == 4:      # its resize and turn (a stretch too), image pixels
        a, b, cc, d = (float(v) for v in m)
        if abs(a * d - b * cc) < 1e-4:
            return None
        p = affinity.affine_transform(p, [a, b, cc, d, c.x - a * c.x - b * c.y, c.y - cc * c.x - d * c.y])
        return affinity.translate(p, float(e.get("dx") or 0), float(e.get("dy") or 0))
    if float(e.get("scale") or 1) != 1:
        p = affinity.scale(p, float(e["scale"]), float(e["scale"]), origin=c)
    if float(e.get("rotate") or 0):
        p = affinity.rotate(p, -float(e["rotate"]), origin=c)       # image y is down
    return affinity.translate(p, float(e.get("dx") or 0), float(e.get("dy") or 0))


def _shape_regions(shapes):
    """Shapes and pen drawings added on the page, as colours of their own: {colour id: (hex,
    [(key, polygon in image pixels)])}. A shape: {id, hex, pts [[x, y] px], closed, width (px, an
    open line's width), rings (a shape made with the Pathfinder: its outlines, filled even-odd, so
    a ring inside another is a hole)}. A closed outline is filled; an open line is a column `width`
    wide, round at its ends (sewn as a satin that follows it). The keys stay with their shape."""
    out = {}
    for sh in shapes or []:
        h = str(sh.get("hex") or "").lower()
        pts = [(float(x), float(y)) for x, y in sh.get("pts") or []]
        if not re.fullmatch(r"#[0-9a-f]{6}", h) or len(pts) < 2:
            continue
        if sh.get("rings"):
            g = Polygon()
            for r in sh["rings"]:
                if len(r) >= 3:
                    g = g.symmetric_difference(shapely.make_valid(Polygon([(float(x), float(y)) for x, y in r])))
        elif sh.get("closed") and len(pts) >= 3:
            g = shapely.make_valid(Polygon(pts))
        else:
            g = LineString(pts).buffer(max(float(sh.get("width") or 1), 0.5) / 2, cap_style=1, join_style=1)
        parts = sorted((p for p in _parts(g) if p.area > 1.0), key=lambda p: -p.area)
        cid = "shape" + h
        for j, p in enumerate(parts):
            out.setdefault(cid, (h, []))[1].append((f"{cid}:s{sh.get('id')}" + (f".{j}" if j else ""), p))
    return out


def _arranged(plan, pieces, edited, arrange, puffed):
    """The pieces sewn in the order arranged on the page (keys, first sewn first). A piece not in it
    (drawn since, or a further part of one) goes right after the piece it is part of, else last. A
    colour whose pieces are no longer together is sewn in blocks, one for each run of its pieces
    ("<id>~1", "<id>~2"... after the first): each a colour change of its own. Puff colours stay
    last (the foam goes on over the finished flat work)."""
    seq = [(c["id"], key, p) for c in plan for key, p in pieces.get(c["id"], [])]
    rank = {k: i for i, k in enumerate(arrange)}

    def where(i):
        key = seq[i][1]
        if key in rank:
            return (rank[key], 0, i)
        base = key.split(".")[0]
        return (rank[base], 1, i) if base in rank else (len(rank), 0, i)
    order = sorted(range(len(seq)), key=where)
    if puffed:
        order = [i for i in order if seq[i][0] not in puffed] + [i for i in order if seq[i][0] in puffed]
    entry = {c["id"]: c for c in plan}
    new_plan, new_pieces, runs, prev = [], {}, {}, None
    for i in order:
        cid, key, p = seq[i]
        if cid != prev:
            n = runs.get(cid, 0)
            runs[cid] = n + 1
            bid = cid if n == 0 else f"{cid}~{n}"
            new_plan.append({**entry[cid], "id": bid})
            new_pieces[bid] = []
            if cid in puffed:
                puffed.add(bid)
            prev = cid
        new_pieces[new_plan[-1]["id"]].append((key, p))
    new_edited = dict(edited)
    for c in new_plan:          # a colour still sewn in one block keeps its shape as it was
        base = c["id"].split("~")[0]
        if runs[base] > 1:
            new_edited[c["id"]] = unary_union([p for _, p in new_pieces[c["id"]]])
    return new_plan, new_pieces, new_edited


PATHFINDER = ("unite", "minus", "intersect", "exclude")


def pathfinder(op, shapes, edits=None):
    """Shapes drawn on the page combined, as Illustrator's Pathfinder: shapes as _shape_regions takes
    them, back to front, each where its edits put it. unite: all of them as one; minus: the back one
    less every other; intersect: where they all overlap; exclude: where an odd number of them lie.
    The result's rings (image pixels): each part's outline, then its holes."""
    if op not in PATHFINDER:
        raise ValueError("Unknown Pathfinder option.")
    geoms = []
    for sh in shapes or []:
        parts = [_apply_edit(key, q, edits or {}) for _h, ps in _shape_regions([sh]).values() for key, q in ps]
        g = unary_union([q for q in parts if q is not None])
        if not g.is_empty:
            geoms.append(g)
    if len(geoms) < 2:
        raise ValueError("Select two or more shapes you drew.")
    if op == "unite":
        out = unary_union(geoms)
    elif op == "minus":
        out = geoms[0].difference(unary_union(geoms[1:]))
    elif op == "intersect":
        out = geoms[0]
        for g in geoms[1:]:
            out = out.intersection(g)
    else:
        out = geoms[0]
        for g in geoms[1:]:
            out = out.symmetric_difference(g)
    rings = []
    for part in _parts(shapely.make_valid(out)):
        if part.area <= 1.0:
            continue
        for ring in [part.exterior, *part.interiors]:
            rings.append([[round(x, 2), round(y, 2)] for x, y in list(ring.coords)[:-1]])
    if not rings:
        raise ValueError("Nothing is left: the shapes do not overlap that way.")
    return rings


def _edited(color_id, g, edits):
    """A colour's pieces [(key, polygon in image pixels)], each as edited: edits {key: {dx, dy (px),
    scale, rotate (degrees, anticlockwise as seen), deleted}}. The keys follow a fixed order of the
    original pieces (top to bottom, left to right), so an edit keeps pointing at its piece."""
    ps = sorted(_parts(g), key=lambda p: (round(p.bounds[1]), round(p.bounds[0]), -p.area))
    out = []
    for n, p in enumerate(ps):
        key = f"{color_id}:{n}"
        p = _apply_edit(key, p, edits)
        if p is not None:
            out.append((key, p))
    return out


def design_details(info):
    """The design's details as Wilcom's Design Information lists them: [(label, value)]. Stops are
    the colour blocks (Wilcom: 3 colours, 2 colour changes, 3 stops); a foam stop is one more."""
    threads = info["colors"] - info["stops"]
    return [("Height", f"{info['height_mm'] / 25.4:.2f} in"), ("Width", f"{info['width_mm'] / 25.4:.2f} in"),
            ("Stitches", f"{info['stitches']:,}"), ("Colors", threads), ("Stops", info["colors"]),
            ("Colorways", 1), ("Trims", info["trims"]), ("Color changes", max(0, info["colors"] - 1)),
            ("Appliqués", 0), ("Sequins", 0), ("Bling", 0), ("Machine format", "Tajima"),
            ("Objects", info.get("objects", 0))]


# ---------------------------------------------------------------------------
# DST

def _record(dx, dy, flag=0):
    """One Tajima record: dx, dy in 0.1 mm (each -121..121, y up); flag 0 stitch, 1 jump, 3 colour change."""
    b0 = b1 = b2 = 0
    x, y = dx, dy
    # x: +81 b2.2, -81 b2.3, +27 b1.2, -27 b1.3, +9 b0.2, -9 b0.3, +3 b1.0, -3 b1.1, +1 b0.0, -1 b0.1
    if x > 40: b2 |= 0x04; x -= 81
    if x < -40: b2 |= 0x08; x += 81
    if x > 13: b1 |= 0x04; x -= 27
    if x < -13: b1 |= 0x08; x += 27
    if x > 4: b0 |= 0x04; x -= 9
    if x < -4: b0 |= 0x08; x += 9
    if x > 1: b1 |= 0x01; x -= 3
    if x < -1: b1 |= 0x02; x += 3
    if x > 0: b0 |= 0x01; x -= 1
    if x < 0: b0 |= 0x02; x += 1
    # y: +81 b2.5, -81 b2.4, +27 b1.5, -27 b1.4, +9 b0.5, -9 b0.4, +3 b1.7, -3 b1.6, +1 b0.7, -1 b0.6
    if y > 40: b2 |= 0x20; y -= 81
    if y < -40: b2 |= 0x10; y += 81
    if y > 13: b1 |= 0x20; y -= 27
    if y < -13: b1 |= 0x10; y += 27
    if y > 4: b0 |= 0x20; y -= 9
    if y < -4: b0 |= 0x10; y += 9
    if y > 1: b1 |= 0x80; y -= 3
    if y < -1: b1 |= 0x40; y += 3
    if y > 0: b0 |= 0x80; y -= 1
    if y < 0: b0 |= 0x40; y += 1
    assert x == 0 and y == 0, "DST step too large"
    if flag == 1:
        b2 |= 0x80
    elif flag == 3:
        b2 |= 0xC0
    return bytes((b0, b1, b2 | 0x03))


def _decode(rec):
    """dx, dy, flag of one record (for checking files)."""
    b0, b1, b2 = rec
    if b2 == 0xF3 and b0 == b1 == 0:
        return 0, 0, "end"
    x = y = 0
    for b, v, bit in ((b2, 81, 2), (b1, 27, 2), (b0, 9, 2), (b1, 3, 0), (b0, 1, 0)):
        x += v * ((b >> bit) & 1) - v * ((b >> (bit + 1)) & 1)
    for b, v, bit in ((b2, 81, 5), (b1, 27, 5), (b0, 9, 5), (b1, 3, 7), (b0, 1, 7)):
        y += v * ((b >> bit) & 1) - v * ((b >> (bit - 1)) & 1)
    flag = "color" if b2 & 0xC0 == 0xC0 else "jump" if b2 & 0x80 else "stitch"
    return x, y, flag


def write_dst(stitches, name="cap") -> bytes:
    body = bytearray()
    px = py = 0                     # where the frame is, 0.1 mm
    count = colors = 0
    minx = maxx = miny = maxy = 0

    def move(tx, ty, flag, n=1, land=False):
        """To (tx, ty) in at least n equal steps of at most JUMP_STEP; land: the last step is a
        stitch (the needle goes in where it arrives)."""
        nonlocal px, py, count, minx, maxx, miny, maxy
        dx, dy = tx - px, ty - py
        n = max(n, math.ceil(math.hypot(dx, dy) / (JUMP_STEP if flag else 121)))
        cx, cy = px, py
        for i in range(1, n + 1):
            sx, sy = px + round(dx * i / n), py + round(dy * i / n)
            body.extend(_record(sx - cx, sy - cy, 0 if land and i == n else flag)); count += 1
            cx, cy = sx, sy
            minx, maxx, miny, maxy = min(minx, cx), max(maxx, cx), min(miny, cy), max(maxy, cy)
        px, py = tx, ty

    # a trim is written as Wilcom writes it: at least three jumps on the way to the next stitch
    # (the machine trims on three jumps in a row), the needle going in where they arrive
    trim, to = False, None          # a trim waiting; where the frame is to jump
    for x, y, cmd in stitches:
        tx, ty = round(x * 10), round(y * 10)
        if cmd == JUMP:
            to = (tx, ty); continue
        if cmd == TRIM:
            trim = True; continue
        if to is not None:          # the jump, now that the next stitch is known
            if to != (px, py):
                move(*to, 1, n=4 if trim and cmd != COLOR else 1, land=cmd == STITCH)
                trim = trim and cmd == COLOR
            to = None
        if trim and cmd in (COLOR, END, STITCH):      # a trim with nowhere to go: three jumps in place
            for dx, dy in ((2, 2), (-4, -4), (2, 2)):
                body.extend(_record(dx, dy, 1)); count += 1
            minx, maxx, miny, maxy = min(minx, px - 2), max(maxx, px + 2), min(miny, py - 2), max(maxy, py + 2)
            trim = False
        if cmd == STITCH:
            if math.hypot(tx - px, ty - py) >= 3:         # stitches under 0.3 mm are left out (Wilcom's minimum)
                move(tx, ty, 0)
        elif cmd == COLOR:
            body.extend(_record(0, 0, 3)); count += 1; colors += 1
        elif cmd == END:
            break
    body.extend(b"\x00\x00\xF3"); count += 1      # the end record counts, and an end-of-file byte follows
    label = "".join(ch for ch in name if 32 <= ord(ch) < 127)[:16] or "cap"
    head = (f"LA:{label:<16}\r" f"ST:{count:7d}\r" f"CO:{colors:3d}\r"
            f"+X:{abs(maxx):5d}\r" f"-X:{abs(minx):5d}\r" f"+Y:{abs(maxy):5d}\r" f"-Y:{abs(miny):5d}\r"
            f"AX:{'+' if px >= 0 else '-'}{abs(px):5d}\r" f"AY:{'+' if py >= 0 else '-'}{abs(py):5d}\r"
            f"MX:+{0:5d}\r" f"MY:+{0:5d}\r" "PD:******\r").encode("ascii") + b"\x1a"
    return head.ljust(512, b" ") + bytes(body) + b"\x1a"


def read_dst(data: bytes):
    """Absolute points of a DST file, [(x, y, flag)] in 0.1 mm (for checking)."""
    x = y = 0
    out = []
    for i in range(512, len(data) - 2, 3):
        dx, dy, f = _decode(data[i:i + 3])
        if f == "end":
            break
        x += dx; y += dy
        out.append((x, y, f))
    return out


DST_COLOURS = ["#1d1d1b", "#c8102e", "#1f2a9c", "#f2c200", "#0a7d3e", "#f4f4f4", "#e5741f", "#7a2a8c",
               "#5b3a1e", "#8a8d8f", "#00a3c4", "#e75480"]      # a DST has no colours: these, in order


def stitches_from_dst(data: bytes):
    """A DST file as stitches [(x mm, y mm, command)], as the digitizer makes them: three or more
    jumps in a row are a trim and a jump; a colour change is a COLOR. Raises ValueError."""
    if len(data) < 515 or not data[:3].startswith(b"LA:"):
        raise ValueError("This is not a Tajima DST file.")
    out, run = [], []
    for x, y, f in read_dst(data):
        if f == "jump":
            run.append((x, y)); continue
        if run:
            if len(run) >= 3 and out:
                out.append((out[-1][0], out[-1][1], TRIM))
            out.append((run[-1][0] / 10, run[-1][1] / 10, JUMP)); run = []
        out.append((x / 10, y / 10, STITCH if f == "stitch" else COLOR))
    if not any(c == STITCH for _, _, c in out):
        raise ValueError("This DST file has no stitches.")
    out.append((out[-1][0], out[-1][1], END))
    return out


def stitch_info(stitches, colors, notes=()):
    """The totals of a finished stitch list (a DST opened and edited on the page), as digitize()
    gives them for a logo."""
    xs = [p[0] for p in stitches if p[2] == STITCH]
    ys = [p[1] for p in stitches if p[2] == STITCH]
    count = len(xs)
    w, h = (max(xs) - min(xs), max(ys) - min(ys)) if xs else (0.0, 0.0)
    stops = sum(1 for c in colors if c.get("stop"))
    info = {"stitches": count, "colors": len(colors), "stops": stops,
            "trims": sum(1 for p in stitches if p[2] == TRIM), "width_mm": round(w, 1), "height_mm": round(h, 1),
            "minutes": round(count / 650, 1), "satin_parts": 0, "fill_parts": 0, "notes": list(notes),
            "aspect": round(w / h, 6) if h else 1.0, "objects": len(colors), "size_mm": [round(w, 2), round(h, 2)]}
    info["details"] = design_details(info)
    return info


# ---------------------------------------------------------------------------
# thread suggestions

def _lab(hexes):
    rgb = np.array([engine.hex_to_rgb(h) for h in hexes], np.float64)
    return engine._rgb_to_lab(rgb)


def delta_e2000(lab1, lab2):
    """CIEDE2000 between one colour lab1 (3,) and many lab2 (n, 3)."""
    L1, a1, b1 = lab1
    L2, a2, b2 = lab2[:, 0], lab2[:, 1], lab2[:, 2]
    C1, C2 = math.hypot(a1, b1), np.hypot(a2, b2)
    Cb = (C1 + C2) / 2
    G = 0.5 * (1 - np.sqrt(Cb ** 7 / (Cb ** 7 + 25 ** 7)))
    a1p, a2p = (1 + G) * a1, (1 + G) * a2
    C1p, C2p = np.hypot(a1p, b1), np.hypot(a2p, b2)
    h1p = np.degrees(np.arctan2(b1, a1p)) % 360
    h2p = np.degrees(np.arctan2(b2, a2p)) % 360
    dLp, dCp = L2 - L1, C2p - C1p
    dh = h2p - h1p
    dh = np.where(dh > 180, dh - 360, np.where(dh < -180, dh + 360, dh))
    dh = np.where(C1p * C2p == 0, 0, dh)
    dHp = 2 * np.sqrt(C1p * C2p) * np.sin(np.radians(dh / 2))
    Lbp, Cbp = (L1 + L2) / 2, (C1p + C2p) / 2
    hs = h1p + h2p
    hbp = np.where(C1p * C2p == 0, hs, np.where(np.abs(h1p - h2p) > 180, np.where(hs < 360, (hs + 360) / 2, (hs - 360) / 2), hs / 2))
    T = (1 - 0.17 * np.cos(np.radians(hbp - 30)) + 0.24 * np.cos(np.radians(2 * hbp))
         + 0.32 * np.cos(np.radians(3 * hbp + 6)) - 0.20 * np.cos(np.radians(4 * hbp - 63)))
    dth = 30 * np.exp(-(((hbp - 275) / 25) ** 2))
    Rc = 2 * np.sqrt(Cbp ** 7 / (Cbp ** 7 + 25 ** 7))
    Sl = 1 + 0.015 * (Lbp - 50) ** 2 / np.sqrt(20 + (Lbp - 50) ** 2)
    Sc, Sh = 1 + 0.045 * Cbp, 1 + 0.015 * Cbp * T
    Rt = -np.sin(np.radians(2 * dth)) * Rc
    return np.sqrt((dLp / Sl) ** 2 + (dCp / Sc) ** 2 + (dHp / Sh) ** 2 + Rt * (dCp / Sc) * (dHp / Sh))


def nearest_threads(hexes, book, n=6):
    """For each colour, the n nearest threads of a chart: [[{num, name, hex, de}]]."""
    threads = [(num, name, hx) for num, name, hx in book["colors"] if hx]
    lab_t = _lab([t[2] for t in threads])
    out = []
    for lab in _lab(hexes):
        de = delta_e2000(lab, lab_t)
        idx = np.argsort(de)[:n]
        out.append([{"num": threads[i][0], "name": threads[i][1], "hex": threads[i][2].lower(), "de": round(float(de[i]), 2)}
                    for i in idx])
    return out


# ---------------------------------------------------------------------------
# preview: the stitches drawn as thread, with the sewing order underneath

LIGHT = math.radians(60)    # the preview's light: thread lying across it shines, along it is darker


def thread_shades(col, angle, vary=1.0):
    """A stitch drawn as a thread, as Wilcom's realistic view: its shaded edge, its body and the
    sheen along its middle, lit by the way it lies; vary: this stitch a shade lighter or darker
    (real thread is never even). A black thread shows dark grey with a grey sheen (it would be a
    flat black line); a white one keeps a grey edge (it would vanish)."""
    lift = max(0.0, 58 - 0.299 * col[0] - 0.587 * col[1] - 0.114 * col[2])    # very dark threads
    f = (0.82 + 0.18 * abs(math.cos(angle - LIGHT))) * vary
    edge = tuple(min(255, int((v * 0.84 + lift * 0.8) * f)) for v in col)
    body = tuple(min(255, int((v * 0.96 + lift) * f)) for v in col)
    sheen = tuple(min(255, int((v + (255 - v) * 0.2 + lift * 1.4) * f)) for v in col)
    return edge, body, sheen


def satin_pair(a, b, c, k):
    """Are a->b and b->c two stitches of a satin (or a fill turning at its edge): each over 0.5 mm,
    the second going back across, at most 1.2 mm from the first? (k: units per mm)"""
    ux, uy, vx, vy = b[0] - a[0], b[1] - a[1], c[0] - b[0], c[1] - b[1]
    lu, lv = math.hypot(ux, uy), math.hypot(vx, vy)
    if lu < 0.5 * k or lv < 0.5 * k or ux * vx + uy * vy >= 0:
        return False
    gap = abs(ux * (c[1] - a[1]) - uy * (c[0] - a[0])) / lu        # c from the line a-b
    return gap <= 1.2 * k


def render_design(stitches, colors, cap=None, ppm=14, box=None):
    """The stitches drawn as thread, as Wilcom's realistic view (each stitch a lit thread, the
    design casting a soft shadow), on white (no background behind the logo) or on the cap
    colour `cap`: (image, its box in mm (x0, y0, x1, y1))."""
    from PIL import ImageFilter
    pts = [p for p in stitches if p[2] in (STITCH, JUMP)]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0, x1, y1 = box or (min(xs) - 3, min(ys) - 3, max(xs) + 3, max(ys) + 3)
    ss = 3                                     # drawn three times as large, then reduced: fine threads
    k = ppm * ss
    W, H = int((x1 - x0) * k), int((y1 - y0) * k)
    bg = engine.hex_to_rgb(cap) if cap else (255, 255, 255)
    art = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(art)
    P = lambda x, y: ((x - x0) * k, (y1 - y) * k)
    rgb = [engine.hex_to_rgb(c["hex"]) for c in colors]
    puff = [c.get("stop") == "foam" for c in colors]
    if not cap:     # on white, a light thread's sheen would vanish: drawn a shade darker (as Wilcom's colour film)
        rgb = [tuple(int(v * 0.8) for v in col) if 0.299 * col[0] + 0.587 * col[1] + 0.114 * col[2] > 200 else col
               for col in rgb]
    # thread as Wilcom draws it: each colour first filled in its thread's shade where the thread
    # covers (the thin triangle between a satin stitch and the next one going back: thread spreads
    # when sewn, so a satin is solid), then each stitch as a fine thread (0.12 mm) with a sheen, lit
    # by the way it lies and a shade lighter or darker
    w_base, w_thread, w_sheen = max(1, round(0.2 * k)), max(1, round(0.12 * k)), max(1, round(0.04 * k))
    w_fill = max(1, round(0.44 * k))           # a fill's rows are 0.4 mm apart: its stitches cover that
    rnd = __import__("random").Random(7)       # the same streaks every time
    blocks, ci, prev = [[]], 0, None
    for x, y, c in stitches:
        if c == COLOR:
            ci = min(ci + 1, len(rgb) - 1); prev = (x, y); blocks.append([]); continue
        if c == STITCH and prev is not None:
            blocks[-1].append((P(*prev), P(x, y), ci, math.atan2(y - prev[1], x - prev[0])))
        prev = (x, y)
    for lines in blocks:
        if not lines:
            continue
        if puff[lines[0][2]]:
            # puff satin (a stitch every 0.15 mm on each side) piles up into one smooth surface: the
            # stitches over the foam are drawn as sheen only, lit by the way they lie, as Wilcom's
            # preview: strokes sewn at different angles stand apart
            for a, b, i, angle in lines:
                shade = 0.74 + 0.26 * abs(math.cos(angle - LIGHT))
                g.line([a, b], fill=tuple(min(255, int((v * 1.08 + 12) * shade)) for v in rgb[i]), width=w_base)
            continue
        # in sewing order, as the thread lies: each stitch (the parts of a split stitch, a long satin
        # stitch sewn in two or three in line, joined) with the cover between it and the next one going
        # back across filled first, then its thread, so later stitches cover the underlay as sewn
        whole = []
        for a, b, i, angle in lines:
            w = whole[-1] if whole else None
            if w and w[1] == a and abs(math.remainder(angle - w[3], 2 * math.pi)) < 0.2:
                whole[-1] = (w[0], b, w[2], w[3], w[4] + [(a, b, i, angle)])
            else:
                whole.append((a, b, i, angle, [(a, b, i, angle)]))
        for j, (a, b, i, angle, parts) in enumerate(whole):
            if j + 1 < len(whole) and whole[j + 1][0] == b and satin_pair(a, b, whole[j + 1][1], k):
                g.polygon([a, b, whole[j + 1][1]], fill=tuple(int(v * 0.9) for v in thread_shades(rgb[i], angle)[1]))
            # a stitch over 1 mm covers the width of its row (a fill's rows, a satin's stitches lie
            # 0.2-0.4 mm apart): its base in the thread's shade, the fine thread over it
            wide = math.dist(a, b) > k
            for pa, pb, pi, pang in parts:
                edge, body, sheen = thread_shades(rgb[pi], pang, 0.94 + 0.12 * rnd.random())
                g.line([pa, pb], fill=tuple(int(v * 0.92) for v in (body if wide else edge)), width=w_fill if wide else w_base)
                g.line([pa, pb], fill=body, width=w_thread)
                g.line([pa, pb], fill=sheen, width=w_sheen)
    # the design stands a little off the fabric: a soft shadow down and to the right
    alpha = art.getchannel("A")
    shadow = alpha.filter(ImageFilter.GaussianBlur(0.35 * k)).point(lambda v: v * 0.35)
    off = round(0.25 * k)
    im = Image.new("RGB", (W, H), bg)
    im.paste((60, 60, 60), (off, off), shadow.crop((0, 0, W - off, H - off)))
    im.paste(art, (0, 0), art)
    return im.resize((W // ss, H // ss), Image.LANCZOS), (x0, y0, x1, y1)


def render_png(stitches, colors, info, cap=None, ppm=14, title="") -> bytes:
    """colors: [{hex, label}] in sewing order. A PNG: the stitches as thread (on white, or on
    the cap colour `cap`); under it the design's details in a row, as Wilcom's Design Information
    lists them; then one line per thread (the order to load the needles)."""
    import io
    from PIL import ImageFont
    im, _box = render_design(stitches, colors, cap, ppm)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 18)
        bold = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 20)
        small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 16)
        value = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 16)
    except OSError:             # not on a Mac: Pillow's own font, at the same sizes
        font, bold, small, value = (ImageFont.load_default(size=n) for n in (18, 20, 16, 16))
    pad, line = 24, 30
    width = max(im.width + 2 * pad, 760)
    # the details, label and value side by side, wrapped into rows across the width
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    cells, rows_, x = [], [[]], pad
    for label, v in info.get("details") or design_details(info):
        w = probe.textlength(f"{label}: ", font=small) + probe.textlength(str(v), font=value) + 26
        if x + w > width - pad and rows_[-1]:
            rows_.append([]); x = pad
        rows_[-1].append((x, f"{label}: ", str(v))); x += w
    detail_h = len(rows_) * 26 + 18
    sheet = Image.new("RGB", (width, im.height + 2 * pad + detail_h + (len(colors) + 1) * line + pad), (255, 255, 255))
    sheet.paste(im, ((sheet.width - im.width) // 2, pad))
    d = ImageDraw.Draw(sheet)
    y = im.height + pad + 8
    d.line([pad, y, width - pad, y], fill=(225, 226, 230), width=1)
    y += 10
    for row in rows_:
        for x, label, v in row:
            d.text((x, y), label, font=small, fill=(100, 104, 114))
            d.text((x + d.textlength(label, font=small), y), v, font=value, fill=(20, 22, 28))
        y += 26
    d.line([pad, y + 2, width - pad, y + 2], fill=(225, 226, 230), width=1)
    y += pad
    d.text((pad, y), title or "Cap embroidery", font=bold, fill=(20, 22, 28)); y += line
    for i, c in enumerate(colors):
        d.rectangle([pad, y + 2, pad + 22, y + 22], fill=engine.hex_to_rgb(c["hex"]), outline=(120, 120, 120))
        text = f"{i + 1}. {c.get('label') or c['hex']}"
        if c.get("stop") == "foam":
            text = f"{i + 1}. Stop: lay the foam, then the same thread (3D puff)"
        d.text((pad + 32, y + 2), text, font=font, fill=(20, 22, 28)); y += line
    buf = io.BytesIO(); sheet.save(buf, "PNG")
    return buf.getvalue()
