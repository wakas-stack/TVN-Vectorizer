"""Desktop app: runs the local server and shows it in its own window.

    python desktop.py              open the app
    python desktop.py --selftest   open, run the page checks, print the result, close
"""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

LOG = Path.home() / "Library" / "Logs" / "EMB Pros.log"
LOG.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(filename=LOG, level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logging.getLogger("werkzeug").setLevel(logging.WARNING)   # no per-request lines
logging.getLogger("ezdxf").setLevel(logging.WARNING)

from werkzeug.serving import make_server  # noqa: E402

import app as webapp  # noqa: E402


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Api:
    """Functions the page can call as window.pywebview.api.*"""

    def __init__(self, base_url: str):
        self.base_url = base_url
        self.window = None

    def save_file(self, name, b64):
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        res = self.window.create_file_dialog(kind, directory=str(Path.home() / "Downloads"), save_filename=name)
        if not res:
            return None
        path = res if isinstance(res, str) else res[0]
        Path(path).write_bytes(base64.b64decode(b64))
        logging.info("saved %s", path)
        return path

    def save_url(self, name, path, body):
        """Save what the local server returns for a POST (large files, without passing them
        through the page). Returns the saved path, None if cancelled, or {"error": ...}."""
        import urllib.error
        import urllib.request
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        res = self.window.create_file_dialog(kind, directory=str(Path.home() / "Downloads"), save_filename=name)
        if not res:
            return None
        dest = res if isinstance(res, str) else res[0]
        req = urllib.request.Request(self.base_url + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                Path(dest).write_bytes(r.read())
        except urllib.error.HTTPError as e:
            try:
                return {"error": json.loads(e.read()).get("error", str(e))}
            except Exception:
                return {"error": str(e)}
        logging.info("saved %s", dest)
        return dest

    def save_bundle(self, files):
        """Save several files the local server makes (files: [{name, path, body}]) into one folder
        the user picks. Returns the folder, None if cancelled, or {"error": ...}."""
        import urllib.error
        import urllib.request
        import webview
        kind = getattr(getattr(webview, "FileDialog", None), "FOLDER", None) or webview.FOLDER_DIALOG
        res = self.window.create_file_dialog(kind, directory=str(Path.home() / "Downloads"))
        if not res:
            return None
        folder = Path(res if isinstance(res, str) else res[0])
        for f in files:
            req = urllib.request.Request(self.base_url + f["path"], data=json.dumps(f["body"]).encode(),
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=900) as r:
                    (folder / f["name"]).write_bytes(r.read())
            except urllib.error.HTTPError as e:
                try:
                    return {"error": json.loads(e.read()).get("error", str(e))}
                except Exception:
                    return {"error": str(e)}
        logging.info("saved %d files to %s", len(files), folder)
        return str(folder)

    def open_window(self, title, path):
        import webview
        webview.create_window(title, self.base_url + path, js_api=self, width=1200, height=860, min_size=(420, 600))


def main():
    # --selftest, or VL_SELFTEST=1 (which `open --env` passes to an app launched like a double-click)
    selftest = "--selftest" in sys.argv or os.environ.get("VL_SELFTEST") == "1"
    port = free_port()
    server = make_server("127.0.0.1", port, webapp.app, threaded=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}/"
    logging.info("serving %s (python %s, %s)", url, sys.version.split()[0], os.uname().machine)

    try:
        import webview
    except Exception:  # no window library: use the default browser instead
        logging.exception("pywebview unavailable; opening the browser")
        webbrowser.open(url)
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return

    api = Api(url.rstrip("/"))
    win = webview.create_window("EMB Pros", url, js_api=api, width=1440, height=920, min_size=(900, 620))
    api.window = win
    result = {}
    if selftest:
        def run():
            from selftest import run_checks
            try:
                result.update(run_checks(win, api))
            except Exception as e:
                result["error"] = repr(e)
            finally:
                win.destroy()
        webview.start(run)
        print(json.dumps(result, indent=1), flush=True)
        logging.info("selftest %s", json.dumps(result))
    else:
        webview.start()
    # the window is closed: quit for good, even if a request thread or the GUI loop lingers
    threading.Thread(target=server.shutdown, daemon=True).start()
    logging.info("window closed, quitting")
    logging.shutdown()
    os._exit(0)


if __name__ == "__main__":
    main()
