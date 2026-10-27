// Patch mockup page
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const LEATHERS = [["Tan", "#a8693a"], ["Saddle", "#8a4f24"], ["Brown", "#5b3a22"], ["Dark", "#3a2617"], ["Black", "#1d1b1a"], ["Grey", "#6d6a66"], ["Natural", "#c9a27a"]];
const ROLE_LABELS = {
  embroidery: { base: "Fabric (twill)", thread: "Embroidered", hidden: "Hidden" },
  woven: { base: "Background", thread: "Woven detail", hidden: "Hidden" },
  sublimated: { base: "Background", thread: "Printed", hidden: "Hidden" },
  leather: { base: "Leather", thread: "Logo", hidden: "Hidden" },
};
const BORDERS = {
  textile: [["merrow", "Merrow (rolled edge)"], ["satin", "Satin stitch"], ["laser", "Laser-cut / heat-sealed"], ["none", "None"]],
  leather: [["seam", "Stitched seam"], ["none", "None"]],
};

const S = {
  file: null, name: "patch", token: null, info: null,
  opts: { style: "embroidery", roles: {}, recolor: {}, shape: "outline", border: "merrow", border_color: null, border_width: 0.035,
          relief: 0.7, density: 1, angle: 45, light: 135, gloss: 0.5, full_embroidery: false,
          leather_color: "#a8693a", leather_finish: "deboss", background: "transparent", shadow: true },
  req: 0, url: null,
};

function toast(msg, isError = false, ms = 3800) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

// ---------------------------------------------------------------- thread numbers
// embroidered colours can be set by Isacord 40 / Madeira Polyneon 40 / Robison-Anton Polyester 40 number (static/thread-data.json)
const CM = window.ColorMath;
const T = { books: null, chart: "isacord-40", pick: {}, src: {} };   // pick: colour id -> thread number; src: the colour of the thread you chose
const esc = (v) => String(v).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const tbook = () => T.books?.find((b) => b.id === T.chart);
const brand = () => tbook()?.title.split(" ")[0] || "";

function findThread(text) {
  const b = tbook(), q = String(text).trim().split(/\s+/)[0];
  if (!b || !q) return null;
  return b.colors.find((c) => c[0] === q) || (/^\d+$/.test(q) && b.colors.find((c) => c[0] === q.padStart(4, "0"))) || null;
}
function nearestThread(hex) {
  const b = tbook(); if (!b) return null;
  const lab = CM.rgbToLab(CM.hexToRgb(hex.toLowerCase()));
  let best = null, de = Infinity;
  for (const c of b.colors) { const d = CM.deltaE2000(lab, c[3]); if (d < de) { de = d; best = c; } }
  return { thread: best, de };
}
function usesThread(role) {
  return S.opts.style === "embroidery" && (role === "thread" || (role === "base" && S.opts.full_embroidery));
}
function setThread(id, t) {
  T.pick[id] = t[0]; T.src[id] = S.opts.recolor[id] = t[2].toLowerCase();
  renderColors(); renderSoon();
}
function fillThreadList() {
  $("#threadList").innerHTML = (tbook()?.colors || []).map((c) => `<option value="${c[0]}">${esc(c[1])}</option>`).join("");
}
$("#threadChart").addEventListener("change", (e) => {
  T.chart = e.target.value; fillThreadList();
  // threads already picked become the nearest thread of the other brand, measured from the
  // thread you chose, so switching back gives your number again
  const ids = Object.keys(T.pick);
  let far = 0;
  for (const id of ids) {
    const n = nearestThread(T.src[id] || S.opts.recolor[id]); if (n.de >= 5) far++;
    T.pick[id] = n.thread[0]; S.opts.recolor[id] = n.thread[2].toLowerCase();
  }
  if (ids.length) toast(`Changed ${ids.length} thread${ids.length > 1 ? "s" : ""} to the nearest ${tbook().title} number.`
    + (far ? ` ${far} ${far > 1 ? "have" : "has"} no close match (ΔE 5 or more), so ${far > 1 ? "they look" : "it looks"} different.` : ""), far > 0, far ? 7000 : 3800);
  renderColors(); if (ids.length) renderSoon();
});
fetch("/static/thread-data.json").then((r) => r.json()).then((d) => {
  for (const b of d.books) for (const c of b.colors) c.push(CM.rgbToLab(CM.hexToRgb(c[2].toLowerCase())));
  T.books = d.books; fillThreadList(); renderColors();
}).catch(() => { /* thread numbers are optional */ });

