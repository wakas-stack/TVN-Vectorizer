// Gang sheet page: logos repeated across a sheet, each at its own size and quantity
"use strict";

const $ = (s) => document.querySelector(s);
const UNIT_IN = { in: 1, cm: 1 / 2.54, mm: 1 / 25.4 };     // one unit, in inches
const dpiNow = () => +$("#dpi").value || 300;
const unitIn = (u) => (u === "px" ? 1 / dpiNow() : UNIT_IN[u]);   // px: at the Download dpi
// logos: what goes on the sheet, in order: {token, w, h, qty} (qty null: fills the rest of the sheet);
// the same logo can be there twice at two sizes. files: token -> {file, name, j} (the upload's answer)
const G = { logos: [], files: new Map(), req: 0, removed: new Set(), layoutKey: null, cells: [], info: null,
            history: [], last: null, dirty: false, pop: null };
window.embHasWork = () => G.logos.length > 0;    // leave.js: logos are on the sheet
const UNDO_STEPS = 50;

function toast(msg, isError = false, ms = 3800) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function busy(on, text) { $("#busy").hidden = !on; if (text) $("#busyText").textContent = text; }
const num = (id) => parseFloat($(id).value) || 0;
const round = (v) => Math.round(v * 1000) / 1000;
const unit = () => setUnit.cur;
const aspect = (token) => G.files.get(token)?.j.aspect || 1;
const nameOf = (token) => G.files.get(token)?.name || "logo";
const fill = () => G.logos.find((l) => l.qty === null);

function options() {
  // pixels are sent as inches at the Download dpi (the engine knows in, cm and mm)
  const px = unit() === "px", k = px ? 1 / dpiNow() : 1;
  return {
    sheet_w: num("#sheetW") * k, sheet_h: num("#sheetH") * k, gap: num("#gap") * k, margin: num("#margin") * k, unit: px ? "in" : unit(),
    rotate: $("#rotate").checked, cell_boxes: $("#boxes").checked, sheet_border: $("#border").checked,
    logos: G.logos.map(({ token, w, h, qty }) => ({ token, w: w * k, h: h * k, qty })), removed: [...G.removed],
  };
}

// ---------------------------------------------------------------- logos
async function upload(file) {
  const fd = new FormData(); fd.append("logo", file, file.name || "logo.png");
  const r = await fetch("/api/gang/logo", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
  G.files.set(j.token, { file, j, name: (file.name || "Pasted logo").replace(/\.[^.]+$/, "") });
  return j.token;
}
// the app restarted or let the logos go: read them all again (a logo keeps its token)
async function reupload() {
  for (const t of new Set(G.logos.map((l) => l.token))) await upload(G.files.get(t).file);
}

// a new logo from the button, a drop or a paste: the first fills the sheet, the next ones come one at a time
async function openFile(file) {
  if (!file) return;
  busy(true, "Reading the logo…");
  try {
    const token = await upload(file);
    beforeEdit();
    const w = round(1.5 / unitIn(unit()));
    G.logos.push({ token, w, h: round(w / aspect(token)), qty: fill() ? 1 : null });
    G.removed.clear();
    renderCards();
    updateFormat();
    await render();
    if (G.logos.length > 1) {
      const q = $("#logoList").lastElementChild?.querySelector(".lq");
      q?.focus(); q?.select();
      toast(`Added ${nameOf(token)}: set its size and quantity in Logos.`);
    }
  } catch (e) { toast(e.message, true, 7000); }
  finally { busy(false); }
}
$("#fileInput").addEventListener("change", (e) => { openFile(e.target.files[0]); e.target.value = ""; });
$("#newLogo").addEventListener("click", () => $("#fileInput").click());
$("#addLogo").addEventListener("click", () => $("#fileInput").click());
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) openFile(f); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) openFile(item.getAsFile());
});

