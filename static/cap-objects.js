// DST Maker: objects, as a digitizing program has them. After Auto Digitize (or Click to Stitch) every
// piece of a logo (a letter, a star: each separate shape of a colour) and every shape drawn is an
// object: the Object panel sets how it is sewn, the Objects list shows the sewing order.
//   Object settings (C.sew, by object: a logo piece's key, or "s<id>" for a drawn shape): type
//   "auto" (the digitizer chooses, as before), "satin", "fill" or "run"; stitch angle (degrees),
//   row spacing (mm), stitch length (mm), pull compensation (mm), underlay, run single or triple,
//   tie in, tie off, trim after, and a start point (image pixels). Sewn on Update Digitizing
//   (digitize._sew_object).
//   Click to Stitch (7): the logo's pieces are found (/api/cap/regions); pointing at one shows it,
//   a click (or a box dragged over several) sews it with the settings in the panel, and only the
//   pieces clicked are sewn (C.only), placed as in the whole logo. Auto Digitize (8) sews the rest.
//   Object tools (one object selected): Reshape (R: drag a point; click an edge to add one; select
//   a point and press Delete to take it away; Enter keeps it, Esc drops it), Cut hole (draw round the
//   hole), Knife (K: drag a line right across it: two objects), Start point (E: click where its
//   sewing begins), Stitch angle (A: drag a line the way the stitches lie). And on the selection:
//   Duplicate (⌘D), Flip horizontal and vertical, Group (⌘G) and Ungroup (⇧⌘G), Lock (⌘L; unlock in
//   the list). Tab and ⇧Tab select the next and the previous object in the sewing order.
//   A logo piece reshaped, cut or copied keeps its colour: its outline is kept with its edit
//   (edits[key].rings, image pixels), a new piece as "<colour>:x<n>"; a drawn shape changes itself.
"use strict";

C.sew = {}; C.only = null; C.regions = null; C.locked = []; C.groups = []; C.ctsCfg = { type: "auto" };
const O = { cts: null, node: null, line: null, lasso: null, tab: "objects", sig: "", drag: null, timer: 0 };

// ---------------------------------------------------------------- keys
function objKey(k) {            // the object's settings key: a drawn shape keeps its own across a recolour
  k = String(k);
  let m = /^draft:(\d+)$/.exec(k); if (m) return "s" + m[1];
  m = SHAPE_KEY.exec(k); if (m) return "s" + m[1];
  return k;
}
function shapeOfKey(k) {
  const d = draftOf(k); if (d) return d;
  const m = SHAPE_KEY.exec(String(k));
  return m ? C.shapes.find((x) => String(x.id) === m[1]) || null : null;
}
const colourOf = (k) => String(k).slice(0, String(k).lastIndexOf(":"));
function sewToSend() {          // the settings as the digitizer keys its pieces
  const out = {};
  for (const [k, cfg] of Object.entries(C.sew || {})) {
    const m = /^s(\d+)$/.exec(k);
    if (!m) { out[k] = cfg; continue; }
    const sh = C.shapes.find((x) => String(x.id) === m[1]);
    if (sh) out[`shape${sh.hex}:s${sh.id}`] = cfg;
  }
  return out;
}
const cfgOf = (k) => C.sew[objKey(k)] || {};
const isLocked = (k) => (C.locked || []).includes(objKey(k));
function groupOf(k) {           // the objects grouped with k (k alone when it is in no group)
  const g = (C.groups || []).find((ks) => ks.includes(objKey(k)));
  if (!g) return [k];
  const all = allPieces();
  return all.filter((x) => g.includes(objKey(x)));
}
const one = () => (C.sels.length === 1 ? C.sels[0] : null);
const nextShapeId = () => (C.shapes.reduce((m, sh) => Math.max(m, sh.id), 0) || 0) + 1;

// ---------------------------------------------------------------- an object's outline, and changing it
// its outline now (image pixels, even-odd: the outline, then its holes), or null
function objRingsPx(k) {
  if (!C.info?.frame) return null;
  const sh = draftOf(k);
  if (sh) return sh.pxRings ? sh.pxRings.map((r) => r.slice()) : sh.closed ? [sh.px.slice()] : null;
  const pd = pending(k);
  const rings = [...pd.rings, ...pd.holes];
  return rings.length ? rings.map((r) => r.map(toPxFrame)) : null;
}
// the pieces of a sewn shape shown as going (until Update Digitizing), as the Pathfinder does
function dropShapePieces(sh) {
  const edits = { ...C.edits };
  for (const p of C.info.pieces || []) {
    const m = SHAPE_KEY.exec(p.key);
    if (m && m[1] === String(sh.id)) edits[p.key] = { ...ID, ...(edits[p.key] || {}), deleted: true };
  }
  C.edits = edits;
}
// a new drawn shape like sh (its thread, its settings), from rings in image pixels
function shapeLike(sh, ringsPx) {
  const id = nextShapeId(), rings = ringsPx.map((r) => r.map(fromPxFrame));
  const out = { id, hex: sh.hex, view: rings[0], px: ringsPx[0], closed: true, width: sh.width, width_mm: sh.width_mm, sewn: false,
                ...(ringsPx.length > 1 ? { rings, pxRings: ringsPx } : {}), ...(sh.text ? { text: sh.text } : {}) };
  if (C.sew["s" + sh.id]) { const c = { ...C.sew["s" + sh.id] }; delete c.start; C.sew["s" + id] = c; }    // its settings, not its start point
  return out;
}
// object k given a new outline (image pixels, even-odd): returns its key now
function setObjRings(k, ringsPx) {
  if (!C.lock) C.lock = C.info.mm_per_px;       // the scale stays while editing
  const sh = shapeOfKey(k);
  if (sh && !sh.sewn) {
    delete sh.corner;
    const rings = ringsPx.map((r) => r.map(fromPxFrame));
    sh.px = ringsPx[0]; sh.view = rings[0]; sh.closed = true;
    if (ringsPx.length > 1 || sh.rings) { sh.pxRings = ringsPx; sh.rings = rings; } else { delete sh.pxRings; delete sh.rings; }
    C.shapes = [...C.shapes];
    return "draft:" + sh.id;
  }
  if (sh) {                     // a sewn shape: replaced by a drawn one with the new outline
    const n = shapeLike(sh, ringsPx);
    dropShapePieces(sh);
    C.shapes = [...C.shapes, n];
    if (C.sew["s" + sh.id]) C.sew["s" + n.id] = { ...C.sew["s" + sh.id] };
    return "draft:" + n.id;
  }
  const e = C.edits[k] || {};               // a logo piece: its outline kept with its edit (its move and turn are in it now)
  C.edits = { ...C.edits, [k]: { ...ID, ...(e.color ? { color: e.color } : {}), rings: ringsPx } };
  return k;
}
// a new object like k with the outline given (a copy, a piece cut off): its key
function addObjLike(k, ringsPx) {
  if (!C.lock) C.lock = C.info.mm_per_px;
  const sh = shapeOfKey(k);
  if (sh) {
    const n = shapeLike(sh, ringsPx);
    C.shapes = [...C.shapes, n];
    return "draft:" + n.id;
  }
  const col = colourOf(k);
  let n = 1;
  for (const key of [...Object.keys(C.edits), ...(C.info.pieces || []).map((p) => p.key)]) {
    const m = new RegExp(`^${col.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}:x(\\d+)$`).exec(key);
    if (m) n = Math.max(n, +m[1] + 1);
  }
  const key = `${col}:x${n}`, e = C.edits[k] || {};
  C.edits = { ...C.edits, [key]: { ...ID, ...(e.color ? { color: e.color } : {}), rings: ringsPx } };
  if (C.sew[objKey(k)]) C.sew[key] = { ...C.sew[objKey(k)] };
  delete (C.sew[key] || {}).start;
  if (C.only) C.only = [...C.only, key];
  return key;
}

