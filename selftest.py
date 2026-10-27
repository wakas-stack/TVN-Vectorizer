"""Checks run inside the app window (desktop.py --selftest)."""

from __future__ import annotations

import base64
import sys
import time


def _step(name):
    print(f"[selftest {time.strftime('%H:%M:%S')}] {name}", file=sys.stderr, flush=True)

DRAW_LOGO = """
const c = document.createElement('canvas'); c.width = 400; c.height = 250; const g = c.getContext('2d');
g.fillStyle = '#ffffff'; g.fillRect(0,0,400,250);
g.fillStyle = '#e12d2d'; g.beginPath(); g.arc(100,100,75,0,7); g.fill();
g.fillStyle = '#ffffff'; g.beginPath(); g.arc(100,100,25,0,7); g.fill();
g.fillStyle = '#1e5ac8'; g.beginPath(); g.roundRect(200,38,162,100,15); g.fill();
g.fillStyle = '#f5be1e'; g.fillRect(225,162,150,63);
g.fillStyle = '#121214'; g.font = 'bold 44px Arial'; g.fillText('AI', 232, 205);
"""


def _wait(win, expr, timeout=20):
    end = time.time() + timeout
    while time.time() < end:
        try:
            if win.evaluate_js(expr):
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def _snapshot(win, name):
    """Save what the window shows as PNG, when VL_SNAPSHOT_DIR is set (for checking the layout)."""
    import os
    import threading
    folder = os.environ.get("VL_SNAPSHOT_DIR")
    if not folder:
        return
    import AppKit
    from PyObjCTools import AppHelper
    from webview.platforms.cocoa import BrowserView
    view = BrowserView.instances[win.uid].webview
    done = threading.Event()

    def handler(image, error):
        if image is not None:
            rep = AppKit.NSBitmapImageRep.imageRepWithData_(image.TIFFRepresentation())
            rep.representationUsingType_properties_(AppKit.NSBitmapImageFileTypePNG, None).writeToFile_atomically_(f"{folder}/{name}.png", True)
        done.set()
    AppHelper.callAfter(lambda: view.takeSnapshotWithConfiguration_completionHandler_(None, handler))
    done.wait(10)


