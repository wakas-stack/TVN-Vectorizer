// Gang sheet page: one logo repeated across a sheet, as many as fit
"use strict";

const $ = (s) => document.querySelector(s);
const UNIT_IN = { in: 1, cm: 1 / 2.54, mm: 1 / 25.4 };     // one unit, in inches
const G = { token: null, info: null, name: "logo", req: 0, removed: new Set(), layoutKey: null, cells: [], cols: 0,
            history: [], last: null, dirty: false };
const UNDO_STEPS = 50;

function toast(msg, isError = false, ms = 3800) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast" + (isError ? " error" : ""); t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}
function busy(on, text) { $("#busy").hidden = !on; if (text) $("#busyText").textContent = text; }
const num = (id) => parseFloat($(id).value) || 0;
const round = (v) => Math.round(v * 1000) / 1000;

function options() {
  return {
    sheet_w: num("#sheetW"), sheet_h: num("#sheetH"), logo_w: num("#logoW"), logo_h: num("#logoH"),
    gap: num("#gap"), margin: num("#margin"), unit: $("#unit").value,
    rotate: $("#rotate").checked, cell_boxes: $("#boxes").checked, sheet_border: $("#border").checked,
    removed: [...G.removed],
  };
}

// ---------------------------------------------------------------- the logo
async function openFile(file) {
  if (!file) return;
  busy(true, "Reading the logo…");
  try {
    const fd = new FormData(); fd.append("logo", file, file.name || "logo.png");
    const r = await fetch("/api/gang/logo", { method: "POST", body: fd });
    const j = await r.json().catch(() => ({ error: `Server error ${r.status}` }));
    if (!r.ok || j.error) throw new Error(j.error || `Server error ${r.status}`);
    if (j.token !== G.token) { G.removed.clear(); G.layoutKey = null; G.history = []; G.last = null; }
    G.token = j.token; G.info = j; G.file = file;
    G.name = (file.name || "logo").replace(/\.[^.]+$/, "");
    $("#logoThumb").src = "data:image/png;base64," + j.preview;
    $("#logoName").textContent = file.name || "Pasted logo";
    $("#logoKind").textContent = j.vector ? (j.svg ? "Vector (SVG)" : "Vector (PDF / AI)") : `Image, ${j.pixels[0]} × ${j.pixels[1]} px`;
    $("#logoCard").hidden = false;
    $("#fileInfo").textContent = file.name || "";
    if ($("#keep").checked) $("#logoH").value = round(num("#logoW") / j.aspect);
    updateFormat();
    await render();
  } catch (e) { toast(e.message, true, 7000); }
  finally { busy(false); }
}
$("#fileInput").addEventListener("change", (e) => { openFile(e.target.files[0]); e.target.value = ""; });
$("#newLogo").addEventListener("click", () => $("#fileInput").click());
["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.add("over"); }));
["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, (e) => { e.preventDefault(); $("#drop").classList.remove("over"); }));
document.addEventListener("drop", (e) => { const f = e.dataTransfer?.files?.[0]; if (f) openFile(f); });
document.addEventListener("paste", (e) => {
  const item = [...(e.clipboardData?.items || [])].find((i) => i.type.startsWith("image/"));
  if (item) openFile(item.getAsFile());
});

// ---------------------------------------------------------------- preview
async function sheetRequest(format, dpi) {
  const body = { token: G.token, options: options(), format, dpi };
  let r = await fetch("/api/gang/sheet", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (r.status === 404 && G.file) {          // the app restarted: read the logo again
    await openFile(G.file);
    body.token = G.token;
    r = await fetch("/api/gang/sheet", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  }
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `Failed (${r.status})`);
  return r;
}

async function render() {
  if (!G.token) return;
  const id = ++G.req;
  const timer = setTimeout(() => busy(true, "Filling the sheet…"), 250);
  try {
    const j = await (await sheetRequest("preview")).json();
    if (id !== G.req) return;
    // a different layout (sheet, logo size, gap...) has other places: removed logos come back
    const key = `${j.info.cols}x${j.info.rows}${j.info.turned ? "t" : ""}`;
    if (G.layoutKey && key !== G.layoutKey && G.removed.size) {
      G.removed.clear(); G.layoutKey = key;
      toast("The layout changed, so the removed logos are back.");
      return render();
    }
    G.layoutKey = key; G.cells = j.info.cells || []; G.cols = j.info.cols;
    const img = $("#preview");
    img.src = "data:image/png;base64," + j.png; img.hidden = false;
    $("#drop").hidden = true;
    const u = $("#unit").value;
    const off = j.info.total - j.info.count;
    $("#count").textContent = j.info.total
      ? `${off ? `${j.info.count} of ${j.info.total}` : j.info.count} logos · ${j.info.cols} across × ${j.info.rows} down${j.info.turned ? " · turned 90°" : ""}${off ? ` · ${off} removed` : ""}`
      : "No logo fits: make the logo smaller or the sheet larger.";
    $("#restoreAll").hidden = !off;
    $("#removeHint").hidden = !j.info.total;
    $("#download").disabled = j.info.count === 0;
    drawOverlay();
    G.last = snapshot(); G.dirty = false;          // the state an edit can go back to
    $("#undo").disabled = !G.history.length;
    $("#status").textContent = `${num("#sheetW")} × ${num("#sheetH")} ${u} sheet · logo ${num("#logoW")} × ${num("#logoH")} ${u}`;
    updateFormat(j.info);
  } catch (e) { if (id === G.req) toast(e.message, true, 6000); }
  finally { clearTimeout(timer); if (id === G.req) busy(false); }
}
let rt;
const renderSoon = () => { clearTimeout(rt); rt = setTimeout(render, 220); };

// ---------------------------------------------------------------- controls
$("#preset").addEventListener("change", (e) => {
  const m = e.target.value.match(/^([\d.]+)x([\d.]+)(in|mm|cm)$/);
  if (!m) return;
  setUnit(m[3]);
  $("#sheetW").value = m[1]; $("#sheetH").value = m[2];
  renderSoon();
});
for (const id of ["#sheetW", "#sheetH"]) $(id).addEventListener("input", () => { $("#preset").value = "custom"; renderSoon(); });
$("#logoW").addEventListener("input", () => { if ($("#keep").checked && G.info) $("#logoH").value = round(num("#logoW") / G.info.aspect); renderSoon(); });
$("#logoH").addEventListener("input", () => { if ($("#keep").checked && G.info) $("#logoW").value = round(num("#logoH") * G.info.aspect); renderSoon(); });
$("#keep").addEventListener("change", (e) => { if (e.target.checked && G.info) $("#logoH").value = round(num("#logoW") / G.info.aspect); renderSoon(); });
for (const id of ["#gap", "#margin"]) $(id).addEventListener("input", renderSoon);
for (const id of ["#rotate", "#boxes", "#border"]) $(id).addEventListener("change", render);

// changing units converts every length, so the sheet stays the same
function setUnit(u) {
  const from = setUnit.cur || "in";
  if (u === from) return;
  const f = UNIT_IN[from] / UNIT_IN[u];
  for (const id of ["#sheetW", "#sheetH", "#logoW", "#logoH", "#gap", "#margin"]) $(id).value = round(num(id) * f);
  setUnit.cur = u; $("#unit").value = u;
  document.querySelectorAll(".unit-label").forEach((s) => (s.textContent = u));
}
setUnit.cur = "in";
document.querySelectorAll(".unit-label").forEach((s) => (s.textContent = "in"));
$("#unit").addEventListener("change", (e) => { setUnit(e.target.value); $("#preset").value = "custom"; renderSoon(); });

// ---------------------------------------------------------------- download
function updateFormat(info) {
  const f = $("#format").value, dpi = +$("#dpi").value, vec = G.info?.vector, svg = G.info?.svg;
  const raster = ["png", "jpg", "tiff"].includes(f);
  $("#dpiRow").hidden = !(raster || (f === "eps" && !svg));
  const inch = UNIT_IN[$("#unit").value];
  const px = `${Math.round(num("#sheetW") * inch * dpi)} × ${Math.round(num("#sheetH") * inch * dpi)} px`;
  $("#formatHint").textContent = {
    pdf: vec ? "Vector: the logo is placed as its own vector artwork." : "The logo image is placed at its own resolution; the boxes and border are vector.",
    ai: "A PDF-based AI file: opens in Illustrator, " + (vec ? "vector like the PDF." : "with the logo image placed."),
    eps: svg ? "Vector: the logo's paths in every box." : `The sheet as a ${px} image (${dpi} dpi). macOS cannot turn PDF or image logos into PostScript paths; for a vector EPS use an SVG logo.`,
    png: `${px} at ${dpi} dpi, transparent background.`,
    jpg: `${px} at ${dpi} dpi, white background.`,
    tiff: `${px} at ${dpi} dpi, transparent background, LZW compressed.`,
  }[f];
}
$("#format").addEventListener("change", () => updateFormat());
$("#dpi").addEventListener("change", () => updateFormat());

$("#download").addEventListener("click", async () => {
  if (!G.token) return;
  const fmt = $("#format").value, dpi = +$("#dpi").value;
  const name = `${G.name}-gang-sheet.${fmt}`;
  const btn = $("#download"); btn.disabled = true; busy(true, `Making the ${fmt.toUpperCase()}…`);
  try {
    const api = window.pywebview?.api;
    if (api?.save_url) {        // the app saves it straight from the local server
      let where = await api.save_url(name, "/api/gang/sheet", { token: G.token, options: options(), format: fmt, dpi });
      if (where && where.error === "expired" && G.file) {     // the app let the logo go: read it again, then save
        await openFile(G.file);
        where = await api.save_url(name, "/api/gang/sheet", { token: G.token, options: options(), format: fmt, dpi });
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

// ---------------------------------------------------------------- removing logos
function drawOverlay() {
  const img = $("#preview"), ov = $("#overlay");
  if (img.hidden || !G.cells.length || !img.naturalWidth) { ov.hidden = true; return; }
  const r = img.getBoundingClientRect(), st = $("#stage").getBoundingClientRect();
  Object.assign(ov.style, { left: `${r.left - st.left}px`, top: `${r.top - st.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  ov.innerHTML = "";
  G.cells.forEach(([x, y, w, h], i) => {
    const b = document.createElement("button");
    const off = G.removed.has(i);
    b.type = "button"; b.className = "gs-cell" + (off ? " off" : "");
    b.title = off ? "Put this logo back" : "Remove this logo";
    Object.assign(b.style, { left: `${x * 100}%`, top: `${y * 100}%`, width: `${w * 100}%`, height: `${h * 100}%` });
    b.addEventListener("click", () => { beforeEdit(); if (off) G.removed.delete(i); else G.removed.add(i); render(); });
    ov.appendChild(b);
  });
  const rows = Math.ceil(G.cells.length / G.cols);
  for (let rr = 0; rr < rows; rr++) {
    const idx = G.cells.map((_, i) => i).filter((i) => Math.floor(i / G.cols) === rr);
    const allOff = idx.every((i) => G.removed.has(i));
    const [x, y, , h] = G.cells[idx[0]];
    const b = document.createElement("button");
    b.type = "button"; b.className = "gs-row" + (allOff ? " restore" : "");
    b.textContent = allOff ? "+" : "−";
    b.title = allOff ? `Put row ${rr + 1} back` : `Remove row ${rr + 1}`;
    Object.assign(b.style, { left: `${x * 100}%`, top: `${(y + h / 2) * 100}%` });
    b.addEventListener("click", () => { beforeEdit(); idx.forEach((i) => (allOff ? G.removed.delete(i) : G.removed.add(i))); render(); });
    ov.appendChild(b);
  }
  ov.hidden = false;
}
$("#preview").addEventListener("load", drawOverlay);
$("#restoreAll").addEventListener("click", () => { beforeEdit(); G.removed.clear(); render(); });

// ---------------------------------------------------------------- undo (Cmd+Z / Ctrl+Z)
// every edit (a logo or row taken off or put back, a sheet or logo setting) can be undone,
// up to UNDO_STEPS times; typing in one box counts as one edit
const FIELDS = ["#preset", "#sheetW", "#sheetH", "#unit", "#logoW", "#logoH", "#keep", "#gap", "#margin", "#rotate", "#boxes", "#border"];
function snapshot() {
  const f = {};
  for (const id of FIELDS) f[id] = $(id).type === "checkbox" ? $(id).checked : $(id).value;
  return { fields: f, removed: [...G.removed] };
}
function beforeEdit() {
  if (!G.token || G.dirty || !G.last) return;
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
  G.layoutKey = null;                    // the places of that layout come back with it
  G.dirty = true;
  updateFormat();
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

window.addEventListener("resize", () => { if (G.token) renderSoon(); });
updateFormat();
