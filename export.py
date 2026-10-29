"""Convert the (possibly edited) SVG into the download formats."""

from __future__ import annotations

import io
import math
import re
import xml.etree.ElementTree as ET

import ezdxf

from engine import _flatten, hex_to_rgb, parse_d, primitive_subpath

SVG_NS = "{http://www.w3.org/2000/svg}"
INK_LABEL = "{http://www.inkscape.org/namespaces/inkscape}label"


def clean_svg(svg: str) -> str:
    """Drop editor-only attributes and hidden shapes before download."""
    svg = re.sub(r'<(path|rect|circle|ellipse)\b[^>]*\bdata-removed="1"[^>]*/>\n?', "", svg)
    svg = re.sub(r'\s(?:data-[a-z-]+|class)="[^"]*"', "", svg)
    svg = re.sub(r"<g\b[^>]*>\s*</g>\n?", "", svg)          # groups emptied by edits
    if not svg.lstrip().startswith("<?xml"):
        svg = '<?xml version="1.0" encoding="UTF-8"?>\n' + svg
    return svg


# ---------------------------------------------------------------------------
# PDF and EPS, written directly (no system libraries, so the app stays portable)

_PT = {"px": 0.75, "pt": 1.0, "in": 72.0, "mm": 72 / 25.4, "cm": 72 / 2.54, "": 0.75}


def _length_pt(v):
    m = re.match(r"\s*([\d.]+)\s*([a-z]*)", v or "")
    return float(m.group(1)) * _PT.get(m.group(2), 0.75) if m else None


def _rgb01(c):
    r, g, b = hex_to_rgb(c)
    return f"{r / 255:.4f} {g / 255:.4f} {b / 255:.4f}"


def _draw_items(root):
    """Shapes in paint order: {loops, fill, stroke, width, cap, join, clip}."""
    clips = {}
    for cp in root.iter(SVG_NS + "clipPath"):
        loops = []
        for el in cp:
            loops += [sub for _, sub, _ in _element_loops(el)]
        clips[cp.get("id")] = loops
    items = []

    def walk(node, clip, inherited):
        for el in node:
            tag = el.tag.replace(SVG_NS, "")
            if tag in ("defs", "clipPath"):
                continue
            style = {**inherited, **{k: el.get(k) for k in ("fill", "stroke", "stroke-width", "stroke-linecap", "stroke-linejoin") if el.get(k)}}
            m = re.match(r"url\(#([^)]+)\)", el.get("clip-path", ""))
            c = clips.get(m.group(1)) if m else clip
            if tag == "g":
                walk(el, c, style)
            elif tag in ("path", "rect", "circle", "ellipse"):
                fill = style.get("fill", "#000000")
                stroke = style.get("stroke")
                items.append({
                    "loops": _element_loops(el),
                    "fill": fill if fill and fill.startswith("#") else None,
                    "stroke": stroke if stroke and stroke.startswith("#") else None,
                    "width": float(style.get("stroke-width", 1)),
                    "cap": {"butt": 0, "round": 1, "square": 2}.get(style.get("stroke-linecap"), 0),
                    "join": {"miter": 0, "round": 1, "bevel": 2}.get(style.get("stroke-linejoin"), 0),
                    "clip": c,
                })
    walk(root, None, {})
    return items


def _page(root):
    vb = [float(v) for v in (root.get("viewBox") or "").replace(",", " ").split()] or [0, 0, 0, 0]
    W, H = vb[2] or 1, vb[3] or 1
    wpt = _length_pt(root.get("width")) or W * 0.75
    hpt = _length_pt(root.get("height")) or H * 0.75
    sx, sy = wpt / W, hpt / H
    if (root.get("preserveAspectRatio") or "") != "none":
        sx = sy = min(sx, sy)
    return vb, wpt, hpt, sx, sy


