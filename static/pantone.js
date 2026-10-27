// Pantone Match page
"use strict";

const $ = (s) => document.querySelector(s);
const C = window.ColorMath;
const CI = window.ColorInput.setup(() => render());   // Hex / RGB / CMYK input
let DATA = null;           // { books: [{ id, title, colors: [[name, L, a, b]] }] }
let selected = new Set(["solid-c"]);
const PRINT = ["solid-c", "solid-u"];

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
  if (q.get("books")) selected = new Set(q.get("books").split(",").filter((id) => DATA.books.some((b) => b.id === id)));
  if (!selected.size) selected = new Set(["solid-c"]);
  if (q.get("n")) $("#count").value = q.get("n");
  CI.fromURL(q);
}
function writeURL(hexes) {
  const q = [];   // built by hand so the commas stay readable in the address bar
  if (CI.urlPart()) q.push(CI.urlPart());
  else if (hexes.length) q.push("hex=" + hexes.map((h) => h.slice(1)).join(","));
  const books = [...selected].join(",");
  if (books !== "solid-c") q.push("books=" + books);
  if ($("#count").value !== "8") q.push("n=" + $("#count").value);
  history.replaceState(null, "", "/pantone" + (q.length ? "?" + q.join("&") : ""));
}

// ---------------------------------------------------------------- matching
function matches(hex, n) {
  const lab = CI.printLab(hex) || C.rgbToLab(C.hexToRgb(hex));   // CMYK: its printed Lab, not the screen colour
  const best = [];
  for (const book of DATA.books) {
    if (!selected.has(book.id)) continue;
    for (const [name, L, a, b] of book.colors) {
      const de = C.deltaE2000(lab, [L, a, b]);
      if (best.length < n || de < best[best.length - 1].de) {
        best.push({ name, book: book.title, lab: [L, a, b], de });
        best.sort((x, y) => x.de - y.de);
        if (best.length > n) best.pop();
      }
    }
  }
  return { lab, best };
}

// ---------------------------------------------------------------- rendering
const fmtLab = (l) => `L ${l[0].toFixed(1)}  a ${l[1].toFixed(1)}  b ${l[2].toFixed(1)}`;
function el(tag, cls, html) { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; }
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast(`Copied ${text}`), () => toast("Copy failed")); }

function render() {
  const { good, bad } = parseInput($("#hexInput").value);
  $("#err").hidden = !bad.length;
  if (bad.length) $("#err").textContent = `Not a hex colour: ${bad.join(", ")}. Use 3 or 6 hex digits, like #E4002B or F00.`;
  if (good.length) $("#picker").value = good[good.length - 1];
  writeURL(good);
  const box = $("#results"); box.innerHTML = "";
  if (!good.length) { box.appendChild(el("p", "pm-empty", "Type or pick a colour to see the closest Pantone colours.")); return; }
  if (!selected.size) { box.appendChild(el("p", "pm-empty", "Choose at least one colour book.")); return; }
  const n = +$("#count").value;
  for (const hex of good) {
    const { lab, best } = matches(hex, n);
    const rgb = C.hexToRgb(hex);
    const g = el("article", "pm-group");
    const yours = el("div", "pm-yours");
    yours.innerHTML = `<div class="chip" style="background:${hex}"></div>
      <div class="meta"><b>${hex.toUpperCase()}</b>
      <div class="mono">RGB ${rgb.join(", ")}</div>${CI.note(hex)}<div class="mono">${fmtLab(lab)}</div>
      <div class="mono" style="margin-top:6px">Best: ${best[0] ? "PANTONE " + best[0].name + " · ΔE " + best[0].de.toFixed(2) : "-"}</div></div>`;
    g.appendChild(yours);
    const cards = el("div", "pm-cards");
    if (best[0] && best[0].de >= 5 && selected.size < DATA.books.length)
      cards.appendChild(el("p", "pm-far", "No close match in the selected books. Try adding more books under Colour books."));
    best.forEach((m, i) => {
      const conv = C.labToRgb(m.lab), phex = C.rgbToHex(conv.rgb).toUpperCase();
      const v = C.verdict(m.de);
      const card = el("div", "pm-card" + (i === 0 ? " best" : ""));
      card.innerHTML = `<div class="pair" title="Top: your colour. Bottom: the Pantone colour."><span style="background:${hex}"></span><span style="background:${phex}"></span></div>
        <div class="body">
          <div class="name">PANTONE ${m.name}</div>
          <div class="book">${m.book}</div>
          <div class="de"><span class="tag ${v.tone}" title="${v.text}">${v.label}</span> ΔE ${m.de.toFixed(2)}</div>
          <div class="mono">${phex}${conv.inGamut ? "" : " *"} · ${fmtLab(m.lab)}</div>
          ${conv.inGamut ? "" : '<div class="gamut">* outside screen range; shown as the nearest screen colour</div>'}
          <div class="actions"><button type="button" data-copy="PANTONE ${m.name}">Copy name</button><button type="button" data-copy="${phex}">Copy hex</button></div>
        </div>`;
      cards.appendChild(card);
    });
    g.appendChild(cards);
    box.appendChild(g);
  }
}
$("#results").addEventListener("click", (e) => { const b = e.target.closest("[data-copy]"); if (b) copy(b.dataset.copy); });

function renderBooks() {
  const list = $("#books"); list.innerHTML = "";
  for (const b of DATA.books) {
    const l = el("label");
    l.innerHTML = `<input type="checkbox" value="${b.id}" ${selected.has(b.id) ? "checked" : ""}> ${b.title} <span class="n">${b.colors.length}</span>`;
    list.appendChild(l);
  }
  const names = DATA.books.filter((b) => selected.has(b.id)).map((b) => b.title.replace(/ \(.*\)$/, ""));
  $("#booksSummary").textContent = names.length === DATA.books.length ? "all books" : names.length > 2 ? `${names.length} books` : names.join(", ") || "none";
}
$("#books").addEventListener("change", (e) => {
  if (e.target.checked) selected.add(e.target.value); else selected.delete(e.target.value);
  renderBooks(); render();
});
$("#booksAll").addEventListener("click", () => { selected = new Set(DATA.books.map((b) => b.id)); renderBooks(); render(); });
$("#booksPrint").addEventListener("click", () => { selected = new Set(PRINT); renderBooks(); render(); });

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

fetch("/static/pantone-data.json").then((r) => r.json()).then((d) => {
  DATA = d;
  readURL();
  if (!$("#hexInput").value) $("#hexInput").value = "#E4002B";
  renderBooks(); render();
  $("#hexInput").focus();
  CI.init();
}).catch(() => { $("#results").innerHTML = '<p class="pm-error">Could not load the Pantone colour data (static/pantone-data.json).</p>'; });