// ---------------------------------------------------------------- settings
function setCfg(patch) {
  if (!hasSel()) {              // Click to Stitch with nothing selected: the settings new objects get
    C.ctsCfg = clean({ ...C.ctsCfg, ...patch }) || { type: "auto" };
    O.sig = ""; objPanelSync();
    return;
  }
  remember();
  for (const k of C.sels) {
    if (isDst()) continue;
    const c = clean({ ...cfgOf(k), ...patch }), ok = objKey(k);
    if (c) C.sew = { ...C.sew, [ok]: c }; else { const s = { ...C.sew }; delete s[ok]; C.sew = s; }
  }
  markDirty();
}
function clean(c) {             // no empty fields; nothing but "auto": no settings at all
  for (const f of Object.keys(c)) if (c[f] === null || c[f] === undefined || c[f] === "" || Number.isNaN(c[f])) delete c[f];
  const keys = Object.keys(c);
  return !keys.length || (keys.length === 1 && c.type === "auto") ? null : c;
}
const numOrNull = (el) => (el.value.trim() === "" ? null : +el.value);

// ---------------------------------------------------------------- the Object panel
const TYPE_NAME = { auto: "Auto", satin: "Satin", fill: "Fill", run: "Run" };
function objPanelSync() {
  const panel = $("#objPanel");
  if (!panel) return;
  const drawing = ["pen", "satinblk", "free"].includes(C.tool) || String(C.tool).startsWith("shape:");
  const cts = (C.tool === "cts" || drawing) && !hasSel() && !isDst();       // the settings what is clicked or drawn next gets
  const keys = isDst() ? [] : C.sels;
  const cfgs = cts ? [C.ctsCfg] : keys.map(cfgOf);
  const sig = JSON.stringify([keys, cfgs, cts, C.digitized, C.dirty, C.tool, C.locked, C.groups,
    (C.info?.sequence || []).filter((e) => keys.includes(e.key)), $("#density").value, $("#pull").value]);
  seqRender();
  if (sig === O.sig) return;
  O.sig = sig;
  panel.hidden = $("#objBody").hidden = !(cts || keys.length);
  $("#objTitle").textContent = cts ? (drawing ? "New shapes" : "Click to Stitch") : keys.length > 1 ? `${keys.length} objects selected` : "Selected object";
  if ($("#objBody").hidden) return;
  const same = (f) => { const v = cfgs.map((c) => c[f]); return v.every((x) => x === v[0]) ? v[0] : undefined; };
  const type = same("type") ?? (cfgs.every((c) => !c.type) ? "auto" : null);
  for (const b of document.querySelectorAll("#objType button")) b.setAttribute("aria-pressed", b.dataset.type === (type || "auto") && type !== null);
  const show = type || "auto";
  for (const el of document.querySelectorAll("#objBody [data-for]")) el.hidden = !el.dataset.for.split(" ").includes(show);
  const put = (id, v) => { $(id).value = v === undefined || v === null ? "" : v; };
  put("#objAngle", same("angle")); put("#objDensity", same("density")); put("#objLength", same("length")); put("#objPull", same("pull"));
  $("#objAngle").placeholder = show === "fill" ? "90 (upright)" : "follows the shape";
  $("#objDensity").placeholder = $("#density").value;
  $("#objPull").placeholder = $("#pull").value;
  $("#objLength").placeholder = show === "run" ? "2.5" : "3.5";
  $("#objRun").value = same("run") || "single";
  const tick = (id, f, dflt) => {
    const v = cfgs.map((c) => (c[f] === undefined ? dflt : c[f]));
    $(id).checked = v.every(Boolean); $(id).indeterminate = !v.every((x) => x === v[0]);
  };
  tick("#objUnder", "underlay", true); tick("#objTieIn", "tie_in", true); tick("#objTieOff", "tie_off", true); tick("#objTrim", "trim", false);
  // how the digitizer sewed it (auto), and the tools that need one object
  const seq = new Map((C.info?.sequence || []).map((e) => [e.key, e]));
  const sewn = keys.map((k) => seq.get(k)?.kind).filter(Boolean);
  $("#objNote").textContent = cts ? (drawing ? "What you draw next is sewn so (a line: a run, unless you pick another type)."
      : "Click a part of the logo to sew it with these settings; drag a box over several. Esc ends Click to Stitch.")
    : keys.some((k) => draftOf(k)) ? "Not sewn yet: Update Digitizing sews it."
    : sewn.length ? `Sewn as ${[...new Set(sewn)].join(" and ")}${keys.length === 1 && seq.get(keys[0]) ? ` · ${seq.get(keys[0]).stitches.toLocaleString()} stitches` : ""}${C.dirty ? " (Update Digitizing to sew the changes)" : ""}.` : "";
  const single = keys.length === 1;
  for (const b of document.querySelectorAll("#objActions [data-act]")) {
    const a = b.dataset.act;
    b.disabled = !C.digitized || (["reshape", "hole", "knife", "start"].includes(a) && !single)
      || (a === "ungroup" && !keys.some((k) => groupOf(k).length > 1)) || (a === "group" && keys.length < 2);
    b.setAttribute("aria-pressed", C.tool === a);
  }
}
document.querySelectorAll("#objType button").forEach((b) => b.addEventListener("click", () => {
  const t = b.dataset.type;
  setCfg({ type: t, ...(t === "auto" ? { angle: null, length: null, run: null } : {}) });
}));
$("#objAngle").addEventListener("change", (e) => { const v = numOrNull(e.target); setCfg({ angle: v === null ? null : ((v % 180) + 180) % 180 }); });
$("#objDensity").addEventListener("change", (e) => { const v = numOrNull(e.target); setCfg({ density: v === null ? null : Math.min(1.5, Math.max(0.2, v)) }); });
$("#objLength").addEventListener("change", (e) => { const v = numOrNull(e.target); setCfg({ length: v === null ? null : Math.min(7, Math.max(1, v)) }); });
$("#objPull").addEventListener("change", (e) => { const v = numOrNull(e.target); setCfg({ pull: v === null ? null : Math.min(1, Math.max(0, v)) }); });
$("#objRun").addEventListener("change", (e) => setCfg({ run: e.target.value === "single" ? null : e.target.value }));
$("#objUnder").addEventListener("change", (e) => setCfg({ underlay: e.target.checked ? null : false }));
$("#objTieIn").addEventListener("change", (e) => setCfg({ tie_in: e.target.checked ? null : false }));
$("#objTieOff").addEventListener("change", (e) => setCfg({ tie_off: e.target.checked ? null : false }));
$("#objTrim").addEventListener("change", (e) => setCfg({ trim: e.target.checked ? true : null }));
$("#objReset").addEventListener("click", () => {
  if (!hasSel()) { C.ctsCfg = { type: "auto" }; O.sig = ""; objPanelSync(); return; }
  remember();
  const s = { ...C.sew }; for (const k of C.sels) delete s[objKey(k)]; C.sew = s;
  markDirty();
});
document.querySelectorAll("#objActions [data-act]").forEach((b) => b.addEventListener("click", () => objAction(b.dataset.act)));

