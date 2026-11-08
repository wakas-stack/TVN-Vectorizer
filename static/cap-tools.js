// DST Maker: the editor's frame and its drawing tools. The tools run along the bottom: Select (S), Pan
// (space or H), Measure (M), Open shape (1), Closed shape (2), Satin blocks (3), Pen (4, freehand),
// Circle (5), Rectangle (6), more shapes, Text (T), Click to Stitch (7), Auto Digitize (8), the
// stitch player and Realistic view (V), Zoom (Z). On the right a rail of tabs: Objects (the sewing
// order), Lettering, Threads, Cap (size and stitch settings), Visibility and Info. A box of
// settings floats top left (what is selected, or what is drawn or clicked next: cap-objects.js); a
// bar over the selection holds its tools; zoom and undo sit bottom left.
//   Open and closed shapes: a click places a straight point, a right-click or a double-click a
//   curved one (the curve runs smoothly through it), Enter finishes; a closed shape is filled, an
//   open one sewn as a run along it unless the settings box says otherwise. Satin blocks: click a
//   point on one side of the column, then its partner on the other side, and on along the column;
//   Enter finishes; it is sewn as satin from rail to rail (digitize.rail_satin). Pen: draw freehand;
//   let go near where it began for a filled shape, else it is a line.
//   Visibility: realistic view or plain stitch lines; jumps, trims, tie-ins and tie-offs, needle
//   points, a 10 mm grid, and snapping drawn points to a 1 mm grid.
"use strict";

C.penMode = "open"; C.plain = false; C.speed = 1; C.tab = "objects";
const T2 = { meas: null, measDrag: false, sb: null, free: null, space: null };

// ---------------------------------------------------------------- the side panel's tabs
function showTab(t) {
  for (const b of document.querySelectorAll("#rail [data-tab]")) b.setAttribute("aria-pressed", b.dataset.tab === t);
  for (const p of document.querySelectorAll("#panel [data-pane]")) p.hidden = p.dataset.pane !== t;
  $("#panel").classList.add("open");
  C.tab = t;
  if (t === "lettering") { if ($("#textMenu").hidden) openTextMenu(); }
  else if (!$("#textMenu").hidden) { $("#textMenu").hidden = true; updateTools(); }
}
$("#letterPane").appendChild($("#textMenu"));        // the lettering lives in its tab
for (const b of document.querySelectorAll("#rail [data-tab]")) b.addEventListener("click", () => {
  if (C.tab === b.dataset.tab && window.innerWidth <= 900) { $("#panel").classList.toggle("open"); return; }
  showTab(b.dataset.tab);
});
$("#toolText").addEventListener("click", () => showTab($("#textMenu").hidden ? "objects" : "lettering"));

// ---------------------------------------------------------------- the menus: above the tools, under the selection bar
const MENU_ANCHOR = { drawMenu: "#toolShapes", penMenu: () => (C.penMode === "closed" ? "#toolClosed" : "#toolPen"), cornerMenu: "#toolCorners",
                      pathMenu: "#toolPathfinder", alignMenu: "#toolAlign", arrangeMenu: "#toolArrange" };
