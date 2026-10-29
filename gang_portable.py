"""Gang sheets without macOS (a Linux web server): what gang.py does with Quartz, done with
pypdfium2 (Google's PDF engine: reading and drawing pages) and pikepdf (writing the sheet PDF).
A PDF or AI logo is placed on the sheet as its own vector page (a form XObject), so the sheet
PDF stays vector, as with Quartz; a raster logo is placed as an image. Both libraries are under
permissive licences (Apache-2.0 / BSD, MPL-2.0)."""

from __future__ import annotations

import io
import zlib

import pikepdf
import pypdfium2 as pdfium
from PIL import Image

MAX_RASTER_SIDE = 16000


def _render(data: bytes, scale: float, transparent=True):
    """The first page drawn at `scale` (pixels per point): (RGBA image, its box (x, y, w, h) in pt)."""
    doc = pdfium.PdfDocument(data)
    try:
        page = doc[0]
        l, b, r, t = page.get_cropbox()
        bitmap = page.render(scale=scale, fill_color=(0, 0, 0, 0) if transparent else (255, 255, 255, 255),
                             may_draw_forms=True)
        im = bitmap.to_pil().convert("RGBA")
        w, h = max(1, round((r - l) * scale)), max(1, round((t - b) * scale))
        if im.size != (w, h):        # the same pixel size as Quartz draws it (rounded, not rounded up)
            im = im.crop((0, 0, w, h)) if im.width >= w and im.height >= h else im.resize((w, h), Image.LANCZOS)
        return im, (l, b, r - l, t - b)
    finally:
        doc.close()


def load_pdf(data: bytes, name: str, logo_class, svg: str | None = None):
    """A PDF (or AI) logo, its artwork's box found by drawing it small (empty margins trimmed)."""
    try:
        doc = pdfium.PdfDocument(data)
        n = len(doc)
        l, b, r, t = doc[0].get_cropbox() if n else (0, 0, 0, 0)
        doc.close()
    except Exception:
        n = 0
    if n < 1:
        raise ValueError("This file could not be read as a PDF.")
    scale = 800 / max(r - l, t - b)
    im, (mx, my, mw, mh) = _render(data, scale)
    bbox = im.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
    if not bbox:
        raise ValueError("The PDF page is empty.")
    x0, y0, x1, y1 = bbox
    pad = 1.5
    bx = mx + max(0, x0 - pad) / scale
    by = my + (im.height - min(im.height, y1 + pad)) / scale       # PDF y is up
    bw = (min(im.width, x1 + pad) - max(0, x0 - pad)) / scale
    bh = (min(im.height, y1 + pad) - max(0, y0 - pad)) / scale
    logo = logo_class("pdf", name, box=(bx, by, bw, bh), svg=svg)
    logo.pdf = data
    return logo


def preview_of(logo, side=360) -> bytes:
    if logo.kind == "image":
        im = logo.image.copy()
        im.thumbnail((side, side))
    else:
        bx, by, bw, bh = logo.box
        scale = side / max(bw, bh)
        full, (mx, my, _mw, _mh) = _render(logo.pdf, scale)
        left = (bx - mx) * scale
        top = full.height - (by - my + bh) * scale
        im = full.crop((int(left), int(top), int(left + bw * scale), int(top + bh * scale)))
    buf = io.BytesIO(); im.save(buf, "PNG")
    return buf.getvalue()


def _image_xobject(pdf: pikepdf.Pdf, im: Image.Image):
    """An RGB image with its alpha as a soft mask."""
    im = im.convert("RGBA")
    rgb, alpha = im.convert("RGB").tobytes(), im.getchannel("A").tobytes()
    smask = pikepdf.Stream(pdf, zlib.compress(alpha, 6))
    smask.Type, smask.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
    smask.Width, smask.Height, smask.ColorSpace, smask.BitsPerComponent = im.width, im.height, pikepdf.Name.DeviceGray, 8
    smask.Filter = pikepdf.Name.FlateDecode
    img = pikepdf.Stream(pdf, zlib.compress(rgb, 6))
    img.Type, img.Subtype = pikepdf.Name.XObject, pikepdf.Name.Image
    img.Width, img.Height, img.ColorSpace, img.BitsPerComponent = im.width, im.height, pikepdf.Name.DeviceRGB, 8
    img.Filter, img.SMask = pikepdf.Name.FlateDecode, smask
    return img


