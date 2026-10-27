// Thread Match page: nearest Isacord 40 / Madeira Polyneon 40 threads for hex colours
"use strict";

const $ = (s) => document.querySelector(s);
const C = window.ColorMath;
const CI = window.ColorInput.setup(() => render());   // Hex / RGB / CMYK input
let DATA = null;           // { books: [{ id, title, colors: [[number, name, hex]] }] }, colours get a .lab
let selected = new Set();
const DEFAULT_BOOKS = () => DATA.books.map((b) => b.id).join(",");

function toast(msg, ms = 2200) {
  const t = $("#toast"); t.textContent = msg; t.className = "toast"; t.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (t.hidden = true), ms);
}

// ---------------------------------------------------------------- input
function parseInput(text) {
  const parts = text.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
  const good = [], bad = [];
  for (const p of parts) { const h = C.parseHex(p); if (h) { if (!good.includes(h)) good.push(h); } else bad.push(p); }
  return { good, bad };
}

function readURL() {
  const q = new URLSearchParams(location.search);
  if (q.get("hex")) $("#hexInput").value = q.get("hex").split(",").map((h) => "#" + h.replace(/^#/, "").toUpperCase()).join(", ");
  if (q.get("charts")) selected = new Set(q.get("charts").split(",").filter((id) => DATA.books.some((b) => b.id === id)));
  if (!selected.size) selected = new Set(DATA.books.map((b) => b.id));
  if (q.get("n")) $("#count").value = q.get("n");
  if (q.get("pms")) $("#pmsInput").value = q.get("pms");
  CI.fromURL(q);
}
function writeURL(hexes) {
  const q = [];   // built by hand so the commas stay readable in the address bar
  if (CI.urlPart()) q.push(CI.urlPart());
  else if (hexes.length) q.push("hex=" + hexes.map((h) => h.slice(1)).join(","));
  const books = DATA.books.filter((b) => selected.has(b.id)).map((b) => b.id).join(",");
  if (books !== DEFAULT_BOOKS()) q.push("charts=" + books);
  if ($("#count").value !== "8") q.push("n=" + $("#count").value);
  if ($("#pmsInput").value.trim()) q.push("pms=" + encodeURIComponent($("#pmsInput").value.trim()));
  history.replaceState(null, "", "/thread" + (q.length ? "?" + q.join("&") : ""));
}

// ---------------------------------------------------------------- matching
function nearest(lab, books, n) {
  const best = [];
  for (const book of books) {
    for (const [num, name, hex, tlab] of book.colors) {
      const de = C.deltaE2000(lab, tlab);
      if (best.length < n || de < best[best.length - 1].de) {
        best.push({ num, name, hex, book: book.title, de });
        best.sort((x, y) => x.de - y.de);
        if (best.length > n) best.pop();
      }
    }
  }
  return best;
}

// ---------------------------------------------------------------- rendering
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast(`Copied ${text}`), () => toast("Copy failed")); }
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function render() {
  const { good, bad } = parseInput($("#hexInput").value);
  $("#err").hidden = !bad.length;
  if (bad.length) $("#err").textContent = `Not a hex colour: ${bad.join(", ")}. Use 3 or 6 hex digits, like #0E6ACE or F00.`;
  if (good.length) $("#picker").value = good[good.length - 1];
  writeURL(good);
  const box = $("#results"); box.innerHTML = "";
  if (!good.length) { box.appendChild(el("p", "pm-empty", "Type or pick a colour to see the closest threads.")); return; }
  const books = DATA.books.filter((b) => selected.has(b.id));
  if (!books.length) { box.appendChild(el("p", "pm-empty", "Choose at least one thread chart.")); return; }
  const n = +$("#count").value;
  for (const hex of good) {
    const lab = C.rgbToLab(C.hexToRgb(hex)), rgb = C.hexToRgb(hex);
    const best = nearest(lab, books, n);
    const g = el("article", "pm-group");
    // the closest thread in each chart, so one brand's number can be swapped for the other's
    const perChart = books.map((b) => {
      const m = nearest(lab, [b], 1)[0];
      return `<div class="th-best"><span class="sw" style="background:${m.hex}"></span><span><b>${esc(b.title.split(" ")[0])} ${m.num}</b> ${esc(m.name)}<br><span class="mono">ΔE ${m.de.toFixed(2)}</span></span></div>`;
    }).join("");
    g.appendChild(el("div", "pm-yours", `<div class="chip" style="background:${hex}"></div>
      <div class="meta"><b>${hex.toUpperCase()}</b>
      <div class="mono">RGB ${rgb.join(", ")}</div>${CI.note(hex)}
      <div class="th-bests">${perChart}</div></div>`));
    const cards = el("div", "pm-cards");
    if (best[0] && best[0].de >= 5)
      cards.appendChild(el("p", "pm-far", "No close thread in the selected charts" + (books.length < DATA.books.length ? ". Try adding the other chart." : "; the nearest are shown.")));
    best.forEach((m, i) => {
      const v = C.verdict(m.de);
      const label = `${m.book.split(" ")[0]} ${m.num}`;
      cards.appendChild(el("div", "pm-card" + (i === 0 ? " best" : ""), `<div class="pair" title="Top: your colour. Bottom: the thread."><span style="background:${hex}"></span><span style="background:${m.hex}"></span></div>
        <div class="body">
          <div class="name">${m.num} <span class="th-name">${esc(m.name)}</span></div>
          <div class="book">${esc(m.book)}</div>
          <div class="de"><span class="tag ${v.tone}" title="${v.text}">${v.label}</span> ΔE ${m.de.toFixed(2)}</div>
          <div class="mono">${m.hex}</div>
          <div class="actions"><button type="button" data-copy="${esc(label + " " + m.name)}">Copy thread</button><button type="button" data-copy="${m.hex}">Copy hex</button></div>
        </div>`));
    });
    g.appendChild(cards);
    box.appendChild(g);
  }
}
$("#results").addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) copy(b.dataset.copy); });