def run_checks(win, api):
    _step("page")
    out = {}
    out["page_loaded"] = _wait(win, "typeof openFile === 'function' && !!window.pywebview && !!window.pywebview.api")
    out["user_agent"] = win.evaluate_js("navigator.userAgent")
    _step("upload")
    # upload an image the same way a drop or file pick does, then wait for the result
    win.evaluate_js(DRAW_LOGO + """
      c.toBlob(b => { window.__st = 'tracing'; openFile(new File([b], 'logo.png', {type: 'image/png'})).then(() => S.pending).then(() => window.__st = 'done', e => window.__st = 'error ' + e); }, 'image/png');
    """)
    _wait(win, "window.__st === 'done' || String(window.__st).startsWith('error')", 30)
    _step("vectorized")
    out["vectorize"] = win.evaluate_js("({state: window.__st, status: document.querySelector('#status').textContent, layers: [...document.querySelectorAll('#layers li .name')].map(n => n.textContent)})")
    win.evaluate_js("fitView()"); time.sleep(0.5)
    _snapshot(win, "vectorizer")
    _step("exports")
    # PNG drawn in the page, and each server export
    win.evaluate_js("""
      window.__ex = null;
      (async () => {
        const o = {};
        for (const f of ['svg', 'pdf', 'eps', 'dxf']) {
          const r = await fetch('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({svg: S.result.svg, format: f, name: 't'})});
          o[f] = [r.status, (await r.blob()).size];
        }
        const svg = await (await fetch('/api/export', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({svg: S.result.svg, format: 'svg', name: 't'})})).text();
        const png = await svgToPng(svg, 2);
        o.png = [png.type, png.size];
        window.__png = await new Promise(r => { const fr = new FileReader(); fr.onload = () => r(fr.result.split(',')[1]); fr.readAsDataURL(png); });
        window.__ex = o;
      })().catch(e => window.__ex = {error: String(e)});
    """)
    _wait(win, "window.__ex !== null", 30)
    _step("exports done")
    out["exports"] = win.evaluate_js("window.__ex")
    _step("png")
    png = base64.b64decode(win.evaluate_js("window.__png") or "")
    out["png_header_ok"] = png[:8] == b"\x89PNG\r\n\x1a\n"
    out["save_api_present"] = bool(win.evaluate_js("typeof window.pywebview.api.save_file === 'function'"))
    out["thread_button"] = bool(win.evaluate_js("!!document.querySelector('#threadBtn')"))
    _step("pantone")
    # Pantone page in the same engine
    win.load_url(api.base_url + "/pantone?hex=E4002B,1E5AC8")
    _wait(win, "document.querySelectorAll('.pm-group').length === 2", 20)
    _step("pantone loaded")
    time.sleep(0.3)
    _snapshot(win, "pantone")
    out["pantone"] = win.evaluate_js("[...document.querySelectorAll('.pm-group')].map(g => g.querySelector('.pm-card .name').textContent + ' ' + g.querySelector('.pm-card .de').textContent.trim())")
    # CMYK input: the boxes come back from the address, and the colour is matched
    win.load_url(api.base_url + "/pantone?cmyk=0,100,81,4")
    _wait(win, "document.querySelectorAll('.pm-group').length === 1", 20)
    _wait(win, "!!document.querySelector('#cmykRow .ci-profile') && document.querySelector('#cmykRow .ci-profile').textContent.includes('FOGRA39')", 10)
    out["pantone_cmyk"] = win.evaluate_js("[...document.querySelectorAll('#cmykRow input')].map(i => i.value).join(',') + ' -> ' + document.querySelector('#hexInput').value + ' (' + document.querySelector('#cmykRow .ci-profile').textContent + ') -> ' + document.querySelector('.pm-card .name').textContent")
    # Thread match page: the best Isacord and Madeira thread for each colour
    _step("thread")
    win.load_url(api.base_url + "/thread?hex=F0E36A,0E6ACE")
    _wait(win, "document.querySelectorAll('.pm-group').length === 2", 20)
    time.sleep(0.3)
    _snapshot(win, "thread")
    out["thread"] = win.evaluate_js("[...document.querySelectorAll('.pm-group')].map(g => [...g.querySelectorAll('.th-best')].map(b => b.innerText.replace(/\\s+/g, ' ')))")
    # Patch mockup page: upload, each style, a large export
    _step("patch")
    win.load_url(api.base_url + "/patch")
    _wait(win, "typeof openFile === 'function'", 20)
    win.evaluate_js(DRAW_LOGO + """
      window.__pt = null;
      c.toBlob(async b => {
        try {
          await openFile(new File([b], 'logo.png', {type: 'image/png'}));
          const o = {};
          for (const st of ['woven', 'sublimated', 'leather', 'embroidery']) {
            S.opts.style = st; const blob = await fetchPng(600); o[st] = blob.size;
          }
          const big = await fetchPng(2000); o.export2000 = [big.type, big.size];
          o.colors = S.info.colors.length;
          // a thread number on an embroidered colour
          // the thread data loads on its own; wait for the boxes it draws
          for (let i = 0; i < 100 && !document.querySelector('#colors .pt-thread input'); i++) await new Promise(r => setTimeout(r, 100));
          const inp = document.querySelector('#colors .pt-thread input');
          if (!inp) throw new Error('no thread box (thread data ' + (T.books ? 'loaded' : 'not loaded') + ')');
          inp.value = '3902'; inp.dispatchEvent(new Event('change'));
          o.thread = Object.entries(T.pick).map(([id, n]) => id + '=' + n + ' ' + S.opts.recolor[id]).join(', ');
          // Robison-Anton Polyester 40: switch the chart, then pick 5625 Lemon by number
          const chart = document.querySelector('#threadChart');
          chart.value = 'robison-anton-polyester'; chart.dispatchEvent(new Event('change'));
          const ra = document.querySelector('#colors .pt-thread input'); ra.value = '5625'; ra.dispatchEvent(new Event('change'));
          o.thread_ra = [document.querySelector('#colors .pt-thread .tn')?.textContent.trim(), Object.values(T.pick).join(',')];
          chart.value = 'isacord-40'; chart.dispatchEvent(new Event('change'));
          // Faux/Leather: a leatherette sheet, and the logo made smaller inside the shape
          for (let i = 0; i < 100 && !SHEETS.list.length; i++) await new Promise(r => setTimeout(r, 100));
          setStyle('leather'); setSheet('walnut-black');
          o.leatherette = [$('#leatherette').value, S.opts.leather_texture, S.opts.engrave_color, (await fetchPng(600)).size];
          S.opts.logo_scale = 0.7; o.logo_scale_70 = (await fetchPng(600)).size; S.opts.logo_scale = 1;
          // seam stitch styles, thickness and colour on a rounded patch
          S.opts.shape = 'rounded'; S.opts.border = 'seam'; o.seams = {};
          for (const st of ['stitch', 'dotted', 'solid']) { S.opts.seam_style = st; S.opts.seam_width = 0.009; S.opts.border_color = '#5a3214'; o.seams[st] = (await fetchPng(600)).size; }
          S.opts.seam_style = 'stitch'; S.opts.seam_width = 0.006; S.opts.border_color = null; S.opts.shape = defaultShape();
          // Faux/Leather turns every logo colour into one logo
          o.leather_roles = [...new Set(S.info.colors.filter(c => c.kind === 'colour').map(c => S.opts.roles[c.id]))].join(',');
          // logo only with a filled outline, embroidered and leather
          S.opts.shape = 'logo'; S.opts.outline = 'filled'; o.outline = {leather: (await fetchPng(600)).size};
          // the layered leather PDF, on a rounded patch with a stitched seam
          S.opts.shape = 'rounded'; S.opts.border = 'seam';
          const pdf = await fetchPdf(); const pt = new TextDecoder('latin1').decode(new Uint8Array(await pdf.arrayBuffer()));
          o.leather_pdf = {shown: !document.querySelector('#savePdf').hidden, type: pdf.type, layers: [...pt.matchAll(/\/Type \/OCG \/Name \(([^)]*)\)/g)].map(m => m[1]).join(',')};
          S.opts.shape = 'logo';
          setStyle('embroidery'); S.opts.shape = 'logo'; S.opts.outline = 'filled'; o.outline.embroidery = (await fetchPng(600)).size;
          S.opts.outline = 'none'; S.opts.shape = defaultShape();
          setStyle('embroidery');
          window.__pt = o;
        } catch (e) { window.__pt = {error: String(e)}; }
      }, 'image/png');
    """)
    _wait(win, "window.__pt !== null", 60)
    out["patch"] = win.evaluate_js("window.__pt")
    # the paths a person uses: the file chooser's change event, then a drop on the page
    win.evaluate_js(DRAW_LOGO + """
      window.__ui = null;
      c.toBlob(async b => {
        try {
          const f = new File([b], 'picked.png', {type: 'image/png'});
          const o = {};
          const dt = new DataTransfer(); dt.items.add(f);
          const input = document.querySelector('#fileInput'); input.files = dt.files;
          const before = S.req;
          input.dispatchEvent(new Event('change', {bubbles: true}));
          for (let i = 0; i < 200 && (S.req === before || !document.querySelector('#busy').hidden); i++) await new Promise(r => setTimeout(r, 100));
          const img = document.querySelector('#preview');
          o.picker = {shown: !img.hidden, loaded: img.complete && img.naturalWidth > 0, file: document.querySelector('#fileInfo').textContent};
          const dt2 = new DataTransfer(); dt2.items.add(new File([b], 'dropped.png', {type: 'image/png'}));
          const before2 = S.req;
          document.querySelector('#stage').dispatchEvent(new DragEvent('drop', {bubbles: true, cancelable: true, dataTransfer: dt2}));
          for (let i = 0; i < 200 && (S.req === before2 || !document.querySelector('#busy').hidden); i++) await new Promise(r => setTimeout(r, 100));
          o.drop = {loaded: img.naturalWidth > 0, file: document.querySelector('#fileInfo').textContent};
          // with a logo loaded, "Choose logo" asks first; "Keep working" leaves the patch alone
          const realClick = input.click; let opened = 0; input.click = () => { opened++; };
          document.querySelector('#newLogo').click();
          const asked = !document.querySelector('#confirmNew').hidden;
          document.querySelector('#confirmKeep').click();
          o.confirm = {asked, closed: document.querySelector('#confirmNew').hidden, chooserOpened: opened};
          document.querySelector('#newLogo').click(); document.querySelector('#confirmDiscard').click();
          o.confirm.discardOpensChooser = opened === 1;
          input.click = realClick;
          window.__ui = o;
        } catch (e) { window.__ui = {error: String(e)}; }
      }, 'image/png');
    """)
    _wait(win, "window.__ui !== null", 60)
    out["patch_ui"] = win.evaluate_js("window.__ui")
    win.evaluate_js("setStyle('embroidery'); render()")
    _wait(win, "!document.querySelector('#preview').hidden && document.querySelector('#busy').hidden", 20)
    time.sleep(0.5)
    _snapshot(win, "patch")
    _step("patch done")
    # Gang sheet: a logo filling a Letter sheet, the vector PDF and a 300 dpi PNG
    _step("gang")
    win.load_url(api.base_url + "/gang")
    _wait(win, "typeof openFile === 'function'", 20)
    win.evaluate_js(DRAW_LOGO + """
      window.__gs = null;
      c.toBlob(async b => {
        try {
          await openFile(new File([b], 'logo.png', {type: 'image/png'}));
          const o = {count: document.querySelector('#count').textContent, h: document.querySelector('#logoH').value};
          for (const f of ['pdf', 'png']) { const r = await sheetRequest(f, 300); const bl = await r.blob(); o[f] = [bl.type, bl.size, r.headers.get('X-Gang-Count')]; }
          o.save_url = typeof window.pywebview.api.save_url === 'function';
          // take one logo and the second row off; the sheet keeps its size
          document.querySelector('.gs-cell').click(); await new Promise(r => setTimeout(r, 900));
          document.querySelectorAll('.gs-row')[1].click(); await new Promise(r => setTimeout(r, 900));
          const rr = await sheetRequest('pdf', 300);
          o.removed = {count: document.querySelector('#count').textContent, pdf: rr.headers.get('X-Gang-Count'), off: document.querySelectorAll('.gs-cell.off').length};
          // Cmd+Z twice puts the row and the logo back
          for (let k = 0; k < 2; k++) { document.dispatchEvent(new KeyboardEvent('keydown', {key: 'z', metaKey: true, bubbles: true})); await new Promise(r => setTimeout(r, 900)); }
          o.undo = document.querySelector('#count').textContent;
          window.__gs = o;
        } catch (e) { window.__gs = {error: String(e)}; }
      }, 'image/png');
    """)
    _wait(win, "window.__gs !== null", 60)
    out["gang"] = win.evaluate_js("window.__gs")
    _snapshot(win, "gang")
    return out
