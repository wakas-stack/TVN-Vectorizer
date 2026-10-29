// Cap DST page: a logo digitized for the front of a cap, as a Tajima .DST file; or a .DST file
// opened to look at, edit and save again.
//   A logo is shown as it is; Digitize makes the stitches. After that every change (a setting, a
//   thread, an edit on the canvas) waits: the button turns to Update Digitizing, and the logo is
//   digitized again when it is clicked (or before a file is saved).
//   A .DST file has no logo behind it: its colour blocks are edited as stitches (cap-edit.js).
"use strict";

const $ = (s) => document.querySelector(s);
const MM = 25.4;
// plan: the logo's colours in sewing order, [{id, hex (logo colour), kind, pick (index into its threads; -1: not stitched),
//        custom (a thread picked from the palette), puff (raised, when the embroidery is 3D puff)}]
const C = { mode: null, token: null, file: null, name: "cap", plan: [], threads: {}, chartTitle: "", st: null, colors: [],
            info: null, req: 0, playing: false, img: null, logoBox: null, aspect: 0, digitized: false, dirty: false,
            applied: {}, pieceThreads: {}, changed: false };
window.embHasWork = () => !!(C.file || C.token); // leave.js: a logo or a DST is open

function toast(msg, isError = false, ms = 3800) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function busy(on, text) { $("#busy").hidden = !on; if (text) $("#busyText").textContent = text; }
const num = (id) => parseFloat($(id).value) || 0;
const post = (url, body) => fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
const isDst = () => C.mode === "dst";

// ---------------------------------------------------------------- opening a logo or a DST
async function analyze() {
  const fd = new FormData(); fd.append("image", C.file, C.file.name || "logo.png");
  const r = await fetch("/api/cap/analyze", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
  C.token = j.token;
  return j;
}
function resetWork() {
  C.edits = {}; C.lock = null; C.sels = []; C.undo = []; C.redo = []; C.applied = {}; C.shapes = []; C.shapeThreads = {}; C.arrange = null;
  C.zoom = 1; C.cam = null;                    // a new file: the whole design in view
  C.st = null; C.colors = []; C.info = null; C.digitized = false; C.dirty = false; C.changed = false; C.pieceThreads = {};
  $("#design").hidden = true; $("#play").hidden = true; $("#stats").innerHTML = ""; $("#notes").innerHTML = "";
}
async function openFile(file) {
  if (!file) return;
  if (/\.dst$/i.test(file.name || "")) return openDst(file);
  if (C.mode === "dst") {        // after a DST (its own size in the fields): back to the front panel area
    $("#preset").value = "4.5x2.25"; $("#w").value = "4.5"; $("#h").value = "2.25";
  }
  resetWork();
  C.mode = "logo"; document.body.classList.remove("dst-mode");
  C.file = file; C.name = (file.name || "cap").replace(/\.[^.]+$/, "");
  busy(true, "Reading the logo…");
  try {
    const j = await analyze();
    // the background colour starts as "don't stitch": the cap shows through
    C.plan = j.colors.map((c) => ({ id: c.id, hex: c.hex, kind: c.kind, pick: c.kind === "background" ? -1 : 0,
                                    custom: null, puff: c.kind !== "background" }));
    C.aspect = j.aspect || 0;
    C.logoBox = j.logo_box || null;
    $("#fileInfo").textContent = file.name || "Pasted logo";
    await loadThreads();
    C.img = await loadImage(j.image || URL.createObjectURL(file));
    fitSize();
    $("#drop").hidden = true; $("#canvas").hidden = false;
    setButtons();
    draw();
    $("#status").textContent = "The logo as it is: click Digitize to make the stitches.";
  } catch (e) { toast(e.message, true, 7000); }
  finally { busy(false); }
}
function loadImage(src) {
  return new Promise((ok, fail) => {
    const im = new Image();
    im.onload = () => ok(im); im.onerror = () => fail(new Error("Could not show this logo."));
    im.src = src;
  });
}
async function openDst(file) {
  resetWork();
  busy(true, "Reading the DST…");
  try {
    const fd = new FormData(); fd.append("file", file, file.name);
    const r = await fetch("/api/cap/dst-open", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
    C.mode = "dst"; document.body.classList.add("dst-mode");
    C.file = file; C.name = file.name.replace(/\.[^.]+$/, ""); C.token = null; C.plan = []; C.img = null;
    C.st = j.stitches; C.colors = j.colors.map((c, i) => ({ ...c, name: `Colour ${i + 1}` })); C.info = j.info;
    C.digitized = true;
    $("#fileInfo").textContent = file.name;
    $("#w").value = inches(C.info.width_mm / MM); $("#h").value = inches(C.info.height_mm / MM); $("#preset").value = "custom";
    $("#drop").hidden = true; $("#canvas").hidden = false; $("#play").hidden = false;
    $("#step").max = C.st.length; $("#step").value = C.st.length;
    renderColors(); setButtons(); showStats(); draw();
  } catch (e) { toast(e.message, true, 7000); }
  finally { busy(false); }
}

// a new file replaces the work on the page: ask first (save it, or let it go)
function hasWork() { return isDst() ? C.changed : !!(C.token && (C.digitized || Object.keys(C.edits || {}).length)); }
function requestOpen(then) {
  if (!hasWork()) return then();
  const m = $("#discard");
  m.hidden = false;
  const done = () => { m.hidden = true; for (const b of m.querySelectorAll("button")) b.onclick = null; };
  $("#discardSave").onclick = async () => {
    done();
    if (await saveAll()) { C.changed = false; C.digitized = false; C.edits = {}; toast("Saved. Now choose the next logo.", false, 5000); then(); }
  };
  $("#discardDrop").onclick = () => { done(); resetWork(); then(); };
  $("#discardCancel").onclick = done;
}
$("#fileInput").addEventListener("change", (e) => { openFile(e.target.files[0]); e.target.value = ""; });
$("#newLogo").addEventListener("click", () => requestOpen(() => $("#fileInput").click()));
$("#drop").addEventListener("click", (e) => { if (hasWork()) { e.preventDefault(); requestOpen(() => $("#fileInput").click()); } });
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) requestOpen(() => openFile(f)); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) { const f = item.getAsFile(); requestOpen(() => openFile(f)); }
});