// one card per logo: its size, its quantity or "fill the rest", and how many are on the sheet
function renderCards() {
  const list = $("#logoList");
  list.innerHTML = "";
  G.logos.forEach((l, i) => {
    const f = G.files.get(l.token), j = f.j;
    const card = document.createElement("div");
    card.className = "gs-card";
    card.innerHTML = `
      <img alt="" src="data:image/png;base64,${j.preview}">
      <div class="gs-card-name"><b></b><small></small></div>
      <button type="button" class="gs-x" title="Take this logo off the sheet" aria-label="Take this logo off the sheet">×</button>
      <div class="row gs-dims"><label>W <input type="number" class="lw" min="0.01" step="0.01"></label>
        <label>H <input type="number" class="lh" min="0.01" step="0.01"></label><span class="unit-label">${unit()}</span></div>
      <div class="row gs-dims"><label>Qty <input type="number" class="lq" min="0" step="1"></label>
        <label class="check"><input type="checkbox" class="lf"> Fill the rest</label></div>
      <small class="gs-warn" hidden></small>`;
    card.querySelector("b").textContent = f.name;
    card.querySelector("small").textContent = j.vector ? (j.svg ? "Vector (SVG)" : "Vector (PDF / AI)") : `Image, ${j.pixels[0]} × ${j.pixels[1]} px`;
    const lw = card.querySelector(".lw"), lh = card.querySelector(".lh"), lq = card.querySelector(".lq"), lf = card.querySelector(".lf");
    lw.value = l.w; lh.value = l.h; lf.checked = l.qty === null; lq.disabled = l.qty === null;
    if (l.qty !== null) lq.value = l.qty;
    const edit = (fn) => { beforeEdit(); fn(); G.removed.clear(); renderSoon(); };
    lw.addEventListener("input", () => edit(() => {
      l.w = parseFloat(lw.value) || 0;
      if ($("#keep").checked) { l.h = round(l.w / aspect(l.token)); lh.value = l.h; }
    }));
    lh.addEventListener("input", () => edit(() => {
      l.h = parseFloat(lh.value) || 0;
      if ($("#keep").checked) { l.w = round(l.h * aspect(l.token)); lw.value = l.w; }
    }));
    lq.addEventListener("input", () => edit(() => (l.qty = Math.max(0, parseInt(lq.value, 10) || 0))));
    lf.addEventListener("change", () => edit(() => {
      if (lf.checked) {         // only one logo fills the rest: the one that did keeps the number it had
        G.logos.forEach((o, k) => { if (o !== l && o.qty === null) o.qty = G.info?.logos?.[k]?.placed ?? 1; });
        l.qty = null;
      } else l.qty = G.info?.logos?.[i]?.placed ?? 1;
      renderCards();
    }));
    card.querySelector(".gs-x").addEventListener("click", () => {
      beforeEdit();
      G.logos.splice(i, 1);
      if (G.logos.length && !fill() && l.qty === null) G.logos[0].qty = null;     // the sheet stays full
      G.removed.clear();
      renderCards(); updateFormat();
      if (G.logos.length) render(); else clearSheet();
    });
    list.appendChild(card);
  });
  $("#addLogo").hidden = $("#keepRow").hidden = !G.logos.length;
}
// the counts on the cards, after each render
function updateCards() {
  [...$("#logoList").children].forEach((card, i) => {
    const l = G.logos[i], s = G.info?.logos?.[i];
    if (!l || !s) return;
    const lq = card.querySelector(".lq");
    if (l.qty === null && document.activeElement !== lq) lq.value = s.on;
    const w = card.querySelector(".gs-warn");
    const short = l.qty !== null ? l.qty - s.placed : 0;
    w.hidden = !short && s.on === s.placed;
    w.textContent = short ? `${short} of ${l.qty} do not fit: make it smaller or the sheet larger.` : `${s.on} on the sheet, ${s.placed - s.on} taken off.`;
    w.classList.toggle("bad", !!short);
  });
}
function clearSheet() {
  G.cells = []; G.info = null; G.layoutKey = null;
  $("#preview").hidden = true; $("#overlay").hidden = true; $("#drop").hidden = false; sheetFrame();
  $("#count").textContent = ""; $("#status").textContent = ""; $("#fileInfo").textContent = "";
  $("#download").disabled = true; $("#restoreAll").hidden = true; $("#removeHint").hidden = true;
}
$("#keep").addEventListener("change", (e) => {
  if (!e.target.checked) return;
  beforeEdit();
  G.logos.forEach((l) => (l.h = round(l.w / aspect(l.token))));
  renderCards(); renderSoon();
});

