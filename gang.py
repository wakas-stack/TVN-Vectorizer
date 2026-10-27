"""Gang sheets: one logo repeated across a print sheet, as many as fit.

The sheet is drawn with Quartz (Core Graphics, part of macOS): a PDF or AI logo is placed
as its own vector page, so the sheet PDF stays vector; an SVG logo is first written as a
vector PDF (export.to_pdf); a raster logo (PNG, JPG...) is placed as an image. PNG, JPG and
TIFF are the sheet PDF drawn at the chosen resolution. EPS is written directly: vector for
SVG logos, otherwise the sheet as a high-resolution image (macOS cannot write PostScript).
"""

from __future__ import annotations

import base64
import io
import math
import xml.etree.ElementTree as ET
import zlib

import Quartz
from Foundation import NSData
from PIL import Image

import export

UNIT_PT = {"in": 72.0, "cm": 72 / 2.54, "mm": 72 / 25.4}
MAX_RASTER_SIDE = 16000          # pixels, for PNG / JPG / TIFF


class Logo:
    """A loaded logo: a vector PDF page (kind "pdf") or an image (kind "image").
    box: the part of the page (pt) or image (px) that holds the artwork, empty margins trimmed."""

    def __init__(self, kind, name, page=None, doc=None, image=None, cgimage=None, box=None, svg=None):
        self.kind, self.name = kind, name
        self.doc, self.page, self.image, self.cgimage, self.box, self.svg = doc, page, image, cgimage, box, svg

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
        raise ValueError("EPS logos cannot be read on this Mac: macOS no longer includes a PostScript "
                         "reader. Save the logo as PDF, AI (PDF compatible) or SVG and add it again.")
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
    buf = io.BytesIO(); im.save(buf, "PNG")
    src = Quartz.CGImageSourceCreateWithData(_cfdata(buf.getvalue()), None)
    cg = Quartz.CGImageSourceCreateImageAtIndex(src, 0, None)
    return Logo("image", name, image=im, cgimage=cg, box=(0, 0, im.width, im.height))


def preview_of(logo: Logo, side=360) -> bytes:
    """A small PNG of the logo for the page."""
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

def layout(sheet_w, sheet_h, logo_w, logo_h, margin, gap, rotate=True):
    """Cells (x, y, w, h, turned) in points, PDF coordinates (y up), the first row at the top.
    As many as fit inside the margin, `gap` apart, the block centred; turned 90 degrees when
    that fits more."""
    def fit(w, h):
        if w <= 0 or h <= 0:
            return 0, 0
        cols = int(math.floor((sheet_w - 2 * margin + gap + 1e-6) / (w + gap)))
        rows = int(math.floor((sheet_h - 2 * margin + gap + 1e-6) / (h + gap)))
        return max(0, cols), max(0, rows)
    cols, rows = fit(logo_w, logo_h)
    turned = False
    if rotate and abs(logo_w - logo_h) > 1e-6:
        c2, r2 = fit(logo_h, logo_w)
        if c2 * r2 > cols * rows:
            cols, rows, turned = c2, r2, True
    w, h = (logo_h, logo_w) if turned else (logo_w, logo_h)
    bw, bh = cols * w + max(0, cols - 1) * gap, rows * h + max(0, rows - 1) * gap
    x0, ytop = (sheet_w - bw) / 2, (sheet_h + bh) / 2
    cells = [(x0 + c * (w + gap), ytop - (r + 1) * h - r * gap, w, h, turned) for r in range(rows) for c in range(cols)]
    return cells, cols, rows, turned


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
        for x, y, w, h, _ in cells:
            Quartz.CGContextStrokeRect(ctx, Quartz.CGRectMake(x, y, w, h))
    if sheet_border:
        Quartz.CGContextStrokeRect(ctx, Quartz.CGRectMake(0.25, 0.25, sheet_w - 0.5, sheet_h - 0.5))


def sheet_pdf(logo: Logo, sheet_w, sheet_h, cells, sheet_border=True, cell_boxes=True) -> bytes:
    data = Quartz.CFDataCreateMutable(None, 0)
    consumer = Quartz.CGDataConsumerCreateWithCFData(data)
    media = Quartz.CGRectMake(0, 0, sheet_w, sheet_h)
    info = {Quartz.kCGPDFContextCreator: "Vectorizer Local", Quartz.kCGPDFContextTitle: f"Gang sheet - {logo.name}"}
    ctx = Quartz.CGPDFContextCreate(consumer, media, info)
    Quartz.CGPDFContextBeginPage(ctx, None)
    for x, y, w, h, turned in cells:
        _place(ctx, logo, x, y, w, h, turned)
    _outlines(ctx, sheet_w, sheet_h, cells, sheet_border, cell_boxes)
    Quartz.CGPDFContextEndPage(ctx)
    Quartz.CGPDFContextClose(ctx)
    return bytes(data)


def raster(pdf: bytes, dpi: float, transparent=True) -> Image.Image:
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

