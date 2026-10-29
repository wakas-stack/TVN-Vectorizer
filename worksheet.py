"""Production worksheet for a cap DST, as a PDF laid out like Wilcom EmbroideryStudio's.

Page 1: the design as stitched, with the machine's start (1, green) and end (2, red) marked by
cross lines; beside it the totals (stitches, colours, colour changes, stops, machine, trims),
the extents left / right / up / down of the start, the end point, the longest and shortest
stitch and the longest jump, then the threads in needle order with their stitches, code and
brand, and the bobbin thread. Page 2 ("Color Film"): each colour on its own, with its thread
and how much of it is used.

Thread used is estimated from the stitch lengths: top thread 2.1 x and bobbin 0.8 x the
length sewn, which is what a Wilcom worksheet gives for a cap logo (calibrated on one file).
The PDF is written directly: Helvetica text, vector lines, the design as one image.
"""

from __future__ import annotations

import datetime
import math
import zlib

import digitize as d
import engine

TOP_PER_MM = 2.1        # top thread per mm sewn
BOBBIN_PER_MM = 0.8
FT = 304.8              # mm in a foot
PAGE_W, PAGE_H = 612, 792
PANEL_X = 418           # the stats panel starts here (points)


def _esc(s: str) -> bytes:
    s = str(s).replace("–", "-").replace("—", "-").replace("’", "'")
    b = s.encode("cp1252", "replace")
    return b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)")


class _Page:
    def __init__(self):
        self.ops = []

    def text(self, x, y, s, size=10, bold=False, rgb=(0, 0, 0)):
        self.ops.append(b"BT /%s %g Tf %.3f %.3f %.3f rg %.2f %.2f Td (" % (b"F2" if bold else b"F1", size, *rgb, x, y)
                        + _esc(s) + b") Tj ET")

    def line(self, x0, y0, x1, y1, rgb=(0, 0, 0), w=0.5):
        self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f m %.2f %.2f l S" % (*rgb, w, x0, y0, x1, y1))

    def rect(self, x, y, w, h, stroke=(0, 0, 0), fill=None, lw=0.5):
        if fill:
            self.ops.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f" % (*fill, x, y, w, h))
        if stroke:
            self.ops.append(b"%.3f %.3f %.3f RG %.2f w %.2f %.2f %.2f %.2f re S" % (*stroke, lw, x, y, w, h))

    def polyline(self, pts, rgb, w=0.3):
        if len(pts) < 2:
            return
        out = [b"%.3f %.3f %.3f RG %.2f w 1 J 1 j %.2f %.2f m" % (*rgb, w, *pts[0])]
        out += [b"%.2f %.2f l" % p for p in pts[1:]]
        self.ops.append(b" ".join(out) + b" S")

    def image(self, name, x, y, w, h):
        self.ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (w, h, x, y, name.encode()))


def _pdf(pages, images) -> bytes:
    """pages: [_Page]; images: {name: PIL RGB image} (drawn on page 1)."""
    objs = []

    def add(b):
        objs.append(b)
        return len(objs)
    f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
    f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
    xo = {}
    for name, im in images.items():
        raw = zlib.compress(im.convert("RGB").tobytes(), 6)
        xo[name] = add(b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace /DeviceRGB "
                       b"/BitsPerComponent 8 /Filter /FlateDecode /Length %d >>\nstream\n" % (im.width, im.height, len(raw))
                       + raw + b"\nendstream")
    res = (b"<< /Font << /F1 %d 0 R /F2 %d 0 R >> /XObject << " % (f1, f2)
           + b" ".join(b"/%s %d 0 R" % (n.encode(), i) for n, i in xo.items()) + b" >> >>")
    pages_id = len(objs) + 1 + 2 * len(pages)
    kids = []
    for p in pages:
        body = zlib.compress(b"\n".join(p.ops), 6)
        c = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(body) + body + b"\nendstream")
        kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %d %d] /Resources %s /Contents %d 0 R >>"
                        % (pages_id, PAGE_W, PAGE_H, res, c)))
    assert add(b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % k for k in kids) + b"] /Count %d >>" % len(kids)) == pages_id
    cat = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offs = []
    for i, b in enumerate(objs, 1):
        offs.append(len(out))
        out += b"%d 0 obj\n" % i + b + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offs)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, cat, xref)
    return bytes(out)