// ---------------------------------------------------------------- the Objects list (the sewing order)
function seqKeys() {
  if (isDst() || !C.digitized) return [];
  if (C.arrange && C.dirty) return sewingOrder();        // a new order not sewn yet; else the order as sewn
  const now = allPieces(), has = new Set(now), out = [];
  for (const e of C.info?.sequence || []) if (has.has(e.key) && !out.includes(e.key)) out.push(e.key);
  for (const k of now) if (!out.includes(k)) out.push(k);
  return out;
}
const hexOf = (k) => draftOf(k)?.hex || pending(k).colour || C.info?.pieces?.find((p) => p.key === k)?.hex || "#888888";
function objName(k) {
  const seq = (C.info?.sequence || []).find((e) => e.key === k), cfg = cfgOf(k), sh = shapeOfKey(k);
  const what = cfg.type && cfg.type !== "auto" ? TYPE_NAME[cfg.type] : seq ? `${TYPE_NAME[seq.kind] || seq.kind}` : "Auto";
  const src = sh ? (sh.text ? `“${String(sh.text).slice(0, 14)}”` : "shape") : String(k).includes(":x") ? "piece (copy)" : "";
  return { what, src, stitches: draftOf(k) || pending(k).changed ? null : seq?.stitches };
}
function seqRender() {
  const ol = $("#seqList");
  if (!ol) return;
  const keys = seqKeys();
  const sig = JSON.stringify([keys, C.sels, O.tab, C.locked, C.sew, (C.info?.sequence || []).map((e) => e.stitches)]);
  if (sig === seqRender.sig) return;
  seqRender.sig = sig;
  $("#seqPanel").hidden = !keys.length;
  ol.innerHTML = "";
  const row = (k, i) => {
    const li = document.createElement("li"), n = objName(k), locked = isLocked(k);
    li.dataset.key = k;
    li.className = (C.sels.includes(k) ? "sel" : "") + (locked ? " locked" : "");
    li.draggable = O.tab === "objects";
    li.innerHTML = `<span class="n">${i + 1}</span><span class="sw"></span><span class="nm"></span><span class="ct"></span>
      <button type="button" class="lk" title="${locked ? "Locked: click to unlock" : "Lock: it cannot be selected on the design"}" aria-pressed="${locked}">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="${locked ? "M8 11V7a4 4 0 0 1 8 0v4" : "M8 11V7a4 4 0 0 1 7.5-2"}"/></svg></button>`;
    li.querySelector(".sw").style.background = hexOf(k);
    li.querySelector(".nm").textContent = n.src ? `${n.what} · ${n.src}` : n.what;
    li.querySelector(".ct").textContent = n.stitches == null ? "new" : n.stitches.toLocaleString();
    li.querySelector(".lk").addEventListener("click", (ev) => { ev.stopPropagation(); toggleLock([k]); });
    li.addEventListener("click", (ev) => {
      if (isLocked(k)) { toast("Locked: unlock it in the list first."); return; }
      const g = groupOf(k);
      C.sels = ev.shiftKey ? (C.sels.includes(k) ? C.sels.filter((x) => !g.includes(x)) : [...new Set([...C.sels, ...g])]) : g;
      if (C.tool !== "select") setTool("select");
      repaint();
    });
    li.addEventListener("dragstart", (ev) => { O.drag = k; ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", k); });
    li.addEventListener("dragover", (ev) => {
      if (!O.drag || O.drag === k) return;
      ev.preventDefault();
      const r = li.getBoundingClientRect(), below = ev.clientY > r.top + r.height / 2;
      li.classList.toggle("drop-below", below); li.classList.toggle("drop-above", !below);
    });
    li.addEventListener("dragleave", () => li.classList.remove("drop-below", "drop-above"));
    li.addEventListener("drop", (ev) => {
      ev.preventDefault();
      const below = li.classList.contains("drop-below");
      li.classList.remove("drop-below", "drop-above");
      if (O.drag && O.drag !== k) reorder(O.drag, k, below);
      O.drag = null;
    });
    li.addEventListener("dragend", () => { O.drag = null; });
    return li;
  };
  if (O.tab === "objects") { keys.forEach((k, i) => ol.appendChild(row(k, i))); return; }
  const byHex = new Map();
  keys.forEach((k, i) => { const h = hexOf(k).toLowerCase(); if (!byHex.has(h)) byHex.set(h, []); byHex.get(h).push([k, i]); });
  for (const [h, ks] of byHex) {
    const head = document.createElement("li");
    head.className = "head";
    head.innerHTML = `<span class="sw"></span><span class="nm"></span><span class="ct"></span>`;
    head.querySelector(".sw").style.background = h;
    const c = C.plan.find((p) => (thread(p)?.hex || p.hex).toLowerCase() === h), t = c && thread(c);
    head.querySelector(".nm").textContent = t ? `${t.num} ${t.name}` : h;
    head.querySelector(".ct").textContent = `${ks.length} object${ks.length === 1 ? "" : "s"}`;
    head.addEventListener("click", () => { C.sels = ks.map(([k]) => k).filter((k) => !isLocked(k)); repaint(); });
    ol.appendChild(head);
    for (const [k, i] of ks) ol.appendChild(row(k, i));
  }
}
function reorder(from, to, after) {
  const seq = seqKeys().filter((k) => k !== from);
  const moving = C.sels.includes(from) ? seqKeys().filter((k) => C.sels.includes(k)) : [from];
  const rest = seq.filter((k) => !moving.includes(k));
  let at = rest.indexOf(to);
  if (at < 0) return;
  if (after) at += 1;
  rest.splice(at, 0, ...moving);
  remember();
  C.arrange = rest.map(sewnKey); C.arrangeExact = true;
  markDirty();
  toast("New sewing order: sewn so when you click Update Digitizing.");
}
document.querySelectorAll("#seqTabs button").forEach((b) => b.addEventListener("click", () => {
  O.tab = b.dataset.tab;
  for (const x of document.querySelectorAll("#seqTabs button")) x.setAttribute("aria-pressed", x === b);
  seqRender.sig = ""; seqRender();
}));

// ---------------------------------------------------------------- Click to Stitch
async function enterCts() {
  if (!C.token || isDst()) return;
  if (!C.regions) {
    busy(true, "Finding the parts of the logo…");
    try {
      const j = await (await request("/api/cap/regions")).json();
      C.regions = j.regions.map((r) => ({ ...r, box: bbox(r.rings) }));
    } catch (e) { toast(e.message, true, 6000); return; }
    finally { busy(false); }
  }
  if (!C.digitized && C.only === null) C.only = [];
  C.sels = [];
  setTool("cts");
  O.sig = "";
  if (C.digitized) repaint(); else draw();
  setButtons();
  toast("Click to Stitch: click a part of the logo to sew it with the settings in the Object panel; drag a box over several.", false, 6000);
}
function evPx(ev) {             // the pointer as a pixel of the logo image
  if (C.digitized && C.view && C.info?.frame) return toPxFrame(toDesign(ev));
  const v = C.logoView;
  if (!v) return null;
  const r = $("#canvas").getBoundingClientRect();
  return [v.sx + (ev.clientX - r.left) / v.k, v.sy + (ev.clientY - r.top) / v.k];
}
function pxToScreen(p) {
  if (C.digitized && C.view && C.info?.frame) return toScreen(fromPxFrame(p));
  const v = C.logoView;
  return [(p[0] - v.sx) * v.k * v.dpr, (p[1] - v.sy) * v.k * v.dpr];
}
const inRegion = (p, r) => p[0] >= r.box[0] && p[0] <= r.box[2] && p[1] >= r.box[1] && p[1] <= r.box[3]
  && r.rings.filter((ring) => inPoly(p, ring)).length % 2 === 1;
function regionAt(p) {           // the smallest piece under the point (a letter in a banner, not the banner)
  let best = null;
  for (const r of C.regions || []) if (inRegion(p, r) && (!best || r.area < best.area)) best = r;
  return best;
}
const sewnNow = (key) => (C.only === null || C.only.includes(key)) && !C.edits[key]?.deleted;
const colourOn = (r) => { const c = C.plan.find((p) => p.id === r.color); return !c || c.pick >= 0; };
function ctsAdd(keys) {
  keys = keys.filter(Boolean);
  if (!keys.length) return;
  remember();
  if (C.only === null && !C.digitized) C.only = [];
  for (const k of keys) {
    if (C.only && !C.only.includes(k)) C.only = [...C.only, k];
    if (C.edits[k]?.deleted) { const e = { ...C.edits[k] }; delete e.deleted; C.edits = { ...C.edits, [k]: e }; }
    const c = clean({ ...C.ctsCfg });
    const s = { ...C.sew }; if (c) s[k] = c; else delete s[k]; C.sew = s;
    const r = (C.regions || []).find((x) => x.key === k), col = r && C.plan.find((p) => p.id === r.color);
    if (col && col.pick < 0) { col.pick = 0; renderColors(); }       // a colour set to "don't stitch": stitched now
  }
  // a short wait, so several clicks are digitized together
  clearTimeout(O.timer);
  O.timer = setTimeout(() => { if (C.only === null || C.only.length) digitize(); }, 450);
  if (C.digitized) markDirty(); else draw();
}
function ctsBounds() {          // the logo's parts not sewn yet (0.1 mm on the design), or null
  if (!C.regions || C.only === null || !C.info?.frame) return null;
  const left = C.regions.filter((r) => !sewnNow(r.key));
  if (!left.length) return null;
  return bbox(left.flatMap((r) => [[r.box[0], r.box[1]], [r.box[2], r.box[1]], [r.box[2], r.box[3]], [r.box[0], r.box[3]]].map(fromPxFrame)).map((p) => [p]));
}
async function autoRest() {     // Auto Digitize what Click to Stitch has not sewn yet
  if (C.only === null) return;
  remember();
  C.only = null;
  if (C.tool === "cts") setTool("select");
  await digitize();
}

// ---------------------------------------------------------------- the pointer (before cap-edit.js's own)
const screenPt = (ev) => { const r = $("#canvas").getBoundingClientRect(); return [(ev.clientX - r.left) * (C.view?.dpr || C.logoView?.dpr || 1), (ev.clientY - r.top) * (C.view?.dpr || C.logoView?.dpr || 1)]; };
function objPointer(ev, phase) {
  if (typeof toolPointer === "function" && toolPointer(ev, phase)) return true;     // measure, satin blocks, pen (cap-tools.js)
  const t = C.tool;
  if (t === "cts") {
    const p = ev && evPx(ev);
    if (phase === "down") {
      if (!p) return true;
      O.cts = { start: p, cur: p, moved: false };
      try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* not started here */ }
    } else if (phase === "move") {
      if (!p) return true;
      if (O.cts) {
        O.cts.cur = p;
        const [a, b] = [pxToScreen(O.cts.start), pxToScreen(p)];
        if (Math.hypot(a[0] - b[0], a[1] - b[1]) > 6) O.cts.moved = true;
      }
      O.hover = regionAt(p)?.key || null;
      $("#canvas").style.cursor = O.hover ? "pointer" : "crosshair";
      ctsRepaint();
    } else if (phase === "up") {
      const d = O.cts; O.cts = null;
      if (!d) return true;
      if (!d.moved) {
        const r = regionAt(d.start);
        if (r) ctsAdd([r.key]); else ctsRepaint();
      } else {
        const [x0, x1] = [Math.min(d.start[0], d.cur[0]), Math.max(d.start[0], d.cur[0])];
        const [y0, y1] = [Math.min(d.start[1], d.cur[1]), Math.max(d.start[1], d.cur[1])];
        const keys = (C.regions || []).filter((r) => { const mx = (r.box[0] + r.box[2]) / 2, my = (r.box[1] + r.box[3]) / 2; return mx >= x0 && mx <= x1 && my >= y0 && my <= y1; }).map((r) => r.key);
        if (keys.length) ctsAdd(keys); else ctsRepaint();
      }
    }
    return true;
  }
  if (!C.view || !C.st || !["reshape", "hole", "knife", "start", "angle"].includes(t)) return false;
  const pt = ev ? toDesign(ev) : null;
  if (t === "reshape") return nodePointer(ev, phase);
  if (t === "start") {
    if (phase === "down") setStart(pt);
    return true;
  }
  if (t === "knife" || t === "angle") {
    if (phase === "down") { O.line = { a: pt, b: pt }; try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* */ } }
    else if (phase === "move" && O.line) { O.line.b = ev.shiftKey ? snap15(O.line.a, pt) : pt; repaint(); }
    else if (phase === "up" && O.line) {
      const l = O.line; O.line = null;
      if (Math.hypot(l.b[0] - l.a[0], l.b[1] - l.a[1]) < 5) { repaint(); return true; }
      if (t === "knife") knifeCut(l); else setAngle(l);
    }
    if (phase === "move" && !O.line) $("#canvas").style.cursor = "crosshair";
    return true;
  }
  if (t === "hole") {
    if (phase === "down") { O.lasso = [pt]; try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* */ } }
    else if (phase === "move" && O.lasso) { const l = O.lasso[O.lasso.length - 1]; if (Math.hypot(pt[0] - l[0], pt[1] - l[1]) * C.view.k > 3) O.lasso.push(pt); repaint(); }
    else if (phase === "up" && O.lasso) { const l = O.lasso; O.lasso = null; cutHole(l); }
    if (phase === "move" && !O.lasso) $("#canvas").style.cursor = "crosshair";
    return true;
  }
  return false;
}
const snap15 = (a, b) => {      // shift: the line at 15° steps
  const d = Math.hypot(b[0] - a[0], b[1] - a[1]), ang = Math.round(Math.atan2(b[1] - a[1], b[0] - a[0]) / (Math.PI / 12)) * (Math.PI / 12);
  return [a[0] + d * Math.cos(ang), a[1] + d * Math.sin(ang)];
};
function ctsRepaint() { if (C.digitized) repaint(); else draw(); }

