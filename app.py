"""Local web app: http://127.0.0.1:8765"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import traceback
from collections import OrderedDict
from pathlib import Path

from flask import Flask, Response, jsonify, request, send_from_directory

import digitize
import engine
import export
import patch
import worksheet

try:                        # gang sheets use Quartz (macOS)
    import gang
except Exception:           # pragma: no cover - other systems
    gang = None

HERE = Path(__file__).parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024
# on a web server (engine/ in the PHP package): more logos kept between requests for many visitors,
# and, when EMB_ENGINE_KEY is set, only requests that carry it (from the site's api.php) are served
KEEP = int(os.environ.get("EMB_KEEP", "6"))
GANG_KEEP = int(os.environ.get("EMB_GANG_KEEP", str(4 * KEEP)))     # gang sheet logos kept (an image one is kept decoded)
ENGINE_KEY = os.environ.get("EMB_ENGINE_KEY", "")


@app.before_request
def _engine_key():
    if ENGINE_KEY and request.path.startswith("/api/") and request.headers.get("X-EMB-Key") != ENGINE_KEY:
        return jsonify(error="Not allowed."), 403

MIME = {"svg": "image/svg+xml", "pdf": "application/pdf", "eps": "application/postscript",
        "dxf": "application/dxf", "png": "image/png"}


@app.get("/")
def index():
    return send_from_directory(HERE / "static", "index.html")


@app.get("/pantone")
def pantone():
    return send_from_directory(HERE / "static", "pantone.html")


@app.get("/thread")
def thread():
    return send_from_directory(HERE / "static", "thread.html")


@app.get("/gang")
def gang_page():
    return send_from_directory(HERE / "static", "gang.html")


@app.get("/cap")
def cap_page():
    return send_from_directory(HERE / "static", "cap.html")


@app.get("/patch")
def patch_page():
    return send_from_directory(HERE / "static", "patch.html")


@app.get("/static/<path:name>")
def static_files(name):
    return send_from_directory(HERE / "static", name)


@app.post("/api/vectorize")
def vectorize():
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image was uploaded."), 400
    try:
        opts = json.loads(request.form.get("options") or "{}")
        return jsonify(engine.trace(f.read(), opts))
    except Exception as e:  # report the cause to the page
        logging.exception("request failed")
        return jsonify(error=f"Could not vectorize this image: {e}"), 400


@app.post("/api/export")
def export_file():
    body = request.get_json(force=True)
    fmt = (body.get("format") or "svg").lower()
    svg = body.get("svg") or ""
    name = re.sub(r"[^\w.-]+", "_", body.get("name") or "vectorized")
    try:
        if fmt == "svg":
            data = export.clean_svg(svg).encode()
        elif fmt == "pdf":
            data = export.to_pdf(svg)
        elif fmt == "eps":
            data = export.to_eps(svg)
        elif fmt == "png":
            data = export.to_png(svg, float(body.get("png_scale") or 4))
        elif fmt == "dxf":
            data = export.to_dxf(svg, body.get("dxf_level") or "lines")
        else:
            return jsonify(error=f"Unknown format {fmt}"), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Export failed: {e}"), 500
    return Response(data, mimetype=MIME[fmt],
                    headers={"Content-Disposition": f'attachment; filename="{name}.{fmt}"'})


# ---------------------------------------------------------------- patch mockups
_patches: OrderedDict = OrderedDict()       # token -> patch.Analysis (traced once, rendered often)
_patch_lock = threading.Lock()


@app.post("/api/patch/analyze")
def patch_analyze():
    f = request.files.get("image")
    if not f:
        return jsonify(error="No image was uploaded."), 400
    data = f.read()
    token = hashlib.sha1(data).hexdigest()[:16]
    try:
        with _patch_lock:
            if token not in _patches:
                _patches[token] = patch.Analysis(data)
            _patches.move_to_end(token)
            while len(_patches) > KEEP:
                _patches.popitem(last=False)
            info = _patches[token].info()
        return jsonify(token=token, **info)
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not read this logo: {e}"), 400


@app.get("/api/patch/info")
def patch_info():
    an = _patches.get(request.args.get("token", ""))
    if not an:
        return jsonify(error="expired"), 404
    return jsonify(token=request.args["token"], **an.info())


@app.post("/api/patch/render")
def patch_render():
    body = request.get_json(force=True)
    an = _patches.get(body.get("token", ""))
    if not an:
        return jsonify(error="expired"), 404
    try:
        with _patch_lock:      # one render at a time keeps memory use flat
            png = patch.render_png(an, body.get("options") or {}, int(body.get("size") or 1000))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not render the patch: {e}"), 500
    return Response(png, mimetype="image/png")


@app.post("/api/patch/pdf")
def patch_pdf():
    """Faux/Leather patch as a layered vector PDF (shape, logo, stitch lines)."""
    body = request.get_json(force=True)
    an = _patches.get(body.get("token", ""))
    if not an:
        return jsonify(error="expired"), 404
    try:
        pdf = patch.leather_pdf(an, body.get("options") or {})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not make the PDF: {e}"), 500
    return Response(pdf, mimetype="application/pdf")


# ---------------------------------------------------------------- gang sheets
_gang_logos: OrderedDict = OrderedDict()     # token -> gang.Logo
_gang_lock = threading.Lock()
GANG_TYPES = {"pdf": "PDF", "ai": "AI", "eps": "EPS", "png": "PNG", "jpg": "JPG", "tiff": "TIFF"}


@app.post("/api/gang/logo")
def gang_logo():
    if gang is None:
        return jsonify(error="Gang sheets need macOS."), 400
    f = request.files.get("logo")
    if not f:
        return jsonify(error="No logo was uploaded."), 400
    data = f.read()
    try:
        logo = gang.load_logo(data, f.filename or "logo")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not read this logo: {e}"), 400
    token = hashlib.sha1(data).hexdigest()[:16]
    _gang_logos[token] = logo
    _gang_logos.move_to_end(token)
    while len(_gang_logos) > GANG_KEEP:
        _gang_logos.popitem(last=False)
    import base64
    return jsonify(token=token, name=logo.name, kind=logo.kind, vector=logo.kind == "pdf",
                   svg=bool(logo.svg), aspect=logo.aspect,
                   pixels=list(logo.image.size) if logo.kind == "image" else None,
                   preview=base64.b64encode(gang.preview_of(logo)).decode())


@app.post("/api/gang/sheet")
def gang_sheet():
    """format "preview" -> JSON with a PNG; otherwise the file."""
    body = request.get_json(force=True)
    o = body.get("options") or {}
    if not o.get("logos"):        # one logo, the sheet filled with it
        o["logos"] = [{"token": body.get("token", ""), "w": o.get("logo_w", 0), "h": o.get("logo_h", 0), "qty": None}]
    logos = [_gang_logos.get(str(e.get("token", ""))) for e in o["logos"]]
    if not all(logos):
        return jsonify(error="expired"), 404
    fmt = (body.get("format") or "preview").lower()
    if fmt != "preview" and fmt not in GANG_TYPES:
        return jsonify(error="Unknown format."), 400
    try:
        with _gang_lock:
            data, mime, info = gang.make(logos, o, fmt, float(body.get("dpi") or 300))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not make the sheet: {e}"), 500
    if fmt == "preview":
        import base64
        return jsonify(info=info, png=base64.b64encode(data).decode())
    return Response(data, mimetype=mime, headers={"X-Gang-Count": str(info["count"])})


# ---------------------------------------------------------------- cap embroidery (.DST)
# the logo is traced like a patch mockup (patch.Analysis, kept in _patches), then digitized
_thread_books = None


def _books():
    global _thread_books
    if _thread_books is None:
        _thread_books = {b["id"]: b for b in json.loads((HERE / "static" / "thread-data.json").read_text(encoding="utf-8"))["books"]}
    return _thread_books


@app.post("/api/cap/analyze")
def cap_analyze():
    f = request.files.get("image")
    if not f:
        return jsonify(error="No logo was uploaded."), 400
    data = f.read()
    token = hashlib.sha1(data).hexdigest()[:16]
    try:
        if data[:4] == b"%PDF" or (f.filename or "").lower().endswith((".pdf", ".ai")):
            if gang is None:
                return jsonify(error="PDF logos need macOS; use a PNG or JPG."), 400
            data = gang.preview_of(gang.load_logo(data, f.filename or "logo.pdf"), side=2000)   # the artwork as an image
        with _patch_lock:
            if token not in _patches:
                _patches[token] = patch.Analysis(data)
            _patches.move_to_end(token)
            while len(_patches) > KEEP:
                _patches.popitem(last=False)
            an = _patches[token]
            info = an.info()
            # the logo itself (not its background): its proportions, for the size before digitizing
            logo = [g for k, g in an.regions.items() if not k.endswith("/background") and not g.is_empty]
            if logo:
                from shapely.ops import unary_union
                x0, y0, x1, y1 = unary_union(logo).bounds
                info["logo_box"] = [x0, y0, x1, y1]
                info["aspect"] = (x1 - x0) / max(y1 - y0, 1e-9)
        # a PDF is shown as the image it was read as (a browser cannot draw it)
        if (f.filename or "").lower().endswith((".pdf", ".ai")) or f.mimetype == "application/pdf":
            info["image"] = "data:image/png;base64," + base64.b64encode(data).decode()
        return jsonify(token=token, **info)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not read this logo: {e}"), 400


@app.post("/api/cap/threads")
def cap_threads():
    """The nearest threads of a chart to each of the logo's colours."""
    body = request.get_json(force=True)
    book = _books().get(body.get("chart") or "isacord-40")
    if not book:
        return jsonify(error="Unknown thread chart."), 400
    hexes = [h for h in body.get("colors") or [] if re.fullmatch(r"#[0-9a-fA-F]{6}", h or "")]
    return jsonify(chart=book["id"], title=book["title"], matches=digitize.nearest_threads(hexes, book) if hexes else [])


