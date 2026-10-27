// Vectorizer Local - page logic
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const S = {
  file: null, name: "", srcURL: "", srcW: 0, srcH: 0,
  rasterURL: "", result: null, svgText: "",
  trace: { max_colors: 0, palette: null, tracer: "precise", detail: 50, smoothing: 50, corner_threshold: 60, crop: null },
  output: {
    shape_stacking: "cutouts", group_by: "color", fit_shapes: true,
    draw_style: "fill_shapes", gap_filler: true, gap_clip: false, gap_non_scaling: true, gap_width: 1.5,
    stroke_non_scaling: true, stroke_override: false, stroke_color: "#000000", stroke_width: 1,
    svg_version: "1.1", fixed_size: true, size_mode: "unchanged", scale: 1, width: null, height: null, unit: "px", dpi: 72,
  },
  edits: { remove: [], recolor: {} }, history: [],
  view: "vectors", tool: "pan", zoom: 1, panX: 0, panY: 0, split: 0.5,
  selected: null, selectedSwatches: [], reqId: 0, traceKey: "", pending: null,
};

// ---------------------------------------------------------------- utilities
function toast(msg, isError = false, ms = 3800) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function debounce(fn, ms) { let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); }; }
const traceKeyOf = () => JSON.stringify([S.trace, S.output.shape_stacking]);

// ---------------------------------------------------------------- loading an image
const ACCEPT = /^image\/(png|jpeg|gif|bmp|webp|x-ms-bmp)$/;
async function openFile(file) {
  if (!file || !(ACCEPT.test(file.type) || /\.(png|jpe?g|gif|bmp|webp)$/i.test(file.name || ""))) {
    toast("Please use a PNG, JPG, GIF, BMP or WebP image.", true); return;
  }
  S.file = file; S.name = (file.name || "pasted-image").replace(/\.[^.]+$/, "");
  if (S.srcURL) URL.revokeObjectURL(S.srcURL);
  S.srcURL = URL.createObjectURL(file);
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = S.srcURL; })
    .catch(() => null);
  if (!img) { toast("This file could not be read as an image.", true); return; }
  S.srcW = img.naturalWidth; S.srcH = img.naturalHeight;
  S.trace = { ...S.trace, max_colors: 0, palette: null, crop: null };
  S.edits = { remove: [], recolor: {} }; S.history = []; S.selected = null; S.selectedSwatches = [];
  S.rasterURL = S.srcURL;
  $("#fileInfo").textContent = `${file.name || "Pasted image"} · ${S.srcW} × ${S.srcH}`;
  $("#landing").hidden = true; $("#workspace").hidden = false; $("#topActions").hidden = false;
  $('input[name=palMode][value=auto]').checked = true; $("#maxColorsRow").hidden = true;
  $("#raster").src = S.rasterURL;
  S.result = null;
  await refresh(true);
  fitView();
}

$("#fileInput").addEventListener("change", (e) => openFile(e.target.files[0]));
const drop = $("#drop");
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) openFile(f); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) openFile(item.getAsFile());
});
$("#newBtn").addEventListener("click", () => $("#fileInput").click());
$("#patchBtn").addEventListener("click", async () => {
  if (!S.file) return;
  try {
    const fd = new FormData();
    fd.append("image", S.file, S.file.name || "logo.png");
    const j = await (await fetch("/api/patch/analyze", { method: "POST", body: fd })).json();
    if (j.error) throw new Error(j.error);
    const url = "/patch?token=" + j.token;
    if (window.pywebview?.api?.open_window) window.pywebview.api.open_window("Patch Mockup", url);
    else window.open(url, "_blank");
  } catch (e) { toast(e.message, true); }
});

// ---------------------------------------------------------------- talking to the server
function requestOptions(withEdits = true) {
  const o = { ...S.trace, ...S.output };
  if (withEdits) o.edits = S.edits;
  return o;
}