// ---------------------------------------------------------------- threads
async function loadThreads() {
  const r = await post("/api/cap/threads", { chart: $("#chart").value, colors: C.plan.map((c) => c.hex) });
  const j = await r.json();
  if (!r.ok || j.error) throw new Error(j.error || "Could not load the thread chart.");
  C.chartTitle = j.title;
  C.plan.forEach((c, i) => { C.threads[c.id] = j.matches[i]; if (c.pick >= 0) c.pick = 0; c.custom = null; });
  renderColors();
}
const thread = (c) => (c.pick < 0 ? null : c.custom || C.threads[c.id]?.[c.pick]);
const label = (c) => { const t = thread(c); return t ? `${C.chartTitle} · ${t.num} ${t.name}` : ""; };
// the thread of each colour as the files list it: the logo's colours, and pieces given a thread of their own
function threadMap() {
  const out = Object.fromEntries(C.plan.filter((c) => thread(c)).map((c) => {
    const t = thread(c); return [c.id, { code: t.num, name: t.name, brand: C.chartTitle }];
  }));
  for (const [hex, t] of Object.entries(C.pieceThreads)) out["piece" + hex.toLowerCase()] = { code: t.num, name: t.name, brand: C.chartTitle };
  for (const [hex, t] of Object.entries(C.shapeThreads || {})) out["shape" + hex.toLowerCase()] = { code: t.num, name: t.name, brand: C.chartTitle };
  return out;
}
const PALETTE_ICON = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3a9 9 0 1 0 0 18c1.1 0 1.6-.8 1.6-1.6 0-1.2-1-1.4-1-2.5 0-.9.7-1.6 1.6-1.6H17a4 4 0 0 0 4-4C21 6.6 17 3 12 3z"/><circle cx="7.5" cy="11" r="1.2" fill="currentColor"/><circle cx="10.5" cy="7.5" r="1.2" fill="currentColor"/><circle cx="15" cy="7.5" r="1.2" fill="currentColor"/></svg>';

