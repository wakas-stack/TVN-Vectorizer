# EMB Pros on your website

Two parts, both in this package:

| Folder | What it is | Where it goes |
| --- | --- | --- |
| `public_html/` | The website, in PHP: the six tools, the EMB Pros header, scripts, styles and data. `api.php` passes the heavy work to the engine. | Your domain's web folder (in cPanel: `public_html`). |
| `engine/` | The engine, in Python: tracing, Pantone and thread matching, patch mockups, gang sheets and DST digitizing. The same code as the Mac app, so results are the same. | Next to it, as a Python app (it never goes inside `public_html`). |

PHP shows the pages and forwards each `/api/...` request; Python does the work. PHP alone
cannot do it: tracing (vtracer), geometry (shapely, numpy) and DXF (ezdxf) have no PHP
equivalent.

You need: PHP 8.0 or newer with the **cURL** extension (almost every host has it), and
**Python 3.12 or 3.13** where the engine runs, on Linux x86_64. The engine's packages are pinned to
versions with ready-made builds for older servers too (glibc 2.17, the CentOS 7 based CloudLinux
many cPanel hosts still run), so nothing has to be compiled. Older Python (3.10, 3.11) cannot install
them. Uploads up to 48 MB are allowed by the `.user.ini` and `.htaccess` in `public_html`.

---

## A. cPanel hosting with "Setup Python App" (most hosts)

Look in cPanel under **Software** for **Setup Python App** (CloudLinux / Passenger). If it is
there, everything runs on your one hosting account. (This is how embpromos.com was set up, on
29 Oct 2026.)

1. **Upload the website.** Set `EMB_ENGINE_URL` in `public_html/config.php` to
   `https://your-domain.com/engine` first, zip the *contents* of `public_html/` (so `index.php`,
   `.htaccess` and `.user.ini` are at the top of the zip), upload it into `public_html` in
   **File Manager** and **Extract** it there.
2. **Upload the engine.** Zip the `engine/` folder as `emb-pros-engine/`, upload it, and extract it
   into your home folder (the Extract dialog: path `/`), so it is `/home/YOURUSER/emb-pros-engine`,
   outside `public_html`.
3. **Create the Python app.** In **Setup Python App** > **Create Application**:
   - Python version: **3.12** (or 3.13)
   - Application root: `emb-pros-engine`
   - Application URL: your domain, path `engine`
   - Application startup file: `passenger_wsgi.py`, entry point: `application`
   - **Create**. No environment variables are needed.
4. **Put the engine's start-up file back.** Creating the app replaces `passenger_wsgi.py` with
   cPanel's own (which then fails with "maximum recursion depth exceeded"). Upload
   `engine/passenger_wsgi.py` from this package again over it (or extract the engine zip once more).
5. **Install the engine's packages.** On the app's page the top line shows a `source .../activate`
   command. In cPanel **Terminal** run it, then:
   ```bash
   pip install --only-binary=:all: -r requirements.txt
   ```
   (`--only-binary` stops pip from trying to compile anything; the Run Pip Install button does the
   same without it.) It takes about a minute and some 230 MB of disk. Then **Restart** the app (or
   `touch tmp/restart.txt` in the app folder).
6. **The key** that keeps the engine for your website only is made by the engine itself the first
   time it starts: `~/.emb-pros-key`, readable by your account only. `config.php` reads the same
   file, so nothing is typed anywhere. (To use a key of your own instead, set `EMB_ENGINE_KEY` in the
   app's environment variables and in `config.php`.)
7. Open `https://your-domain.com`. Try each tool (section C).

If **Setup Python App** is not there, or it offers no Python 3.12 or 3.13, ask the host to add it
(CloudLinux calls it alt-python 3.12), or use a small VPS (B) for the engine only (the website can stay on this hosting; set
`EMB_ENGINE_URL` to the VPS address, `http://VPS-IP:8765`, and open that port only to your
hosting's IP).

## B. A VPS (Ubuntu 24.04 or Debian 13, with Apache or nginx and PHP)

These come with Python 3.12 or newer (Ubuntu 22.04 has 3.10: too old for the engine).

```bash
sudo apt install python3 python3-venv php-curl unzip
sudo mkdir -p /var/www/emb-pros && sudo unzip emb-pros-web.zip -d /tmp/emb && \
  sudo cp -r /tmp/emb/emb-pros-web/* /var/www/emb-pros/
cd /var/www/emb-pros/engine
sudo python3 -m venv .venv && sudo .venv/bin/pip install -r requirements.txt
sudo chmod +x run.sh
sudo cp emb-pros-engine.service /etc/systemd/system/     # then edit it: the key (and paths, user)
sudo systemctl daemon-reload && sudo systemctl enable --now emb-pros-engine
```

Point the domain's web root at `/var/www/emb-pros/public_html`, and in `config.php` set
`EMB_ENGINE_URL` to `http://127.0.0.1:8765` and `EMB_ENGINE_KEY` to the key in the service file.

- **Apache**: `.htaccess` works as it is (enable `mod_rewrite`; `AllowOverride All`).
- **nginx**: add to the site's `server { }` block:
  ```nginx
  client_max_body_size 48m;
  location ~ ^/(includes/|config\.php) { deny all; }
  location /api/ { rewrite ^/api/(.+)$ /api.php?__path=$1 last; }
  location ~ ^/(pantone|thread|patch|gang|cap)/?$ { rewrite ^/([a-z]+)/?$ /$1.php last; }
  location ~ \.php$ { include snippets/fastcgi-php.conf; fastcgi_pass unix:/run/php/php-fpm.sock;
                      fastcgi_read_timeout 300; fastcgi_buffering off; }
  ```

## C. Checking it works

- `https://your-domain.com` shows the Logo Vectorizer with the EMB Pros header; each tab opens.
- **Logo Vectorizer**: drop a PNG, download SVG/PDF.
- **DST Maker**: choose a logo, click Digitize, download the DST.
- **Gang Sheet Maker**: add a PDF logo, download the PDF.
- If a tool says *"The EMB Pros engine is not reachable"*: the engine is not running, or
  `EMB_ENGINE_URL` in `config.php` is wrong. *"Not allowed"*: the two keys differ (or the engine
  made its key after the page was opened: try once more). An *error 500* from `/engine/`: read
  `stderr.log` in the app folder.
  `https://your-domain.com/engine/` (A) should show a page; the engine's log is in its app
  folder (cPanel) or `journalctl -u emb-pros-engine` (VPS).

## Notes

- Memory: a cPanel plan counts the engine's memory (RAM) against "Physical Memory Usage". The
  engine keeps only the newest few logos per worker (`EMB_KEEP` 4, `EMB_GANG_KEEP` 6) and at most
  64 MB of drawing work per logo (`EMB_CACHE_MB`), set in `passenger_wsgi.py`; a page sends its logo
  again when it was let go. A large mockup or sheet still needs a few hundred MB while it is drawn.
  Raise the numbers on a plan with more memory for faster repeat requests.

- On the website, files download through the browser (the Mac app asked where to save).
  "Save DST, PDF and PNG" downloads three files; the browser may ask once to allow it.
- Gang sheets: on a Mac the app reads PDF/AI logos with macOS; the server uses pypdfium2 and
  pikepdf. Layout and vector output are the same. Previews and PNG/JPG/TIFF of logos with print
  (CMYK) colours can look a shade lighter than on the Mac; PDF/AI/EPS downloads keep the colours.
- Updating: on the Mac, run `.venv/bin/python make_web.py` and upload the new package
  (keep your `config.php`).