function renderBooks() {
  const list = $("#books"); list.innerHTML = "";
  for (const b of DATA.books) {
    const l = el("label", "th-book");
    l.innerHTML = `<input type="checkbox" value="${b.id}" ${selected.has(b.id) ? "checked" : ""}> ${esc(b.title)} <span class="n">${b.colors.length} colours</span>`;
    list.appendChild(l);
  }
}
$("#books").addEventListener("change", (e) => {
  if (e.target.checked) selected.add(e.target.value); else selected.delete(e.target.value);
  render();
});

let timer;
// a one-line field drops line breaks from pasted text, which would glue codes together
$("#hexInput").addEventListener("paste", (e) => {
  const text = e.clipboardData?.getData("text");
  if (!text || !/[\r\n]/.test(text)) return;
  e.preventDefault();
  const f = e.target, ins = text.split(/[\r\n]+/).map((s) => s.trim()).filter(Boolean).join(", ");
  f.setRangeText(ins, f.selectionStart, f.selectionEnd, "end");
  render();
});
$("#hexInput").addEventListener("input", () => { clearTimeout(timer); timer = setTimeout(render, 120); });
$("#picker").addEventListener("input", (e) => { $("#hexInput").value = e.target.value.toUpperCase(); render(); });
$("#count").addEventListener("change", render);
if ("EyeDropper" in window) {
  $("#eyedrop").hidden = false;
  $("#eyedrop").addEventListener("click", async () => {
    try { const r = await new window.EyeDropper().open(); $("#hexInput").value = r.sRGBHex.toUpperCase(); render(); } catch (_) { /* cancelled */ }
  });
}

// ---------------------------------------------------------------- PMS -> Robison-Anton
const RA = "robison-anton-polyester";
let PANTONE = null;        // Solid Coated, loaded only when a PMS is not on the R-A chart
// "PMS 101", "101c", "Pantone Cool Gray 5 C", "116 C 2X" -> "101C", "COOLGRAY5C", "116C2X"
function pmsKey(s) {
  let k = s.toUpperCase().replace(/\b(PANTONE|PMS)\b/g, "").replace(/[^A-Z0-9]/g, "");
  if (k.endsWith("2X") && !k.endsWith("C2X")) k = k.slice(0, -2) + "C2X";
  else if (k && !/[CU]$|C2X$/.test(k)) k += "C";
  return k;
}