function renderColors() {
  const ol = $("#colors"), puff = isPuff();
  ol.innerHTML = "";
  ol.classList.toggle("puff", puff && !isDst());
  if (isDst()) {          // a DST: its colour blocks, each with the thread picked for it
    C.colors.forEach((c, i) => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="n">${i + 1}</span><span class="sw"></span><span class="nm"></span>
        <button type="button" class="pal" title="Pick a thread from the ${C.chartTitle || "chart"} palette">${PALETTE_ICON}</button>`;
      li.querySelector(".sw").style.background = c.hex;
      li.querySelector(".nm").textContent = c.thread ? `${c.thread.num} ${c.thread.name}` : c.name;
      li.querySelector(".pal").addEventListener("click", (e) => openPalette(e.currentTarget, (t) => {
        c.hex = t.hex; c.thread = t; C.changed = true; renderColors(); draw();
      }));
      ol.appendChild(li);
    });
    return;
  }
  let n = 0;
  C.plan.forEach((c, i) => {
    const t = thread(c), li = document.createElement("li");
    li.className = t ? "" : "off";
    li.innerHTML = `<span class="n">${t ? ++n : ""}</span><span class="sw"></span><select aria-label="Thread"></select>
      <button type="button" class="pal" title="Pick any thread from the palette">${PALETTE_ICON}</button>
      ${puff ? `<label class="pf" title="Sew this colour as 3D puff"><input type="checkbox"${c.puff ? " checked" : ""}${t ? "" : " disabled"}> Puff</label>` : ""}
      <span class="mv"><button type="button" class="up" title="Sew earlier">▲</button><button type="button" class="dn" title="Sew later">▼</button></span>`;
    li.querySelector(".pf input")?.addEventListener("change", (e) => { c.puff = e.target.checked; markDirty(); });
    const sw = li.querySelector(".sw");
    sw.style.background = t ? t.hex : c.hex;
    sw.classList.toggle("off", !t);
    sw.title = `Logo colour ${c.hex}${c.kind === "background" ? " (the logo's background: sewn only inside the logo)" : ""}`;
    const sel = li.querySelector("select");
    if (c.custom) {
      const o = document.createElement("option");
      o.value = "custom"; o.textContent = `${c.custom.num} ${c.custom.name}  (palette)`;
      sel.appendChild(o);
    }
    (C.threads[c.id] || []).forEach((m, k) => {
      const o = document.createElement("option");
      o.value = k; o.textContent = `${m.num} ${m.name}  (ΔE ${m.de.toFixed(1)})`;
      sel.appendChild(o);
    });
    const off = document.createElement("option");
    off.value = -1; off.textContent = c.kind === "background" ? `Don't stitch (logo background ${c.hex})` : "Don't stitch (cap shows)";
    sel.appendChild(off);
    sel.value = c.custom && c.pick >= 0 ? "custom" : c.pick;
    sel.addEventListener("change", () => {
      if (sel.value !== "custom") { c.pick = +sel.value; c.custom = null; }
      renderColors(); recolour(); markDirty();
    });
    li.querySelector(".pal").addEventListener("click", (e) => openPalette(e.currentTarget, (pick) => {
      c.custom = pick; if (c.pick < 0) c.pick = 0;
      renderColors(); recolour(); markDirty();
    }));
    li.querySelector(".up").disabled = i === 0;
    li.querySelector(".dn").disabled = i === C.plan.length - 1;
    li.querySelector(".up").addEventListener("click", () => moveColour(i, -1));
    li.querySelector(".dn").addEventListener("click", () => moveColour(i, 1));
    ol.appendChild(li);
  });
}
// a thread changed: the stitches on screen take it at once (the files take it when digitized again)
function recolour() {
  if (!C.colors?.length) return;
  for (const col of C.colors) { const c = C.plan.find((p) => p.id === col.id.split("~")[0]); if (c && thread(c)) col.hex = thread(c).hex; }   // (a colour sewn in blocks: "<id>~n")
  draw();
}
function moveColour(i, d) {
  const [c] = C.plan.splice(i, 1);
  C.plan.splice(i + d, 0, c);
  renderColors(); markDirty();
}
$("#chart").addEventListener("change", async () => {
  PAL.data = null;
  if (isDst()) { C.chartTitle = $("#chart").selectedOptions[0].textContent; renderColors(); return; }
  if (!C.token) return;
  try { await loadThreads(); recolour(); markDirty(); } catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- the palette: every thread of the chart
const PAL = { data: null, pick: null };
async function chartColours() {
  if (!PAL.data) {
    const all = await (await fetch("/static/thread-data.json")).json();
    const book = all.books.find((b) => b.id === $("#chart").value) || all.books[0];
    PAL.data = { title: book.title, colors: book.colors.map(([n, name, hex]) => ({ num: n, name, hex: hex.toLowerCase() })) };
  }
  return PAL.data;
}
async function openPalette(anchor, onPick) {
  const box = $("#palette"), data = await chartColours();
  PAL.pick = onPick;
  $("#palTitle").textContent = `${data.title}: ${data.colors.length} threads`;
  $("#palSearch").value = "";
  fillPalette("");
  const r = anchor.getBoundingClientRect();
  box.hidden = false;
  const w = box.offsetWidth, h = box.offsetHeight;
  box.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.right - w))}px`;
  box.style.top = `${Math.max(8, Math.min(window.innerHeight - h - 8, r.bottom + 6))}px`;
  $("#palSearch").focus();
}
function fillPalette(q) {
  const grid = $("#palGrid"); grid.innerHTML = "";
  if (!PAL.data) return;
  q = q.trim().toLowerCase();
  for (const t of PAL.data.colors) {
    if (q && !t.num.toLowerCase().includes(q) && !t.name.toLowerCase().includes(q)) continue;
    const b = document.createElement("button");
    b.type = "button"; b.style.background = t.hex; b.title = `${t.num} ${t.name}`;
    b.addEventListener("click", () => { $("#palette").hidden = true; PAL.pick?.(t); });
    grid.appendChild(b);
  }
}
$("#palSearch").addEventListener("input", (e) => fillPalette(e.target.value));
$("#palClose").addEventListener("click", () => ($("#palette").hidden = true));
document.addEventListener("pointerdown", (e) => {
  const box = $("#palette");
  if (!box.hidden && !box.contains(e.target) && !e.target.closest(".pal, #toolColour")) box.hidden = true;
});

// ---------------------------------------------------------------- digitizing (on the button)
const isPuff = () => $('input[name="kind"]:checked').value === "puff";
function options() {
  return {
    width_mm: num("#w") * MM, height_mm: num("#h") * MM,
    density: +$("#density").value, pull_comp: +$("#pull").value, name: C.name, origin: $("#origin").value, order: $("#order").value,
    crown_mm: num("#crown") * MM || null, tilt: +$("#tilt").value,
    tackdown: $("#tackdown").checked, light: $("#light").checked,
    kind: isPuff() ? "puff" : "flat", puff: C.plan.filter((c) => c.puff).map((c) => c.id),
    colors: C.plan.map((c) => ({ id: c.id, hex: thread(c)?.hex || c.hex, skip: c.pick < 0 })),
    edits: C.edits, mm_per_px: C.lock,          // the pieces as edited on the page (cap-edit.js)
    shapes: (C.shapes || []).map(shapeToSend),    // drawn on it
    arrange: C.arrange?.length ? C.arrange.map(sewnKey) : null,     // the sewing order arranged (cap-edit.js)
  };
}
// a shape drawn on the page as the digitizer takes it (image pixels); a Pathfinder shape with its rings
const shapeToSend = ({ id, hex, px, closed, width, pxRings }) => ({ id, hex, pts: px, closed, width, ...(pxRings ? { rings: pxRings } : {}) });
async function request(url, extra = {}) {
  const send = () => post(url, { token: C.token, options: options(), ...extra });
  let r = await send();
  if (r.status === 404 && C.file) { await analyze(); r = await send(); }   // the app restarted: read the logo again
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Failed (${r.status})`);
  return r;
}

