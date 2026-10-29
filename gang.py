"""Gang sheets: logos repeated across a print sheet, each at its own size and quantity.

The sheet is drawn with Quartz (Core Graphics, part of macOS): a PDF or AI logo is placed
as its own vector page, so the sheet PDF stays vector; an SVG logo is first written as a
vector PDF (export.to_pdf); a raster logo (PNG, JPG...) is placed as an image. PNG, JPG and
TIFF are the sheet PDF drawn at the chosen resolution. EPS is written directly: vector for
SVG logos, otherwise the sheet as a high-resolution image (macOS cannot write PostScript).

Without macOS (a Linux web server, or EMB_PORTABLE=1) the same is done by gang_portable.py with
pypdfium2 and pikepdf.
"""

from __future__ import annotations

import base64
import io
import math
import os
import xml.etree.ElementTree as ET
import zlib

from PIL import Image

try:
    if os.environ.get("EMB_PORTABLE"):
        raise ImportError("portable asked for")
    import Quartz
    from Foundation import NSData
except ImportError:              # not on a Mac: pypdfium2 and pikepdf
    Quartz = None
    import gang_portable

import export

UNIT_PT = {"in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4}
MAX_RASTER_SIDE = 16000          # pixels, for PNG / JPG / TIFF


class Logo:
    """A loaded logo: a vector PDF page (kind "pdf") or an image (kind "image").
    box: the part of the page (pt) or image (px) that holds the artwork, empty margins trimmed."""

    def __init__(self, kind, name, page=None, doc=None, image=None, cgimage=None, box=None, svg=None):
        self.kind, self.name = kind, name
        self.doc, self.page, self.image, self.cgimage, self.box, self.svg = doc, page, image, cgimage, box, svg
        self.pdf = None            # the PDF itself (without macOS)

    @property
    def aspect(self):
        return self.box[2] / self.box[3]


def _cfdata(data: bytes):
    return NSData.dataWithBytes_length_(data, len(data))


def _bitmap(w, h, transparent=True):
    cs = Quartz.CGColorSpaceCreateWithName(Quartz.kCGColorSpaceSRGB)
    ctx = Quartz.CGBitmapContextCreate(None, w, h, 8, w * 4, cs, Quartz.kCGImageAlphaPremultipliedLast)
    if not transparent:
        Quartz.CGContextSetRGBFillColor(ctx, 1, 1, 1, 1)
        Quartz.CGContextFillRect(ctx, Quartz.CGRectMake(0, 0, w, h))
    return ctx


def _to_pil(ctx, w, h):
    img = Quartz.CGBitmapContextCreateImage(ctx)
    raw = bytes(Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(img)))
    stride = Quartz.CGImageGetBytesPerRow(img)
    return Image.frombuffer("RGBa", (w, h), raw, "raw", "RGBa", stride, 1).convert("RGBA")


def _render_page(page, scale, transparent=True):
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    w = max(1, int(round(box.size.width * scale)))
    h = max(1, int(round(box.size.height * scale)))
    ctx = _bitmap(w, h, transparent)
    Quartz.CGContextScaleCTM(ctx, scale, scale)
    Quartz.CGContextTranslateCTM(ctx, -box.origin.x, -box.origin.y)
    Quartz.CGContextDrawPDFPage(ctx, page)
    return _to_pil(ctx, w, h), box


def _load_pdf(data: bytes, name: str, svg: str | None = None) -> Logo:
    if Quartz is None:
        return gang_portable.load_pdf(data, name, Logo, svg)
    doc = Quartz.CGPDFDocumentCreateWithProvider(Quartz.CGDataProviderCreateWithCFData(_cfdata(data)))
    if doc is None or Quartz.CGPDFDocumentGetNumberOfPages(doc) < 1:
        raise ValueError("This file could not be read as a PDF.")
    page = Quartz.CGPDFDocumentGetPage(doc, 1)
    crop = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFCropBox)
    # trim the empty part of the artboard: find the artwork in a small transparent render
    scale = 800 / max(crop.size.width, crop.size.height)
    im, media = _render_page(page, scale)
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not bbox:
        raise ValueError("The PDF page is empty.")
    x0, y0, x1, y1 = bbox
    pad = 1.5
    bx = media.origin.x + max(0, x0 - pad) / scale
    by = media.origin.y + (im.height - min(im.height, y1 + pad)) / scale       # PDF y is up
    bw = (min(im.width, x1 + pad) - max(0, x0 - pad)) / scale
    bh = (min(im.height, y1 + pad) - max(0, y0 - pad)) / scale
    return Logo("pdf", name, page=page, doc=doc, box=(bx, by, bw, bh), svg=svg)