function pmsRender() {
  const box = $("#pmsResults"), text = $("#pmsInput").value.trim();
  box.innerHTML = "";
  writeURL(parseInput($("#hexInput").value).good);
  if (!text) return;
  const book = DATA.books.find((b) => b.id === RA), key = pmsKey(text);
  const byNum = new Map(book.colors.map((c) => [c[0], c]));
  const rows = book.pms.filter(([p]) => pmsKey(p) === key);
  const g = el("article", "pm-group");
  const card = (c, pmsLab, how) => {
    const from = book.colorFromPms[c[0]];       // no swatch: shown in its Pantone's colour, so no ΔE to show
    const hex = c[2], de = pmsLab && !from ? C.deltaE2000(pmsLab, c[3]) : null, label = `R-A ${c[0]} ${c[1]}`;
    return el("div", "pm-card", `<div class="pair"><span style="background:${hex}"></span><span style="background:${hex}"></span></div>
      <div class="body">
        <div class="name">${c[0]} <span class="th-name">${esc(c[1])}</span></div>
        <div class="book">${esc(book.title)}${how ? " · " + how : ""}</div>
        ${de != null ? `<div class="de"><span class="tag ${C.verdict(de).tone}" title="${C.verdict(de).text}">${C.verdict(de).label}</span> ΔE ${de.toFixed(2)} on screen</div>` : ""}
        <div class="mono">${hex}${from ? ` · colour of PMS ${esc(from)}` : ""}</div>
        <div class="actions"><button type="button" data-copy="${esc(label)}">Copy thread</button><button type="button" data-copy="${hex}">Copy hex</button></div>
      </div>`);
  };
  const head = (name, hex) => el("div", "pm-yours", `<div class="chip${hex ? "" : " nosw"}" style="${hex ? "background:" + hex : ""}"></div>
    <div class="meta"><b>${esc(name)}</b>${hex ? `<div class="mono">${hex}</div>` : '<div class="mono">no colour sample</div>'}</div>`);
  if (rows.length) {
    const [p, , phex] = rows[0];
    const plab = phex ? C.rgbToLab(C.hexToRgb(phex.toLowerCase())) : null;
    g.appendChild(head("PMS " + p, phex));
    const cards = el("div", "pm-cards");
    cards.appendChild(el("p", "pm-note", `${rows.length === 1 ? "The" : rows.length} Robison-Anton thread${rows.length === 1 ? "" : "s"} matched to PMS ${esc(p)} on the chart:`));
    for (const [, num] of rows) {
      const c = byNum.get(num);
      if (c) cards.appendChild(card(c, plab, "chart match"));
      else cards.appendChild(el("div", "pm-card", `<div class="pair nosw"></div><div class="body"><div class="name">${num}</div><div class="book">${esc(book.title)} · chart match</div><div class="mono">no colour sample</div><div class="actions"><button type="button" data-copy="R-A ${num}">Copy thread</button></div></div>`));
    }
    g.appendChild(cards); box.appendChild(g);
    return;
  }
  // not on the chart: the nearest threads by colour, if the PMS is a Pantone Solid Coated colour
  const load = PANTONE ? Promise.resolve(PANTONE) : fetch("/static/pantone-data.json").then((r) => r.json()).then((d) => (PANTONE = d.books.find((b) => b.id === "solid-c").colors));
  load.then((solid) => {
    if ($("#pmsInput").value.trim() !== text) return;          // typed on meanwhile
    const hit = solid.find(([n]) => pmsKey(n) === key);
    if (!hit) { box.innerHTML = `<p class="pm-empty">PMS “${esc(text)}” is not on the Robison-Anton chart or in Pantone Solid Coated. Try a number like 286 C.</p>`; return; }
    const lab = hit.slice(1, 4), hex = C.rgbToHex(C.labToRgb(lab).rgb).toUpperCase();
    g.appendChild(head("PMS " + hit[0], hex));
    const cards = el("div", "pm-cards");
    cards.appendChild(el("p", "pm-note", `PMS ${esc(hit[0])} is not on the Robison-Anton chart. The nearest threads by screen colour:`));
    for (const m of nearest(lab, [book], 4)) cards.appendChild(card(byNum.get(m.num), lab, "nearest by colour"));
    g.appendChild(cards); box.appendChild(g);
  }).catch(() => { box.innerHTML = '<p class="pm-error">Could not load the Pantone data (static/pantone-data.json).</p>'; });
}
$("#pmsResults").addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) copy(b.dataset.copy); });
let pmsTimer;
$("#pmsInput").addEventListener("input", () => { clearTimeout(pmsTimer); pmsTimer = setTimeout(pmsRender, 150); listShow(); });