async function vectorize(opts) {
  const fd = new FormData();
  fd.append("image", S.file, S.file.name || "image.png");
  fd.append("options", JSON.stringify(opts));
  const r = await fetch("/api/vectorize", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
  return j;
}

async function refresh(showBusy = false) {
  if (!S.file) return;
  const key = traceKeyOf();
  if (S.traceKey && key !== S.traceKey && (S.edits.remove.length || Object.keys(S.edits.recolor).length)) {
    S.edits = { remove: [], recolor: {} }; S.history = [];
    toast("Shapes were traced again, so the shape edits were cleared.");
  }
  S.traceKey = key;
  const id = ++S.reqId;
  const timer = setTimeout(() => ($("#busy").hidden = false), showBusy ? 0 : 350);
  const t0 = performance.now();
  const p = vectorize(requestOptions()).then((res) => {
    if (id !== S.reqId) return;
    S.result = res; render(res, performance.now() - t0);
  }).catch((e) => { if (id === S.reqId) toast(e.message, true, 6000); })
    .finally(() => { clearTimeout(timer); if (id === S.reqId) $("#busy").hidden = true; });
  S.pending = p;
  return p;
}
const refreshSoon = debounce(() => refresh(), 250);

// ---------------------------------------------------------------- rendering
function render(res, ms) {
  S.svgText = res.svg;
  const host = $("#vector");
  host.innerHTML = res.svg.replace(/^<\?xml[^>]*>\s*/, "");
  const svg = host.querySelector("svg");
  svg.setAttribute("width", "100%"); svg.setAttribute("height", "100%");
  const stage = $("#stage");
  stage.style.width = res.width + "px"; stage.style.height = res.height + "px";
  if (S.selected && !svg.querySelector("#" + CSS.escape(S.selected))) S.selected = null;
  markSelection();
  renderSwatches(res); renderLayers(svg); updateEditButtons();
  const st = res.stats;
  $("#status").textContent = [
    `${res.colors.length} colours`, `${st.shapes} shapes`, `${st.groups} groups/layers`,
    st.fitted ? `${st.fitted} whole shapes fitted` : null, `traced at ${res.upscale}×`,
    `${res.width}×${res.height}px`, ms ? `${(ms / 1000).toFixed(2)} s` : null,
  ].filter(Boolean).join(" · ") + (res.notes.length ? " — " + res.notes.join(" ") : "");
  applyView();
}

function renderSwatches(res) {
  const box = $("#swatches"); box.innerHTML = "";
  const total = res.colors.reduce((a, c) => a + c.pixels, 0) || 1;
  S.selectedSwatches = S.selectedSwatches.filter((h) => res.colors.some((c) => c.hex === h));
  for (const c of res.colors) {
    const b = document.createElement("div");
    b.className = "swatch" + (S.selectedSwatches.includes(c.hex) ? " selected" : "");
    b.title = c.hex;
    b.innerHTML = `<span class="chip" style="background:${c.hex}"></span><span class="pct">${c.hex}<br>${(c.pixels / total * 100).toFixed(c.pixels / total < 0.01 ? 2 : 1)}%</span><input type="color" value="${c.hex}" aria-label="Change ${c.hex}">`;
    b.addEventListener("click", (e) => {
      if (e.target.tagName === "INPUT") return;
      if (e.shiftKey || e.metaKey) S.selectedSwatches = S.selectedSwatches.includes(c.hex) ? S.selectedSwatches.filter((h) => h !== c.hex) : [...S.selectedSwatches, c.hex];
      else S.selectedSwatches = S.selectedSwatches.length === 1 && S.selectedSwatches[0] === c.hex ? [] : [c.hex];
      renderSwatches(res);
    });
    b.querySelector("input").addEventListener("change", (e) => editPalette((pal) => pal.forEach((p) => { if (p.to === c.hex) p.to = e.target.value; })));
    box.appendChild(b);
  }
  $("#mergeBtn").disabled = S.selectedSwatches.length < 2;
  $("#removeColorBtn").disabled = S.selectedSwatches.length < 1 || res.colors.length <= S.selectedSwatches.length;
}

function currentPalette() {
  // palette entries map detected colours ("from") to output colours ("to")
  return (S.trace.palette || S.result.palette).map((p) => ({ ...p }));
}
function editPalette(fn) {
  const pal = currentPalette(); fn(pal);
  S.trace.palette = pal.filter((p) => p.from);
  refresh(true);
}
$("#mergeBtn").addEventListener("click", () => {
  const [first, ...rest] = S.selectedSwatches;
  editPalette((pal) => pal.forEach((p) => { if (rest.includes(p.to)) p.to = first; }));
  S.selectedSwatches = [first];
});
$("#removeColorBtn").addEventListener("click", () => {
  const gone = new Set(S.selectedSwatches);
  editPalette((pal) => pal.splice(0, pal.length, ...pal.filter((p) => !gone.has(p.to))));
  S.selectedSwatches = [];
});
function openMatch(page, title) {
  const hexes = (S.selectedSwatches.length ? S.selectedSwatches : (S.result?.colors || []).map((c) => c.hex)).map((h) => h.slice(1));
  const url = page + (hexes.length ? "?hex=" + hexes.join(",") : "");
  if (window.pywebview?.api?.open_window) window.pywebview.api.open_window(title, url);   // second app window keeps this work
  else window.open(url, "_blank");
}
$("#pantoneBtn").addEventListener("click", () => openMatch("/pantone", "Pantone Match"));
$("#threadBtn").addEventListener("click", () => openMatch("/thread", "Thread Match"));
$("#addColor").addEventListener("change", (e) => editPalette((pal) => pal.push({ from: e.target.value, to: e.target.value })));
$$("input[name=palMode]").forEach((r) => r.addEventListener("change", () => {
  const max = $('input[name=palMode]:checked').value === "max";
  $("#maxColorsRow").hidden = !max;
  S.trace.palette = null;
  S.trace.max_colors = max ? +$("#maxColors").value : 0;
  refresh(true);
}));
$("#maxColors").addEventListener("input", (e) => { $("#maxColorsOut").textContent = e.target.value; });
$("#maxColors").addEventListener("change", (e) => { S.trace.palette = null; S.trace.max_colors = +e.target.value; refresh(true); });

function renderLayers(svg) {
  const ul = $("#layers"); ul.innerHTML = "";
  const groups = [...svg.children].filter((g) => g.tagName === "g" && g.getAttribute("inkscape:groupmode") === "layer");
  for (const g of groups.slice().reverse()) {        // top of the drawing first, like a layers panel
    const shapes = [...g.querySelectorAll(".shape")];
    const isGap = g.id.startsWith("gap-filler");
    const li = document.createElement("li");
    const first = shapes[0] || g.querySelector("path");
    const col = first ? (first.getAttribute("fill") !== "none" ? first.getAttribute("fill") : first.getAttribute("stroke")) : "transparent";
    const allOff = shapes.length && shapes.every((s) => S.edits.remove.includes(s.id));
    if (allOff || g.classList.contains("layer-hidden")) li.classList.add("off");
    li.innerHTML = `<span class="dot" style="background:${col}"></span><span class="name"></span><span class="count">${isGap ? "" : shapes.length || g.children.length}</span><button title="Show or hide this layer">${allOff ? "Show" : "Hide"}</button>`;
    li.querySelector(".name").textContent = g.getAttribute("inkscape:label") || g.id;
    li.addEventListener("mouseenter", () => shapes.forEach((s) => s.classList.add("selected")));
    li.addEventListener("mouseleave", () => { shapes.forEach((s) => s.classList.remove("selected")); markSelection(); });
    li.querySelector("button").addEventListener("click", () => {
      if (isGap) { $("#gapFiller").checked = false; S.output.gap_filler = false; refresh(); return; }
      if (!shapes.length) { g.classList.toggle("layer-hidden"); renderLayers(svg); toast("Edge layers are hidden in the preview only."); return; }
      pushHistory();
      const ids = shapes.map((s) => s.id);
      S.edits.remove = allOff ? S.edits.remove.filter((i) => !ids.includes(i)) : [...new Set([...S.edits.remove, ...ids])];
      refresh();
    });
    ul.appendChild(li);
  }
  const removedCount = svg.querySelectorAll("#removed-shapes .shape").length;
  if (removedCount) {
    const li = document.createElement("li"); li.classList.add("off");
    li.innerHTML = `<span class="dot"></span><span class="name">Removed shapes (not downloaded)</span><span class="count">${removedCount}</span><button>Restore</button>`;
    li.querySelector("button").addEventListener("click", () => { pushHistory(); S.edits.remove = []; refresh(); });
    ul.appendChild(li);
  }
}

// ---------------------------------------------------------------- view, zoom, pan, compare
function applyView() {
  const vp = $("#viewport");
  vp.classList.remove("view-vectors", "view-compare", "view-pixels");
  vp.classList.add("view-" + S.view);
  vp.className = vp.className.replace(/\btool-\w+/g, "") + " tool-" + S.tool;
  $("#stage").style.transform = `translate(${S.panX}px, ${S.panY}px) scale(${S.zoom})`;
  $("#zoomLabel").textContent = Math.round(S.zoom * 100) + "%";
  $("#raster").classList.toggle("pixelated", S.zoom > 2);
  const split = $("#split");
  split.hidden = S.view !== "compare";
  const vec = $("#vector");
  if (S.view === "compare" && S.result) {
    const x = S.split * vp.clientWidth;
    split.style.left = x + "px";
    const pct = Math.min(100, Math.max(0, ((x - S.panX) / S.zoom) / S.result.width * 100));
    vec.style.clipPath = `inset(0 0 0 ${pct}%)`;
  } else vec.style.clipPath = "";
}
function fitView() {
  if (!S.result) return;
  const vp = $("#viewport"), W = S.result.width, H = S.result.height;
  S.zoom = Math.min(vp.clientWidth / W, vp.clientHeight / H) * 0.92;
  S.panX = (vp.clientWidth - W * S.zoom) / 2; S.panY = (vp.clientHeight - H * S.zoom) / 2;
  applyView();
}
function zoomAt(f, cx, cy) {
  const z = Math.min(64, Math.max(0.05, S.zoom * f));
  S.panX = cx - (cx - S.panX) * (z / S.zoom); S.panY = cy - (cy - S.panY) * (z / S.zoom); S.zoom = z;
  applyView();
}
$("#zoomIn").addEventListener("click", () => { const vp = $("#viewport"); zoomAt(1.25, vp.clientWidth / 2, vp.clientHeight / 2); });
$("#zoomOut").addEventListener("click", () => { const vp = $("#viewport"); zoomAt(0.8, vp.clientWidth / 2, vp.clientHeight / 2); });
$("#zoomFit").addEventListener("click", fitView);
window.addEventListener("resize", () => applyView());
$("#viewport").addEventListener("wheel", (e) => {
  e.preventDefault();
  const r = e.currentTarget.getBoundingClientRect();
  zoomAt(Math.exp(-e.deltaY * (e.ctrlKey ? 0.01 : 0.002)), e.clientX - r.left, e.clientY - r.top);
}, { passive: false });

$$("#viewSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#viewSeg button").forEach((x) => x.classList.toggle("on", x === b)); S.view = b.dataset.view; applyView();
}));
$$("#toolSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#toolSeg button").forEach((x) => x.classList.toggle("on", x === b)); S.tool = b.dataset.tool;
  if (S.tool !== "select") { S.selected = null; markSelection(); }
  $("#editHint").hidden = S.tool === "select" || S.tool === "background";
  if (S.tool === "background") toast("Click shapes to take them out of the image, click again to put them back.");
  if (S.tool === "crop") toast("Drag a box over the part to vectorize. Click once to clear the crop.");
  applyView();
}));