// ---------------------------------------------------------------- the sheet on screen
// before any logo: the empty sheet at its size, fitted into the stage (with logos, the preview is it)
function sheetFrame() {
  const sh = $("#sheet"), st = $("#stage"), w = num("#sheetW"), h = num("#sheetH");
  sh.hidden = !$("#preview").hidden || !(w > 0 && h > 0);
  if (sh.hidden) return;
  const cs = getComputedStyle(st), top = parseFloat(cs.paddingTop), side = parseFloat(cs.paddingLeft), bottom = parseFloat(cs.paddingBottom);
  const aw = st.clientWidth - 2 * side, ah = st.clientHeight - top - bottom, k = Math.min(aw / w, ah / h);
  Object.assign(sh.style, { width: `${w * k}px`, height: `${h * k}px`, left: `${side + (aw - w * k) / 2}px`, top: `${top + (ah - h * k) / 2}px` });
}
window.addEventListener("resize", sheetFrame);
// the sheet's colour on screen only (the files stay transparent)
$("#sheetColor").addEventListener("input", (e) => $("#stage").style.setProperty("--sheet", e.target.value));
$("#sheetWhite").addEventListener("click", () => { $("#sheetColor").value = "#ffffff"; $("#stage").style.setProperty("--sheet", "#ffffff"); });