async function digitize() {
  if (!C.token || isDst()) return;
  const id = ++C.req;
  busy(true, C.digitized ? "Updating the digitizing…" : "Digitizing…");
  try {
    const j = await (await request("/api/cap/stitches")).json();
    if (id !== C.req) return;
    C.st = j.stitches; C.colors = j.colors; C.info = j.info;
    C.digitized = true; C.dirty = false; C.applied = JSON.parse(JSON.stringify(C.edits || {}));
    for (const sh of C.shapes || []) sh.sewn = true;      // shapes drawn are stitches now
    C.sels = (C.sels || []).map((k) => {        // a drawn shape still selected: as the piece it is now
      const sh = String(k).startsWith("draft:") && C.shapes.find((x) => "draft:" + x.id === k);
      return sh ? `shape${sh.hex}:s${sh.id}` : k;
    }).filter((k) => !String(k).startsWith("draft:"));
    if (C.lock) {           // while editing the scale stays: the fields show the logo's size as it is now
      $("#w").value = inches(C.info.size_mm[0] / MM); $("#h").value = inches(C.info.size_mm[1] / MM);
    } else fitSize();
    $("#play").hidden = false;
    $("#step").max = C.st.length; $("#step").value = C.st.length;
    stop();
    showStats();            // first: the details row under the preview takes its room before the preview is sized
    draw();
  } catch (e) {
    if (id === C.req) toast(e.message, true, 6000);
  } finally { if (id === C.req) { busy(false); setButtons(); } }
}
// a change after digitizing waits for Update Digitizing; before it, it only shows on the logo
function markDirty() {
  if (isDst()) return;
  if (C.digitized) {
    C.dirty = true;
    $("#status").textContent = "Changes not digitized yet: click Update Digitizing.";
  }
  setButtons();
  draw();
}
function setButtons() {
  const b = $("#digitizeBtn");
  b.hidden = isDst();
  b.disabled = !C.token || (C.digitized && !C.dirty);
  b.textContent = C.digitized ? "Update Digitizing" : "Digitize";
  b.classList.toggle("pulse", C.dirty);
  const can = isDst() ? !!C.st : C.digitized;
  $("#saveDst").disabled = $("#savePng").disabled = $("#savePdf").disabled = !can;
  if (typeof updateTools === "function") updateTools();
}
$("#digitizeBtn").addEventListener("click", digitize);

function showStats() {
  const i = C.info, inch = (v) => (v / MM).toFixed(2);
  const rows = [
    ["Size", `${inch(i.width_mm)} × ${inch(i.height_mm)} in (${i.width_mm} × ${i.height_mm} mm)`],
    ["Stitches", i.stitches.toLocaleString()],
    ["Colours", `${i.colors - i.stops} (${Math.max(0, i.colors - 1)} colour change${i.colors === 2 ? "" : "s"})`],
    ...(i.stops ? [["Foam stops", `${i.stops} (same thread; lay the foam)`]] : []),
    ["Trims", i.trims],
    ["Sewing time", `about ${Math.max(1, Math.round(i.minutes))} min at 650 stitches/min`],
    ...(isDst() ? [] : [["Parts", `${i.fill_parts} fill, ${i.satin_parts} satin`]]),
  ];
  $("#stats").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  $("#notes").innerHTML = "";
  for (const n of i.notes) { const li = document.createElement("li"); li.textContent = n; $("#notes").appendChild(li); }
  $("#status").textContent = `${i.stitches.toLocaleString()} stitches · ${inch(i.width_mm)} × ${inch(i.height_mm)} in`;
  // under the logo, in a row: the design's details as Wilcom's Design Information lists them
  $("#design").innerHTML = (i.details || []).map(([k, v]) => `<div><dt>${k}:</dt><dd>${v}</dd></div>`).join("");
  $("#design").hidden = !(i.details || []).length;
}