// pointer: pan, split drag, crop drag, shape clicks
let drag = null;
const vp = $("#viewport");
vp.addEventListener("pointerdown", (e) => {
  const r = vp.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  if (e.target.closest("#split")) { drag = { kind: "split" }; vp.setPointerCapture(e.pointerId); return; }
  if (S.tool === "crop") { drag = { kind: "crop", x0: x, y0: y, x, y }; vp.setPointerCapture(e.pointerId); return; }
  const shape = e.target.closest(".shape");
  if ((S.tool === "select" || S.tool === "background") && shape) { onShapeClick(shape, e); return; }
  drag = { kind: "pan", x, y, px: S.panX, py: S.panY }; vp.classList.add("dragging"); vp.setPointerCapture(e.pointerId);
});
vp.addEventListener("pointermove", (e) => {
  if (!drag) return;
  const r = vp.getBoundingClientRect();
  const x = e.clientX - r.left, y = e.clientY - r.top;
  if (drag.kind === "pan") { S.panX = drag.px + x - drag.x; S.panY = drag.py + y - drag.y; applyView(); }
  else if (drag.kind === "split") { S.split = Math.min(1, Math.max(0, x / vp.clientWidth)); applyView(); }
  else if (drag.kind === "crop") { drag.x = x; drag.y = y; drawCropBox(); }
});
vp.addEventListener("pointerup", () => {
  if (drag?.kind === "crop") finishCrop();
  drag = null; vp.classList.remove("dragging");
});