// ---------------------------------------------------------------- preview
async function sheetRequest(format, dpi) {
  const send = () => fetch("/api/gang/sheet", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ options: options(), format, dpi }) });
  let r = await send();
  if (r.status === 404) { await reupload(); r = await send(); }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Failed (${r.status})`);
  return r;
}

async function render() {
  if (!G.logos.length) return;
  const id = ++G.req;
  const timer = setTimeout(() => busy(true, "Filling the sheet…"), 250);
  try {
    const j = await (await sheetRequest("preview")).json();
    if (id !== G.req) return;
    // a different layout (sheet, a logo's size, gap...) has other places: removed logos come back
    const key = JSON.stringify(j.info.cells);
    if (G.layoutKey && key !== G.layoutKey && G.removed.size) {
      G.removed.clear(); G.layoutKey = key;
      toast("The layout changed, so the removed logos are back.");
      return render();
    }
    G.layoutKey = key; G.cells = j.info.cells || []; G.info = j.info;
    const img = $("#preview");
    img.src = "data:image/png;base64," + j.png; img.hidden = false;
    $("#drop").hidden = true; sheetFrame();
    const off = j.info.total - j.info.count, kinds = G.logos.length;
    $("#count").textContent = j.info.total
      ? `${off ? `${j.info.count} of ${j.info.total}` : j.info.count} logos${kinds > 1 ? ` (${kinds} kinds)` : ""} · ${j.info.rows} row${j.info.rows > 1 ? "s" : ""}${off ? ` · ${off} removed` : ""}`
      : "No logo fits: make the logos smaller or the sheet larger.";
    $("#fileInfo").textContent = kinds > 1 ? `${kinds} logos` : G.files.get(G.logos[0].token).file.name || "";
    $("#restoreAll").hidden = !off;
    $("#removeHint").hidden = !j.info.total;
    $("#download").disabled = j.info.count === 0;
    drawOverlay();
    updateCards();
    G.last = snapshot(); G.dirty = false;          // the state an edit can go back to
    $("#undo").disabled = !G.history.length;
    $("#status").textContent = `${num("#sheetW")} × ${num("#sheetH")} ${unit()} sheet`;
    updateFormat();
  } catch (e) { if (id === G.req) toast(e.message, true, 6000); }
  finally { clearTimeout(timer); if (id === G.req) busy(false); }
}
let rt;
const renderSoon = () => { clearTimeout(rt); rt = setTimeout(render, 220); };

// ---------------------------------------------------------------- controls
$("#preset").addEventListener("change", (e) => {
  const m = e.target.value.match(/^([\d.]+)x([\d.]+)(in|mm|cm)$/);
  if (!m) return;
  // the preset's size in the unit chosen for the page
  const f = UNIT_IN[m[3]] / unitIn(unit());
  $("#sheetW").value = round(+m[1] * f); $("#sheetH").value = round(+m[2] * f);
  sheetFrame();
  renderSoon();
});
for (const id of ["#sheetW", "#sheetH"]) $(id).addEventListener("input", () => { $("#preset").value = "custom"; sheetFrame(); renderSoon(); });
for (const id of ["#gap", "#margin"]) $(id).addEventListener("input", renderSoon);
for (const id of ["#rotate", "#boxes", "#border"]) $(id).addEventListener("change", render);

// changing units converts every length, so the sheet stays the same
function setUnit(u) {
  const from = setUnit.cur || "in";
  if (u === from) return;
  const f = unitIn(from) / unitIn(u);
  for (const id of ["#sheetW", "#sheetH", "#gap", "#margin"]) $(id).value = round(num(id) * f);
  G.logos.forEach((l) => { l.w = round(l.w * f); l.h = round(l.h * f); });
  setUnit.cur = u; $("#unit").value = u;
  document.querySelectorAll(".unit-label").forEach((s) => (s.textContent = u));
  renderCards();
}
setUnit.cur = "in";
document.querySelectorAll(".unit-label").forEach((s) => (s.textContent = "in"));
$("#unit").addEventListener("change", (e) => { setUnit(e.target.value); sheetFrame(); updateFormat(); renderSoon(); });

// ---------------------------------------------------------------- download
function updateFormat() {
  const f = $("#format").value, dpi = +$("#dpi").value;
  const js = G.logos.map((l) => G.files.get(l.token).j);
  const vec = js.length && js.every((j) => j.vector), svg = js.length && js.every((j) => j.svg), many = js.length > 1;
  const raster = ["png", "jpg", "tiff"].includes(f);
  $("#dpiRow").hidden = !(raster || (f === "eps" && !svg) || unit() === "px");     // px sizes depend on it
  const inch = unitIn(unit());
  const px = `${Math.round(num("#sheetW") * inch * dpi)} × ${Math.round(num("#sheetH") * inch * dpi)} px`;
  $("#formatHint").textContent = {
    pdf: vec ? `Vector: ${many ? "each logo" : "the logo"} is placed as its own vector artwork.`
      : `Image logos are placed at their own resolution; vector logos, the boxes and the border stay vector.`,
    ai: "A PDF-based AI file: opens in Illustrator, " + (vec ? "vector like the PDF." : "with image logos placed."),
    eps: svg ? `Vector: ${many ? "each logo's" : "the logo's"} paths in every box.` : `The sheet as a ${px} image (${dpi} dpi). macOS cannot turn PDF or image logos into PostScript paths; for a vector EPS use SVG logos only.`,
    png: `${px} at ${dpi} dpi, transparent background.`,
    jpg: `${px} at ${dpi} dpi, white background.`,
    tiff: `${px} at ${dpi} dpi, transparent background, LZW compressed.`,
  }[f];
}
$("#format").addEventListener("change", () => updateFormat());
// a new dpi with sizes in px: the sheet and the logos keep their real size, so their pixels change
let lastDpi = dpiNow();
$("#dpi").addEventListener("change", () => {
  if (unit() === "px" && lastDpi !== dpiNow()) {
    const f = dpiNow() / lastDpi;
    for (const id of ["#sheetW", "#sheetH", "#gap", "#margin"]) $(id).value = round(num(id) * f);
    G.logos.forEach((l) => { l.w = round(l.w * f); l.h = round(l.h * f); });
    renderCards(); renderSoon();
  }
  lastDpi = dpiNow();
  updateFormat();
});

$("#download").addEventListener("click", async () => {
  if (!G.logos.length) return;
  const fmt = $("#format").value, dpi = +$("#dpi").value;
  const name = `${G.logos.length > 1 ? "logos" : nameOf(G.logos[0].token)}-gang-sheet.${fmt}`;
  const btn = $("#download"); btn.disabled = true; busy(true, `Making the ${fmt.toUpperCase()}…`);
  try {
    const api = window.pywebview?.api;
    if (api?.save_url) {        // the app saves it straight from the local server
      const body = () => ({ options: options(), format: fmt, dpi });
      let where = await api.save_url(name, "/api/gang/sheet", body());
      if (where && where.error === "expired") {     // the app let the logos go: read them again, then save
        await reupload();
        where = await api.save_url(name, "/api/gang/sheet", body());
      }
      if (where && where.error) throw new Error(where.error);
      if (where) toast(`Saved ${name} to ${where}.`);
    } else {
      const blob = await (await sheetRequest(fmt, dpi)).blob();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob); a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
      toast(`Saved ${name} (${(blob.size / 1024 / 1024).toFixed(1)} MB) to your Downloads folder.`);
    }
  } catch (e) { toast(e.message, true, 7000); }
  finally { btn.disabled = false; busy(false); }
});

// ---------------------------------------------------------------- removing logos, and filling empty places
function drawOverlay() {
  const img = $("#preview"), ov = $("#overlay");
  if (img.hidden || !G.cells.length || !img.naturalWidth) { ov.hidden = true; return; }
  const r = img.getBoundingClientRect(), st = $("#stage").getBoundingClientRect();
  Object.assign(ov.style, { left: `${r.left - st.left}px`, top: `${r.top - st.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  ov.innerHTML = "";
  G.cells.forEach(([x, y, w, h, g], i) => {
    const b = document.createElement("button");
    const off = G.removed.has(i);
    b.type = "button"; b.className = "gs-cell" + (off ? " off" : "");
    b.title = off ? "Put logos here" : `Remove this ${nameOf(G.logos[g]?.token)}`;
    Object.assign(b.style, { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });
    b.addEventListener("click", () => { if (off) openPop(i, b); else { beforeEdit(); G.removed.add(i); render(); } });
    ov.appendChild(b);
  });
  const rows = Math.max(...G.cells.map((c) => c[5])) + 1;
  for (let rr = 0; rr < rows; rr++) {
    const idx = G.cells.map((_, i) => i).filter((i) => G.cells[i][5] === rr);
    if (!idx.length) continue;
    const allOff = idx.every((i) => G.removed.has(i));
    const [x, y, , h] = G.cells[idx[0]];
    const b = document.createElement("button");
    b.type = "button"; b.className = "gs-row" + (allOff ? " restore" : "");
    b.textContent = allOff ? "+" : "−";
    b.title = allOff ? `Put logos in row ${rr + 1}` : `Remove row ${rr + 1}`;
    Object.assign(b.style, { left: `${x * 100}%`, top: `${(y + h / 2) * 100}%` });
    b.addEventListener("click", () => {
      if (allOff) return openPop(idx[0], b, true);
      beforeEdit(); idx.forEach((i) => G.removed.add(i)); render();
    });
    ov.appendChild(b);
  }
  ov.hidden = false;
}
$("#preview").addEventListener("load", drawOverlay);
$("#restoreAll").addEventListener("click", () => { beforeEdit(); G.removed.clear(); render(); });