def load_logo(data: bytes, name: str) -> Logo:
    low = (name or "").lower()
    if low.endswith(".eps") or data[:4] in (b"%!PS", b"\xc5\xd0\xd3\xc6"):
        raise ValueError("EPS logos cannot be read here (there is no PostScript reader). "
                         "Save the logo as PDF, AI (PDF compatible) or SVG and add it again.")
    head = data[:1024]
    if low.endswith((".pdf", ".ai")) or b"%PDF" in head:
        i = data.find(b"%PDF")
        if i < 0:
            raise ValueError("This AI file was saved without PDF compatibility. In Illustrator, save it again with "
                             "\"Create PDF Compatible File\" ticked, or save it as PDF.")
        return _load_pdf(data[i:], name)
    if low.endswith(".svg") or data.lstrip()[:5] in (b"<?xml", b"<svg ") or b"<svg" in head:
        svg = data.decode("utf-8", "replace")
        return _load_pdf(export.to_pdf(svg), name, svg=svg)
    try:
        im = Image.open(io.BytesIO(data))
        im.load()
    except Exception:
        raise ValueError("Please use a PDF, AI, SVG, PNG, JPG, WebP or TIFF logo.")
    im = im.convert("RGBA")
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox() or (0, 0, im.width, im.height)
    im = im.crop(bbox)
    if Quartz is None:
        return Logo("image", name, image=im, box=(0, 0, im.width, im.height))
    buf = io.BytesIO(); im.save(buf, "PNG")
    src = Quartz.CGImageSourceCreateWithData(_cfdata(buf.getvalue()), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    return Logo("image", name, image=im, cgimage=cg, box=(0, 0, im.width, im.height))


def preview_of(logo: Logo, side=360) -> bytes:
    """A small PNG of the logo for the page."""
    if Quartz is None:
        return gang_portable.preview_of(logo, side)
    if logo.kind == "image":
        im = logo.image.copy()
        im.thumbnail((side, side))
    else:
        bx, by, bw, bh = logo.box
        scale = side / max(bw, bh)
        full, media = _render_page(logo.page, scale)
        left = (bx - media.origin.x) * scale
        top = full.height - (by - media.origin.y + bh) * scale
        im = full.crop((int(left), int(top), int(left + bw * scale), int(top + bh * scale)))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------
# layout

MAX_CELLS = 20000


def pack(sheet_w, sheet_h, groups, margin, gap, rotate=True):
    """Place several logos on one sheet. groups: [(w, h, qty)] in points; qty None means as
    many as still fit (the logo that fills the rest of the sheet).
    The logos go in rows across the sheet, `gap` apart, inside the margin: the logos with a
    quantity first, tallest first, each into the first row with room for it (first-fit
    decreasing height); then the filling logo, into the gaps left and new rows below. The
    block is centred. A logo is turned 90 degrees when that fits more (filling) or needs
    fewer rows (a quantity).
    Returns (cells, rows, placed): cells [(x, y, w, h, turned, group, row)] in PDF coordinates
    (y up), row by row from the top left; placed: how many of each group are on the sheet."""
    aw, ah, eps = sheet_w - 2 * margin, sheet_h - 2 * margin, 1e-6

    def across(w):
        return max(0, int((aw + gap + eps) // (w + gap)))

    def down(h):
        return max(0, int((ah + gap + eps) // (h + gap)))

    sizes = []
    for w, h, q in groups:
        turned = False
        if rotate and abs(w - h) > eps:
            if q is None:
                turned = across(h) * down(w) > across(w) * down(h)
            else:
                def rows_h(a, b):
                    n = min(across(a), q)
                    return math.inf if n == 0 or b > ah + eps else math.ceil(q / n) * (b + gap)
                turned = rows_h(h, w) < rows_h(w, h) - eps
        sizes.append((h, w, True) if turned else (w, h, False))

    shelves = []          # [top, height, next x], from the top of the usable area
    out, placed = [], [0] * len(groups)

    def put(g):
        w, h, t = sizes[g]
        if len(out) >= MAX_CELLS:
            raise ValueError(f"Over {MAX_CELLS:,} logos: make the logos larger or the sheet smaller.")
        for r, s in enumerate(shelves):
            if h <= s[1] + eps and s[2] + w <= aw + eps:
                out.append((s[2], s[0], w, h, t, g, r)); s[2] += w + gap; placed[g] += 1
                return True
        top = shelves[-1][0] + shelves[-1][1] + gap if shelves else 0.0
        if w > aw + eps or top + h > ah + eps:
            return False
        shelves.append([top, h, w + gap])
        out.append((0.0, top, w, h, t, g, len(shelves) - 1)); placed[g] += 1
        return True

    fixed = sorted((g for g, (_, _, q) in enumerate(groups) if q is not None), key=lambda g: -sizes[g][1])
    for g in fixed:
        for _ in range(groups[g][2]):
            if not put(g):          # one does not fit, so none of the same size does
                break
    for g, (_, _, q) in enumerate(groups):
        if q is None:
            while put(g):
                pass

    bw = max((s[2] - gap for s in shelves), default=0.0)
    bh = shelves[-1][0] + shelves[-1][1] if shelves else 0.0
    x0, t0 = margin + (aw - bw) / 2, margin + (ah - bh) / 2
    out.sort(key=lambda c: (c[6], c[0]))
    cells = [(x0 + x, sheet_h - (t0 + top + h), w, h, t, g, r) for x, top, w, h, t, g, r in out]
    return cells, len(shelves), placed


# --------------------------------------------------------------------------
# the sheet as PDF (vector where the logo is)

def _place(ctx, logo: Logo, x, y, w, h, turned):
    """Draw the logo into the cell, fitted inside it (proportions kept), centred."""
    Quartz.CGContextSaveGState(ctx)
    Quartz.CGContextTranslateCTM(ctx, x + w / 2, y + h / 2)
    if turned:
        Quartz.CGContextRotateCTM(ctx, math.pi / 2)
        w, h = h, w
    bx, by, bw, bh = logo.box
    s = min(w / bw, h / bh)
    dw, dh = bw * s, bh * s
    if logo.kind == "pdf":
        Quartz.CGContextClipToRect(ctx, Quartz.CGRectMake(-dw / 2, -dh / 2, dw, dh))
        Quartz.CGContextScaleCTM(ctx, s, s)
        Quartz.CGContextTranslateCTM(ctx, -bx - bw / 2, -by - bh / 2)
        Quartz.CGContextDrawPDFPage(ctx, logo.page)
    else:
        Quartz.CGContextSetInterpolationQuality(ctx, Quartz.kCGInterpolationHigh)
        Quartz.CGContextDrawImage(ctx, Quartz.CGRectMake(-dw / 2, -dh / 2, dw, dh), logo.cgimage)
    Quartz.CGContextRestoreGState(ctx)


def _outlines(ctx, sheet_w, sheet_h, cells, sheet_border, cell_boxes):
    Quartz.CGContextSetRGBStrokeColor(ctx, 0, 0, 0, 1)
    Quartz.CGContextSetLineWidth(ctx, 0.5)
    if cell_boxes:
        for x, y, w, h, *_ in cells:
            Quartz.CGContextStrokeRect(ctx, Quartz.CGRectMake(x, y, w, h))
    if sheet_border:
        Quartz.CGContextStrokeRect(ctx, Quartz.CGRectMake(0.25, 0.25, sheet_w - 0.5, sheet_h - 0.5))


def sheet_pdf(logos, sheet_w, sheet_h, cells, sheet_border=True, cell_boxes=True, title="logo") -> bytes:
    """logos: one Logo per group; cells from pack()."""
    if Quartz is None:
        return gang_portable.sheet_pdf(logos, sheet_w, sheet_h, cells, sheet_border, cell_boxes, title)
    data = Quartz.CFDataCreateMutable(None, 0)
    consumer = Quartz.CGDataConsumerCreateWithCFData(data)
    media = Quartz.CGRectMake(0, 0, sheet_w, sheet_h)
    info = {Quartz.kCGPDFContextCreator: "EMB Pros", Quartz.kCGPDFContextTitle: f"Gang sheet - {title}"}
    ctx = Quartz.CGPDFContextCreate(consumer, media, info)
    Quartz.CGPDFContextBeginPage(ctx, None)
    for x, y, w, h, turned, g, _ in cells:
        _place(ctx, logos[g], x, y, w, h, turned)
    _outlines(ctx, sheet_w, sheet_h, cells, sheet_border, cell_boxes)
    Quartz.CGPDFContextEndPage(ctx)
    Quartz.CGPDFContextClose(ctx)
    return bytes(data)


def raster(pdf: bytes, dpi: float, transparent=True) -> Image.Image:
    if Quartz is None:
        return gang_portable.raster(pdf, dpi, transparent)
    doc = Quartz.CGPDFDocumentCreateWithProvider(Quartz.CGDataProviderCreateWithCFData(_cfdata(pdf)))
    page = Quartz.CGPDFDocumentGetPage(doc, 1)
    box = Quartz.CGPDFPageGetBoxRect(page, Quartz.kCGPDFMediaBox)
    scale = dpi / 72
    if max(box.size.width, box.size.height) * scale > MAX_RASTER_SIDE:
        raise ValueError(f"At {dpi:g} dpi this sheet would be over {MAX_RASTER_SIDE} pixels wide; choose a lower resolution.")
    im, _ = _render_page(page, scale, transparent)
    return im


# --------------------------------------------------------------------------
# EPS

def sheet_eps(logos, sheet_w, sheet_h, cells, sheet_border=True, cell_boxes=True, dpi=300, title="logo") -> bytes:
    head = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {math.ceil(sheet_w)} {math.ceil(sheet_h)}",
            f"%%HiResBoundingBox: 0 0 {sheet_w:.3f} {sheet_h:.3f}", "%%Creator: EMB Pros",
            f"%%Title: Gang sheet - {title}", "%%LanguageLevel: 3", "%%Pages: 1", "%%EndComments",
            "%%Page: 1 1", "save"]
    body = []
    used = sorted({c[5] for c in cells})
    if all(logos[g].svg for g in used):     # vector: each logo's paths once, as a procedure, drawn in its cells
        place = {}
        for g in used:
            root = ET.fromstring(export.clean_svg(logos[g].svg).encode())
            vb, wpt, hpt, sx, sy = export._page(root)          # the same placement as export.to_pdf
            ox, oy = (wpt - vb[2] * sx) / 2, (hpt - vb[3] * sy) / 2
            place[g] = f"[{sx:.6f} 0 0 {-sy:.6f} {ox - vb[0] * sx:.4f} {hpt - oy + vb[1] * sy:.4f}] concat"
            body.append(f"/logo{g} {{")
            body += export._ops(export._draw_items(root), ps=True)
            body.append("} bind def")
        for x, y, w, h, turned, g, _ in cells:
            bx, by, bw, bh = logos[g].box
            ww, hh = (h, w) if turned else (w, h)
            s = min(ww / bw, hh / bh)
            body.append(f"gsave {x + w / 2:.3f} {y + h / 2:.3f} translate" + (" 90 rotate" if turned else "")
                        + f" {s:.6f} dup scale {-(bx + bw / 2):.3f} {-(by + bh / 2):.3f} translate {place[g]} logo{g} grestore")
    else:            # the sheet as an image (white behind it: EPS has no transparency)
        im = raster(sheet_pdf(logos, sheet_w, sheet_h, cells, False, False), dpi, transparent=False).convert("RGB")
        data = base64.a85encode(zlib.compress(im.tobytes(), 6), adobe=False, wrapcol=76).decode() + "~>"
        body += [f"gsave 0 0 translate {sheet_w:.3f} {sheet_h:.3f} scale", "/DeviceRGB setcolorspace",
                 f"<< /ImageType 1 /Width {im.width} /Height {im.height} /BitsPerComponent 8 /Decode [0 1 0 1 0 1]",
                 f"/ImageMatrix [{im.width} 0 0 {-im.height} 0 {im.height}] /DataSource currentfile /ASCII85Decode filter /FlateDecode filter >> image",
                 data, "grestore"]
    lines = ["0 setgray 0.5 setlinewidth"]
    if cell_boxes:
        lines += [f"{x:.3f} {y:.3f} {w:.3f} {h:.3f} rectstroke" for x, y, w, h, *_ in cells]
    if sheet_border:
        lines.append(f"0.25 0.25 {sheet_w - 0.5:.3f} {sheet_h - 0.5:.3f} rectstroke")
    tail = ["restore", "showpage", "%%EOF"]
    return ("\n".join(head + body + lines + tail) + "\n").encode("latin-1")


# --------------------------------------------------------------------------
# one call for the page

def make(logos, o: dict, fmt: str = "preview", dpi: float = 300):
    """logos: one Logo per entry of o["logos"]. o: sheet_w, sheet_h, margin, gap (all in `unit`),
    unit, rotate, sheet_border, cell_boxes; logos: [{w, h, qty}] (qty null: fill the rest);
    removed: places (row by row from the top left) left empty.
    Returns (bytes, mimetype, info)."""
    k = UNIT_PT.get(o.get("unit", "in"), 72.0)
    sw, sh = float(o["sheet_w"]) * k, float(o["sheet_h"]) * k
    if min(sw, sh) <= 0:
        raise ValueError("Sizes must be more than 0.")
    if sw * sh > (200 * 72) ** 2:
        raise ValueError("The sheet is too large (over 200 x 200 in).")
    groups = []
    for e in o["logos"]:
        w, h = float(e["w"]) * k, float(e["h"]) * k
        if min(w, h) <= 0:
            raise ValueError("Logo sizes must be more than 0.")
        q = e.get("qty")
        groups.append((w, h, None if q is None else max(0, int(q))))
    every, rows, placed = pack(sw, sh, groups, float(o.get("margin", 0)) * k, float(o.get("gap", 0)) * k,
                               bool(o.get("rotate", True)))
    # logos taken off the sheet leave their place empty: the layout and sheet stay the same
    removed = {int(i) for i in (o.get("removed") or []) if isinstance(i, (int, float)) or str(i).isdigit()}
    cells = [c for i, c in enumerate(every) if i not in removed]
    on = [0] * len(groups)
    for c in cells:
        on[c[5]] += 1
    info = {"count": len(cells), "total": len(every), "rows": rows,
            "logos": [{"placed": placed[g], "on": on[g], "wanted": groups[g][2]} for g in range(len(groups))]}
    if fmt == "preview":    # every place as fractions of the sheet, from the top left, for clicking
        info["cells"] = [[round(x / sw, 6), round((sh - y - h) / sh, 6), round(w / sw, 6), round(h / sh, 6), g, r]
                         for x, y, w, h, _, g, r in every]
    border, boxes = bool(o.get("sheet_border", True)), bool(o.get("cell_boxes", False))
    title = logos[0].name if len(logos) == 1 else f"{len(logos)} logos"
    if fmt == "eps":
        return sheet_eps(logos, sw, sh, cells, border, boxes, dpi, title), "application/postscript", info
    pdf = sheet_pdf(logos, sw, sh, cells, border, boxes, title)
    if fmt in ("pdf", "ai"):
        return pdf, ("application/pdf" if fmt == "pdf" else "application/illustrator"), info
    if fmt == "preview":
        im = raster(pdf, 1100 / max(sw, sh) * 72)
        buf = io.BytesIO(); im.save(buf, "PNG")
        return buf.getvalue(), "image/png", info
    im = raster(pdf, dpi, transparent=fmt != "jpg")
    buf = io.BytesIO()
    if fmt == "png":
        im.save(buf, "PNG", dpi=(dpi, dpi)); mime = "image/png"
    elif fmt == "tiff":
        im.save(buf, "TIFF", dpi=(dpi, dpi), compression="tiff_lzw"); mime = "image/tiff"
    elif fmt == "jpg":
        Image.alpha_composite(Image.new("RGBA", im.size, (255, 255, 255, 255)), im).convert("RGB").save(
            buf, "JPEG", quality=95, dpi=(dpi, dpi)); mime = "image/jpeg"
    else:
        raise ValueError("Unknown format.")
    return buf.getvalue(), mime, info