function stagePoint(x, y) { return [(x - S.panX) / S.zoom, (y - S.panY) / S.zoom]; }
function drawCropBox() {
  const box = $("#cropBox");
  const [ax, ay] = stagePoint(drag.x0, drag.y0), [bx, by] = stagePoint(drag.x, drag.y);
  Object.assign(box.style, { left: Math.min(ax, bx) + "px", top: Math.min(ay, by) + "px", width: Math.abs(bx - ax) + "px", height: Math.abs(by - ay) + "px" });
  box.hidden = false;
}
async function finishCrop() {
  $("#cropBox").hidden = true;
  const [ax, ay] = stagePoint(drag.x0, drag.y0), [bx, by] = stagePoint(drag.x, drag.y);
  const W = S.result.width, H = S.result.height;
  const x0 = Math.max(0, Math.min(ax, bx)), y0 = Math.max(0, Math.min(ay, by));
  const x1 = Math.min(W, Math.max(ax, bx)), y1 = Math.min(H, Math.max(ay, by));
  if (x1 - x0 < 4 || y1 - y0 < 4) {
    if (S.trace.crop) { S.trace.crop = null; S.rasterURL = S.srcURL; $("#raster").src = S.rasterURL; await refresh(true); fitView(); toast("Crop cleared."); }
    return;
  }
  const base = S.trace.crop || { x: 0, y: 0, w: S.srcW, h: S.srcH };
  const f = base.w / W;                       // source pixels per displayed pixel
  const crop = { x: Math.round(base.x + x0 * f), y: Math.round(base.y + y0 * f), w: Math.round((x1 - x0) * f), h: Math.round((y1 - y0) * f) };
  S.trace.crop = crop;
  const img = $("#raster");
  const src = await new Promise((res) => { const i = new Image(); i.onload = () => res(i); i.src = S.srcURL; });
  const c = document.createElement("canvas"); c.width = crop.w; c.height = crop.h;
  c.getContext("2d").drawImage(src, crop.x, crop.y, crop.w, crop.h, 0, 0, crop.w, crop.h);
  S.rasterURL = c.toDataURL(); img.src = S.rasterURL;
  await refresh(true); fitView();
  toast(`Cropped to ${crop.w} × ${crop.h}. Click once with the Crop tool to clear it.`);
}