// ---------------------------------------------------------------- preview: the logo, or the stitches as thread
function rgb(hex) { const n = parseInt(hex.slice(1), 16); return [(n >> 16) & 255, (n >> 8) & 255, n & 255]; }
const css = (c) => `rgb(${c[0] | 0},${c[1] | 0},${c[2] | 0})`;
const LIGHT = Math.PI / 3;      // the light: thread lying across it shines, along it is darker
// a stitch as a thread, as Wilcom's realistic view (same as the PNG preview), lit by the way it
// lies, each a shade lighter or darker (real thread is never even): [base, body, sheen]
function threadShades([r, gg, b], angle, vary = 1) {
  const lift = Math.max(0, 58 - (0.299 * r + 0.587 * gg + 0.114 * b));
  const f = (0.82 + 0.18 * Math.abs(Math.cos(angle - LIGHT))) * vary;
  const map = (fn) => [r, gg, b].map((v) => Math.min(255, fn(v)));
  return [map((v) => (v * 0.84 + lift * 0.8) * f), map((v) => (v * 0.96 + lift) * f), map((v) => (v + (255 - v) * 0.2 + lift * 1.4) * f)];
}
// two stitches of a satin (or a fill turning at its edge): each over 0.5 mm, the second going back
// across, at most 1.2 mm from the first (k: px per mm)
function satinPair(p, q, k) {
  const ux = p[2] - p[0], uy = p[3] - p[1], vx = q[2] - q[0], vy = q[3] - q[1];
  const lu = Math.hypot(ux, uy), lv = Math.hypot(vx, vy);
  if (lu < 0.5 * k || lv < 0.5 * k || ux * vx + uy * vy >= 0) return false;
  return Math.abs(ux * (q[3] - p[1]) - uy * (q[2] - p[0])) / lu <= 1.2 * k;
}
// stitches with others of the same colour sewn close beside them and lying the same way (a fill's
// rows, a satin): their spreading thread covers the space between, so they are drawn wide; a run
// (an outline, a pen line, the underlay under a satin) stays a thin thread, as in Wilcom. For each
// stitch (by index in C.st): the first stitch sewn beside it on its left, and on its right ([left,
// right]), so while the preview plays an underlay stays thin until what covers it is sewn, and a
// stitch is drawn wide only with thread on both sides (inside a fill or a satin, not at its edge or
// beside one other run). Worked out again when the stitches change.
function denseStitches() {
  const st = C.st;
  let sig = st.length;
  for (const p of st) sig = (sig * 31 + p[0] * 7 + p[1] * 13 + p[2]) % 1000000007;
  if (denseStitches.c?.st === st && denseStitches.c.sig === sig) return denseStitches.c.flags;
  const cell = 5, near = 7;                    // 0.5 mm cells; beside: 0.15-0.7 mm to the side (units: 0.1 mm)
  const key = (gx, gy) => (gx + 32768) * 65536 + (gy + 32768);
  const grid = new Map(), segs = [];
  let prev = null, block = 0;
  st.forEach(([x, y, c], i) => {
    if (c === 3) { block++; prev = [x, y]; return; }
    if (c === 0 && prev) {
      const len = Math.hypot(x - prev[0], y - prev[1]) || 1, ux = (x - prev[0]) / len, uy = (y - prev[1]) / len;
      segs.push([i, prev[0], prev[1], x, y, block, ux, uy]);
      const n = Math.max(1, Math.ceil(len / cell));
      for (let t = 0; t <= n; t++) {
        const px = prev[0] + (x - prev[0]) * t / n, py = prev[1] + (y - prev[1]) * t / n;
        const k = key(Math.floor(px / cell), Math.floor(py / cell));
        if (!grid.has(k)) grid.set(k, []);
        grid.get(k).push([px, py, i, block, ux, uy]);
      }
    }
    prev = c === 2 ? prev : [x, y];
  });
  const left = new Int32Array(st.length).fill(st.length + 1), right = new Int32Array(st.length).fill(st.length + 1);
  for (const [i, ax, ay, bx, by, blk, ux, uy] of segs) {
    if (Math.hypot(bx - ax, by - ay) <= 3) continue;           // under 0.3 mm: a tie-in, not a stitch to judge
    const mx = (ax + bx) / 2, my = (ay + by) / 2, gx = Math.floor(mx / cell), gy = Math.floor(my / cell);
    for (let dx = -2; dx <= 2; dx++) for (let dy = -2; dy <= 2; dy++) {
      for (const [px, py, j, b, vx, vy] of grid.get(key(gx + dx, gy + dy)) || []) {
        if (b !== blk || j === i || Math.abs(ux * vx + uy * vy) <= 0.8 || Math.hypot(px - mx, py - my) >= near) continue;
        const side = ux * (py - my) - uy * (px - mx);                   // how far to the side of this stitch's line
        // the stitches before and after it in a run, or a run sewn back over itself, lie on its line: not beside
        if (side > 1.5) { if (j < left[i]) left[i] = j; }
        else if (side < -1.5 && j < right[i]) right[i] = j;
      }
    }
  }
  denseStitches.c = { st, sig, flags: [left, right] };
  return denseStitches.c.flags;
}
const vary = (i) => 0.94 + 0.12 * ((Math.sin(i * 12.9898) * 43758.5453) % 1 + 1) % 1;   // the same streaks every time
function stageRoom() {          // the room the preview has in the stage (css px): less the stage's padding and
  const st = $("#stage"), cs = getComputedStyle(st), r = st.getBoundingClientRect();   // the rows under the preview
  const below = [$("#design"), $("#play")].reduce((h, el) => el.hidden ? h
    : h + el.offsetHeight + parseFloat(getComputedStyle(el).marginTop) + parseFloat(getComputedStyle(el).marginBottom), 0);
  return [r.width - 120, r.height - parseFloat(cs.paddingTop) - parseFloat(cs.paddingBottom) - below - 4];
}
function fitCanvas(wUnits, hUnits, k) {  // the canvas sized wUnits x hUnits at k css px per unit (fitted to the stage when k is not given)
  const cv = $("#canvas"), [availW, availH] = stageRoom();
  k = k || Math.max(0.05, Math.min(availW / wUnits, availH / hUnits));
  const dpr = window.devicePixelRatio || 1;
  cv.style.width = `${Math.round(wUnits * k)}px`; cv.style.height = `${Math.round(hUnits * k)}px`;
  cv.width = Math.round(wUnits * k * dpr); cv.height = Math.round(hUnits * k * dpr);
  return [k, dpr];
}
function drawLogo() {           // before digitizing: the logo as it is
  const im = C.img, b = C.logoBox || [0, 0, im.naturalWidth, im.naturalHeight];
  const pad = 0.04 * Math.max(b[2] - b[0], b[3] - b[1]);
  const sx = Math.max(0, b[0] - pad), sy = Math.max(0, b[1] - pad);
  const sw = Math.min(im.naturalWidth, b[2] + pad) - sx, sh = Math.min(im.naturalHeight, b[3] + pad) - sy;
  const [k, dpr] = fitCanvas(sw, sh);
  const g = $("#canvas").getContext("2d");
  g.clearRect(0, 0, $("#canvas").width, $("#canvas").height);
  g.drawImage(im, sx, sy, sw, sh, 0, 0, sw * k * dpr, sh * k * dpr);
  C.view = null;
}
function draw() {
  if (!isDst() && !C.digitized) { if (C.img) drawLogo(); return; }
  if (!C.st) return;
  const cv = $("#canvas");
  const pts = C.st.filter((p) => p[2] <= 1);
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const pad = 40;                                                  // 4 mm around the design
  x0 -= pad; y0 -= pad; x1 += pad; y1 += pad;
  // zoomed in (C.zoom > 1, cap-edit.js): the preview fills the stage, centred on C.cam (0.1 mm)
  const [availW, availH] = stageRoom(), fit = Math.max(0.05, Math.min(availW / (x1 - x0), availH / (y1 - y0)));
  let k, dpr;
  if ((C.zoom || 1) > 1.001 || C.cam) {         // zoomed in, or moved with the hand: the view fills the stage
    k = fit * (C.zoom || 1);
    const cam = C.cam || [(x0 + x1) / 2, (y0 + y1) / 2];
    C.cam = cam;
    const wU = availW / k, hU = availH / k;
    x0 = cam[0] - wU / 2; x1 = cam[0] + wU / 2; y0 = cam[1] - hU / 2; y1 = cam[1] + hU / 2;
    [k, dpr] = fitCanvas(x1 - x0, y1 - y0, k);
  } else [k, dpr] = fitCanvas(x1 - x0, y1 - y0);                   // css px per 0.1 mm
  C.fit = fit;
  // the stitches are drawn apart, then onto the page with a soft shadow (the design stands off the fabric)
  const art = draw.art || (draw.art = document.createElement("canvas"));
  art.width = cv.width; art.height = cv.height;
  const g = art.getContext("2d");
  const s = k * dpr;
  g.lineCap = "butt";            // square stitch ends: no blobs where the needle goes in
  // each colour first as a flat base in the thread's shade (the spaces between stitches filled, as
  // thread spreads when sewn), then each stitch as a thin thread with a fine sheen
  const wBase = Math.max(0.6, 2 * s), wThread = Math.max(0.45, 1.2 * s), wSheen = Math.max(0.3, 0.4 * s);    // 0.2, 0.12, 0.04 mm
  const wRun = Math.max(0.5, 1.2 * s), wRunThread = Math.max(0.35, 0.7 * s), wRunSheen = Math.max(0.25, 0.25 * s);   // a lone run: 0.12, 0.07, 0.025 mm
  const wFill = Math.max(1, 4.4 * s);          // a fill's rows are 0.4 mm apart: its stitches cover that
  const upto = +$("#step").value;
  // no background behind the logo: on white, a light thread is drawn a shade darker so it shows
  const cols = C.colors.map((c) => rgb(c.hex)).map(([r, gg, b]) => 0.299 * r + 0.587 * gg + 0.114 * b > 200 ? [r * 0.8, gg * 0.8, b * 0.8] : [r, gg, b]);
  const line = (l, col, w) => { g.strokeStyle = css(col); g.lineWidth = w; g.beginPath(); g.moveTo(l[0], l[1]); g.lineTo(l[2], l[3]); g.stroke(); };
  const blocks = [[]], [left, right] = denseStitches();
  let ci = 0, prev = null, n = 0, last = null;
  for (let i = 0; i < Math.min(upto, C.st.length); i++) {
    const [x, y, c] = C.st[i];
    if (c === 3) { ci = Math.min(ci + 1, cols.length - 1); prev = [x, y]; blocks.push([]); continue; }
    if (c === 0) n++;
    if (c === 0 && prev) blocks[blocks.length - 1].push([(prev[0] - x0) * s, (y1 - prev[1]) * s, (x - x0) * s, (y1 - y) * s, ci, Math.atan2(y - prev[1], x - prev[0]), i]);
    prev = c === 2 ? prev : [x, y];
    last = prev;
  }
  for (const lines of blocks) {
    if (!lines.length) continue;
    if (C.colors[lines[0][4]]?.stop === "foam") {
      // puff satin piles up into one smooth surface: sheen only, lit by the way each stitch lies
      // (as the PNG preview and Wilcom's), so strokes sewn at different angles stand apart
      for (const l of lines) { const sh = 0.74 + 0.26 * Math.abs(Math.cos(l[5] - LIGHT)); line(l, cols[l[4]].map((v) => Math.min(255, (v * 1.08 + 12) * sh)), wBase); }
      continue;
    }
    // in sewing order, as the thread lies: each stitch (the parts of a split stitch, a long satin
    // stitch sewn in two or three in line, joined) with the cover between it and the next one going
    // back across filled first (thread spreads when sewn: a satin is solid, as in Wilcom's view),
    // then its thread, so later stitches cover the underlay as sewn
    const whole = [];
    for (const l of lines) {
      const w = whole[whole.length - 1], turn = w ? Math.abs(Math.atan2(Math.sin(l[5] - w.l[5]), Math.cos(l[5] - w.l[5]))) : 9;
      if (w && l[6] === w.l[6] + 1 && turn < 0.2) { w.l = [w.l[0], w.l[1], l[2], l[3], w.l[4], w.l[5], l[6]]; w.parts.push(l); }
      else whole.push({ l: [...l], parts: [l] });
    }
    whole.forEach((w, j) => {
      const p = w.l, q = whole[j + 1]?.l;
      if (q && q[0] === p[2] && q[1] === p[3] && satinPair(p, q, 10 * s)) {
        g.fillStyle = css(threadShades(cols[p[4]], p[5])[1].map((v) => v * 0.9));
        g.beginPath(); g.moveTo(p[0], p[1]); g.lineTo(p[2], p[3]); g.lineTo(q[2], q[3]); g.closePath(); g.fill();
      }
      // a stitch over 1 mm with others beside it covers the width of its row (a fill's rows, a
      // satin's stitches lie 0.2-0.4 mm apart): its base in the thread's shade, the fine thread over it
      // a run with nothing sewn beside it (an outline, the underlay, a pen line): a single fine thread
      const sewn = (l) => [left[l[6]] < upto, right[l[6]] < upto];
      const beside = w.parts.some((l) => sewn(l).some(Boolean));
      const wide = w.parts.some((l) => sewn(l).every(Boolean)) && Math.hypot(p[2] - p[0], p[3] - p[1]) > 10 * s;
      for (const l of w.parts) {
        const [edge, body, sheen] = threadShades(cols[l[4]], l[5], vary(l[6]));
        if (!beside) { line(l, edge.map((v) => v * 0.92), wRun); line(l, body, wRunThread); line(l, sheen, wRunSheen); continue; }
        line(l, (wide ? body : edge).map((v) => v * 0.92), wide ? wFill : wBase); line(l, body, wThread); line(l, sheen, wSheen);
      }
    });
  }
  if (upto < C.st.length && last) {                   // where the needle is
    g.fillStyle = "#ff3b30";
    g.beginPath(); g.arc((last[0] - x0) * s, (y1 - last[1]) * s, Math.max(3, 6 * s), 0, 7); g.fill();
  }
  const out = cv.getContext("2d");
  out.clearRect(0, 0, cv.width, cv.height);
  out.save();
  // a soft shadow, kept small when zoomed in so it does not thicken fine threads
  out.shadowColor = "rgba(0,0,0,.35)"; out.shadowBlur = Math.min(3.5 * s, 4 * dpr); out.shadowOffsetX = out.shadowOffsetY = Math.min(2.5 * s, 2 * dpr);
  out.drawImage(art, 0, 0);
  out.restore();
  // kept for editing (cap-edit.js): where the design sits, and the drawing without the selection
  C.view = { x0, y1, k, dpr };
  const base = draw.base || (draw.base = document.createElement("canvas"));
  base.width = cv.width; base.height = cv.height; base.getContext("2d").drawImage(cv, 0, 0);
  if (typeof editOverlay === "function") editOverlay(out);
  const total = C.info?.stitches || 0;
  $("#stepText").textContent = upto >= C.st.length ? `All ${total.toLocaleString()} stitches` : `Stitch ${n.toLocaleString()} of ${total.toLocaleString()} · colour ${ci + 1}`;
}
$("#step").addEventListener("input", () => { stop(); draw(); });
window.addEventListener("resize", () => { clearTimeout(draw._t); draw._t = setTimeout(draw, 120); });