function placeMenu(m) {
  const a = MENU_ANCHOR[m.id], el = a && $(typeof a === "function" ? a() : a);
  if (!el || m.hidden) return;
  const r = el.getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  const up = r.top > window.innerHeight / 2;
  const top = up ? r.top - h - 10 : r.bottom + 10;
  m.style.left = `${Math.max(8, Math.min(window.innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
  m.style.top = `${Math.max(8, Math.min(window.innerHeight - h - 8, top))}px`;
}
const menuWatch = new MutationObserver((ms) => { for (const mu of ms) if (!mu.target.hidden) placeMenu(mu.target); });
for (const id of Object.keys(MENU_ANCHOR)) menuWatch.observe($("#" + id), { attributes: true, attributeFilter: ["hidden"] });

// ---------------------------------------------------------------- the tools
const canEdit = () => !!(C.digitized || (isDst() && C.st));
function toolsSync() {
  $("#tools").hidden = !(C.token || (isDst() && C.st));
  $("#zoomBox").hidden = !canEdit();
  const drawing = ["toolHand", "toolMeasure", "toolPen", "toolClosed", "toolSatin", "toolFree", "toolCircle", "toolRect", "toolShapes",
                   "toolText", "toolZoom", "toolPlay", "toolView"];
  for (const id of drawing) $("#" + id).disabled = !canEdit();
  $("#toolCts").disabled = isDst() || !C.token;
  $("#toolAuto").disabled = isDst() || !C.token || (C.digitized && !C.dirty && C.only === null);
  $("#textAdd").disabled = !canEdit();
  const press = (id, on) => $("#" + id).setAttribute("aria-pressed", !!on);
  press("toolPen", C.tool === "pen" && C.penMode !== "closed"); press("toolClosed", C.tool === "pen" && C.penMode === "closed");
  press("toolMeasure", C.tool === "measure"); press("toolSatin", C.tool === "satinblk"); press("toolFree", C.tool === "free");
  press("toolCircle", C.tool === "shape:circle"); press("toolRect", C.tool === "shape:rectangle");
  press("toolShapes", C.tool.startsWith("shape:") && !["shape:circle", "shape:rectangle"].includes(C.tool));
  press("toolCts", C.tool === "cts"); press("toolPlay", document.body.classList.contains("cpx-player")); press("toolView", !C.plain);
  $("#zoomN").textContent = `${Math.round((C.zoom || 1) * 100)}%`;
  $("#seqEmpty").hidden = !!seqKeys().length;
}
function useTool(t) {
  if (!canEdit()) return;
  T2.sb = null; T2.free = null;
  if (t !== "measure") { T2.meas = null; $("#measureTag").hidden = true; }
  setTool(C.tool === t ? "select" : t);
  O.sig = "";
  repaint();
}
$("#toolMeasure").addEventListener("click", () => useTool("measure"));
$("#toolPen").addEventListener("click", () => { C.penMode = "open"; O.sig = ""; updateTools(); placeMenu($("#penMenu")); });
$("#toolClosed").addEventListener("click", () => {
  if (!canEdit()) return;
  $("#drawMenu").hidden = true;
  if (C.tool === "pen" && C.penMode === "closed") { setTool("select"); return; }
  C.penMode = "closed"; setTool("pen"); openPenMenu(); O.sig = ""; updateTools();
});
$("#toolSatin").addEventListener("click", () => { useTool("satinblk"); if (C.tool === "satinblk") toast("Satin blocks: click a point on one side of the column, then its partner on the other side, and on along the column. Enter finishes, Backspace takes a point back.", false, 7000); });
$("#toolFree").addEventListener("click", () => useTool("free"));
$("#toolCircle").addEventListener("click", () => useTool("shape:circle"));
$("#toolRect").addEventListener("click", () => useTool("shape:rectangle"));
$("#toolCts").addEventListener("click", () => (C.tool === "cts" ? finishTool(false) : enterCts()));
$("#toolAuto").addEventListener("click", () => { if (C.only !== null) autoRest(); else digitize(); });
$("#toolPlay").addEventListener("click", () => togglePlayer());
$("#toolView").addEventListener("click", () => setReal(C.plain));

// ---------------------------------------------------------------- the stitch player and the view
function togglePlayer(on = !document.body.classList.contains("cpx-player")) {
  document.body.classList.toggle("cpx-player", on);
  if (!on) { stop(); $("#step").value = C.st?.length || 0; }
  draw();
}
const speedBtn = document.createElement("button");
speedBtn.type = "button"; speedBtn.id = "speedBtn"; speedBtn.textContent = "1×"; speedBtn.title = "Playing speed";
$("#play").insertBefore(speedBtn, $("#step"));
speedBtn.addEventListener("click", () => {
  const steps = [0.5, 1, 2, 4, 8], i = steps.indexOf(C.speed);
  C.speed = steps[(i + 1) % steps.length]; speedBtn.textContent = `${C.speed}×`;
});
function setReal(on) { C.plain = !on; $("#vReal").checked = on; draw(); }
$("#vReal").addEventListener("change", (e) => setReal(e.target.checked));
for (const id of ["#vJumps", "#vTrims", "#vTies", "#vNeedles", "#vGrid"]) $(id).addEventListener("change", () => repaint());

// ---------------------------------------------------------------- the bar over the selection
function placeSelBar() {
  const bar = $("#selBar");
  const show = hasSel() && C.view && C.tool === "select" && !E.drag;
  if (!show) { bar.hidden = true; return; }
  for (const b of bar.querySelectorAll("[data-act]")) b.hidden = isDst() && !["duplicate", "fliph", "flipv"].includes(b.dataset.act);
  for (const id of ["#toolCorners", "#toolPathfinder"]) $(id).hidden = isDst();
  bar.hidden = false;
  const [x0, y0, x1, y1] = bbox(selOutlines()), dpr = C.view.dpr;
  const [ax, ay] = toScreen([x0, y1]), [bx, by] = toScreen([x1, y0]);
  const cr = $("#canvas").getBoundingClientRect(), sr = $("#stage").getBoundingClientRect();
  const L = cr.left - sr.left + ax / dpr, R = cr.left - sr.left + bx / dpr, Tp = cr.top - sr.top + ay / dpr, Bt = cr.top - sr.top + by / dpr;
  const w = bar.offsetWidth, h = bar.offsetHeight;
  let y = Tp - KNOB - 16 - h;
  if (y < 56) y = Bt + 16;
  y = Math.max(56, Math.min(sr.height - h - 70, y));
  bar.style.left = `${Math.max(8, Math.min(sr.width - w - 8, (L + R) / 2 - w / 2))}px`;
  bar.style.top = `${y}px`;
}

// ---------------------------------------------------------------- pointer: measure, satin blocks, pen
const snapPt = (p) => ($("#vSnap").checked ? [Math.round(p[0] / 10) * 10, Math.round(p[1] / 10) * 10] : p);
function toolPointer(ev, phase) {
  const t = C.tool;
  if (!C.view || !["measure", "satinblk", "free"].includes(t)) return false;
  const pt = ev ? toDesign(ev) : null;
  if (t === "measure") {
    if (phase === "down") { T2.meas = { a: snapPt(pt), b: snapPt(pt) }; T2.measDrag = true; try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* */ } }
    else if (phase === "move") { $("#canvas").style.cursor = "crosshair"; if (T2.measDrag) { T2.meas.b = ev.shiftKey ? snap15(T2.meas.a, pt) : snapPt(pt); repaint(); } }
    else if (phase === "up") { T2.measDrag = false; repaint(); }
    return true;
  }
  if (t === "satinblk") {
    if (phase === "down" && ev.button === 0) {
      if (!T2.sb) T2.sb = { pts: [], cursor: pt };
      const p = ev.shiftKey && T2.sb.pts.length ? snap15(T2.sb.pts[T2.sb.pts.length - 1], pt) : snapPt(pt);
      T2.sb.pts.push(p); repaint();
    } else if (phase === "move") { $("#canvas").style.cursor = "crosshair"; if (T2.sb) { T2.sb.cursor = pt; repaint(); } }
    return true;
  }
  if (t === "free") {
    if (phase === "down") { T2.free = [pt]; try { $("#canvas").setPointerCapture(ev.pointerId); } catch (_e) { /* */ } }
    else if (phase === "move") {
      $("#canvas").style.cursor = "crosshair";
      if (T2.free) { const l = T2.free[T2.free.length - 1]; if (Math.hypot(pt[0] - l[0], pt[1] - l[1]) * C.view.k > 2) { T2.free.push(pt); repaint(); } }
    } else if (phase === "up" && T2.free) {
      const path = T2.free; T2.free = null;
      const len = path.reduce((s, p, i) => s + (i ? Math.hypot(p[0] - path[i - 1][0], p[1] - path[i - 1][1]) : 0), 0);
      if (len < 15) { repaint(); return true; }
      const closed = path.length > 8 && Math.hypot(path[0][0] - path[path.length - 1][0], path[0][1] - path[path.length - 1][1]) < Math.max(30, 12 / C.view.k);
      addShape({ path: rdp(path, 1.5), closed, width_mm: +$("#penWidth").value });
    }
    return true;
  }
  return false;
}
function finishSatinBlock() {
  const sb = T2.sb; T2.sb = null;
  if (!sb) return;
  const n = Math.floor(sb.pts.length / 2);
  if (n < 2) { toast("A satin block needs at least two pairs of points: one on each side, twice."); repaint(); return; }
  const pairs = Array.from({ length: n }, (_v, i) => [sb.pts[2 * i], sb.pts[2 * i + 1]]);
  const outline = [...pairs.map((p) => p[0]), ...pairs.map((p) => p[1]).reverse()];
  if (isDst()) { sewRailsOnDst(pairs, outline); return; }
  remember();
  if (!C.lock) C.lock = C.info.mm_per_px;
  const t = drawThread(), id = nextShapeId();
  if (t.num) C.shapeThreads[t.hex.toLowerCase()] = t;
  C.shapes = [...C.shapes, { id, hex: t.hex.toLowerCase(), view: outline, px: outline.map(toPxFrame), closed: true, railsView: pairs,
                             rails: pairs.map((p) => p.map(toPxFrame)), width: 1.5 / C.lock, width_mm: 1.5, sewn: false }];
  newObjectCfg(id, true, "satinblk");
  C.sels = ["draft:" + id];
  setTool("select");
  markDirty();
  toast("Satin block added and selected. Click Update Digitizing to sew it.");
}
async function sewRailsOnDst(pairs, outline) {      // an opened DST: sewn at once, as a colour of its own at the end
  busy(true, "Sewing the satin block…");
  try {
    const r = await post("/api/cap/shape", { rails: pairs, pts: outline, closed: true, options: { density: 0.4, pull_comp: 0.2, order: "center" } });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
    remember();
    const t = drawThread();
    const piece = j.stitches.filter((p) => p[2] !== 4), first = piece.find((p) => p[2] === 0);
    if (piece[0][2] !== 1) piece.unshift([first[0], first[1], 1]);
    let end = C.st.length;
    if (C.st[end - 1]?.[2] === 4) end -= 1;
    const at = C.st[end - 1], same = C.colors[C.colors.length - 1]?.hex.toLowerCase() === t.hex.toLowerCase();
    C.st.splice(end, 0, [at[0], at[1], 2], ...(same ? [] : [[at[0], at[1], 3]]), ...piece);
    if (!same) C.colors.push({ id: `block${Date.now()}`, hex: t.hex, thread: t.num ? t : null, name: t.num ? `${t.num} ${t.name}` : `Colour ${C.colors.length + 1}` });
    C.changed = true; afterDst(); setTool("select");
  } catch (e) { toast(e.message, true, 6000); repaint(); }
  finally { busy(false); }
}
// a new drawn object takes the settings in the box; a line is a run unless the box says otherwise,
// a satin block a satin
function newObjectCfg(id, closed, kind) {
  let c = { ...(C.ctsCfg || {}) };
  if (!c.type || c.type === "auto") {
    if (kind === "satinblk") c.type = "satin";
    else if (!closed) c.type = "run";
  }
  c = clean(c);
  if (c) C.sew = { ...C.sew, ["s" + id]: c };
}

// ---------------------------------------------------------------- drawn over the design
function toolsOverlay(g) {
  const dpr = C.view.dpr, st = C.st || [], upto = Math.min(+$("#step").value || st.length, st.length);
  g.save();
  if ($("#vGrid").checked) {                   // behind the stitches: lines every 10 mm
    g.globalCompositeOperation = "destination-over";
    const cv = $("#canvas"), x0 = C.view.x0, y1 = C.view.y1, k = C.view.k * dpr;
    const x1 = x0 + cv.width / k, y0 = y1 - cv.height / k;
    g.strokeStyle = "rgba(0,0,0,.07)"; g.lineWidth = 1;
    g.beginPath();
    for (let x = Math.ceil(x0 / 100) * 100; x <= x1; x += 100) { const [sx] = toScreen([x, 0]); g.moveTo(sx, 0); g.lineTo(sx, cv.height); }
    for (let y = Math.ceil(y0 / 100) * 100; y <= y1; y += 100) { const [, sy] = toScreen([0, y]); g.moveTo(0, sy); g.lineTo(cv.width, sy); }
    g.stroke();
    g.globalCompositeOperation = "source-over";
  }
  const jumps = $("#vJumps").checked, trims = $("#vTrims").checked, needles = $("#vNeedles").checked, ties = $("#vTies").checked;
  if (jumps || trims || needles || ties) {
    let prev = null, since = 99;
    g.lineWidth = 1 * dpr;
    for (let i = 0; i < upto; i++) {
      const [x, y, c] = st[i], [sx, sy] = toScreen([x, y]);
      if (c === 1 && prev && jumps) {
        const [px, py] = toScreen(prev);
        g.strokeStyle = "rgba(255,59,48,.7)"; g.setLineDash([3 * dpr, 3 * dpr]);
        g.beginPath(); g.moveTo(px, py); g.lineTo(sx, sy); g.stroke(); g.setLineDash([]);
      }
      if (c === 2 && trims) {
        const r = 4 * dpr;
        g.strokeStyle = "#ff9500"; g.lineWidth = 2 * dpr;
        g.beginPath(); g.moveTo(sx - r, sy - r); g.lineTo(sx + r, sy + r); g.moveTo(sx + r, sy - r); g.lineTo(sx - r, sy + r); g.stroke();
        g.lineWidth = 1 * dpr;
      }
      if (c !== 0) since = 0;
      if (c === 0) {
        const short = prev && Math.hypot(x - prev[0], y - prev[1]) < 10;
        const tie = ties && short && (since < 4 || [1, 2, 3, 4].some((d) => st[i + d]?.[2] === 2));
        if (tie) { g.fillStyle = "#34c759"; g.beginPath(); g.arc(sx, sy, 2.6 * dpr, 0, 7); g.fill(); }
        else if (needles) { g.fillStyle = "rgba(0,0,0,.55)"; g.fillRect(sx - 1 * dpr, sy - 1 * dpr, 2 * dpr, 2 * dpr); }
        since++;
      }
      if (c !== 2) prev = [x, y];
    }
  }
  // measuring: the line and its length
  const tag = $("#measureTag");
  if (T2.meas && C.tool === "measure") {
    const [ax, ay] = toScreen(T2.meas.a), [bx, by] = toScreen(T2.meas.b);
    g.strokeStyle = "#0a84ff"; g.lineWidth = 1.5 * dpr;
    g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke();
    for (const [x, y] of [[ax, ay], [bx, by]]) { g.beginPath(); g.arc(x, y, 3 * dpr, 0, 7); g.fillStyle = "#0a84ff"; g.fill(); }
    const mm = Math.hypot(T2.meas.b[0] - T2.meas.a[0], T2.meas.b[1] - T2.meas.a[1]) / 10;
    const cr = $("#canvas").getBoundingClientRect(), sr = $("#stage").getBoundingClientRect();
    tag.textContent = `${mm.toFixed(1)} mm · ${(mm / 25.4).toFixed(2)} in`;
    tag.hidden = mm < 0.05;
    tag.style.left = `${cr.left - sr.left + (ax + bx) / 2 / dpr + 10}px`; tag.style.top = `${cr.top - sr.top + (ay + by) / 2 / dpr - 28}px`;
  } else tag.hidden = true;
  // a satin block being drawn: its pairs and the column between them
  if (T2.sb && C.tool === "satinblk") {
    const P = T2.sb.pts, hex = drawHex();
    const n = Math.floor(P.length / 2);
    if (n >= 2) {
      const outline = [...Array.from({ length: n }, (_v, i) => P[2 * i]), ...Array.from({ length: n }, (_v, i) => P[2 * i + 1]).reverse()];
      g.globalAlpha = 0.45; g.fillStyle = hex; g.beginPath();
      outline.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.fill(); g.globalAlpha = 1;
    }
    g.strokeStyle = "#0a84ff"; g.lineWidth = 1.2 * dpr;
    for (let i = 0; i + 1 < P.length; i += 2) { const [ax, ay] = toScreen(P[i]), [bx, by] = toScreen(P[i + 1]); g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke(); }
    if (P.length % 2 === 1 && T2.sb.cursor) {            // the partner still to place
      const [ax, ay] = toScreen(P[P.length - 1]), [bx, by] = toScreen(T2.sb.cursor);
      g.setLineDash([4 * dpr, 3 * dpr]); g.beginPath(); g.moveTo(ax, ay); g.lineTo(bx, by); g.stroke(); g.setLineDash([]);
    }
    P.forEach((p, i) => { const [x, y] = toScreen(p), s = 3.5 * dpr; g.fillStyle = i % 2 ? "#ff9500" : "#ffffff"; g.strokeStyle = "#0a84ff"; g.fillRect(x - s, y - s, 2 * s, 2 * s); g.strokeRect(x - s, y - s, 2 * s, 2 * s); });
  }
  // a freehand line being drawn
  if (T2.free?.length > 1) {
    g.strokeStyle = drawHex(); g.lineWidth = Math.max(1.5 * dpr, +$("#penWidth").value * 10 * C.view.k * dpr); g.lineCap = "round"; g.lineJoin = "round"; g.globalAlpha = 0.7;
    g.beginPath(); T2.free.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.stroke(); g.globalAlpha = 1;
  }
  g.restore();
  placeSelBar();
}

// ---------------------------------------------------------------- keys
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  const take = () => { ev.preventDefault(); ev.stopImmediatePropagation(); };
  const mod = ev.metaKey || ev.ctrlKey, key = ev.key.toLowerCase();
  if (C.tool === "satinblk" && T2.sb) {
    if (ev.key === "Enter") { take(); finishSatinBlock(); return; }
    if (ev.key === "Escape") { take(); T2.sb = null; setTool("select"); repaint(); return; }
    if (ev.key === "Backspace" || ev.key === "Delete") { take(); T2.sb.pts.pop(); if (!T2.sb.pts.length) T2.sb = null; repaint(); return; }
  }
  if (document.body.classList.contains("cpx-player") && !hasSel() && C.st) {     // the player: step through the stitches
    const d = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1 }[ev.key];
    if (d) { take(); stop(); $("#step").value = Math.max(0, Math.min(C.st.length, +$("#step").value + d * (ev.shiftKey ? 10 : 1))); draw(); return; }
    if (ev.key === "Escape") { take(); togglePlayer(false); return; }
  }
  if (ev.code === "Space" && !mod && canEdit() && !T2.space && C.tool !== "hand") {        // hold space: pan
    take(); T2.space = C.tool; setTool("hand"); return;
  }
  if (mod || ev.altKey || !canEdit() || (C.tool === "pen" && E.pen)) return;
  const tools = { s: () => setTool("select"), m: () => useTool("measure"), 1: () => $("#toolPen").click(), 2: () => $("#toolClosed").click(),
                  3: () => $("#toolSatin").click(), 4: () => useTool("free"), 5: () => useTool("shape:circle"), 6: () => useTool("shape:rectangle"),
                  t: () => $("#toolText").click(), v: () => setReal(C.plain) };
  if (tools[key] && !(key === "t" && isDst() === false && !C.digitized)) { take(); tools[key](); }
}, true);
document.addEventListener("keyup", (ev) => {
  if (ev.code === "Space" && T2.space) { setTool(T2.space === "hand" ? "select" : T2.space); T2.space = null; }
});
$("#canvas").addEventListener("contextmenu", (ev) => { if (C.tool === "pen" || C.tool === "satinblk") ev.preventDefault(); });
window.addEventListener("resize", () => { if (window.innerWidth > 900) $("#panel").classList.remove("open"); });