// ---------------------------------------------------------------- shape editing
function pushHistory() { S.history.push(JSON.stringify(S.edits)); if (S.history.length > 100) S.history.shift(); updateEditButtons(); }
function updateEditButtons() {
  $("#undoBtn").disabled = !S.history.length;
  $("#resetEdits").disabled = !(S.edits.remove.length || Object.keys(S.edits.recolor).length);
  const sel = S.selected && $("#vector").querySelector("#" + CSS.escape(S.selected));
  $("#selection").hidden = !sel;
  if (sel && S.selShown !== sel) {      // only when the selection changes, so a picked colour is not overwritten
    S.selShown = sel;
    $("#selLabel").textContent = `Shape ${S.selected} · ${sel.tagName}`;
    $("#selColor").value = sel.dataset.color;
  }
  if (!sel) S.selShown = null;
}
function markSelection() {
  $$("#vector .shape.selected").forEach((s) => s.classList.remove("selected"));
  if (S.selected) $("#vector").querySelector("#" + CSS.escape(S.selected))?.classList.add("selected");
}
function onShapeClick(shape, e) {
  e.stopPropagation();
  if (S.tool === "background") {
    pushHistory();
    const id = shape.id, off = S.edits.remove.includes(id);
    S.edits.remove = off ? S.edits.remove.filter((i) => i !== id) : [...S.edits.remove, id];
    shape.classList.toggle("removed", !off);
    refreshSoon(); updateEditButtons();
    return;
  }
  if (shape.classList.contains("removed")) return;
  S.selected = shape.id; markSelection(); updateEditButtons();
}
$("#selColor").addEventListener("change", (e) => {
  const sel = $("#vector").querySelector("#" + CSS.escape(S.selected)); if (!sel) return;
  const color = e.target.value;
  pushHistory();
  const targets = $("#selAll").checked ? $$("#vector .shape").filter((s) => s.dataset.color === sel.dataset.color) : [sel];
  for (const t of targets) {
    S.edits.recolor[t.id] = color;
    t.setAttribute(t.getAttribute("fill") === "none" ? "stroke" : "fill", color);
  }
  refreshSoon(); updateEditButtons();
});
$("#selDelete").addEventListener("click", () => {
  if (!S.selected) return;
  pushHistory();
  S.edits.remove = [...new Set([...S.edits.remove, S.selected])];
  $("#vector").querySelector("#" + CSS.escape(S.selected))?.classList.add("removed");
  S.selected = null; refreshSoon(); updateEditButtons();
});
$("#bgAuto").addEventListener("click", () => {
  const ids = S.result?.background_shapes || [];
  if (!ids.length) { toast("No background shapes were found along the image border."); return; }
  pushHistory();
  S.edits.remove = [...new Set([...S.edits.remove, ...ids])];
  refresh();
  toast(`Removed ${ids.length} background shape${ids.length > 1 ? "s" : ""}, including the background colour inside letters. Use the Background tool to put shapes back.`);
});
$("#undoBtn").addEventListener("click", () => { if (!S.history.length) return; S.edits = JSON.parse(S.history.pop()); refresh(); });
$("#resetEdits").addEventListener("click", () => { pushHistory(); S.edits = { remove: [], recolor: {} }; refresh(); });
document.addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) return;
  if ((e.metaKey || e.ctrlKey) && e.key === "z") { e.preventDefault(); $("#undoBtn").click(); }
  if ((e.key === "Delete" || e.key === "Backspace") && S.selected) { e.preventDefault(); $("#selDelete").click(); }
});