// watch it sew: about 6 seconds from the first stitch to the last
function stop() { C.playing = false; $("#playBtn").textContent = "▶"; }
$("#playBtn").addEventListener("click", () => {
  if (C.playing) return stop();
  if (+$("#step").value >= C.st.length) $("#step").value = 0;
  C.playing = true; $("#playBtn").textContent = "❚❚";
  const per = Math.max(1, Math.ceil(C.st.length / 360));
  const tick = () => {
    if (!C.playing) return;
    const v = Math.min(C.st.length, +$("#step").value + per);
    $("#step").value = v; draw();
    if (v >= C.st.length) stop(); else requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);
});

// ---------------------------------------------------------------- size
// width and height are the logo's own size: change one and the other follows, in the logo's
// proportions (as it is stitched: the colours sewn, the turn; before digitizing, as traced)
const inches = (v) => (Math.round(v * 100) / 100).toString();
const aspectNow = () => C.info?.aspect || C.aspect || 0;
function linkSize(changed) {
  if (C.lock && C.info?.size_mm) {      // while editing: the whole design scales to the size typed
    const v = num(changed) * MM, [w, h] = C.info.size_mm;
    if (v > 0) C.lock *= changed === "#w" ? v / w : v / h;
  }
  const a = aspectNow();
  if (!a || !(num(changed) > 0)) return;
  // rounded up to 0.01 in, so the side typed is the one the logo fills exactly
  if (changed === "#w") $("#h").value = inches(Math.ceil(num("#w") / a * 100) / 100);
  else $("#w").value = inches(Math.ceil(num("#h") * a * 100) / 100);
}
// after an area preset, the crown or a new logo: the size shrinks to the logo fitted inside it
function fitSize() {
  if (C.lock && C.info?.size_mm) {      // while editing: the design scales to fit the area
    const [w, h] = C.info.size_mm;
    C.lock *= Math.min(num("#w") * MM / w, num("#h") * MM / h);
    return;
  }
  const a = aspectNow(), W = num("#w"), H = num("#h");
  if (!(a > 0 && W > 0 && H > 0) || Math.abs(W / H - a) / a < 0.01) return;
  // rounded to 0.01 in, the box can be a hair narrower than the logo: the larger side is rounded up
  if (W / H > a) $("#w").value = inches(Math.ceil(H * a * 100) / 100); else $("#h").value = inches(Math.ceil(W / a * 100) / 100);
}
// the crown keeps about 1/2 in clear at the top and bottom of the design
function fitCrown() {
  const crown = num("#crown");
  if (crown && num("#h") > crown - 1) { $("#h").value = (crown - 1).toFixed(2).replace(/\.?0+$/, ""); linkSize("#h"); }
}
$("#preset").addEventListener("change", (e) => {
  const m = e.target.value.match(/^([\d.]+)x([\d.]+)$/);
  if (!m) return;
  $("#w").value = m[1]; $("#h").value = m[2];
  if (isDst()) { dstResizeTo(num("#w"), num("#h")); return; }
  fitSize();
  fitCrown();
  markDirty();
});
$("#crown").addEventListener("change", () => { fitCrown(); markDirty(); });
for (const id of ["#w", "#h"]) {
  $(id).addEventListener("input", () => { if (isDst()) return; $("#preset").value = "custom"; linkSize(id); markDirty(); });
  $(id).addEventListener("change", () => {      // a DST: the stitches scaled when the size is entered
    if (!isDst()) return;
    $("#preset").value = "custom";
    dstResizeTo(id === "#w" ? num("#w") : 0, id === "#h" ? num("#h") : 0);
  });
}
for (const id of ["#density", "#pull", "#origin", "#order", "#tilt", "#tackdown", "#light"]) $(id).addEventListener("change", markDirty);
document.querySelectorAll('input[name="kind"]').forEach((r) => r.addEventListener("change", () => {
  $("#puffNote").hidden = !isPuff();
  renderColors(); markDirty();
}));