// the PMS numbers on the chart, as a grid of five across under the box, filtered as you type
let PMS_LIST = [], listAt = -1;
const COLS = 5;
function listItems() { return [...$("#pmsList").querySelectorAll("button")]; }
function listShow() {
  const list = $("#pmsList"), q = pmsKey($("#pmsInput").value).replace(/C$/, "");
  const starts = PMS_LIST.filter(([p]) => pmsKey(p).startsWith(q));          // "28" lists 282 C before 128 C
  const hits = starts.concat(PMS_LIST.filter(([p]) => !pmsKey(p).startsWith(q) && pmsKey(p).includes(q)));
  list.innerHTML = hits.length
    ? hits.map(([p, hex]) => `<button type="button" role="option" data-pms="${esc(p)}"><span class="sw" style="background:${hex}"></span>${esc(p)}</button>`).join("")
    : '<p class="none">No PMS on the chart matches that. Press Enter for the nearest threads by colour.</p>';
  list.hidden = false; listAt = -1;
  $("#pmsInput").setAttribute("aria-expanded", "true");
}
function listHide() { $("#pmsList").hidden = true; listAt = -1; $("#pmsInput").setAttribute("aria-expanded", "false"); }
function listPick(p) { $("#pmsInput").value = p; listHide(); clearTimeout(pmsTimer); pmsRender(); }
function listMove(to) {
  const items = listItems(); if (!items.length) return;
  listAt = Math.max(0, Math.min(items.length - 1, to));
  items.forEach((b, i) => b.classList.toggle("on", i === listAt));
  items[listAt].scrollIntoView({ block: "nearest" });
}
$("#pmsInput").addEventListener("focus", listShow);
$("#pmsInput").addEventListener("click", listShow);
$("#pmsInput").addEventListener("keydown", (e) => {
  const open = !$("#pmsList").hidden;
  if (e.key === "Escape") { listHide(); return; }
  if (e.key === "Enter") { e.preventDefault(); if (open && listAt >= 0) listPick(listItems()[listAt].dataset.pms); else { listHide(); clearTimeout(pmsTimer); pmsRender(); } return; }
  const cols = getComputedStyle($("#pmsList")).gridTemplateColumns.split(" ").length || COLS;   // 5, or 3 on a phone
  const step = { ArrowDown: cols, ArrowUp: -cols, ArrowRight: 1, ArrowLeft: -1 }[e.key];
  if (!step || (step === 1 || step === -1) && listAt < 0) return;     // left/right move the caret until a number is chosen
  e.preventDefault();
  if (!open) listShow();
  listMove(listAt < 0 ? 0 : listAt + step);
});
$("#pmsList").addEventListener("mousedown", (e) => e.preventDefault());   // keep the focus in the box
$("#pmsList").addEventListener("click", (e) => { const b = e.target.closest("[data-pms]"); if (b) listPick(b.dataset.pms); });
$("#pmsInput").addEventListener("blur", () => setTimeout(listHide, 100));

fetch("/static/thread-data.json").then((r) => r.json()).then((d) => {
  for (const b of d.books) for (const c of b.colors) c.push(C.rgbToLab(C.hexToRgb(c[2].toLowerCase())));
  DATA = d;
  const ra = d.books.find((b) => b.id === RA);
  // one entry per PMS, coloured by the PMS (or its thread when the Pantone book lacks it)
  const seen = new Map();
  for (const [p, num, hex] of ra.pms) if (!seen.has(p)) seen.set(p, hex || ra.colors.find((c) => c[0] === num)?.[2] || "transparent");
  PMS_LIST = [...seen];
  readURL();
  if (!$("#hexInput").value) $("#hexInput").value = "#0E6ACE";
  renderBooks(); render(); pmsRender();
  $("#hexInput").focus();
  CI.init();
}).catch(() => { $("#results").innerHTML = '<p class="pm-error">Could not load the thread colour data (static/thread-data.json).</p>'; });