// ---------------------------------------------------------------- tracing and layer controls
function bindRange(sel, key, fmt = (v) => v) {
  const el = $(sel), out = el.parentElement.querySelector("output");
  el.addEventListener("input", () => (out.textContent = fmt(el.value)));
  el.addEventListener("change", () => { S.trace[key] = +el.value; refresh(true); });
}
bindRange("#detail", "detail");
bindRange("#smoothing", "smoothing");
bindRange("#corner", "corner_threshold", (v) => v + "°");
$("#tracer").addEventListener("change", (e) => { S.trace.tracer = e.target.value; refresh(true); });
$("#fitShapes").addEventListener("change", (e) => { S.output.fit_shapes = e.target.checked; refresh(true); });
$$("#stackSeg button").forEach((b) => b.addEventListener("click", () => {
  $$("#stackSeg button").forEach((x) => x.classList.toggle("on", x === b));
  S.output.shape_stacking = b.dataset.v; refresh(true);
}));
$("#groupBy").addEventListener("change", (e) => { S.output.group_by = e.target.value; refresh(); });
$("#gapFiller").addEventListener("change", (e) => { S.output.gap_filler = e.target.checked; refresh(); });
$("#gapClip").addEventListener("change", (e) => { S.output.gap_clip = e.target.checked; refresh(); });
$("#gapNSS").addEventListener("change", (e) => { S.output.gap_non_scaling = e.target.checked; refresh(); });
$("#gapWidth").addEventListener("input", (e) => (e.target.parentElement.querySelector("output").textContent = e.target.value));
$("#gapWidth").addEventListener("change", (e) => { S.output.gap_width = +e.target.value; refresh(); });

// ---------------------------------------------------------------- download
const dl = $("#dl");
const OUT_FIELDS = {
  drawStyle: "draw_style", strokeWidth: "stroke_width", strokeNSS: "stroke_non_scaling", strokeOverride: "stroke_override",
  strokeColor: "stroke_color", svgVersion: "svg_version", fixedSize: "fixed_size", sizeMode: "size_mode",
  sizeScale: "scale", sizeW: "width", sizeH: "height", sizeUnit: "unit", sizeDpi: "dpi",
};
function readDialog() {
  for (const [id, key] of Object.entries(OUT_FIELDS)) {
    const el = $("#" + id);
    S.output[key] = el.type === "checkbox" ? el.checked : el.type === "number" ? (el.value === "" ? null : +el.value) : el.value;
  }
}
function writeDialog() {
  for (const [id, key] of Object.entries(OUT_FIELDS)) {
    const el = $("#" + id), v = S.output[key];
    if (el.type === "checkbox") el.checked = !!v; else el.value = v ?? "";
  }
  updateDialogNote();
}
function updateDialogNote() {
  const fmt = $("input[name=fmt]:checked").value;
  const notes = {
    svg: "SVG keeps every group as a named layer (Illustrator, Inkscape, Figma, Affinity).",
    pdf: "PDF 1.4 does not keep groups; colours and shapes stay vector.",
    eps: "EPS does not keep groups or transparency.",
    dxf: "DXF puts each group on its own CAD layer. Y points up, units are pixels.",
    png: "PNG is a cleaned-up bitmap rendered from the vectors.",
  };
  $("#dlNote").textContent = notes[fmt];
}
$("#downloadBtn").addEventListener("click", () => { writeDialog(); dl.showModal(); });