// the empty places from place i on, row by row (then from the top again)
function emptyFrom(i) {
  const n = G.cells.length, out = [];
  for (let k = 0; k < n; k++) { const c = (i + k) % n; if (G.removed.has(c)) out.push(c); }
  return out;
}

// clicking an empty place (or the + of an empty row): which logo, its size and how many
function openPop(i, anchor, wholeRow = false) {
  const row = G.cells[i][5];
  const inRow = emptyFrom(i).filter((c) => G.cells[c][5] === row && c >= i);
  const [, , cw, ch] = G.cells[i];
  const place = [cw * num("#sheetW"), ch * num("#sheetH")];      // the place's size, in the sheet's unit
  // the logo offered first: the last one added after the first, else the one that fills the sheet
  const choice = G.logos.length - 1;
  G.pop = { i, place, choice, token: G.logos[choice].token, wholeRow };
  $("#popTitle").textContent = wholeRow ? `Put logos in row ${row + 1}` : "Put logos here";
  $("#popQty").value = Math.max(1, inRow.length);
  popLogos(); popPick(choice);
  const pop = $("#pop"), st = $("#stage").getBoundingClientRect(), a = anchor.getBoundingClientRect();
  pop.hidden = false;
  const pw = pop.offsetWidth, ph = pop.offsetHeight;
  let left = a.left - st.left + a.width / 2 - pw / 2, top = a.bottom - st.top + 6;
  if (top + ph > st.height - 8) top = a.top - st.top - ph - 6;
  left = Math.max(8, Math.min(left, st.width - pw - 8)); top = Math.max(8, Math.min(top, st.height - ph - 8));
  Object.assign(pop.style, { left: `${left}px`, top: `${top}px` });
  $("#popQty").focus(); $("#popQty").select();
}
function popLogos() {
  const box = $("#popLogos");
  box.innerHTML = "";
  G.logos.forEach((l, k) => {
    const b = document.createElement("button");
    b.type = "button"; b.setAttribute("role", "radio"); b.dataset.k = k;
    b.title = `${nameOf(l.token)}, ${l.w} × ${l.h} ${unit()}`;
    b.innerHTML = `<img alt="" src="data:image/png;base64,${G.files.get(l.token).j.preview}"><span></span>`;
    b.querySelector("span").textContent = `${l.w} × ${l.h}`;
    b.addEventListener("click", () => popPick(k));
    box.appendChild(b);
  });
  const nb = document.createElement("button");
  nb.type = "button"; nb.className = "new"; nb.setAttribute("role", "radio");
  nb.innerHTML = "<b>+</b><span>New logo…</span>";
  nb.addEventListener("click", () => $("#popFile").click());
  box.appendChild(nb);
}
function popPick(k) {
  const l = G.logos[k];
  G.pop.choice = k; G.pop.token = l.token;
  [...$("#popLogos").children].forEach((b) => b.setAttribute("aria-checked", String(+b.dataset.k === k)));
  $("#popW").value = l.w; $("#popH").value = l.h;
  popNote();
}
// the logo the popover would add: one already on the sheet at this size, if it is there
const popSame = () => G.logos.find((l) => l.token === G.pop.token && Math.abs(l.w - num("#popW")) < 1e-6 && Math.abs(l.h - num("#popH")) < 1e-6);
function popNote() {
  const p = G.pop, same = popSame(), empty = emptyFrom(p.i).length;
  $("#popNote").textContent = same && same.qty === null
    ? `Puts ${nameOf(p.token)} back in ${Math.min(Math.max(1, num("#popQty")), empty)} of the ${empty} empty places.`
    : `Adds ${nameOf(p.token)} at ${num("#popW")} × ${num("#popH")} ${unit()}; the sheet is arranged again to fit it.`;
}
$("#popFile").addEventListener("change", async (e) => {
  const file = e.target.files[0]; e.target.value = "";
  if (!file || !G.pop) return;
  try {
    busy(true, "Reading the logo…");
    const token = await upload(file);
    // sized to fit the place that was clicked, upright or turned, whichever is larger
    const a = aspect(token), [pw, ph] = G.pop.place;
    const fit = (w, h) => (w / h > a ? [h * a, h] : [w, w / a]);
    const [f1, f2] = [fit(pw, ph), fit(ph, pw)];
    const [w, h] = f1[0] * f1[1] >= f2[0] * f2[1] ? f1 : f2;
    G.pop.token = token; G.pop.choice = -1;
    [...$("#popLogos").children].forEach((b) => b.setAttribute("aria-checked", "false"));
    const nb = $("#popLogos .new");
    nb.innerHTML = `<img alt="" src="data:image/png;base64,${G.files.get(token).j.preview}"><span></span>`;
    nb.querySelector("span").textContent = G.files.get(token).name;
    nb.setAttribute("aria-checked", "true");
    $("#popW").value = round(w); $("#popH").value = round(h);
    popNote();
  } catch (err) { toast(err.message, true, 7000); }
  finally { busy(false); }
});
$("#popW").addEventListener("input", () => { if ($("#keep").checked) $("#popH").value = round(num("#popW") / aspect(G.pop.token)); popNote(); });
$("#popH").addEventListener("input", () => { if ($("#keep").checked) $("#popW").value = round(num("#popH") * aspect(G.pop.token)); popNote(); });
$("#popQty").addEventListener("input", popNote);
function closePop() { $("#pop").hidden = true; G.pop = null; }
$("#popCancel").addEventListener("click", closePop);
$("#popAdd").addEventListener("click", () => {
  const p = G.pop;
  if (!p) return;
  const qty = Math.max(1, parseInt($("#popQty").value, 10) || 1), w = num("#popW"), h = num("#popH");
  if (!(w > 0 && h > 0)) return toast("Give the logo a width and height.", true);
  beforeEdit();
  const same = popSame();
  if (same && same.qty === null) {             // the logo that fills the sheet: back into the empty places
    emptyFrom(p.i).slice(0, qty).forEach((c) => G.removed.delete(c));
  } else {
    if (same) same.qty += qty;
    else G.logos.push({ token: p.token, w: round(w), h: round(h), qty });
    G.removed.clear();                         // a new arrangement
    toast(`${qty} × ${nameOf(p.token)} added; the sheet was arranged again.`, false, 3000);
  }
  closePop();
  renderCards(); updateFormat(); render();
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && G.pop) closePop(); });
document.addEventListener("pointerdown", (e) => {
  if (G.pop && !$("#pop").contains(e.target) && !e.target.closest(".gs-cell.off, .gs-row.restore")) closePop();
});
$("#pop").addEventListener("keydown", (e) => { if (e.key === "Enter" && e.target.matches("input")) $("#popAdd").click(); });

