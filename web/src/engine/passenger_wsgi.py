"""EMB Pros engine, for cPanel "Setup Python App" (Passenger): the application startup file.
The key it shares with the website: EMB_ENGINE_KEY in the app's environment variables, or else the
file .emb-pros-key in the account's home folder, made here on the first start (read by config.php too)."""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# memory: the hosting plan has 2 GB for everything, so each worker keeps only the newest few logos
# (a page sends its logo again when it was let go) and a little drawing work for each
os.environ.setdefault("EMB_KEEP", "4")
os.environ.setdefault("EMB_GANG_KEEP", "6")
os.environ.setdefault("EMB_CACHE_MB", "64")
# one maths thread per worker: shared hosting counts every thread against the account's process
# limit, and numpy's maths library otherwise starts one thread per CPU core (24 or more)
for _v in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ.setdefault(_v, "1")
if not os.environ.get("EMB_ENGINE_KEY"):
    _key = os.path.join(os.path.expanduser("~"), ".emb-pros-key")
    if not os.path.isfile(_key):        # the first start: a long random key, readable by this account only
        import secrets
        fd = os.open(_key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(secrets.token_hex(32) + "\n")
    with open(_key) as f:
        os.environ["EMB_ENGINE_KEY"] = f.read().strip()

from app import app as application  # noqa: E402