def _cap_run(body):
    an = _patches.get(body.get("token", ""))
    if not an:
        return None
    with _patch_lock:
        return digitize.digitize(an, body.get("options") or {})


@app.post("/api/cap/stitches")
def cap_stitches():
    """The stitches for the preview: [x, y, command] in 0.1 mm, the colours, the totals."""
    body = request.get_json(force=True)
    try:
        r = _cap_run(body)
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not digitize the logo: {e}"), 500
    if r is None:
        return jsonify(error="expired"), 404
    st, colors, info = r
    return jsonify(stitches=[[round(x * 10), round(y * 10), c] for x, y, c in st], colors=colors, info=info)


@app.post("/api/cap/file")
def cap_file():
    """format "dst" (the machine file) or "png" (the preview with the thread list)."""
    body = request.get_json(force=True)
    fmt = (body.get("format") or "dst").lower()
    try:
        r = _cap_run(body)
        if r is None:
            return jsonify(error="expired"), 404
        st, colors, info = r
        name = str((body.get("options") or {}).get("name") or "cap")
        if fmt == "dst":
            return Response(digitize.write_dst(st, name), mimetype="application/octet-stream")
        if fmt == "pdf":             # the production worksheet, laid out like Wilcom's
            threads = body.get("threads") or {}        # region id -> {code, name, brand}
            cols = [{**c, **(threads.get(c["id"]) or threads.get(c["id"].split("~")[0]) or {})} for c in colors]    # a colour sewn in blocks: its thread
            o = {**digitize.DEFAULTS, **{k: v for k, v in (body.get("options") or {}).items() if v is not None}}
            inch = lambda mm: f"{float(mm) / 25.4:.2f} in"
            settings = [
                ("Area", f"{inch(o['width_mm'])} x {inch(o['height_mm'])}"),
                ("Embroidery", "3D puff" if o["kind"] == "puff" else "Flat"),
                ("Sewing starts", "at the centre, outwards" if o["order"] == "center" else "at the bottom, centre-out"),
                ("Machine start", "bottom centre" if o["origin"] == "bottom" else "centre of the design"),
                ("Density", f"{float(o['density']):.2f} mm"),
                ("Pull comp.", f"{float(o['pull_comp']):.1f} mm"),
                ("Tack-down", "yes" if o["tackdown"] else "no"),
                ("Fewer stitches", "yes" if o["light"] else "no"),
            ]
            if o.get("crown_mm"):
                settings.append(("Crown", inch(o["crown_mm"])))
            if float(o.get("tilt") or 0):
                settings.append(("Turned", f"{float(o['tilt']):g} deg"))
            settings.append(("Sewing time", f"about {max(1, round(info['minutes']))} min at 650/min"))
            pdf = worksheet.worksheet_pdf(st, cols, info, digitize.write_dst(st, name), name=body.get("title") or name,
                                          chart=body.get("chart") or "", cap=None,     # no background behind the logo
                                          notes=info["notes"], settings=settings)
            return Response(pdf, mimetype="application/pdf")
        if fmt == "png":
            labels = body.get("labels") or {}          # region id -> "Isacord 40 · 0015 White"
            cols = [{**c, "label": labels.get(c["id"]) or c["hex"]} for c in colors]
            png = digitize.render_png(st, cols, info, None, title=body.get("title") or name)
            return Response(png, mimetype="image/png")
        return jsonify(error="Unknown format."), 400
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not make the file: {e}"), 500


