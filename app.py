"""Local web app: http://127.0.0.1:8765"""

from __future__ import annotations

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

import engine
import export
import patch

try:                        # gang sheets use Quartz (macOS)
    import gang
except Exception:           # pragma: no cover - other systems
    gang = None

HERE = Path(__file__).parent
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 40 * 1024 * 1024

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
            while len(_patches) > 6:
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
    while len(_gang_logos) > 6:
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
    logo = _gang_logos.get(body.get("token", ""))
    if not logo:
        return jsonify(error="expired"), 404
    fmt = (body.get("format") or "preview").lower()
    if fmt != "preview" and fmt not in GANG_TYPES:
        return jsonify(error="Unknown format."), 400
    try:
        with _gang_lock:
            data, mime, info = gang.make(logo, body.get("options") or {}, fmt, float(body.get("dpi") or 300))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        logging.exception("request failed")
        return jsonify(error=f"Could not make the sheet: {e}"), 500
    if fmt == "preview":
        import base64
        return jsonify(info=info, png=base64.b64encode(data).decode())
    return Response(data, mimetype=mime, headers={"X-Gang-Count": str(info["count"])})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8765"))
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)
