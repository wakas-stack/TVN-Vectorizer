#!/bin/bash
# EMB Pros engine on a VPS: one process with 8 threads (the logos a visitor uploads stay in it),
# listening only on this server (the PHP site reaches it at http://127.0.0.1:8765).
#   first time:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
#   start:       EMB_ENGINE_KEY='same as config.php' ./run.sh   (or the systemd service, see DEPLOY.md)
cd "$(dirname "$0")"
export EMB_KEEP="${EMB_KEEP:-32}"
exec .venv/bin/gunicorn --workers 1 --threads 8 --timeout 300 --bind 127.0.0.1:8765 app:app