// ---------------------------------------------------------------- object tools
function objAction(a) {
  if (isDst() && !["duplicate", "fliph", "flipv"].includes(a)) return;
  if (a === "duplicate") return duplicate();
  if (a === "fliph") return stretch(-1, 1);
  if (a === "flipv") return stretch(1, -1);
  if (a === "group") return group();
  if (a === "ungroup") return ungroup();
  if (a === "lock") return toggleLock(C.sels);
  if (!one()) { toast("Select one object first."); return; }
  if (C.tool === a) { finishTool(true); return; }
  if (a === "reshape") return startReshape();
  setTool(a);
  O.sig = "";
  toast({ hole: "Cut hole: draw round the hole inside the object.", knife: "Knife: drag a line right across the object to cut it in two (shift: 15° steps).",
          start: "Start point: click where its sewing should begin.", angle: "Stitch angle: drag a line the way the stitches should lie (shift: 15° steps)." }[a], false, 5000);
}
function finishTool(keep) {
  if (C.tool === "reshape" && O.node) { if (keep) commitReshape(); O.node = null; }
  O.line = null; O.lasso = null;
  setTool("select");
  repaint();
}
function setStart(pt) {
  const k = one();
  if (!k) return;
  setCfg({ start: toPxFrame(pt).map((v) => Math.round(v * 10) / 10) });
  setTool("select");
  toast("Start point set: Update Digitizing sews it from there.");
}
function setAngle(l) {
  let deg = Math.atan2(l.b[1] - l.a[1], l.b[0] - l.a[0]) * 180 / Math.PI;
  deg = Math.round(((deg % 180) + 180) % 180);
  remember();
  for (const k of C.sels) {       // a satin keeps its type; anything else is a fill at that angle
    const c = cfgOf(k);
    C.sew = { ...C.sew, [objKey(k)]: { ...c, angle: deg, type: c.type === "satin" ? "satin" : "fill" } };
  }
  setTool("select");
  markDirty();
  toast(`Stitch angle ${deg}°: Update Digitizing sews it.`);
}
async function knifeCut(l) {
  const k = one(), rings = k && objRingsPx(k);
  if (!rings) { toast("This object cannot be cut.", true); repaint(); return; }
  busy(true, "Cutting…");
  try {
    const r = await post("/api/cap/knife", { rings, line: [l.a, l.b].map(toPxFrame) });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
    remember();
    const first = setObjRings(k, j.pieces[0]);
    const more = j.pieces.slice(1).map((p) => addObjLike(first, p));
    C.sels = [first, ...more];
    setTool("select");
    markDirty();
    toast(`Cut into ${j.pieces.length} objects: Update Digitizing sews them.`);
  } catch (e) { toast(e.message, true, 6000); repaint(); }
  finally { busy(false); }
}
async function cutHole(lasso) {
  const k = one(), rings = k && objRingsPx(k);
  if (!rings || lasso.length < 3) { repaint(); return; }
  busy(true, "Cutting the hole…");
  try {
    const r = await post("/api/cap/hole", { rings, hole: [lasso.map(toPxFrame)] });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
    remember();
    C.sels = [setObjRings(k, j.rings)];
    setTool("select");
    markDirty();
    toast("Hole cut: Update Digitizing sews it.");
  } catch (e) { toast(e.message, true, 6000); repaint(); }
  finally { busy(false); }
}
function duplicate() {
  if (!hasSel()) return;
  if (isDst()) { dupDst(); return; }
  remember();
  const off = toPx([20, -20]), out = [];     // 2 mm right and down
  for (const k of C.sels) {
    const rings = objRingsPx(k);
    const sh = draftOf(k);
    if (sh && !sh.closed && !sh.rings) {     // a line: its points
      const id = nextShapeId(), px = sh.px.map(([x, y]) => [x + off[0], y + off[1]]);
      C.shapes = [...C.shapes, { ...sh, id, px, view: px.map(fromPxFrame) }];
      if (C.sew["s" + sh.id]) C.sew["s" + id] = { ...C.sew["s" + sh.id] };
      out.push("draft:" + id);
      continue;
    }
    if (!rings) continue;
    out.push(addObjLike(k, rings.map((r) => r.map(([x, y]) => [x + off[0], y + off[1]]))));
  }
  if (!out.length) return;
  C.sels = out;
  markDirty();
  toast(`${out.length === 1 ? "Copy" : `${out.length} copies`} made, 2 mm along: Update Digitizing sews ${out.length === 1 ? "it" : "them"}.`);
}
function dupDst() {             // a DST: the pieces' stitches again at the end, 2 mm along, in their colour
  const segs = segments(), off = [20, -20];
  remember();
  for (const k of C.sels) {
    const [s, e, b] = segs[k] || [];
    if (s === undefined) continue;
    let piece = C.st.slice(s, e).filter((p) => p[2] !== 4).map(([x, y, c]) => [x + off[0], y + off[1], c]);
    const first = piece.find((p) => p[2] === 0);
    if (!first) continue;
    if (piece[0][2] !== 1) piece = [[first[0], first[1], 1], ...piece];
    let end = C.st.length;
    if (C.st[end - 1]?.[2] === 4) end -= 1;
    const at = C.st[end - 1], lastBlock = blocks().length - 1;
    C.st.splice(end, 0, [at[0], at[1], 2], ...(b === lastBlock ? [] : [[at[0], at[1], 3]]), ...piece);
    if (b !== lastBlock) C.colors.push({ ...C.colors[b], id: `block${Date.now()}${k}` });
  }
  C.changed = true; C.sels = [];
  afterDst();
}
function group() {
  if (C.sels.length < 2) { toast("Select two or more objects to group."); return; }
  remember();
  const ks = C.sels.map(objKey);
  C.groups = [...(C.groups || []).map((g) => g.filter((k) => !ks.includes(k))).filter((g) => g.length > 1), ks];
  O.sig = ""; repaint();
  toast("Grouped: a click on one selects them all.");
}
function ungroup() {
  const ks = C.sels.map(objKey);
  if (!(C.groups || []).some((g) => g.some((k) => ks.includes(k)))) return;
  remember();
  C.groups = C.groups.filter((g) => !g.some((k) => ks.includes(k)));
  O.sig = ""; repaint();
  toast("Ungrouped.");
}
function toggleLock(keys) {
  if (!keys.length) return;
  remember();
  const ks = keys.map(objKey), all = ks.every((k) => (C.locked || []).includes(k));
  C.locked = all ? C.locked.filter((k) => !ks.includes(k)) : [...new Set([...(C.locked || []), ...ks])];
  if (!all) C.sels = C.sels.filter((k) => !isLocked(k));
  O.sig = ""; seqRender.sig = ""; repaint();
  toast(all ? "Unlocked." : "Locked: it cannot be selected or moved on the design. Unlock it in the Objects list.");
}