# ---------------------------------------------------------------- a DST opened, edited, saved again
@app.post("/api/cap/dst-open")
def cap_dst_open():
    """A .dst file: its stitches [x, y, command] in 0.1 mm, a colour for each colour block, totals."""
    f = request.files.get("file")
    if not f:
        return jsonify(error="No file was uploaded."), 400
    try:
        st = digitize.stitches_from_dst(f.read())
    except ValueError as e:
        return jsonify(error=str(e)), 400
    blocks = 1 + sum(1 for p in st if p[2] == digitize.COLOR)
    colors = [{"id": f"block{i}", "hex": digitize.DST_COLOURS[i % len(digitize.DST_COLOURS)]} for i in range(blocks)]
    return jsonify(stitches=[[round(x * 10), round(y * 10), c] for x, y, c in st], colors=colors,
                   info=digitize.stitch_info(st, colors))


@app.post("/api/cap/shape")
def cap_shape():
    """A shape or pen line drawn on an opened DST (pts in 0.1 mm, closed or a line width_mm wide),
    digitized: its stitches [x, y, command] in 0.1 mm."""
    from shapely.geometry import LineString, Polygon
    body = request.get_json(force=True)
    try:
        pts = [(float(x) / 10, float(y) / 10) for x, y in body.get("pts") or []]
        if len(pts) < 2:
            return jsonify(error="Draw a little more."), 400
        geom = Polygon(pts) if body.get("closed") and len(pts) >= 3 else \
            LineString(pts).buffer(max(float(body.get("width_mm") or 1.5), 0.5) / 2, cap_style=1, join_style=1)
        st = digitize.sew_shape(geom, body.get("options") or {})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not sew the shape: {e}"), 500
    return jsonify(stitches=[[round(x * 10), round(y * 10), c] for x, y, c in st])


