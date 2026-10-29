"""Build the EMB Pros website package from this project: web/dist/emb-pros-web/ and a zip.

  public_html/   the PHP site: the six pages (the header shared from includes/layout.php),
                 static/ (scripts, styles, data), api.php (passes /api/... to the engine),
                 .htaccess (the same addresses as the app: /, /pantone, /cap...), .user.ini
  engine/        the Python engine that does the work (the same code as the Mac app), with
                 passenger_wsgi.py (cPanel "Setup Python App"), requirements.txt and run.sh (a VPS)
  DEPLOY.md      how to put both online

Run: .venv/bin/python make_web.py   (again after any change to the app)
"""

import re
import shutil
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "web" / "dist" / "emb-pros-web"
PAGES = {"index": "/", "pantone": "/pantone", "thread": "/thread", "patch": "/patch", "gang": "/gang", "cap": "/cap"}
ENGINE_FILES = ["app.py", "engine.py", "precise.py", "planar.py", "upscale.py", "export.py", "patch.py", "gang.py",
                "gang_portable.py", "digitize.py", "worksheet.py"]
# models/ (the AI upscaler, 18 MB) stays on the Mac: without it the server traces as before
WEB_WORDS = [("Runs on this computer; nothing is uploaded anywhere.",
              "Your files are processed on the EMB Pros server, kept only while you work, never saved.")]
WEB = HERE / "web" / "src"           # the PHP files written by hand: api.php, includes/, .htaccess...


def page_php(name: str) -> str:
    html = (HERE / "static" / f"{name}.html").read_text()
    m = re.search(r"<header class=\"top\">.*?</header>", html, re.S)
    if not m:
        raise SystemExit(f"{name}.html: no header")
    html = html.replace(m.group(0), f"<?php emb_header('{PAGES[name]}'); ?>")
    for mac, web in WEB_WORDS:      # what is true of the Mac app, said as it is on the website
        html = html.replace(mac, web)
    return "<?php require __DIR__ . '/includes/layout.php'; ?>\n" + html


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    pub, eng = OUT / "public_html", OUT / "engine"
    shutil.copytree(HERE / "static", pub / "static", ignore=shutil.ignore_patterns("*.html", ".DS_Store"))
    for name in PAGES:
        (pub / f"{name}.php").write_text(page_php(name))
    left = [w for w, _ in WEB_WORDS if any(w in (pub / f"{n}.php").read_text() for n in PAGES)]
    if left:
        raise SystemExit(f"still says: {left}")
    shutil.copytree(WEB / "public_html", pub, dirs_exist_ok=True)
    eng.mkdir(parents=True)
    for f in ENGINE_FILES:
        shutil.copy2(HERE / f, eng / f)
    shutil.copytree(HERE / "static", eng / "static", ignore=shutil.ignore_patterns(".DS_Store"))
    shutil.copytree(WEB / "engine", eng, dirs_exist_ok=True)
    shutil.copy2(WEB / "DEPLOY.md", OUT / "DEPLOY.md")
    z = OUT.parent / "emb-pros-web.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(OUT.rglob("*")):
            if p.is_file() and "__pycache__" not in p.parts:
                zf.write(p, p.relative_to(OUT.parent))
    print(f"{OUT}\n{z} ({z.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    build()