def stats(dst: bytes, stitches, colors, info):
    """The worksheet's figures, from the DST file as the machine reads it."""
    head = dst[:512].decode("ascii", "replace")
    field = lambda k: head.split(k + ":", 1)[1].split("\r", 1)[0].strip()
    pts = d.read_dst(dst)
    st, jp = [], []
    for i in range(1, len(pts)):
        L = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1]) / 10
        if L > 0:
            (st if pts[i][2] == "stitch" else jp if pts[i][2] == "jump" else []).append(L)
    changes = int(field("CO"))
    foam = sum(1 for c in colors if c.get("stop"))
    per = []                    # mm sewn per colour block
    ci, prev, acc = 0, None, [0.0] * len(colors)
    for x, y, c in stitches:
        if c == d.COLOR:
            ci = min(ci + 1, len(colors) - 1); prev = (x, y); continue
        if c == d.STITCH and prev is not None:
            acc[ci] += math.dist(prev, (x, y))
        prev = (x, y)
    counts = [0] * len(colors)
    ci = 0
    for x, y, c in stitches:
        if c == d.COLOR:
            ci = min(ci + 1, len(colors) - 1)
        elif c == d.STITCH:
            counts[ci] += 1
    return {
        "stitches": int(field("ST")), "colors": len(colors) - foam, "changes": changes - foam,
        "stops": changes + 1, "trims": info["trims"],
        "left": int(field("-X")) / 10, "right": int(field("+X")) / 10, "up": int(field("+Y")) / 10,
        "down": int(field("-Y")) / 10,
        "endx": int(field("AX").replace("+", "").replace(" ", "")) / 254,
        "endy": int(field("AY").replace("+", "").replace(" ", "")) / 254,
        "max_stitch": max(st, default=0), "min_stitch": min(st, default=0), "max_jump": max(jp, default=0),
        "top_ft": [a * TOP_PER_MM / FT for a in acc], "bobbin_ft": sum(acc) * BOBBIN_PER_MM / FT,
        "block_stitches": counts,
    }


def _rgb(hex_):
    r, g, b = engine.hex_to_rgb(hex_)
    return r / 255, g / 255, b / 255