def sheet_eps(logo: Logo, sheet_w, sheet_h, cells, sheet_border=True, cell_boxes=True, dpi=300) -> bytes:
    head = ["%!PS-Adobe-3.0 EPSF-3.0", f"%%BoundingBox: 0 0 {math.ceil(sheet_w)} {math.ceil(sheet_h)}",
            f"%%HiResBoundingBox: 0 0 {sheet_w:.3f} {sheet_h:.3f}", "%%Creator: Vectorizer Local",
            f"%%Title: Gang sheet - {logo.name}", "%%LanguageLevel: 3", "%%Pages: 1", "%%EndComments",
            "%%Page: 1 1", "save"]
    body = []
    if logo.svg:     # vector: the logo's paths once, as a procedure, drawn in every cell
        root = ET.fromstring(export.clean_svg(logo.svg).encode())
        vb, wpt, hpt, sx, sy = export._page(root)          # the same placement as export.to_pdf
        ox, oy = (wpt - vb[2] * sx) / 2, (hpt - vb[3] * sy) / 2
        to_page = f"[{sx:.6f} 0 0 {-sy:.6f} {ox - vb[0] * sx:.4f} {hpt - oy + vb[1] * sy:.4f}] concat"
        bx, by, bw, bh = logo.box
        body.append("/logo {")
        body += export._ops(export._draw_items(root), ps=True)
        body.append("} bind def")
        for x, y, w, h, turned in cells:
            ww, hh = (h, w) if turned else (w, h)
            s = min(ww / bw, hh / bh)
            body.append(f"gsave {x + w / 2:.3f} {y + h / 2:.3f} translate" + (" 90 rotate" if turned else "")
                        + f" {s:.6f} dup scale {-(bx + bw / 2):.3f} {-(by + bh / 2):.3f} translate {to_page} logo grestore")
    else:            # the sheet as an image (white behind it: EPS has no transparency)
        im = raster(sheet_pdf(logo, sheet_w, sheet_h, cells, False, False), dpi, transparent=False).convert("RGB")
        data = base64.a85encode(zlib.compress(im.tobytes(), 6), adobe=False, wrapcol=76).decode() + "~>"
        body += [f"gsave 0 0 translate {sheet_w:.3f} {sheet_h:.3f} scale", "/DeviceRGB setcolorspace",
                 f"<< /ImageType 1 /Width {im.width} /Height {im.height} /BitsPerComponent 8 /Decode [0 1 0 1 0 1]",
                 f"/ImageMatrix [{im.width} 0 0 {-im.height} 0 {im.height}] /DataSource currentfile /ASCII85Decode filter /FlateDecode filter >> image",
                 data, "grestore"]
    lines = ["0 setgray 0.5 setlinewidth"]
    if cell_boxes:
        lines += [f"{x:.3f} {y:.3f} {w:.3f} {h:.3f} rectstroke" for x, y, w, h, _ in cells]
    if sheet_border:
        lines.append(f"0.25 0.25 {sheet_w - 0.5:.3f} {sheet_h - 0.5:.3f} rectstroke")
    tail = ["restore", "showpage", "%%EOF"]
    return ("\n".join(head + body + lines + tail) + "\n").encode("latin-1")


# --------------------------------------------------------------------------
# one call for the page

def make(logo: Logo, o: dict, fmt: str = "preview", dpi: float = 300):
    """o: sheet_w, sheet_h, logo_w, logo_h, margin, gap (all in `unit`), unit, rotate,
    sheet_border, cell_boxes; removed: places (row by row from the top left) left empty.
    Returns (bytes, mimetype, info)."""
    k = UNIT_PT.get(o.get("unit", "in"), 72.0)
    sw, sh = float(o["sheet_w"]) * k, float(o["sheet_h"]) * k
    lw, lh = float(o["logo_w"]) * k, float(o["logo_h"]) * k
    if min(sw, sh, lw, lh) <= 0:
        raise ValueError("Sizes must be more than 0.")
    if sw * sh > (200 * 72) ** 2:
        raise ValueError("The sheet is too large (over 200 x 200 in).")
    cells, cols, rows, turned = layout(sw, sh, lw, lh, float(o.get("margin", 0)) * k, float(o.get("gap", 0)) * k,
                                       bool(o.get("rotate", True)))
    # logos taken off the sheet leave their place empty: the layout and sheet stay the same
    removed = {int(i) for i in (o.get("removed") or []) if isinstance(i, (int, float)) or str(i).isdigit()}
    every = cells
    cells = [c for i, c in enumerate(every) if i not in removed]
    info = {"count": len(cells), "total": len(every), "cols": cols, "rows": rows, "turned": turned}
    if fmt == "preview":    # every place as fractions of the sheet, from the top left, for clicking
        info["cells"] = [[round(x / sw, 6), round((sh - y - h) / sh, 6), round(w / sw, 6), round(h / sh, 6)] for x, y, w, h, _ in every]
    border, boxes = bool(o.get("sheet_border", True)), bool(o.get("cell_boxes", False))
    if fmt == "eps":
        return sheet_eps(logo, sw, sh, cells, border, boxes, dpi), "application/postscript", info
    pdf = sheet_pdf(logo, sw, sh, cells, border, boxes)
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