// ---------------------------------------------------------------- loading a logo
async function svgToPngFile(file) {
  // any SVG is drawn by the page itself, at about 2000 px on its long side
  const text = await file.text();
  const url = URL.createObjectURL(new Blob([text], { type: "image/svg+xml" }));
  try {
    const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error("This SVG could not be drawn.")); i.src = url; });
    let w = img.naturalWidth, h = img.naturalHeight;
    const vb = (text.match(/viewBox\s*=\s*"([^"]+)"/) || [])[1]?.trim().split(/[\s,]+/).map(Number);
    if ((!w || !h) && vb) { w = vb[2]; h = vb[3]; }
    if (!w || !h) { w = h = 1000; }
    const f = 2000 / Math.max(w, h);
    const c = document.createElement("canvas"); c.width = Math.round(w * f); c.height = Math.round(h * f);
    c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
    const blob = await new Promise((res) => c.toBlob(res, "image/png"));
    return new File([blob], file.name.replace(/\.svg$/i, ".png"), { type: "image/png" });
  } finally { URL.revokeObjectURL(url); }
}

async function openFile(file) {
  if (!file) return;
  const isSvg = file.type === "image/svg+xml" || /\.svg$/i.test(file.name || "");
  if (!isSvg && !/^image\/(png|jpeg|gif|bmp|webp|x-ms-bmp)$/.test(file.type) && !/\.(png|jpe?g|gif|bmp|webp)$/i.test(file.name || "")) {
    toast("Please use a PNG, JPG, WebP, GIF, BMP or SVG logo.", true); return;
  }
  busy(true, "Reading the logo…");
  try {
    S.file = isSvg ? await svgToPngFile(file) : file;
    S.name = (file.name || "logo").replace(/\.[^.]+$/, "") + "-patch";
    await analyze();
    $("#fileInfo").textContent = `${file.name || "Pasted logo"} · ${S.info.colors.filter((c) => c.kind === "colour").length} colours`;
    S.opts.roles = {}; S.opts.recolor = {}; T.pick = {}; T.src = {}; S.savedRoles = {};
    leatherRoles();
    applyDefaultShape();
    renderColors();
    await render();
  } catch (e) { toast(e.message, true, 6000); busy(false); }
}

async function analyze() {
  const fd = new FormData();
  fd.append("image", S.file, S.file.name || "logo.png");
  const r = await fetch("/api/patch/analyze", { method: "POST", body: fd });
  const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
  if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
  S.token = j.token; S.info = j;
}

$("#fileInput").addEventListener("change", (e) => openFile(e.target.files[0]));
// a logo is already being worked on: ask before another one replaces it
function askNewLogo() {
  if (!S.token) { $("#fileInput").click(); return; }
  $("#confirmNew").hidden = false;
  $("#confirmKeep").focus();
}
function closeAsk() { $("#confirmNew").hidden = true; $("#newLogo").focus(); }
$("#newLogo").addEventListener("click", askNewLogo);
$("#confirmKeep").addEventListener("click", closeAsk);
$("#confirmDiscard").addEventListener("click", () => {
  $("#confirmNew").hidden = true;
  $("#fileInput").value = "";      // the same file can be chosen again
  $("#fileInput").click();         // the current patch stays until a new logo is actually picked
});
$("#confirmNew").addEventListener("click", (e) => { if (e.target === e.currentTarget) closeAsk(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#confirmNew").hidden) closeAsk(); });
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) openFile(f); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) openFile(item.getAsFile());
});

// ---------------------------------------------------------------- rendering
function busy(on, text) {
  $("#busy").hidden = !on;
  if (text) $("#busyText").textContent = text;
}