def worksheet_pdf(stitches, colors, info, dst: bytes, name="cap", chart="", cap=None, notes=(),
                  settings=(), app="EMB Pros - DST Maker") -> bytes:
    """colors: [{hex, code, name, brand, stop}] in sewing order (as digitize returns them, with
    the thread's details). settings: [(label, value)] shown under the totals."""
    s = stats(dst, stitches, colors, info)
    now = datetime.datetime.now()
    w_in, h_in = info["width_mm"] / 25.4, info["height_mm"] / 25.4
    needles, nums = {}, []
    for c in colors:            # a foam stop uses the same needle as the colour before it
        key = (c.get("code"), c["hex"])
        if key not in needles:
            needles[key] = len(needles) + 1
        nums.append(needles[key])

    def frame(p, title_right):
        p.rect(6, 6, PAGE_W - 12, PAGE_H - 12, stroke=(0.7, 0.7, 0.7))
        p.line(6, PAGE_H - 26, PAGE_W - 6, PAGE_H - 26, (0.7, 0.7, 0.7))
        p.line(6, 26, PAGE_W - 6, 26, (0.7, 0.7, 0.7))
        p.text(12, PAGE_H - 20, app, 10)
        p.text(300, PAGE_H - 20, name[:34], 10)
        p.text(PAGE_W - 12 - 5.2 * len(title_right), PAGE_H - 20, title_right, 10)
        p.text(12, 12, "Author:", 9)
        p.text(160, 12, "Last saved: " + now.strftime("%d %b, %Y"), 9)
        p.text(300, 12, "Printed: " + now.strftime("%d %b, %Y %H:%M"), 9)
        p.text(460, 12, "Keywords: cap", 9)

    # ---- page 1: the design and the totals
    p1 = _Page()
    frame(p1, f"H: {h_in:.2f} in  W: {w_in:.2f} in")
    p1.line(PANEL_X, 26, PANEL_X, PAGE_H - 26, (0.7, 0.7, 0.7))
    area = (12, 32, PANEL_X - 6, PAGE_H - 32)          # x0, y0, x1, y1 in points
    im, (bx0, by0, bx1, by1) = d.render_design(stitches, colors, cap, ppm=16)
    aw, ah = area[2] - area[0], area[3] - area[1]
    k = min(aw / (bx1 - bx0), ah / (by1 - by0), 72 / 25.4 * 4)       # points per mm, at most 4x real size
    iw, ih = (bx1 - bx0) * k, (by1 - by0) * k
    ix, iy = area[0] + (aw - iw) / 2, area[1] + (ah - ih) / 2
    p1.image("Im1", ix, iy, iw, ih)
    P = lambda x, y: (ix + (x - bx0) * k, iy + (y - by0) * k)
    p1.text(PANEL_X - 120, PAGE_H - 40, f"Z: {k / (72 / 25.4):.2f}", 9, rgb=(0.4, 0.4, 0.4))
    first = next(((x, y) for x, y, c in stitches if c == d.STITCH), (0, 0))
    start, end = P(0.0, 0.0), P(s["endx"] * 25.4, s["endy"] * 25.4)
    for (x, y), label, col in ((start, "1", (0.1, 0.75, 0.1)), (end, "2", (0.85, 0.1, 0.1))):
        p1.line(x, area[1], x, area[3], (0.8, 0.8, 0.55), 0.5)
        p1.line(area[0], y, area[2], y, (0.8, 0.8, 0.55), 0.5)
    p1.text(start[0] + 3, area[3] - 10, "1", 10, rgb=(0.1, 0.75, 0.1))
    p1.text(area[0] + 3, start[1] + 3, "1", 10, rgb=(0.1, 0.75, 0.1))
    p1.text(end[0] + 3, area[1] + 3, "2", 10, rgb=(0.85, 0.1, 0.1))
    p1.text(area[2] - 10, end[1] + 3, "2", 10, rgb=(0.85, 0.1, 0.1))
    fx, fy = P(*first)
    p1.rect(fx - 2.5, fy - 2.5, 5, 5, stroke=(0.1, 0.75, 0.1), lw=1)
    p1.text(fx + 4, fy - 9, "first stitch", 7, rgb=(0.1, 0.6, 0.1))

    x, vx = PANEL_X + 6, PANEL_X + 104
    y = PAGE_H - 42

    def row(label, value="", gap=0):
        nonlocal y
        y -= gap
        p1.text(x, y, label, 10)
        if value != "":
            p1.text(vx, y, value, 10)
        y -= 13
    row("Stitches:", f"{s['stitches']}")
    row("Colors:", f"{s['colors']}")
    row("Color changes:", f"{s['changes']}")
    row("Stops:", f"{s['stops']}")
    row("Machine:", "Tajima", 6)
    row("Trims:", f"{s['trims']}")
    row("Left:", f"{s['left']:.1f} mm", 6)
    row("Right:", f"{s['right']:.1f} mm")
    row("Up:", f"{s['up']:.1f} mm")
    row("Down:", f"{s['down']:.1f} mm")
    row("EndX:", f"{s['endx']:.2f} in", 6)
    row("EndY:", f"{s['endy']:.2f} in")
    row("Max Stitch:", f"{s['max_stitch']:.1f} mm", 6)
    row("Min Stitch:", f"{s['min_stitch']:.1f} mm")
    row("Max Jump:", f"{s['max_jump']:.1f} mm")
    row("Colorway:", chart or "-", 8)
    y -= 6
    p1.text(x, y, "#", 10, bold=True); p1.text(x + 20, y, "N#", 10, bold=True)
    p1.text(x + 72, y, "St.", 10, bold=True); p1.text(x + 104, y, "Descr  Code", 10, bold=True)
    p1.line(x, y - 2, x + 180, y - 2, (0.3, 0.3, 0.3), 0.4)
    y -= 18
    for i, c in enumerate(colors):
        if y < 120:
            p1.text(x, y, f"... {len(colors) - i} more on page 2", 9); y -= 13
            break
        p1.text(x, y, f"{i + 1}.", 10)
        p1.text(x + 20, y, f"{nums[i]}", 10)
        p1.rect(x + 42, y - 1, 9, 9, stroke=(0.5, 0.5, 0.5), fill=_rgb(c["hex"]), lw=0.4)
        p1.text(x + 72, y, f"{s['block_stitches'][i]}", 10)
        desc = "Foam stop" if c.get("stop") else f"{c.get('name') or c['hex']} {c.get('code') or ''}".strip()
        p1.text(x + 104, y, desc[:20], 10)
        y -= 12
        if not c.get("stop") and c.get("brand"):
            p1.text(x + 14, y, f"Brand: {c['brand']}", 9, rgb=(0.25, 0.25, 0.25)); y -= 12
        y -= 2
    row("Total Bobbin:", f"{s['bobbin_ft']:.2f}ft", 2)
    if settings:
        y -= 8
        p1.text(x, y, "Cap settings", 10, bold=True); y -= 14
        for label, value in settings:
            if y < 70:
                break
            p1.text(x, y, f"{label}:", 8.5, rgb=(0.25, 0.25, 0.25))
            p1.text(vx - 18, y, str(value)[:30], 8.5); y -= 11
    if notes:
        y -= 6
        p1.text(x, y, "Notes", 10, bold=True); y -= 13
        for n in notes:
            words, line_ = n.split(), ""
            for wd in words:
                if len(line_) + len(wd) > 42:
                    if y < 40:
                        break
                    p1.text(x, y, line_, 8, rgb=(0.6, 0.1, 0.1)); y -= 10; line_ = ""
                line_ += ("" if not line_ else " ") + wd
            if line_ and y >= 40:
                p1.text(x, y, line_, 8, rgb=(0.6, 0.1, 0.1)); y -= 12

    # ---- page 2: each colour on its own (Color Film)
    p2 = _Page()
    frame(p2, "Color Film")
    cols, cw, chh = 3, 186, 186                       # a grid of boxes, three across
    blocks, ci, cur, prev = [[] for _ in colors], 0, [], None
    for xx, yy, c in stitches:
        if c == d.COLOR:
            if cur:
                blocks[ci].append(cur)
            ci, cur, prev = min(ci + 1, len(colors) - 1), [], None
            continue
        if c == d.STITCH:
            cur.append((xx, yy))
        elif cur:
            blocks[ci].append(cur); cur = []
    if cur:
        blocks[ci].append(cur)
    kk = min((cw - 16) / (bx1 - bx0), (chh - 16) / (by1 - by0))
    for i, c in enumerate(colors):
        col, rw = i % cols, i // cols
        gx, gy = 16 + col * (cw + 6), PAGE_H - 40 - (rw + 1) * (chh + 84) + 84
        if gy < 40:
            break
        p2.rect(gx, gy, cw, chh, stroke=(0.75, 0.75, 0.75))
        r, g, b = _rgb(c["hex"])
        if 0.299 * r + 0.587 * g + 0.114 * b > 0.85:          # white thread: drawn grey so it shows
            r, g, b = 0.72, 0.72, 0.72
        ox, oy = gx + (cw - (bx1 - bx0) * kk) / 2, gy + (chh - (by1 - by0) * kk) / 2
        for run in blocks[i]:
            p2.polyline([(ox + (px - bx0) * kk, oy + (py - by0) * kk) for px, py in run], (r, g, b), 0.25)
        ty = gy - 12
        lines = [f"#: {i + 1}."]
        if c.get("stop"):
            lines += ["Stop: lay the foam", f"Same thread as {i}.", f"Stitches: {s['block_stitches'][i]}"]
        else:
            lines += [f"Color: {c.get('name') or c['hex']}", f"Code: {c.get('code') or '-'}",
                      f"Brand: {c.get('brand') or '-'}", f"Stitches: {s['block_stitches'][i]}"]
        lines.append(f"Thread Used: {s['top_ft'][i]:.2f}ft")
        for ln in lines:
            p2.text(gx + 4, ty, ln, 9); ty -= 11
    return _pdf([p1, p2], {"Im1": im})