def sheet_pdf(logos, sheet_w, sheet_h, cells, sheet_border=True, cell_boxes=True, title="logo") -> bytes:
    """The sheet as one PDF page, as gang.sheet_pdf draws it with Quartz: each logo fitted in its
    cell (proportions kept, centred, turned 90 degrees when the cell says so)."""
    out = pikepdf.new()
    xobjects, names, ops = pikepdf.Dictionary(), {}, []
    for x, y, w, h, turned, g, _ in cells:
        logo = logos[g]
        if g not in names:              # each logo once, drawn in all its cells
            nm = f"/L{g}"
            if logo.kind == "pdf":
                src = pikepdf.open(io.BytesIO(logo.pdf))
                xobjects[nm] = out.copy_foreign(pikepdf.Page(src.pages[0]).as_form_xobject())
            else:
                xobjects[nm] = _image_xobject(out, logo.image)
            names[g] = nm
        bx, by, bw, bh = logo.box
        ww, hh = (h, w) if turned else (w, h)
        s = min(ww / bw, hh / bh)
        dw, dh = bw * s, bh * s
        op = [f"q 1 0 0 1 {x + w / 2:.4f} {y + h / 2:.4f} cm"]
        if turned:
            op.append("0 1 -1 0 0 0 cm")
        if logo.kind == "pdf":
            op.append(f"{-dw / 2:.4f} {-dh / 2:.4f} {dw:.4f} {dh:.4f} re W n")
            op.append(f"{s:.6f} 0 0 {s:.6f} 0 0 cm 1 0 0 1 {-bx - bw / 2:.4f} {-by - bh / 2:.4f} cm {names[g]} Do Q")
        else:
            op.append(f"{dw:.4f} 0 0 {dh:.4f} {-dw / 2:.4f} {-dh / 2:.4f} cm {names[g]} Do Q")
        ops.append(" ".join(op))
    lines = ["0 0 0 RG 0.5 w"]
    if cell_boxes:
        lines += [f"{x:.3f} {y:.3f} {w:.3f} {h:.3f} re S" for x, y, w, h, *_ in cells]
    if sheet_border:
        lines.append(f"0.25 0.25 {sheet_w - 0.5:.3f} {sheet_h - 0.5:.3f} re S")
    content = pikepdf.Stream(out, ("\n".join(ops + lines) + "\n").encode("latin-1"))
    page = pikepdf.Dictionary(Type=pikepdf.Name.Page, MediaBox=[0, 0, sheet_w, sheet_h],
                              Resources=pikepdf.Dictionary(XObject=xobjects), Contents=content)
    out.pages.append(pikepdf.Page(page))
    out.docinfo["/Creator"] = "EMB Pros"
    out.docinfo["/Producer"] = "EMB Pros"
    out.docinfo["/Title"] = f"Gang sheet - {title}"
    buf = io.BytesIO()
    out.save(buf, compress_streams=True)
    return buf.getvalue()


def raster(pdf: bytes, dpi: float, transparent=True) -> Image.Image:
    doc = pdfium.PdfDocument(pdf)
    l, b, r, t = doc[0].get_cropbox()
    doc.close()
    scale = dpi / 72
    if max(r - l, t - b) * scale > MAX_RASTER_SIDE:
        raise ValueError(f"At {dpi:g} dpi this sheet would be over {MAX_RASTER_SIDE} pixels wide; choose a lower resolution.")
    im, _ = _render(pdf, scale, transparent)
    return im