def _ops(items, ps=False):
    """Painting operators shared by PDF (ps=False) and PostScript (ps=True)."""
    M, L, Cc, Z = ("moveto", "lineto", "curveto", "closepath") if ps else ("m", "l", "c", "h")
    f = lambda v: f"{v:.3f}".rstrip("0").rstrip(".")
    def path(loops):
        out = []
        for closed, sub, _ in loops:
            out.append(f"{f(sub[0][1][0])} {f(sub[0][1][1])} {M}")
            for op, v in sub[1:]:
                out.append(" ".join(f(x) for x in v) + (f" {L}" if op == "L" else f" {Cc}"))
            if closed:
                out.append(Z)
        return out
    out = []
    for it in items:
        if not it["fill"] and not it["stroke"]:
            continue
        save, restore = ("gsave", "grestore") if ps else ("q", "Q")
        out.append(save)
        if it["clip"]:
            out += path([(True, s, None) for s in it["clip"]])
            out.append("clip newpath" if ps else "W n")
        out += path(it["loops"])
        if it["stroke"]:
            out.append(f"{f(it['width'])} {'setlinewidth' if ps else 'w'} {it['cap']} {'setlinecap' if ps else 'J'} {it['join']} {'setlinejoin' if ps else 'j'}")
        if ps:
            if it["fill"] and it["stroke"]:
                out.append(f"gsave {_rgb01(it['fill'])} setrgbcolor fill grestore {_rgb01(it['stroke'])} setrgbcolor stroke")
            elif it["fill"]:
                out.append(f"{_rgb01(it['fill'])} setrgbcolor fill")
            else:
                out.append(f"{_rgb01(it['stroke'])} setrgbcolor stroke")
        else:
            if it["fill"]:
                out.append(f"{_rgb01(it['fill'])} rg")
            if it["stroke"]:
                out.append(f"{_rgb01(it['stroke'])} RG")
            out.append("B" if it["fill"] and it["stroke"] else "f" if it["fill"] else "S")
        out.append(restore)
    return out


def to_pdf(svg: str) -> bytes:
    """PDF 1.4, one page, vector paths in RGB."""
    import zlib
    root = ET.fromstring(clean_svg(svg).encode())
    vb, wpt, hpt, sx, sy = _page(root)
    ox, oy = (wpt - vb[2] * sx) / 2, (hpt - vb[3] * sy) / 2
    body = [f"1 0 0 1 0 0 cm {sx:.6f} 0 0 {-sy:.6f} {ox - vb[0] * sx:.4f} {hpt - oy + vb[1] * sy:.4f} cm"]
    body += _ops(_draw_items(root))
    stream = zlib.compress("\n".join(body).encode("latin-1"))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {wpt:.3f} {hpt:.3f}] /Contents 4 0 R /Resources << >> >>".encode(),
        f"<< /Length {len(stream)} /Filter /FlateDecode >>\nstream\n".encode() + stream + b"\nendstream",
        b"<< /Producer (EMB Pros) >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, o in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R /Info 5 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def to_eps(svg: str) -> bytes:
    """EPS level 3 (PostScript), vector paths in RGB."""
    root = ET.fromstring(clean_svg(svg).encode())
    vb, wpt, hpt, sx, sy = _page(root)
    ox, oy = (wpt - vb[2] * sx) / 2, (hpt - vb[3] * sy) / 2
    head = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {math.ceil(wpt)} {math.ceil(hpt)}",
            f"%%HiResBoundingBox: 0 0 {wpt:.3f} {hpt:.3f}", "%%Creator: EMB Pros", "%%LanguageLevel: 3",
            "%%Pages: 1", "%%EndComments", "%%Page: 1 1", "save",
            f"{ox - vb[0] * sx:.4f} {hpt - oy + vb[1] * sy:.4f} translate {sx:.6f} {-sy:.6f} scale"]
    tail = ["restore", "showpage", "%%EOF"]
    return ("\n".join(head + _ops(_draw_items(root), ps=True) + tail) + "\n").encode("latin-1")


def to_png(svg: str, scale: float = 4.0) -> bytes:
    """PNG via cairo, when it is installed (the app renders PNG in the page); without cairo (a web
    server that lacks it) the SVG as PDF, drawn by pypdfium2 at the same size."""
    try:
        import cairosvg
        return cairosvg.svg2png(bytestring=clean_svg(svg).encode(), scale=scale)
    except (ImportError, OSError):
        import io
        import gang_portable
        im = gang_portable.raster(to_pdf(svg), 72 * scale / 0.75)      # a CSS px is 0.75 pt
        buf = io.BytesIO(); im.save(buf, "PNG")
        return buf.getvalue()


def _rotate_from(el):
    m = re.search(r"rotate\(([-\d.e]+)", el.get("transform", ""))
    return float(m.group(1)) if m else 0.0


def _num(el, k, default=0.0):
    v = el.get(k)
    return float(re.sub(r"[a-z%]+$", "", v)) if v else default