// ---------------------------------------------------------------- undo (Cmd+Z / Ctrl+Z)
// every edit (a logo or row taken off or put back, a logo added, a size, quantity or sheet setting)
// can be undone, up to UNDO_STEPS times; typing in one box counts as one edit
const FIELDS = ["#preset", "#sheetW", "#sheetH", "#unit", "#keep", "#gap", "#margin", "#rotate", "#boxes", "#border"];
function snapshot() {
  const f = {};
  for (const id of FIELDS) f[id] = $(id).type === "checkbox" ? $(id).checked : $(id).value;
  return { fields: f, removed: [...G.removed], logos: G.logos.map((l) => ({ ...l })) };
}
function beforeEdit() {
  if (!G.logos.length || G.dirty || !G.last) return;
  G.history.push(G.last);
  if (G.history.length > UNDO_STEPS) G.history.shift();
  G.dirty = true;
  $("#undo").disabled = false;
}
function undo() {
  if (!G.history.length) return;
  const s = G.history.pop();
  for (const id of FIELDS) { if ($(id).type === "checkbox") $(id).checked = s.fields[id]; else $(id).value = s.fields[id]; }
  setUnit.cur = s.fields["#unit"];
  document.querySelectorAll(".unit-label").forEach((x) => (x.textContent = setUnit.cur));
  G.removed = new Set(s.removed);
  G.logos = s.logos.map((l) => ({ ...l }));
  G.layoutKey = null;                    // the places of that layout come back with it
  G.dirty = true;
  closePop();
  renderCards(); updateFormat();
  render();
  toast(G.history.length ? `Undone (${G.history.length} more step${G.history.length > 1 ? "s" : ""} can be undone)` : "Undone", false, 1600);
}
for (const id of FIELDS) {
  $(id).addEventListener("input", beforeEdit, true);
  $(id).addEventListener("change", beforeEdit, true);
}
$("#undo").addEventListener("click", undo);
document.addEventListener("keydown", (e) => {
  if (!(e.metaKey || e.ctrlKey) || e.shiftKey || e.key.toLowerCase() !== "z") return;
  if (e.target.matches?.("input[type=number], input[type=text], textarea")) return;   // a box being typed in undoes its own text
  e.preventDefault();
  undo();
});

window.addEventListener("resize", () => { if (G.logos.length) renderSoon(); });
updateFormat();
sheetFrame();                                   // the empty sheet when the page opens