@app.post("/api/cap/pathfinder")
def cap_pathfinder():
    """Shapes drawn on a logo combined (op: unite, minus, intersect or exclude; shapes back to front,
    as sent for digitizing, with the page's edits): the result's rings in image pixels."""
    body = request.get_json(force=True)
    try:
        rings = digitize.pathfinder(body.get("op"), body.get("shapes") or [], body.get("edits") or {})
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not combine the shapes: {e}"), 500
    return jsonify(rings=rings)


@app.post("/api/cap/dst-file")
def cap_dst_file():
    """An opened DST as edited on the page (body: stitches in 0.1 mm, colours with their threads),
    written again: format "dst", "png" or "pdf"."""
    body = request.get_json(force=True)
    fmt = (body.get("format") or "dst").lower()
    name = str(body.get("name") or "design")
    try:
        st = [(float(x) / 10, float(y) / 10, int(c)) for x, y, c in body.get("stitches") or []]
        if not any(c == digitize.STITCH for _, _, c in st):
            return jsonify(error="Nothing to stitch."), 400
        if st[-1][2] != digitize.END:
            st.append((st[-1][0], st[-1][1], digitize.END))
        colors = body.get("colors") or []
        info = digitize.stitch_info(st, colors)
        dst = digitize.write_dst(st, name)
        if fmt == "dst":
            return Response(dst, mimetype="application/octet-stream")
        if fmt == "pdf":
            pdf = worksheet.worksheet_pdf(st, colors, info, dst, name=body.get("title") or name,
                                          chart=body.get("chart") or "", cap=None, notes=[],
                                          settings=[("Opened from", "a DST file"),
                                                    ("Sewing time", f"about {max(1, round(info['minutes']))} min at 650/min")])
            return Response(pdf, mimetype="application/pdf")
        if fmt == "png":
            cols = [{**c, "label": c.get("label") or c["hex"]} for c in colors]
            return Response(digitize.render_png(st, cols, info, None, title=body.get("title") or name), mimetype="image/png")
        return jsonify(error="Unknown format."), 400
    except (ValueError, TypeError) as e:
        return jsonify(error=f"Could not make the file: {e}"), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not make the file: {e}"), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