async function svgToPng(svgText, scale) {
  const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml" }));
  try {
    const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("Could not draw the PNG.")); i.src = url; });
    const vb = (svgText.match(/viewBox="([^"]+)"/) || [])[1]?.split(/[\s,]+/).map(Number) || [0, 0, img.naturalWidth, img.naturalHeight];
    const w = Math.max(1, Math.round((img.naturalWidth || vb[2]) * scale)), h = Math.max(1, Math.round((img.naturalHeight || vb[3]) * scale));
    if (w * h > 268e6) throw new Error("That PNG would be too large; lower the PNG scale.");
    const c = document.createElement("canvas"); c.width = w; c.height = h;
    c.getContext("2d").drawImage(img, 0, 0, w, h);
    return await new Promise((res) => c.toBlob(res, "image/png"));
  } finally { URL.revokeObjectURL(url); }
}

// In the desktop app the window asks Python for a save dialog; in a browser the file goes to Downloads.
// Returns the saved path (app), "" (browser) or null (cancelled).
async function saveBlob(blob, name) {
  const api = window.pywebview?.api;
  if (api?.save_file) {
    const b64 = await new Promise((res) => { const fr = new FileReader(); fr.onload = () => res(fr.result.split(",")[1]); fr.readAsDataURL(blob); });
    return await api.save_file(name, b64);
  }
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 4000);
  return "";
}
$$("input[name=fmt]").forEach((r) => r.addEventListener("change", updateDialogNote));
$$(".presets button").forEach((b) => b.addEventListener("click", () => {
  $$(".presets button").forEach((x) => x.classList.toggle("on", x === b));
  const p = {
    edit: { draw_style: "fill_shapes", stroke_override: false },
    cut: { draw_style: "stroke_edges", stroke_override: true, stroke_color: "#000000", stroke_width: 1, stroke_non_scaling: true },
    print: { draw_style: "fill_shapes", stroke_override: false },
  }[b.dataset.preset];
  Object.assign(S.output, p);
  if (b.dataset.preset === "cut") { $("#gapFiller").checked = false; S.output.gap_filler = false; }
  if (b.dataset.preset === "print") { S.output.gap_non_scaling = false; $("#gapNSS").checked = false; S.output.gap_clip = true; $("#gapClip").checked = true; }
  if (b.dataset.preset === "edit") { S.output.gap_filler = true; $("#gapFiller").checked = true; S.output.gap_non_scaling = true; $("#gapNSS").checked = true; }
  writeDialog(); refreshSoon();
}));
// dialog changes show in the preview behind it
$("#dl form").addEventListener("change", (e) => { if (e.target.name !== "fmt") { readDialog(); refreshSoon(); } });
$("#dlGo").addEventListener("click", async () => {
  readDialog();
  const fmt = $("input[name=fmt]:checked").value;
  const btn = $("#dlGo"); btn.disabled = true; btn.textContent = "Preparing…";
  try {
    await S.pending;
    const res = await vectorize(requestOptions());
    S.result = res; render(res);
    // PNG is drawn here from the cleaned SVG, so no image library is needed on the computer
    const r = await fetch("/api/export", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ svg: res.svg, format: fmt === "png" ? "svg" : fmt, name: S.name, dxf_level: $("#dxfLevel").value }),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Export failed (${r.status})`);
    let blob = await r.blob();
    if (fmt === "png") blob = await svgToPng(await blob.text(), +$("#pngScale").value || 4);
    const where = await saveBlob(blob, `${S.name}.${fmt}`);
    if (where === null) return;               // save dialog cancelled
    dl.close();
    toast(`Saved ${S.name}.${fmt} (${(blob.size / 1024).toFixed(1)} KB) ${where ? "to " + where : "to your Downloads folder"}.`);
  } catch (e) { toast(e.message, true, 6000); }
  finally { btn.disabled = false; btn.textContent = "Download"; }
});