async function fetchPng(size) {
  const body = JSON.stringify({ token: S.token, options: S.opts, size });
  let r = await fetch("/api/patch/render", { method: "POST", headers: { "Content-Type": "application/json" }, body });
  if (r.status === 404 && S.file) {           // the app restarted: read the logo again
    await analyze();
    r = await fetch("/api/patch/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: S.token, options: S.opts, size }) });
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Render failed (${r.status})`);
  return r.blob();
}

function previewSize() {
  const st = $("#stage");
  return Math.max(500, Math.min(1400, Math.round(Math.max(st.clientWidth, st.clientHeight) * (window.devicePixelRatio || 1) * 0.9)));
}

async function render() {
  if (!S.token) return;
  const id = ++S.req;
  const timer = setTimeout(() => busy(true, "Making the patch…"), 250);
  const t0 = performance.now();
  try {
    const blob = await fetchPng(previewSize());
    if (id !== S.req) return;
    if (S.url) URL.revokeObjectURL(S.url);
    S.url = URL.createObjectURL(blob);
    const img = $("#preview");
    img.src = S.url; img.hidden = false;
    $("#drop").hidden = true;
    $("#savePng").disabled = false;
    $("#savePdf").disabled = false;
    $("#status").textContent = `${labelOf(S.opts.style)} · preview ${((performance.now() - t0) / 1000).toFixed(2)} s`;
  } catch (e) { if (id === S.req) toast(e.message, true, 6000); }
  finally { clearTimeout(timer); if (id === S.req) busy(false); }
}
let rt;
const renderSoon = () => { clearTimeout(rt); rt = setTimeout(render, 140); };
const labelOf = (s) => ({ embroidery: "Embroidered", woven: "Woven", sublimated: "Dye-sublimated", leather: "Faux/Leather" })[s];

// ---------------------------------------------------------------- controls
function renderColors() {
  const ul = $("#colors"); ul.innerHTML = "";
  if (!S.info) return;
  const labels = ROLE_LABELS[S.opts.style];
  for (const c of S.info.colors) {
    const role = S.opts.roles[c.id] || S.info.roles[c.id];
    const shown = S.opts.recolor[c.id] || c.hex;
    const li = document.createElement("li");
    li.className = role === "hidden" ? "hidden" : "";
    const note = c.kind === "outline" ? "outline around the logo" : c.kind === "background" ? "background of the image" : `${(c.area * 100).toFixed(c.area < 0.01 ? 1 : 0)}% of the logo`;
    li.innerHTML = `<input type="color" value="${shown}" title="Change this colour">
      <span class="name">${shown.toUpperCase()}<small>${note}</small></span>
      <select>${Object.entries(labels).map(([v, t]) => `<option value="${v}" ${v === role ? "selected" : ""}>${t}</option>`).join("")}</select>`;
    li.querySelector("input").addEventListener("change", (e) => { S.opts.recolor[c.id] = e.target.value; delete T.pick[c.id]; delete T.src[c.id]; renderColors(); renderSoon(); });
    if (T.books && usesThread(role)) li.appendChild(threadRow(c, shown));
    li.querySelector("select").addEventListener("change", (e) => {
      if (e.target.value === "base") {        // one fabric: the previous fabric colour becomes thread
        for (const o of S.info.colors) {
          const r = S.opts.roles[o.id] || S.info.roles[o.id];
          if (o.id !== c.id && r === "base") S.opts.roles[o.id] = "thread";
        }
      }
      S.opts.roles[c.id] = e.target.value; renderColors(); updateBorderRow(); renderSoon();
    });
    ul.appendChild(li);
  }
  $("#rolesHint").textContent = {
    embroidery: "Embroidered colours are raised thread; the fabric is the twill they are stitched on. Type a thread number, or click Use for the nearest thread.",
    woven: "Every colour is woven into one flat fabric; detail colours sit very slightly higher.",
    sublimated: "Every colour is printed onto smooth fabric.",
    leather: "The logo colours are pressed, raised or engraved into the leather; the leather colour is set under Look.",
  }[S.opts.style];
}

function threadRow(c, shown) {
  const div = document.createElement("div");
  div.className = "pt-thread";
  const picked = T.pick[c.id] && findThread(T.pick[c.id]);
  const near = picked ? null : nearestThread(shown);
  div.title = picked ? `${brand()} ${picked[0]} ${picked[1]} (${picked[2]})` : `Nearest ${brand()} thread: ${near.thread[0]} ${near.thread[1]}, ΔE ${near.de.toFixed(1)}`;
  div.innerHTML = `<input type="text" list="threadList" value="${picked ? picked[0] : ""}" placeholder="No." autocomplete="off" spellcheck="false" aria-label="${esc(tbook().title)} thread number">
    <span class="tn">${picked ? `<b>${brand()} ${picked[0]}</b> ${esc(picked[1])}`
      : `Nearest <b>${near.thread[0]}</b> ΔE ${near.de.toFixed(1)} · ${esc(near.thread[1])}`}</span>
    ${picked ? "" : '<button type="button" title="Colour it like this thread">Use</button>'}`;
  const input = div.querySelector("input");
  input.addEventListener("change", () => {
    if (!input.value.trim()) { delete T.pick[c.id]; delete T.src[c.id]; renderColors(); return; }
    const t = findThread(input.value);
    if (!t) { input.classList.add("bad"); toast(`No thread ${input.value.trim()} in ${tbook().title}.`, true); return; }
    setThread(c.id, t);
  });
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") input.blur(); });
  div.querySelector("button")?.addEventListener("click", () => setThread(c.id, near.thread));
  return div;
}

// Faux/Leather shows the logo as one piece, engraved or pressed: every logo colour becomes "Logo"
// (the roles chosen for the other patch types come back when you leave it)
function leatherRoles() {
  if (S.opts.style !== "leather" || !S.info) return;
  // the background's colour inside letters (the holes of B, O, D) stays open
  const bg = new Set(S.info.colors.filter((c) => c.kind === "background").map((c) => c.hex.toLowerCase()));
  for (const c of S.info.colors) if (c.kind === "colour") S.opts.roles[c.id] = bg.has(c.hex.toLowerCase()) ? "hidden" : "thread";
}

function setStyle(style) {
  const was = S.opts.style;
  S.opts.style = style;
  if (style === "leather" && was !== "leather") { S.savedRoles = { ...S.opts.roles }; leatherRoles(); }
  else if (style !== "leather" && was === "leather" && S.savedRoles) { S.opts.roles = S.savedRoles; S.savedRoles = null; }
  $$("#styles button").forEach((b) => b.classList.toggle("on", b.dataset.style === style));
  const leather = style === "leather";
  const list = leather ? BORDERS.leather : BORDERS.textile;
  const keep = list.some(([v]) => v === S.opts.border);
  if (!keep) S.opts.border = list[0][0];
  $("#border").innerHTML = list.map(([v, t]) => `<option value="${v}" ${v === S.opts.border ? "selected" : ""}>${t}</option>`).join("");
  $("#leatherBox").hidden = !leather;
  $("#savePdf").hidden = !leather;          // the production PDF is for leather patches
  if (leather && !SHEETS.picked && SHEETS.list.length) { SHEETS.picked = true; setSheet(SHEETS.list.find((s) => s.texture)?.id); }
  $("#angleRow").hidden = style !== "embroidery";
  $("#fullRow").hidden = style !== "embroidery";
  $("#densityRow").hidden = leather;
  $("#threadChartRow").hidden = style !== "embroidery";
  $("#borderAutoText").textContent = leather ? "Cream thread" : "Same as fabric";
  if ($("#borderAuto").checked) $("#borderColor").value = leather ? "#efe3c8" : "#000000";
  // leather patches are usually rounded rectangles; only while you have not picked a shape yourself
  if (!setStyle.touchedShape) { S.opts.shape = defaultShape(); $("#shape").value = S.opts.shape; }
  updateBorderRow();
  renderColors();
}
// a one-colour logo is shown as the logo only; leather patches are usually rounded rectangles
function defaultShape() {
  if (S.info?.suggested_shape === "logo") return "logo";
  return S.opts.style === "leather" ? "rounded" : "outline";
}
function updateBorderRow() {
  const logoOnly = S.opts.shape === "logo";
  const none = logoOnly || S.opts.border === "none";
  $("#borderRow").hidden = logoOnly;
  $("#logoScaleRow").hidden = logoOnly;
  // logo only: an optional filled outline around it (leather: the leather piece itself)
  const filled = logoOnly && S.opts.outline === "filled";
  $("#outlineRow").hidden = !logoOnly;
  $("#outlineWidthRow").hidden = !filled;
  $("#outlineColorRow").hidden = !filled || S.opts.style === "leather";
  $("#borderColorRow").hidden = none || S.opts.border === "laser";
  const seam = S.opts.style === "leather" && !none;      // leather seam: stitch style and thickness
  $("#seamRow").hidden = !seam;
  $("#seamWidthRow").hidden = !seam;
  $("#borderWidth").closest("label").hidden = none || S.opts.border === "laser";
  // fabric colour only matters when the patch has a backing and no logo colour is the fabric
  const hasBase = S.info && S.info.colors.some((c) => (S.opts.roles[c.id] || S.info.roles[c.id]) === "base");
  $("#fabricRow").hidden = logoOnly || !S.info || hasBase;
}
function applyDefaultShape() {
  setStyle.touchedShape = false;
  S.opts.shape = defaultShape(); $("#shape").value = S.opts.shape;
  updateBorderRow();
}

$$("#styles button").forEach((b) => b.addEventListener("click", () => { setStyle(b.dataset.style); render(); }));
$("#shape").addEventListener("change", (e) => { S.opts.shape = e.target.value; setStyle.touchedShape = true; updateBorderRow(); render(); });
$("#fabricAuto").addEventListener("change", (e) => {
  $("#fabricColor").disabled = e.target.checked;
  S.opts.fabric_color = e.target.checked ? null : $("#fabricColor").value; render();
});
$("#fabricColor").addEventListener("change", (e) => { S.opts.fabric_color = e.target.value; render(); });
$("#border").addEventListener("change", (e) => { S.opts.border = e.target.value; updateBorderRow(); render(); });
$("#borderAuto").addEventListener("change", (e) => {
  S.opts.border_color = e.target.checked ? null : $("#borderColor").value; render();
});
// picking a colour switches the automatic colour off
$("#borderColor").addEventListener("input", (e) => { $("#borderAuto").checked = false; S.opts.border_color = e.target.value; renderSoon(); });
$("#seamStyle").addEventListener("change", (e) => { S.opts.seam_style = e.target.value; render(); });

function bindSlider(id, key, fmt, scale = 1) {
  const el = $("#" + id), out = el.parentElement.querySelector("output");
  el.addEventListener("input", () => { out.textContent = fmt(+el.value); S.opts[key] = +el.value * scale; renderSoon(); });
}
bindSlider("borderWidth", "border_width", (v) => v + "%", 0.01);
bindSlider("logoScale", "logo_scale", (v) => v + "%", 0.01);
bindSlider("outlineWidth", "outline_width", (v) => v + "%", 0.01);
$("#outline").addEventListener("change", (e) => { S.opts.outline = e.target.value; updateBorderRow(); render(); });
$("#outlineAuto").addEventListener("change", (e) => { S.opts.outline_color = e.target.checked ? null : $("#outlineColor").value; render(); });
$("#outlineColor").addEventListener("input", (e) => { $("#outlineAuto").checked = false; S.opts.outline_color = e.target.value; renderSoon(); });
bindSlider("seamWidth", "seam_width", (v) => v.toFixed(1) + "×", 0.006);
bindSlider("relief", "relief", (v) => Math.round(v * 100) + "%");
bindSlider("density", "density", (v) => v.toFixed(1) + "×");
bindSlider("angle", "angle", (v) => v + "°");
bindSlider("light", "light", (v) => v + "°");
bindSlider("gloss", "gloss", (v) => Math.round(v * 100) + "%");
$("#fullEmb").addEventListener("change", (e) => { S.opts.full_embroidery = e.target.checked; renderColors(); render(); });
$("#finish").addEventListener("change", (e) => { S.opts.leather_finish = e.target.value; render(); });
$("#shadow").addEventListener("change", (e) => { S.opts.shadow = e.target.checked; render(); });
$("#bgMode").addEventListener("change", (e) => {
  const v = e.target.value;
  $("#bgColor").hidden = v !== "custom";
  S.opts.background = v === "custom" ? $("#bgColor").value : v;
  $("#stage").classList.toggle("solid", v !== "transparent");
  render();
});
$("#bgColor").addEventListener("change", (e) => { S.opts.background = e.target.value; render(); });

// ---------------------------------------------------------------- leatherette sheets
// Heritage Collection leatherette (static/leatherette/catalog.json, made by make_leatherette.py):
// a photo texture, and the core colour a laser engraving uncovers
const SHEETS = { list: [], picked: false };
function setSheet(id) {
  const sh = SHEETS.list.find((x) => x.id === id);
  $("#leatherette").value = sh ? sh.id : "";
  $("#sheetChip").style.backgroundImage = sh?.texture ? `url(/static/leatherette/${sh.texture}.jpg)` : "";
  $("#sheetChip").style.backgroundColor = sh ? sh.color : S.opts.leather_color;
  $("#sheetHint").hidden = !sh;
  if (sh) $("#sheetHint").textContent = `Laser engraving uncovers the ${sh.core.toLowerCase()} core.` + (sh.texture ? "" : " (No blank photo for this colour: drawn in its colour.)");
  $("#leatherColorRow").hidden = !!sh;
  S.opts.leather_texture = sh?.texture || null;
  S.opts.engrave_color = sh ? sh.core_hex : null;
  if (sh) {
    S.opts.leather_color = sh.color;
    S.opts.leather_finish = "engrave"; $("#finish").value = "engrave";   // these sheets are made for laser engraving
  }
}
$("#leatherette").addEventListener("change", (e) => { SHEETS.picked = true; setSheet(e.target.value); render(); });
fetch("/static/leatherette/catalog.json").then((r) => r.json()).then((d) => {
  SHEETS.list = d.sheets;
  const g = document.createElement("optgroup"); g.label = "Heritage Leatherette (Lone Star Adhesive)";
  g.innerHTML = d.sheets.map((s) => `<option value="${s.id}">${s.name}</option>`).join("");
  $("#leatherette").appendChild(g);
  if (S.opts.style === "leather" && !SHEETS.picked) { SHEETS.picked = true; setSheet(d.sheets.find((s) => s.texture)?.id); render(); }
}).catch(() => { /* drawn leather only */ });

const lbox = $("#leathers");
for (const [name, hex] of LEATHERS) {
  const b = document.createElement("button");
  b.type = "button"; b.title = name; b.style.background = hex;
  b.classList.toggle("on", hex === S.opts.leather_color);
  b.addEventListener("click", () => { S.opts.leather_color = hex; $("#leatherColor").value = hex; $$("#leathers button").forEach((x) => x.classList.toggle("on", x === b)); render(); });
  lbox.appendChild(b);
}
$("#leatherColor").addEventListener("change", (e) => { S.opts.leather_color = e.target.value; $$("#leathers button").forEach((x) => x.classList.remove("on")); render(); });

// ---------------------------------------------------------------- download
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
$("#savePng").addEventListener("click", async () => {
  const size = +$("#exportSize").value;
  const btn = $("#savePng"); btn.disabled = true; busy(true, `Making a ${size} px PNG…`);
  try {
    const blob = await fetchPng(size);
    const name = `${S.name}-${S.opts.style}.png`;
    const where = await saveBlob(blob, name);
    if (where !== null) toast(`Saved ${name} (${(blob.size / 1024 / 1024).toFixed(1)} MB) ${where ? "to " + where : "to your Downloads folder"}.`);
  } catch (e) { toast(e.message, true, 6000); }
  finally { btn.disabled = false; busy(false); }
});

// Faux/Leather: layered vector PDF (white shape with a thin outline, black logo, stitch lines)
async function fetchPdf() {
  const send = () => fetch("/api/patch/pdf", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ token: S.token, options: S.opts }) });
  let r = await send();
  if (r.status === 404 && S.file) { await analyze(); r = await send(); }   // the app restarted: read the logo again
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `PDF failed (${r.status})`);
  return r.blob();
}
$("#savePdf").addEventListener("click", async () => {
  const btn = $("#savePdf"); btn.disabled = true; busy(true, "Making the PDF…");
  try {
    const blob = await fetchPdf();
    const name = `${S.name}-leather.pdf`;
    const where = await saveBlob(blob, name);
    if (where !== null) toast(`Saved ${name} ${where ? "to " + where : "to your Downloads folder"}: layers Shape, Logo and Stitch lines.`);
  } catch (e) { toast(e.message, true, 6000); }
  finally { btn.disabled = false; busy(false); }
});

window.addEventListener("resize", () => { if (S.token) renderSoon(); });

// ---------------------------------------------------------------- start
setStyle("embroidery");
const token = new URLSearchParams(location.search).get("token");
if (token) {
  fetch("/api/patch/info?token=" + encodeURIComponent(token)).then((r) => r.ok ? r.json() : Promise.reject())
    .then((j) => { S.token = j.token; S.info = j; $("#fileInfo").textContent = "Logo from the Vectorizer"; leatherRoles(); applyDefaultShape(); renderColors(); render(); })
    .catch(() => toast("Choose the logo again to make a patch."));
}