def _element_loops(el):
    """[(closed, subpath, primitive)] for one SVG shape element."""
    tag = el.tag.replace(SVG_NS, "")
    if tag == "path":
        out = []
        for piece in re.findall(r"M[^M]*", el.get("d", "")):
            subs = parse_d(piece)
            if subs:
                out.append((piece.rstrip().upper().endswith("Z"), subs[0], None))
        return out
    if tag == "circle":
        p = {"cx": _num(el, "cx"), "cy": _num(el, "cy"), "r": _num(el, "r")}
        return [(True, primitive_subpath("circle", p), ("circle", p))]
    if tag == "ellipse":
        p = {"cx": _num(el, "cx"), "cy": _num(el, "cy"), "rx": _num(el, "rx"), "ry": _num(el, "ry"), "angle": _rotate_from(el)}
        return [(True, primitive_subpath("ellipse", p), ("ellipse", p))]
    if tag == "rect":
        w, h = _num(el, "width"), _num(el, "height")
        p = {"cx": _num(el, "x") + w / 2, "cy": _num(el, "y") + h / 2, "w": w, "h": h,
             "angle": _rotate_from(el), "r": _num(el, "rx")}
        return [(True, primitive_subpath("rect", p), ("rect", p))]
    return []


def to_dxf(svg: str, level: str = "lines") -> bytes:
    """DXF AC1021 (2007). level: lines | lines_arcs | splines (as on vectorizer.ai)."""
    root = ET.fromstring(clean_svg(svg).encode())
    vb = [float(v) for v in (root.get("viewBox") or "0 0 0 0").split()]
    H = vb[3] if len(vb) == 4 else _num(root, "height")
    doc = ezdxf.new("R2007")
    msp = doc.modelspace()
    fy = lambda y: H - y

    def color_of(el, inherited):
        c = el.get("fill")
        if not c or c == "none":
            c = el.get("stroke")
        return c if c and c.startswith("#") else inherited

    def layer_for(name):
        name = re.sub(r"[<>/\\\":;?*|=`]", "_", name or "0")[:250] or "0"
        if name not in doc.layers:
            doc.layers.add(name)
        return name

    def emit(el, layer, color):
        rgb = hex_to_rgb(color) if color else (0, 0, 0)
        attrs = {"layer": layer, "true_color": ezdxf.colors.rgb2int(rgb)}
        for closed, sub, prim in _element_loops(el):
            if prim and level in ("lines_arcs", "splines") and prim[0] in ("circle", "ellipse"):
                kind, p = prim
                if kind == "circle":
                    msp.add_circle((p["cx"], fy(p["cy"])), p["r"], dxfattribs=attrs)
                else:
                    a = math.radians(-p["angle"])
                    rx, ry = (p["rx"], p["ry"]) if p["rx"] >= p["ry"] else (p["ry"], p["rx"])
                    if p["rx"] < p["ry"]:
                        a += math.pi / 2
                    msp.add_ellipse((p["cx"], fy(p["cy"])), (rx * math.cos(a), rx * math.sin(a)), ry / rx, dxfattribs=attrs)
                continue
            if level == "splines":
                cur = sub[0][1]
                for op, v in sub[1:]:
                    if op == "L":
                        msp.add_line((cur[0], fy(cur[1])), (v[0], fy(v[1])), dxfattribs=attrs)
                    else:
                        ctrl = [(cur[0], fy(cur[1])), (v[0], fy(v[1])), (v[2], fy(v[3])), (v[4], fy(v[5]))]
                        msp.add_open_spline(ctrl, degree=3, dxfattribs=attrs)
                    cur = v[-2:]
                if closed and cur != sub[0][1]:
                    msp.add_line((cur[0], fy(cur[1])), (sub[0][1][0], fy(sub[0][1][1])), dxfattribs=attrs)
            else:
                pts = [(x, fy(y)) for x, y in _flatten(sub, tol=0.1)]
                msp.add_lwpolyline(pts, close=closed, dxfattribs=attrs)

    def walk(node, layer, color, in_defs=False):
        for el in node:
            tag = el.tag.replace(SVG_NS, "")
            if tag in ("defs", "clipPath") or "gap" in (el.get("id") or "") or "Gap filler" in (el.get(INK_LABEL) or ""):
                continue
            if tag == "g":
                walk(el, layer if layer != "0" else layer_for(el.get(INK_LABEL) or el.get("id") or "0"), color_of(el, color))
            elif tag in ("path", "rect", "circle", "ellipse"):
                emit(el, layer, color_of(el, color))

    walk(root, "0", None)
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode()