// ---------------------------------------------------------------- reshape: the outline's points
function rdp(pts, tol) {        // fewer points, the outline kept within tol (Douglas-Peucker)
  if (pts.length < 4) return pts;
  const keep = new Uint8Array(pts.length); keep[0] = keep[pts.length - 1] = 1;
  const stack = [[0, pts.length - 1]];
  while (stack.length) {
    const [a, b] = stack.pop();
    let far = -1, fd = tol;
    const [ax, ay] = pts[a], [bx, by] = pts[b], L = Math.hypot(bx - ax, by - ay);
    for (let i = a + 1; i < b; i++) {     // (a closed outline starts and ends at one point: from that point)
      const d = L < 1e-6 ? Math.hypot(pts[i][0] - ax, pts[i][1] - ay) : Math.abs((bx - ax) * (ay - pts[i][1]) - (ax - pts[i][0]) * (by - ay)) / L;
      if (d > fd) { fd = d; far = i; }
    }
    if (far >= 0) { keep[far] = 1; stack.push([a, far], [far, b]); }
  }
  return pts.filter((_p, i) => keep[i]);
}
function startReshape() {
  const k = one(), sh = draftOf(k);
  const open = sh && !sh.closed && !sh.rings;
  const rings = open ? [sh.px.slice()] : objRingsPx(k);
  if (!rings) { toast("This object cannot be reshaped.", true); return; }
  const tol = 0.25 / (C.lock || C.info.mm_per_px);           // 0.25 mm, in image pixels
  const pts = rings.map((r) => {
    const closed = !open && r.length > 3 && Math.hypot(r[0][0] - r[r.length - 1][0], r[0][1] - r[r.length - 1][1]) < 1e-6 ? r.slice(0, -1) : r;
    return open ? rdp(closed, tol) : rdp([...closed, closed[0]], tol).slice(0, -1);
  }).filter((r) => r.length >= (open ? 2 : 3));
  O.node = { key: k, rings: pts, open, sel: null, drag: null };
  setTool("reshape");
  O.sig = "";
  repaint();
  toast("Reshape: drag a point; click an edge to add one; select a point and press Delete to remove it. Enter keeps it, Esc drops it.", false, 7000);
}
function nodeHit(ev) {          // the point under the pointer: [ring, index], or the edge: {edge: [ring, index], at}
  const n = O.node, s = screenPt(ev), dpr = C.view.dpr;
  for (let r = 0; r < n.rings.length; r++) for (let i = 0; i < n.rings[r].length; i++) {
    const q = pxToScreen(n.rings[r][i]);
    if (Math.hypot(q[0] - s[0], q[1] - s[1]) <= 7 * dpr) return { node: [r, i] };
  }
  for (let r = 0; r < n.rings.length; r++) {
    const R = n.rings[r], m = n.open ? R.length - 1 : R.length;
    for (let i = 0; i < m; i++) {
      const a = pxToScreen(R[i]), b = pxToScreen(R[(i + 1) % R.length]);
      const vx = b[0] - a[0], vy = b[1] - a[1], L2 = vx * vx + vy * vy || 1e-9;
      const t = Math.max(0, Math.min(1, ((s[0] - a[0]) * vx + (s[1] - a[1]) * vy) / L2));
      if (Math.hypot(a[0] + vx * t - s[0], a[1] + vy * t - s[1]) <= 5 * dpr) return { edge: [r, i] };
    }
  }
  return null;
}
function nodePointer(ev, phase) {
  const n = O.node;
  if (!n) return true;
  if (phase === "down") {
    const h = nodeHit(ev), p = toPxFrame(toDesign(ev));
    if (h?.node) { n.sel = h.node; n.drag = { moved: false }; }
    else if (h?.edge) {          // a new point on the edge, and it is dragged
      const [r, i] = h.edge;
      n.rings[r].splice(i + 1, 0, p);
      n.sel = [r, i + 1]; n.drag = { moved: true };
    } else { n.sel = null; }
    try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* */ }
    repaint();
  } else if (phase === "move") {
    if (n.drag && n.sel) {
      let p = toPxFrame(toDesign(ev));
      n.rings[n.sel[0]][n.sel[1]] = p; n.drag.moved = true;
      repaint();
    } else {
      const h = nodeHit(ev);
      $("#canvas").style.cursor = h?.node ? "move" : h?.edge ? "copy" : "default";
    }
  } else if (phase === "up") { n.drag = null; repaint(); }
  return true;
}
function commitReshape() {
  const n = O.node;
  if (!n) return;
  remember();
  if (n.open) {
    const sh = draftOf(n.key);
    if (sh) { sh.px = n.rings[0]; sh.view = sh.px.map(fromPxFrame); C.shapes = [...C.shapes]; }
  } else C.sels = [setObjRings(n.key, n.rings.map((r) => [...r, r[0]]))];
  markDirty();
  toast("Reshaped: Update Digitizing sews the new outline.");
}