// ---------------------------------------------------------------- files
// what the server needs to make a file: for a logo its token and settings; for a DST its stitches
function fileRequest(fmt) {
  if (isDst()) {
    const colors = C.colors.map((c) => ({ id: c.id, hex: c.hex, code: c.thread?.num, name: c.thread?.name || c.name,
                                           brand: c.thread ? C.chartTitle : "", label: c.thread ? `${C.chartTitle} · ${c.thread.num} ${c.thread.name}` : c.name }));
    return { path: "/api/cap/dst-file", body: { format: fmt, name: C.name, title: fmt === "png" ? `${C.name} · embroidery` : C.name,
                                               stitches: C.st, colors, chart: C.chartTitle } };
  }
  const threads = threadMap();
  const labels = Object.fromEntries(Object.entries(threads).map(([id, t]) => [id, `${t.brand} · ${t.code} ${t.name}`]));
  const extra = fmt === "png" ? { format: "png", title: `${C.name} · cap embroidery`, labels }
              : fmt === "pdf" ? { format: "pdf", title: C.name, chart: C.chartTitle, threads } : { format: "dst" };
  return { path: "/api/cap/file", body: { token: C.token, options: options(), ...extra } };
}
async function ready() {               // a logo changed since it was digitized: digitize it first
  if (!isDst() && (C.dirty || !C.digitized)) await digitize();
  return isDst() ? !!C.st : C.digitized && !C.dirty;
}
async function save(fmt) {
  if (!(await ready())) return;
  const name = `${C.name}.${fmt}`;
  busy(true, fmt === "dst" ? "Writing the DST…" : fmt === "pdf" ? "Making the worksheet…" : "Drawing the preview…");
  try {
    const api = window.pywebview?.api, f = fileRequest(fmt);
    if (api?.save_url) {        // the app saves it straight from the local server
      let where = await api.save_url(name, f.path, f.body);
      if (where && where.error === "expired" && C.file && !isDst()) { await analyze(); where = await api.save_url(name, f.path, fileRequest(fmt).body); }
      if (where && where.error) throw new Error(where.error);
      if (where) toast(`Saved ${name} to ${where}.`);
    } else {
      await download(name, f);
      toast(`Saved ${name} to your Downloads folder.`);
    }
  } catch (e) { toast(e.message, true, 7000); }
  finally { busy(false); }
}
async function download(name, f) {
  const r = f.path === "/api/cap/file" ? await request(f.path, (({ token, options: _o, ...rest }) => rest)(f.body)) : await post(f.path, f.body);
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Failed (${r.status})`);
  const blob = await r.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
// the DST, the worksheet PDF and the preview PNG together, into one folder (the app asks which)
async function saveAll() {
  try {
    if (!(await ready())) return false;
    busy(true, "Saving the DST, PDF and PNG…");
    const files = ["dst", "pdf", "png"].map((fmt) => ({ name: `${C.name}.${fmt}`, ...fileRequest(fmt) }));
    const api = window.pywebview?.api;
    if (api?.save_bundle) {
      const where = await api.save_bundle(files);
      if (where && where.error) throw new Error(where.error);
      if (!where) return false;
      toast(`Saved ${C.name}.dst, .pdf and .png to ${where}.`, false, 6000);
    } else {
      for (const f of files) await download(f.name, f);
      toast(`Saved ${C.name}.dst, .pdf and .png to your Downloads folder.`, false, 6000);
    }
    return true;
  } catch (e) { toast(e.message, true, 7000); return false; }
  finally { busy(false); }
}
$("#saveDst").addEventListener("click", () => save("dst"));
$("#savePng").addEventListener("click", () => save("png"));
$("#savePdf").addEventListener("click", () => save("pdf"));