// ---------------------------------------------------------------- drawn over the design
function objOverlay(g) {
  const dpr = C.view?.dpr || C.logoView?.dpr || 1;
  const path = (r, map) => { g.beginPath(); r.forEach((p, i) => { const [x, y] = map(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); };
  // Click to Stitch: the parts not sewn yet (in their colour, faint), the one pointed at, the box
  if (C.regions && (C.only !== null || C.tool === "cts") && (C.digitized ? C.view : C.logoView)) {
    g.save();
    for (const r of C.regions) {
      const queued = !C.digitized && C.only?.includes(r.key);
      if (C.digitized && sewnNow(r.key)) continue;
      if (!C.digitized && !queued && r.key !== O.hover) continue;
      const c = C.plan.find((p) => p.id === r.color), hex = (c && thread(c)?.hex) || c?.hex || "#888888";
      g.beginPath();
      for (const ring of r.rings) { ring.forEach((p, i) => { const [x, y] = pxToScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); }
      if (C.digitized) { g.globalAlpha = colourOn(r) ? 0.28 : 0.12; g.fillStyle = hex; g.fill("evenodd"); g.globalAlpha = 1; }
      if (queued) { g.fillStyle = "rgba(52,199,89,.35)"; g.fill("evenodd"); }
      g.setLineDash([3 * dpr, 3 * dpr]); g.strokeStyle = "rgba(0,0,0,.35)"; g.lineWidth = 1 * dpr; g.stroke(); g.setLineDash([]);
    }
    const h = O.hover && C.tool === "cts" && (C.regions || []).find((r) => r.key === O.hover);
    if (h) {
      g.beginPath();
      for (const ring of h.rings) { ring.forEach((p, i) => { const [x, y] = pxToScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); }
      g.fillStyle = "rgba(10,132,255,.22)"; g.fill("evenodd");
      g.strokeStyle = "#0a84ff"; g.lineWidth = 2 * dpr; g.stroke();
    }
    if (O.cts?.moved) {
      const [ax, ay] = pxToScreen(O.cts.start), [bx, by] = pxToScreen(O.cts.cur);
      g.fillStyle = "rgba(10,132,255,.08)"; g.strokeStyle = "#0a84ff"; g.lineWidth = 1 * dpr; g.setLineDash([4 * dpr, 3 * dpr]);
      g.fillRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
      g.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
    }
    g.restore();
  }
  if (!C.view) return;
  if (typeof toolsOverlay === "function") toolsOverlay(g);      // grid, jumps, trims, measuring, satin blocks (cap-tools.js)
  g.save();
  // the selected object's start point (green) and stitch angle (a line through its centre)
  for (const k of C.sels) {
    const c = cfgOf(k);
    if (c.start) {
      const [x, y] = toScreen(fromPxFrame(c.start));
      g.fillStyle = "#34c759"; g.strokeStyle = "#ffffff"; g.lineWidth = 1.5 * dpr;
      g.beginPath(); g.arc(x, y, 5 * dpr, 0, 7); g.fill(); g.stroke();
    }
    if (c.angle !== undefined && (c.type === "fill" || c.type === "satin")) {
      const rs = ringsOf(k); if (!rs.length) continue;
      const [cx, cy] = toScreen(centroid(rs)), a = c.angle * Math.PI / 180, L = 22 * dpr;
      g.strokeStyle = "#ff9500"; g.lineWidth = 2 * dpr;
      g.beginPath(); g.moveTo(cx - L * Math.cos(a), cy + L * Math.sin(a)); g.lineTo(cx + L * Math.cos(a), cy - L * Math.sin(a)); g.stroke();
    }
  }
  // a line being drawn (knife, angle), a hole being drawn round
  if (O.line) {
    const [ax, ay] = toScreen(O.line.a), [bx, by] = toScreen(O.line.b);
    g.strokeStyle = C.tool === "knife" ? "#ff3b30" : "#ff9500"; g.lineWidth = 2 * dpr; g.setLineDash(C.tool === "knife" ? [6 * dpr, 4 * dpr] : []);
    g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke(); g.setLineDash([]);
  }
  if (O.lasso?.length > 1) {
    g.strokeStyle = "#ff3b30"; g.lineWidth = 1.5 * dpr; g.setLineDash([4 * dpr, 3 * dpr]);
    path(O.lasso, toScreen); g.closePath(); g.stroke(); g.setLineDash([]);
    g.fillStyle = "rgba(255,59,48,.12)"; g.fill();
  }
  // reshape: the outline being changed and its points
  const n = O.node;
  if (n && C.tool === "reshape") {
    g.fillStyle = "rgba(10,132,255,.12)"; g.strokeStyle = "#0a84ff"; g.lineWidth = 1.5 * dpr;
    g.beginPath();
    for (const r of n.rings) { r.forEach((p, i) => { const [x, y] = pxToScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); if (!n.open) g.closePath(); }
    if (!n.open) g.fill("evenodd");
    g.stroke();
    n.rings.forEach((r, ri) => r.forEach((p, i) => {
      const [x, y] = pxToScreen(p), on = n.sel && n.sel[0] === ri && n.sel[1] === i, s = (on ? 4.5 : 3.5) * dpr;
      g.fillStyle = on ? "#0a84ff" : "#ffffff"; g.strokeStyle = "#0a84ff"; g.lineWidth = 1.5 * dpr;
      g.fillRect(x - s, y - s, 2 * s, 2 * s); g.strokeRect(x - s, y - s, 2 * s, 2 * s);
    }));
  }
  g.restore();
}

// ---------------------------------------------------------------- keys (before cap-edit.js's own)
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  if (isDst() && !C.st) return;
  const mod = ev.metaKey || ev.ctrlKey, key = ev.key.toLowerCase();
  const take = () => { ev.preventDefault(); ev.stopImmediatePropagation(); };
  if (C.tool === "reshape" && O.node) {
    if (ev.key === "Enter") { take(); finishTool(true); return; }
    if (ev.key === "Escape") { take(); finishTool(false); return; }
    if ((ev.key === "Delete" || ev.key === "Backspace") && O.node.sel) {
      take();
      const [r, i] = O.node.sel, ring = O.node.rings[r];
      if (ring.length > (O.node.open ? 2 : 3)) ring.splice(i, 1); else toast("An outline needs at least three points.");
      O.node.sel = null; repaint(); return;
    }
    if (ev.key.startsWith("Arrow") && O.node.sel) {       // nudge the point: 0.1 mm (shift: 1 mm)
      take();
      const st = (ev.shiftKey ? 10 : 1), d = { ArrowLeft: [-st, 0], ArrowRight: [st, 0], ArrowUp: [0, st], ArrowDown: [0, -st] }[ev.key];
      const [r, i] = O.node.sel, p = fromPxFrame(O.node.rings[r][i]);
      O.node.rings[r][i] = toPxFrame([p[0] + d[0], p[1] + d[1]]); repaint(); return;
    }
    return;
  }
  if (["cts", "hole", "knife", "start", "angle"].includes(C.tool) && ev.key === "Escape") { take(); O.cts = null; O.hover = null; finishTool(false); ctsRepaint(); return; }
  if (!C.token && !isDst()) return;
  if (!mod && !ev.altKey && key === "7" && !isDst()) { take(); enterCts(); return; }
  if (!mod && !ev.altKey && key === "8" && !isDst()) { take(); if (C.only !== null) autoRest(); else if (!C.digitized || C.dirty) digitize(); return; }
  if (!C.digitized && !isDst()) return;
  if (mod && key === "d") { take(); duplicate(); return; }
  if (mod && key === "g") { take(); ev.shiftKey ? ungroup() : group(); return; }
  if (mod && key === "l") { take(); toggleLock(C.sels); return; }
  if (ev.key === "Tab" && !mod) {               // the next object in the sewing order (shift: the one before)
    const ks = seqKeys().filter((k) => !isLocked(k));
    if (!ks.length) return;
    take();
    const at = C.sels.length ? ks.indexOf(C.sels[C.sels.length - 1]) : -1;
    C.sels = [ks[((ev.shiftKey ? at - 1 : at + 1) + ks.length) % ks.length]];
    repaint(); return;
  }
  if (mod || ev.altKey || isDst()) return;
  if (key === "r" && one()) { take(); objAction("reshape"); return; }
  if (key === "k" && one()) { take(); objAction("knife"); return; }
  if (key === "e" && one()) { take(); objAction("start"); return; }
  if (key === "a" && hasSel()) { take(); objAction("angle"); return; }
}, true);

$("#ctsBtn").addEventListener("click", () => (C.tool === "cts" ? finishTool(false) : enterCts()));
$("#autoRestBtn").addEventListener("click", autoRest);
