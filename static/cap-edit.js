// Cap DST page: editing on the canvas, as Wilcom's Select tool. Click a piece to select it, shift-click
// to add or take one away, or drag a box over empty space to select every piece inside it; drag the
// selection to move it, a handle to resize it (a side: its height or width only; a corner: both,
// freely; shift: in proportion), the knob above it to turn it; the tool strip turns,
// resizes, recolours (from the thread palette) and deletes it; arrows nudge, Delete removes, ⌘A selects
// all, ⌘Z / ⇧⌘Z undo and redo, Esc deselects.
//   The hand (H) drags the view around, at any zoom.
//   Corners (live, as Illustrator's): a shape drawn on a logo shows a dot inside each corner; drag a
//   dot to round every corner, or click dots to pick corners (shift: more) and drag one of them to
//   round only those; the Corners panel sets the radius (mm) and the corner: round, chamfer or
//   inverted. The corners are kept apart from the shape (sh.corner: its outline with sharp corners in
//   image pixels, a radius and a style for each point), so they can be changed again at any time.
//   Arrange: Bring to Front (⇧⌘]), Bring Forward (⌘]), Send Backward (⌘[), Send to Back (⇧⌘[). In
//   embroidery the front is what is sewn last, so these change the sewing order: a DST's stitches at
//   once; a logo's pieces when it is digitized again (a colour whose pieces part is sewn in blocks).
//   Align lines the selected pieces up by their edges or centres (one piece: on the whole design),
//   and Distribute spaces three or more evenly, as Illustrator's Align panel; one undo for each.
//   The Pathfinder combines shapes drawn on the page (two or more selected) into one new shape, as
//   Illustrator's: Unite, Minus Front, Intersect, Exclude. Its outlines may hold holes (rings).
//   Shapes and the pen draw new pieces: a shape dragged out (shift: even), or a freehand line (let
//   go near its start: a filled shape; else a satin line of the pen's width).
//   A logo: a piece is each separate shape of a colour. An edit is kept for it ({dx, dy in image
//   pixels, m: its resize and turn as a matrix in image pixels, color, deleted}); the piece shows where it will be (moved,
//   resized, turned, recoloured) until Update Digitizing sews it there. While edits exist the
//   scale stays fixed (C.lock, mm per image pixel), so the rest of the design does not change.
//   A DST: a piece is a run of stitches between trims and colour changes (a letter, a swoosh: an
//   object, as Wilcom shows a DST); it is changed at once, as stitches. Resized, its stitches are
//   spaced again as they were (a satin keeps its density, a run its stitch length). A piece given
//   another thread becomes a colour block of its own, sewn right after the one it came from.
"use strict";

C.edits = {}; C.lock = null; C.sels = []; C.undo = []; C.redo = []; C.shapes = []; C.shapeThreads = {};
C.arrange = null;                               // a logo's pieces in the sewing order arranged (Arrange), or null
C.tool = "select";                              // "select", "shape:<kind>", "pen", "zoom" or "hand"
C.zoom = 1; C.cam = null;                       // the preview's zoom (1: the whole design) and its centre (0.1 mm)
const E = { drag: null };
const HANDLE = 5, KNOB = 26;                   // css px: a handle's half size, the knob's distance
const ID = { dx: 0, dy: 0, m: [1, 0, 0, 1] };

// ---------------------------------------------------------------- geometry (0.1 mm, y up, as the stitches)
function toDesign(ev) {
  const r = $("#canvas").getBoundingClientRect(), v = C.view;
  return [v.x0 + (ev.clientX - r.left) / v.k, v.y1 - (ev.clientY - r.top) / v.k];
}
const toScreen = ([x, y]) => [(x - C.view.x0) * C.view.k * C.view.dpr, (C.view.y1 - y) * C.view.k * C.view.dpr];
function inPoly([x, y], pts) {
  let inside = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i], [xj, yj] = pts[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
function bbox(rings) {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const r of rings) for (const [x, y] of r) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  return [x0, y0, x1, y1];
}
function centroid(rings) {                      // as the digitizer turns and resizes: about the area's centre
  let a = 0, cx = 0, cy = 0;
  for (const r of rings) for (let i = 0, j = r.length - 1; i < r.length; j = i++) {
    const f = r[j][0] * r[i][1] - r[i][0] * r[j][1];
    a += f; cx += (r[j][0] + r[i][0]) * f; cy += (r[j][1] + r[i][1]) * f;
  }
  if (Math.abs(a) < 1e-9) { const [x0, y0, x1, y1] = bbox(rings); return [(x0 + x1) / 2, (y0 + y1) / 2]; }
  return [cx / (3 * a), cy / (3 * a)];
}
const turnAbout = ([cx, cy], f, a, [dx, dy] = [0, 0]) => {      // p -> c + d + R(a) f (p - c)
  const cs = Math.cos(a) * f, sn = Math.sin(a) * f;
  return ([x, y]) => [cx + dx + (x - cx) * cs - (y - cy) * sn, cy + dy + (x - cx) * sn + (y - cy) * cs];
};
// 2 x 2 matrices [a, b, c, d]: x' = a x + b y, y' = c x + d y
const matMul = ([a, b, c, d], [e, f, g, h]) => [a * e + b * g, a * f + b * h, c * e + d * g, c * f + d * h];
const matInv = ([a, b, c, d]) => { const k = a * d - b * c || 1e-9; return [d / k, -b / k, -c / k, a / k]; };
const linAbout = ([cx, cy], [a, b, c, d], [dx, dy] = [0, 0]) =>                // p -> c + d + L (p - c)
  ([x, y]) => [cx + dx + a * (x - cx) + b * (y - cy), cy + dy + c * (x - cx) + d * (y - cy)];
// turned by a (radians) after resized by f: one factor, or [across, up] for a stretch
const designLin = (f, a = 0) => {
  const [fx, fy] = Array.isArray(f) ? f : [f, f], cs = Math.cos(a), sn = Math.sin(a);
  return [cs * fx, -sn * fy, sn * fx, cs * fy];
};
// from the design's directions (0.1 mm, y up, after the turn of the whole design) to the image's (y down)
function imageFrame() {
  const t = -(+$("#tilt").value || 0) * Math.PI / 180, cs = Math.cos(t), sn = Math.sin(t);
  return [cs, -sn, -sn, -cs];
}
// an edit's resize and turn (image pixels): its matrix, or the scale and turn of an older edit
function mOf(e) {
  if (Array.isArray(e.m)) return e.m;
  const s = e.scale ?? 1, r = (e.rotate || 0) * Math.PI / 180;
  return [s * Math.cos(r), s * Math.sin(r), -s * Math.sin(r), s * Math.cos(r)];
}
// the drag as it goes: the outlines moved, resized or turned
function dragged(p) {
  const d = E.drag;
  if (!d || !["move", "scale", "rotate"].includes(d.mode)) return p;      // a box, a shape or the pen: not the selection
  if (d.mode === "move") return [p[0] + d.cur[0] - d.start[0], p[1] + d.cur[1] - d.start[1]];
  if (d.mode === "scale") return linAbout(d.anchor, designLin([d.fx, d.fy]))(p);
  return turnAbout(d.c, 1, d.a)(p);
}

// ---------------------------------------------------------------- pieces: a logo's shapes, or a DST's runs of stitches
function blocks() {              // a DST: each colour block's records [start, end)
  const out = []; let s = 0;
  C.st.forEach((p, i) => { if (p[2] === 3) { out.push([s, i]); s = i + 1; } });
  out.push([s, C.st.length]);
  return out;
}
function segments() {           // a DST's pieces: each run of stitches between trims and colour changes [start, end, block]
  const out = []; let s = 0, b = 0;
  const close = (e) => { for (let i = s; i < e; i++) if (C.st[i][2] === 0) { out.push([s, e, b]); return; } };
  C.st.forEach((p, i) => {
    if (p[2] === 3) { close(i); s = i + 1; b++; }
    else if (p[2] === 2) { close(i); s = i + 1; }
  });
  close(C.st.length);
  return out;
}
function blockRings(k) {        // a DST piece's outline: the box around its stitches
  const [s, e] = segments()[k] || [0, 0], pts = [];
  for (let i = s; i < e; i++) if (C.st[i][2] === 0) pts.push(C.st[i]);
  if (!pts.length) return [];
  const [x0, y0, x1, y1] = bbox([pts]);
  return [[[x0, y0], [x1, y0], [x1, y1], [x0, y1]]];
}
// a logo piece where it will be: its outline as last digitized, moved by the edits since
function pending(key) {
  const a = { ...ID, ...(C.applied[key] || {}) }, b = { ...ID, ...(C.edits[key] || {}) };
  const mine = (C.info?.pieces || []).filter((p) => p.key === key);
  const rings = mine.map((p) => p.pts), holes = mine.flatMap((p) => p.holes || []);
  if (!rings.length || a.deleted) return { rings: [], holes: [], old: rings, changed: false };
  if (b.deleted) return { rings: [], holes: [], old: rings, changed: true, deleted: true };
  const ma = mOf(a), mb = mOf(b);
  const same = a.dx === b.dx && a.dy === b.dy && ma.every((v, i) => Math.abs(v - mb[i]) < 1e-9);
  const colour = b.color && b.color !== a.color ? b.color : null;
  if (same) return { rings, holes, old: rings, changed: !!colour, colour };
  const t = -(+$("#tilt").value || 0) * Math.PI / 180, mmpp = C.lock || C.info.mm_per_px;
  const px = [b.dx - a.dx, b.dy - a.dy];
  const v = [px[0] * mmpp * 10, -px[1] * mmpp * 10];                         // image pixels -> 0.1 mm, y up
  const d = [v[0] * Math.cos(-t) - v[1] * Math.sin(-t), v[0] * Math.sin(-t) + v[1] * Math.cos(-t)];
  const K = imageFrame(), rel = matMul(matInv(K), matMul(matMul(mb, matInv(ma)), K));    // in the design's directions
  const f = linAbout(centroid(rings), rel, d);
  return { rings: rings.map((r) => r.map(f)), holes: holes.map((r) => r.map(f)), old: rings, changed: true, colour };
}
function allPieces() {          // every piece there is now: logo keys, or DST piece numbers
  if (isDst()) return segments().map((_g, k) => k);
  return [...new Set((C.info?.pieces || []).map((p) => p.key))].filter((k) => pending(k).rings.length && !redrawnShape(k))
    .concat(C.shapes.filter((sh) => !sh.sewn).map((sh) => "draft:" + sh.id));
}
// a shape drawn on a logo, not digitized yet: a piece of its own ("draft:<id>"), edited as drawn
const draftOf = (k) => (typeof k === "string" && k.startsWith("draft:") ? C.shapes.find((sh) => "draft:" + sh.id === k && !sh.sewn) : null);
function draftRings(sh) {       // its outline (0.1 mm): the shape (a Pathfinder shape: every ring), or the band of a line
  if (sh.rings) return sh.rings;
  if (sh.closed) return [sh.view];
  const w = sh.width_mm * 5, P = sh.view, L = [], R = [];
  P.forEach((p, i) => {
    const a = P[Math.max(0, i - 1)], b = P[Math.min(P.length - 1, i + 1)];
    let nx = -(b[1] - a[1]), ny = b[0] - a[0];
    const n = Math.hypot(nx, ny) || 1; nx /= n; ny /= n;
    L.push([p[0] + nx * w, p[1] + ny * w]); R.push([p[0] - nx * w, p[1] - ny * w]);
  });
  return [L.concat(R.reverse())];
}
const ringsOf = (k) => (isDst() ? blockRings(k) : draftOf(k) ? draftRings(draftOf(k)) : pending(k).rings);
function pieceAt(pt) {
  if (isDst()) {                // the piece of the nearest stitch, within 1.5 mm
    let best = null, bd = 15 * 15;
    segments().forEach(([s, e], k) => { for (let i = s; i < e; i++) { const p = C.st[i]; if (p[2] !== 0) continue;
      const d = (p[0] - pt[0]) ** 2 + (p[1] - pt[1]) ** 2; if (d < bd) { bd = d; best = k; } } });
    return best;
  }
  for (const key of allPieces().reverse()) {   // the last drawn is on top; in a shape's hole is outside it
    const rs = ringsOf(key);
    if (draftOf(key)?.rings ? rs.filter((r) => inPoly(pt, r)).length % 2 === 1 : rs.some((r) => inPoly(pt, r))) return key;
  }
  return null;
}
const selOutlines = () => C.sels.flatMap(ringsOf);
const hasSel = () => C.sels.length > 0;

// ---------------------------------------------------------------- drawn over the stitches
function editOverlay(g) {
  updateTools();
  if (!C.view) return;
  const dpr = C.view.dpr;
  const path = (r) => { g.beginPath(); r.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); };
  // a logo's edits waiting for Update Digitizing: the piece shown where it will be, in its thread
  if (!isDst() && C.digitized) {
    g.save();
    const keys = new Set([...Object.keys(C.edits || {}), ...Object.keys(C.applied || {})]);
    for (const key of keys) {
      const pd = pending(key);
      if (!pd.changed) continue;
      g.fillStyle = "rgba(255,255,255,.9)";
      for (const r of pd.old) { path(r); g.fill(); }
      if (pd.deleted) {
        g.setLineDash([4 * dpr, 4 * dpr]); g.strokeStyle = "#ff3b30"; g.lineWidth = 1.2 * dpr;
        for (const r of pd.old) { path(r); g.stroke(); }
        continue;
      }
      const hex = pd.colour || (C.info.pieces.find((p) => p.key === key)?.hex) || "#888888";
      g.fillStyle = hex; g.globalAlpha = 0.85;
      for (const r of pd.rings) { path(r); g.fill(); }
      g.globalAlpha = 1; g.setLineDash([4 * dpr, 3 * dpr]); g.strokeStyle = "rgba(10,132,255,.8)"; g.lineWidth = 1 * dpr;
      for (const r of pd.rings) { path(r); g.stroke(); }
      g.setLineDash([]);
    }
    g.restore();
  }
  // shapes drawn on a logo, not digitized yet: shown in their thread until Update Digitizing; with
  // pieces arranged since (Bring to Front...), those whose place in the sewing order changed and what
  // they overlap shown flat in their thread, all of it in the order arranged, so the front is on top
  if (!isDst()) {
    // a sewn shape being changed again (its corners): its stitches covered until Update Digitizing
    g.save(); g.fillStyle = "rgba(255,255,255,.92)";
    for (const p of C.info?.pieces || []) if (redrawnShape(p.key)) { g.beginPath(); p.pts.forEach((q, i) => { const [x, y] = toScreen(q); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.fill(); }
    g.restore();
    const seq = sewingOrder(), sewnNow = allPieces().filter((k) => !draftOf(k));
    const posA = new Map(seq.map((k, i) => [k, i])), posN = new Map(sewnNow.map((k, i) => [k, i]));
    const box = new Map(seq.map((k) => [k, bbox(ringsOf(k))]));
    const meet = (p, q) => p[0] <= q[2] && p[2] >= q[0] && p[1] <= q[3] && p[3] >= q[1];
    const shown = new Set();
    // two pieces that overlap and now lie the other way round: both shown flat, in the new order
    for (let i = 0; i < sewnNow.length; i++) for (let j = i + 1; j < sewnNow.length; j++) {
      const p = sewnNow[i], q = sewnNow[j];
      if (posA.get(p) > posA.get(q) && meet(box.get(p), box.get(q))) { shown.add(p); shown.add(q); }
    }
    // then whatever is sewn after a piece shown flat, or after a drawn shape, and overlaps it: over it
    seq.forEach((k, i) => {
      if (!draftOf(k) && seq.slice(0, i).some((x) => (draftOf(x) || shown.has(x)) && meet(box.get(x), box.get(k)))) shown.add(k);
    });
    for (const k of seq) {
      const sh = draftOf(k);
      if (sh) sh.rings ? drawRings(g, sh.rings, sh.hex, 0.85) : drawShapePath(g, sh.view, sh.closed, sh.width_mm, sh.hex, 0.85);
      else if (shown.has(k)) {
        const pd = pending(k), hex = pd.colour || C.info.pieces.find((p) => p.key === k)?.hex || "#888888";
        drawRings(g, [...pd.rings, ...pd.holes], hex, 1);
      }
    }
  }
  // the shape or line being drawn
  if (E.drag?.mode === "draw") drawShapePath(g, E.drag.path, E.drag.closed, E.drag.width_mm, drawHex(), 0.6);
  if (E.pen) drawPen(g);                          // also while the hand moves the view
  // the box being dragged over empty space
  if (E.drag?.mode === "box") {
    const [ax, ay] = toScreen(E.drag.start), [bx, by] = toScreen(E.drag.cur);
    g.save();
    g.fillStyle = "rgba(10,132,255,.08)"; g.strokeStyle = "#0a84ff"; g.lineWidth = 1 * dpr; g.setLineDash([4 * dpr, 3 * dpr]);
    g.fillRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
    g.strokeRect(Math.min(ax, bx), Math.min(ay, by), Math.abs(bx - ax), Math.abs(by - ay));
    g.restore();
  }
  const rings = selOutlines();
  if (!rings.length) return;
  const moved = rings.map((r) => r.map(dragged));
  g.save();
  g.lineWidth = 1.5 * dpr; g.strokeStyle = "#0a84ff"; g.setLineDash([5 * dpr, 4 * dpr]);
  for (const r of moved) { path(r); g.stroke(); }
  // one box with handles around the whole selection
  const [x0, y0, x1, y1] = bbox(moved);
  const [ax, ay] = toScreen([x0, y1]), [bx, by] = toScreen([x1, y0]);
  g.setLineDash([]); g.lineWidth = 1 * dpr; g.strokeStyle = "rgba(10,132,255,.7)";
  g.strokeRect(ax, ay, bx - ax, by - ay);
  const h = HANDLE * dpr, mx = (ax + bx) / 2, ky = ay - KNOB * dpr;
  g.beginPath(); g.moveTo(mx, ay); g.lineTo(mx, ky); g.stroke();
  g.fillStyle = "#ffffff"; g.strokeStyle = "#0a84ff"; g.lineWidth = 1.5 * dpr;
  for (const [x, y] of handlePoints(ax, ay, bx, by)) { g.fillRect(x - h, y - h, 2 * h, 2 * h); g.strokeRect(x - h, y - h, 2 * h, 2 * h); }
  g.beginPath(); g.arc(mx, ky, h * 1.2, 0, 7); g.fill(); g.stroke();
  if (C.sels.length > 1) {
    g.fillStyle = "#0a84ff"; g.font = `${11 * dpr}px -apple-system, sans-serif`;
    g.fillText(`${C.sels.length} pieces`, ax, by + 14 * dpr);
  }
  g.restore();
  drawCornerDots(g);
}
function repaint() {                            // the cached drawing, and the selection on top
  if (!draw.base || !C.view) return;
  const cv = $("#canvas"), g = cv.getContext("2d");
  g.clearRect(0, 0, cv.width, cv.height); g.drawImage(draw.base, 0, 0);
  editOverlay(g);
}
// the selection box's handles (screen): the corners, then the middles of the sides; with each, which
// side it moves (hx: -1 left, 1 right, 0 neither; hy: 1 top, -1 bottom, 0 neither)
function handlePoints(ax, ay, bx, by) {
  const mx = (ax + bx) / 2, my = (ay + by) / 2;
  return [[ax, ay, -1, 1], [bx, ay, 1, 1], [ax, by, -1, -1], [bx, by, 1, -1],
          [mx, ay, 0, 1], [mx, by, 0, -1], [ax, my, -1, 0], [bx, my, 1, 0]];
}
// which handle is under the pointer (css px): { mode: "scale", hx, hy }, { mode: "rotate" } or null
function handleAt(ev) {
  const rings = selOutlines();
  if (!rings.length) return null;
  const r = $("#canvas").getBoundingClientRect(), px = ev.clientX - r.left, py = ev.clientY - r.top;
  const [x0, y0, x1, y1] = bbox(rings), k = C.view.k;
  const ax = (x0 - C.view.x0) * k, bx = (x1 - C.view.x0) * k, ay = (C.view.y1 - y1) * k, by = (C.view.y1 - y0) * k;
  if (Math.hypot(px - (ax + bx) / 2, py - (ay - KNOB)) <= HANDLE + 4) return { mode: "rotate" };
  for (const [x, y, hx, hy] of handlePoints(ax, ay, bx, by)) {
    if (Math.abs(px - x) <= HANDLE + 3 && Math.abs(py - y) <= HANDLE + 3) return { mode: "scale", hx, hy };
  }
  return null;
}
const HANDLE_CURSOR = { "-1,1": "nwse-resize", "1,-1": "nwse-resize", "1,1": "nesw-resize", "-1,-1": "nesw-resize",
                        "0,1": "ns-resize", "0,-1": "ns-resize", "-1,0": "ew-resize", "1,0": "ew-resize" };

// ---------------------------------------------------------------- edits, undo, redo
const snapshot = () => JSON.stringify(isDst() ? { st: C.st, colors: C.colors } : { edits: C.edits, lock: C.lock, shapes: C.shapes, arrange: C.arrange });
function remember() { C.undo.push(snapshot()); C.redo = []; }
function restore(json) {
  const o = JSON.parse(json);
  C.sels = [];
  if (isDst()) { C.st = o.st; C.colors = o.colors; C.changed = true; afterDst(); return; }
  C.edits = o.edits; C.lock = o.lock; C.shapes = o.shapes || []; C.arrange = o.arrange || null; markDirty();
}
function undo() { if (!C.undo.length) return; C.redo.push(snapshot()); restore(C.undo.pop()); }
function redo() { if (!C.redo.length) return; C.undo.push(snapshot()); restore(C.redo.pop()); }
// a move of v (0.1 mm, y up, after the turn of the whole design) as image pixels
function toPx([vx, vy]) {
  const t = -(+$("#tilt").value || 0) * Math.PI / 180, mmpp = C.lock || C.info.mm_per_px;
  const x = (vx * Math.cos(t) - vy * Math.sin(t)) / 10, y = (vx * Math.sin(t) + vy * Math.cos(t)) / 10;
  return [x / mmpp, -y / mmpp];               // image y is down
}
// the selection moved by v, then resized by f (one factor, or [across, up]: stretched) and turned by
// a (radians) about the point at (the selection's centre when not given)
function transform(v, f, a, at, undoTaken) {
  if (!hasSel()) return;
  const c = at || centroid(selOutlines()), L = designLin(f, a), [fx, fy] = Array.isArray(f) ? f : [f, f];
  if (!undoTaken) remember();
  if (isDst()) {
    const map = linAbout(c, L, v), Li = matInv(L);
    // the stitches transformed; when resized, spaced again as they were (each piece, last first)
    const segs = segments(), picked = C.sels.map((k) => segs[k]).filter(Boolean).sort((p, q) => q[0] - p[0]);
    for (const [s, e] of picked) for (let i = s; i < e; i++) { const [x, y] = map(C.st[i]); C.st[i] = [x, y, C.st[i][2]]; }
    // how much longer a stitch lying along w (as it is now) became
    const ratio = ([wx, wy]) => { const n = Math.hypot(wx, wy); return n ? n / Math.hypot(Li[0] * wx + Li[1] * wy, Li[2] * wx + Li[3] * wy) : 1; };
    if (Math.max(Math.abs(fx - 1), Math.abs(fy - 1)) > 0.05) for (const [s, e] of picked) respace(s, e, ratio);
    for (let i = 0; i < C.st.length; i++) C.st[i] = [Math.round(C.st[i][0]), Math.round(C.st[i][1]), C.st[i][2]];
    C.changed = true; afterDst();
    return;
  }
  // a logo: each piece's own edit; turned and resized about the selection's centre, a piece's own
  // centre moves too (its edit turns and resizes about that centre)
  if (!C.lock) C.lock = C.info.mm_per_px;      // from the first edit on, the scale stays
  const map = linAbout(c, L, v), K = imageFrame(), Mimg = matMul(K, matMul(L, matInv(K)));
  const fw = Math.sqrt(fx * fy);              // a line's width: by the mean of the two
  const edits = { ...C.edits };
  C.shapes = C.shapes.map((sh) => {          // shapes not digitized yet: their own points moved
    if (!C.sels.includes("draft:" + sh.id) || sh.sewn) return sh;
    const view = sh.view.map(map), rings = sh.rings?.map((r) => r.map(map));
    const out = { ...sh, view, px: view.map(toPxFrame), width_mm: sh.width_mm * fw, width: sh.width_mm * fw / C.lock,
                  ...(rings ? { rings, pxRings: rings.map((r) => r.map(toPxFrame)) } : {}),
                  ...(sh.text ? { text: { ...sh.text, height_mm: Math.round(sh.text.height_mm * fy * 10) / 10 } } : {}) };
    if (sh.corner) setCorners(out, sh.corner.base.map(fromPxFrame).map(map).map(toPxFrame), sh.corner.r.map((x) => x * fw), sh.corner.style);
    return out;
  });
  for (const key of C.sels) {
    if (draftOf(key) || key.startsWith?.("draft:")) continue;
    const pc = centroid(pending(key).rings), to = map(pc);
    const e = { ...ID, ...(edits[key] || {}) };
    const [dx, dy] = toPx([to[0] - pc[0], to[1] - pc[1]]);
    e.dx += dx; e.dy += dy;
    e.m = matMul(Mimg, mOf(e)).map((x) => Math.round(x * 1e6) / 1e6);
    delete e.scale; delete e.rotate;
    edits[key] = e;
  }
  C.edits = edits; markDirty();
}
const nudge = (vx, vy) => transform([vx, vy], 1, 0);
// ---------------------------------------------------------------- arrange: the sewing order
// a piece's key as the digitizer knows it: a drawn shape once sewn ("shape#hex:s<id>")
function sewnKey(k) {
  const m = /^draft:(\d+)$/.exec(String(k)), sh = m && C.shapes.find((x) => String(x.id) === m[1]);
  return sh ? `shape${sh.hex}:s${sh.id}` : k;
}
// the pieces in the order they are sewn now (a logo: as arranged since, if not digitized yet)
function sewingOrder() {
  const now = allPieces();
  if (isDst() || !C.arrange) return now;
  const known = new Map(now.map((k) => [sewnKey(k), k]));
  const seq = C.arrange.map((k) => known.get(sewnKey(k))).filter((k) => k !== undefined);
  return [...new Set([...seq, ...now])];
}
function arrangePieces(how) {
  if (!hasSel()) { toast("Select pieces first."); return; }
  const seq = sewingOrder(), sel = new Set(C.sels), out = [...seq];
  if (how === "front") out.splice(0, out.length, ...seq.filter((k) => !sel.has(k)), ...seq.filter((k) => sel.has(k)));
  else if (how === "back") out.splice(0, out.length, ...seq.filter((k) => sel.has(k)), ...seq.filter((k) => !sel.has(k)));
  else if (how === "forward") { for (let i = out.length - 2; i >= 0; i--) if (sel.has(out[i]) && !sel.has(out[i + 1])) [out[i], out[i + 1]] = [out[i + 1], out[i]]; }
  else for (let i = 1; i < out.length; i++) if (sel.has(out[i]) && !sel.has(out[i - 1])) [out[i], out[i - 1]] = [out[i - 1], out[i]];
  if (out.every((k, i) => k === seq[i])) { toast(how === "front" || how === "forward" ? "Already sewn last (at the front)." : "Already sewn first (at the back)."); return; }
  remember();
  const word = { front: "Brought to the front", forward: "Brought forward", backward: "Sent backward", back: "Sent to the back" }[how];
  if (isDst()) { arrangeDst(out); toast(`${word}: the stitches are sewn in the new order.`); return; }
  C.arrange = out.map(sewnKey);
  markDirty();
  toast(`${word}: sewn in the new order when you click Update Digitizing (a colour split in two adds a colour change).`);
}
// a DST sewn again in a new order of its pieces (segment numbers): trimmed between pieces, a colour
// change where the colour block changes (a block whose pieces part comes twice)
function arrangeDst(order) {
  const segs = segments(), keep = new Set(C.sels), cols = [], out = [], used = {};
  const hadEnd = C.st[C.st.length - 1]?.[2] === 4;
  let prev = null;
  for (const k of order) {
    const [s, e, b] = segs[k];
    let recs = C.st.slice(s, e).filter((p) => p[2] === 0 || p[2] === 1);
    const first = recs.find((p) => p[2] === 0);
    if (recs[0][2] !== 1) recs = [[first[0], first[1], 1], ...recs];      // a jump to its first stitch
    const last = out[out.length - 1];
    if (last) { out.push([last[0], last[1], 2]); if (b !== prev) out.push([last[0], last[1], 3]); }
    if (b !== prev) {
      const n = used[b] || 0; used[b] = n + 1;
      cols.push(n ? { ...C.colors[b], id: `${C.colors[b].id}~${n}` } : C.colors[b]);
      prev = b;
    }
    out.push(...recs);
  }
  const end = out[out.length - 1];
  if (hadEnd && end) out.push([end[0], end[1], 4]);
  C.st = out; C.colors = cols; C.changed = true;
  C.sels = order.map((k, i) => (keep.has(k) ? i : -1)).filter((i) => i >= 0);    // the same pieces, where they are now
  afterDst();
}
function openArrangeMenu() {
  const m = $("#arrangeMenu"), r = $("#toolArrange").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  updateArrangeMenu();
}
function updateArrangeMenu() {
  for (const b of document.querySelectorAll("#arrangeMenu [data-arrange]")) b.disabled = !hasSel();
  $("#arrangeHint").textContent = hasSel() ? "In embroidery the front is what is sewn last: these change the sewing order." : "In embroidery the front is what is sewn last. Select pieces first.";
}

// ---------------------------------------------------------------- align and distribute
// each selected piece by its box (0.1 mm, y up): moved so the chosen edges or centres line up, or are
// spaced evenly; all of it one undo
function alignPieces(how) {
  const keys = [...C.sels];
  if (!keys.length) return;
  const boxes = keys.map((k) => bbox(ringsOf(k)));
  if (how.startsWith("d") && keys.length < 3) { toast("Select three or more pieces to distribute them."); return; }
  // to each other; one piece: to the whole design
  const ref = keys.length > 1 ? bbox(boxes.map(([a, b, c, d]) => [[a, b], [c, d]])) : bbox(allPieces().flatMap(ringsOf));
  const at = { left: (b) => b[0], right: (b) => b[2], hcenter: (b) => (b[0] + b[2]) / 2,
               bottom: (b) => b[1], top: (b) => b[3], vcenter: (b) => (b[1] + b[3]) / 2 };
  const moves = boxes.map(() => [0, 0]);
  const line = (name, axis) => boxes.forEach((b, i) => { moves[i][axis] = at[name](ref) - at[name](b); });
  if (how === "center") { line("hcenter", 0); line("vcenter", 1); }
  else if (["left", "right", "hcenter"].includes(how)) line(how, 0);
  else if (["top", "bottom", "vcenter"].includes(how)) line(how, 1);
  else {                        // distribute: the first and last stay, the rest evenly between them
    const name = { dleft: "left", dhcenter: "hcenter", dright: "right", dtop: "top", dvcenter: "vcenter", dbottom: "bottom" }[how];
    const axis = ["left", "hcenter", "right"].includes(name) ? 0 : 1;
    const order = boxes.map((b, i) => i).sort((i, j) => at[name](boxes[i]) - at[name](boxes[j]));
    const lo = at[name](boxes[order[0]]), hi = at[name](boxes[order[order.length - 1]]);
    order.forEach((i, n) => { moves[i][axis] = lo + (hi - lo) * n / (order.length - 1) - at[name](boxes[i]); });
  }
  if (moves.every(([x, y]) => Math.abs(x) < 0.5 && Math.abs(y) < 0.5)) { toast("Already lined up."); return; }
  remember();
  keys.forEach((k, i) => { if (Math.abs(moves[i][0]) >= 0.5 || Math.abs(moves[i][1]) >= 0.5) { C.sels = [k]; transform(moves[i], 1, 0, null, true); } });
  C.sels = keys;
  repaint();
}
function openAlignMenu() {
  const m = $("#alignMenu"), r = $("#toolAlign").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  updateAlignMenu();
}
function updateAlignMenu() {
  const n = C.sels.length;
  for (const b of document.querySelectorAll("#alignMenu [data-align]")) b.disabled = b.dataset.align.startsWith("d") ? n < 3 : n < 1;
  $("#alignHint").textContent = n === 0 ? "Select pieces, then align them to each other (one piece: to the whole design). Distribute needs three or more."
    : n === 1 ? "1 piece selected: it is aligned on the whole design. Select three or more to distribute."
    : `${n} pieces selected: aligned to each other${n < 3 ? "; distribute needs three or more" : ""}.`;
}
const turn = (deg) => transform([0, 0], 1, deg * Math.PI / 180);
const resize = (f) => transform([0, 0], f, 0);
const stretch = (fx, fy, at) => transform([0, 0], [fx, fy], 0, at);

// a DST piece resized by f (a factor, or a function: how much longer a stitch lying along [dx, dy] became):
// its stitches spaced again as they were. A satin (stitches going back and
// forth across) gets its two edges walked again at the old spacing; a run (an underlay, a travel)
// gets its stretched stitches split back to their old length. Records [s, e) of C.st.
function respace(s, e, f) {
  const ratio = typeof f === "function" ? f : () => f;
  const out = [];
  let run = [];
  const flush = () => { if (run.length) { out.push(...respaceRun(run, ratio).map(([x, y]) => [x, y, 0])); run = []; } };
  for (let i = s; i < e; i++) {
    const p = C.st[i];
    if (p[2] === 0) run.push([p[0], p[1]]); else { flush(); out.push(p); }
  }
  flush();
  C.st.splice(s, e - s, ...out);
}
function respaceRun(pts, ratio) {
  if (pts.length < 3) return pts;
  // each stitch: part of a satin when it is over 0.8 mm and turns back on the one before it
  const n = pts.length - 1, seg = (i) => [pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]];
  const back = new Array(n).fill(false);
  for (let i = 1; i < n; i++) {
    const u = seg(i - 1), v = seg(i);
    back[i] = Math.hypot(...u) > 8 && Math.hypot(...v) > 8 && u[0] * v[0] + u[1] * v[1] < 0;
  }
  const out = [pts[0]];
  const runPart = (i0, i1) => {                // stitches i0..i1-1 of a run: stretched ones split back
    for (let i = i0; i < i1; i++) {
      const [x0, y0] = pts[i], [x1, y1] = pts[i + 1], f = ratio([x1 - x0, y1 - y0]), parts = f > 1 ? Math.max(1, Math.round(f)) : 1;
      for (let j = 1; j <= parts; j++) out.push([x0 + (x1 - x0) * j / parts, y0 + (y1 - y0) * j / parts]);
    }
  };
  let i = 0;
  while (i < n) {
    let j = i;
    while (j < n && back[j]) j++;
    if (j - i >= 6) {                          // a satin: stitches i-1..j-1, points i-1..j; its edges walked again
      const zz = pts.slice(i - 1, j + 1);
      const A = zz.filter((_p, k) => k % 2 === 0), B = zz.filter((_p, k) => k % 2 === 1);
      const along = [A[A.length - 1][0] - A[0][0], A[A.length - 1][1] - A[0][1]];       // the way the satin runs
      const m = Math.max(2, Math.round(Math.min(A.length, B.length) * ratio(along)));
      const a = resample(A, m), b = resample(B, m);
      out.pop();                               // its first point is the one before: walked again too
      for (let k = 0; k < m; k++) out.push(a[k], b[k]);
      out.push(pts[j]);                        // and on from its last point, as before
      i = j;
      if (i >= n) break;
      runPart(i, i + 1); i += 1;
      continue;
    }
    runPart(i, Math.max(j, i + 1));
    i = Math.max(j, i + 1);
  }
  return out;
}
function resample(line, m) {                    // m points evenly along a polyline
  const d = [0];
  for (let i = 1; i < line.length; i++) d.push(d[i - 1] + Math.hypot(line[i][0] - line[i - 1][0], line[i][1] - line[i - 1][1]));
  const L = d[d.length - 1], out = [];
  for (let k = 0, j = 0; k < m; k++) {
    const t = m === 1 ? 0 : L * k / (m - 1);
    while (j < line.length - 2 && d[j + 1] < t) j++;
    const w = d[j + 1] > d[j] ? (t - d[j]) / (d[j + 1] - d[j]) : 0;
    out.push([line[j][0] + (line[j + 1][0] - line[j][0]) * w, line[j][1] + (line[j + 1][1] - line[j][1]) * w]);
  }
  return out;
}

function afterDst() {           // a DST changed: its totals, the size fields, the preview
  C.sels = C.sels.filter((k) => k < segments().length);
  dstStats();
  $("#w").value = inches(C.info.width_mm / MM); $("#h").value = inches(C.info.height_mm / MM);
  $("#step").max = C.st.length; $("#step").value = C.st.length;
  renderColors(); draw();
}
function dstStats() {
  const pts = C.st.filter((p) => p[2] === 0);
  const [x0, y0, x1, y1] = bbox([pts]);
  const w = (x1 - x0) / 10, h = (y1 - y0) / 10, n = pts.length, cols = C.colors.length;
  C.info = { stitches: n, colors: cols, stops: 0, trims: C.st.filter((p) => p[2] === 2).length, width_mm: +w.toFixed(1),
             height_mm: +h.toFixed(1), minutes: n / 650, satin_parts: 0, fill_parts: 0, notes: [], aspect: h ? w / h : 1, objects: segments().length };
  C.info.details = [["Height", `${(h / MM).toFixed(2)} in`], ["Width", `${(w / MM).toFixed(2)} in`], ["Stitches", n.toLocaleString()],
    ["Colors", cols], ["Stops", cols], ["Colorways", 1], ["Trims", C.info.trims], ["Color changes", Math.max(0, cols - 1)],
    ["Appliqués", 0], ["Sequins", 0], ["Bling", 0], ["Machine format", "Tajima"], ["Objects", C.info.objects]];
  showStats();
}
// a DST resized from the size fields: every stitch scaled about the design's centre, then spaced
// again as it was, piece by piece
function dstResizeTo(wIn, hIn) {
  const pts = C.st.filter((p) => p[2] === 0);
  const [x0, y0, x1, y1] = bbox([pts]);
  const f = wIn > 0 ? wIn * MM * 10 / (x1 - x0) : hIn > 0 ? hIn * MM * 10 / (y1 - y0) : 1;
  if (!(f > 0) || Math.abs(f - 1) < 1e-3) return afterDst();
  const all = C.sels; C.sels = segments().map((_g, k) => k);
  const c = [(x0 + x1) / 2, (y0 + y1) / 2], map = turnAbout(c, f, 0);
  remember();
  for (let i = 0; i < C.st.length; i++) { const [x, y] = map(C.st[i]); C.st[i] = [x, y, C.st[i][2]]; }
  if (Math.abs(f - 1) > 0.05) for (const [s, e] of segments().sort((p, q) => q[0] - p[0])) respace(s, e, f);
  for (let i = 0; i < C.st.length; i++) C.st[i] = [Math.round(C.st[i][0]), Math.round(C.st[i][1]), C.st[i][2]];
  C.sels = all; C.changed = true;
  afterDst();
}
function remove() {
  if (!hasSel()) return;
  if (isDst()) {
    const segs = segments();
    if (C.sels.length >= segs.length) { toast("That is the whole design: keep at least one piece.", true); return; }
    remember();
    for (const k of [...C.sels].sort((p, q) => segs[q][0] - segs[p][0])) {       // last first: the indices stay right
      const [s, e, b] = segments().find((g) => g[0] === segs[k][0]);
      if (segments().filter((g) => g[2] === b).length > 1) C.st.splice(s, e - s);
      else {                    // the last piece of its colour: the colour block goes with it
        const [bs, be] = blocks()[b];
        const from = b > 0 ? bs - 1 : bs, to = b > 0 ? be : be + 1;
        C.st.splice(from, to - from);
        C.colors.splice(b, 1);
      }
    }
    C.sels = []; C.changed = true; afterDst();
    return;
  }
  remember();
  const edits = { ...C.edits };
  C.shapes = C.shapes.filter((sh) => sh.sewn || !C.sels.includes("draft:" + sh.id));
  for (const key of C.sels) if (!String(key).startsWith("draft:")) edits[key] = { ...ID, ...(edits[key] || {}), deleted: true };
  C.edits = edits; C.sels = [];
  markDirty();
}
// the selection given a thread from the palette
function recolourSel(anchor) {
  if (!hasSel()) return;
  openPalette(anchor, (t) => {
    remember();
    if (isDst()) { recolourPieces(C.sels, t); C.changed = true; afterDst(); return; }
    C.pieceThreads[t.hex] = t;
    C.shapeThreads[t.hex.toLowerCase()] = t;
    C.shapes = C.shapes.map((sh) => (!sh.sewn && C.sels.includes("draft:" + sh.id) ? { ...sh, hex: t.hex.toLowerCase() } : sh));
    const edits = { ...C.edits };
    for (const key of C.sels) if (!String(key).startsWith("draft:")) edits[key] = { ...ID, ...(edits[key] || {}), color: t.hex };
    C.edits = edits; markDirty();
  });
}
// DST pieces given a thread: a colour whose pieces are all picked takes it; else the picked pieces of
// each colour become one colour block of their own, sewn right after the block they came from
function recolourPieces(ks, t) {
  const segs = segments(), byBlock = {};
  for (const k of ks) { const g = segs[k]; if (g) (byBlock[g[2]] = byBlock[g[2]] || []).push(g); }
  const firsts = ks.map((k) => segs[k]?.[0]);
  for (const b of Object.keys(byBlock).map(Number).sort((p, q) => q - p)) {     // last block first
    const mine = byBlock[b];
    if (segs.filter((g) => g[2] === b).length === mine.length) { Object.assign(C.colors[b], { hex: t.hex, thread: t, name: `${t.num} ${t.name}` }); continue; }
    let moved = [];
    for (const [s, e] of [...mine].sort((p, q) => q[0] - p[0])) {
      let piece = C.st.slice(s, e).filter((p) => p[2] !== 4);
      C.st.splice(s, e - s);
      const first = piece.find((p) => p[2] === 0);
      if (piece[0][2] !== 1) piece = [[first[0], first[1], 1], ...piece];       // a jump to its first stitch
      moved = [...piece, [first[0], first[1], 2], ...moved];                    // sewn in their order, trimmed between
    }
    let end = blocks()[b][1];                             // the block's end, without the pieces
    if (C.st[end - 1]?.[2] === 4) end -= 1;               // (before the end of the design)
    const at = C.st[Math.max(0, end - 1)] || moved[0];
    C.st.splice(end, 0, [at[0], at[1], 2], [at[0], at[1], 3], ...moved.slice(0, -1));
    C.colors.splice(b + 1, 0, { id: `block${Date.now()}${b}`, hex: t.hex, thread: t, name: `${t.num} ${t.name}` });
  }
  // the same pieces stay selected, where they are now
  const now = segments();
  C.sels = now.map((g, k) => [g, k]).filter(([g]) => g[2] > 0 && C.colors[g[2]]?.thread === t).map(([, k]) => k);
  if (!C.sels.length) C.sels = firsts.map((s) => now.findIndex((g) => g[0] === s)).filter((k) => k >= 0);
}
function resetEdits() {
  if (isDst()) { if (C.undo.length) { const first = C.undo[0]; C.redo = []; C.undo = []; restore(first); } return; }
  if (!Object.keys(C.edits).length && !C.shapes.length) return;
  remember(); C.edits = {}; C.lock = null; C.sels = []; C.shapes = []; C.arrange = null; markDirty();
}

// ---------------------------------------------------------------- the pointer
const cv = $("#canvas");
cv.addEventListener("pointerdown", (ev) => {
  if (!C.view || !C.st) return;
  if (C.tool === "zoom") {      // click: zoom in (option: out); drag: move around
    E.drag = { mode: "zoom", sx: ev.clientX, sy: ev.clientY, cam: C.cam, pt: toDesign(ev), out: ev.altKey, moved: false };
    try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
    return;
  }
  if (C.tool === "hand") { handDown(ev); return; }
  if (C.tool === "pen") { penDown(ev); return; }
  if (C.tool !== "select") {    // a shape: drag it out
    const pt = toDesign(ev);
    E.drag = { mode: "draw", start: pt, cur: pt, path: [], closed: true, width_mm: +$("#penWidth").value };
    try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
    return;
  }
  const pt = toDesign(ev), dot = cornerDotAt(ev);
  if (dot) {                    // a corner's dot: a click picks it, a drag rounds the corners
    E.drag = { mode: "corner", start: pt, cur: pt, moved: false, shift: ev.shiftKey, i: dot.d.i, bis: dot.d.bis, sinH: dot.d.sinH, r0: [...dot.c.r] };
    try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
    return;
  }
  const h = handleAt(ev);
  let mode = h?.mode;
  if (!h) {
    const k = pieceAt(pt);
    C.cornerSel = [];             // the shape itself clicked: all its corners again
    if (k === null) {           // empty space: drag a box to select what is inside it
      if (!ev.shiftKey) C.sels = [];
      E.drag = { mode: "box", start: pt, cur: pt, keep: [...C.sels] };
      try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
      repaint();
      return;
    }
    if (ev.shiftKey) {          // shift: add the piece, or take it away
      C.sels = C.sels.includes(k) ? C.sels.filter((x) => x !== k) : [...C.sels, k];
      repaint();
      return;
    }
    if (!C.sels.includes(k)) C.sels = [k];
    mode = "move";
  }
  E.drag = { mode, start: pt, cur: pt, c: centroid(selOutlines()), fx: 1, fy: 1, a: 0 };
  if (mode === "scale") {       // resized about the opposite side or corner, which stays where it is
    const [x0, y0, x1, y1] = bbox(selOutlines());
    Object.assign(E.drag, { hx: h.hx, hy: h.hy, anchor: [h.hx > 0 ? x0 : h.hx < 0 ? x1 : (x0 + x1) / 2, h.hy > 0 ? y0 : h.hy < 0 ? y1 : (y0 + y1) / 2] });
  }
  try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
  repaint();
});
cv.addEventListener("pointermove", (ev) => {
  if (!C.view || !C.st) return;
  if (C.tool === "zoom") {
    cv.style.cursor = E.drag ? "grabbing" : ev.altKey ? "zoom-out" : "zoom-in";
    const d = E.drag;
    if (d?.mode === "zoom" && C.zoom > 1.001) {
      const dx = ev.clientX - d.sx, dy = ev.clientY - d.sy;
      if (Math.hypot(dx, dy) > 3) d.moved = true;
      if (d.moved) { C.cam = [d.cam[0] - dx / C.view.k, d.cam[1] + dy / C.view.k]; draw(); }
    }
    return;
  }
  if (C.tool === "hand") { if (E.drag) handMove(ev); return; }
  if (C.tool === "pen") { penMove(ev); return; }
  if (!E.drag) {
    if (C.tool !== "select") { cv.style.cursor = "crosshair"; return; }
    if (cornerDotAt(ev)) { cv.style.cursor = "pointer"; return; }
    const h = handleAt(ev);
    cv.style.cursor = h?.mode === "scale" ? HANDLE_CURSOR[`${h.hx},${h.hy}`] : h?.mode === "rotate" ? "grab" : pieceAt(toDesign(ev)) !== null ? "move" : "crosshair";
    return;
  }
  const d = E.drag; d.cur = toDesign(ev);
  if (d.mode === "corner") {    // along the line into the corner: the radius follows the dot
    const along = (d.cur[0] - d.start[0]) * d.bis[0] + (d.cur[1] - d.start[1]) * d.bis[1];
    if (!d.moved && Math.abs(along) * C.view.k < 3) return;
    const c = cornerShape();
    if (!c) return;
    if (!d.moved) { d.moved = true; remember(); if (c.sh.sewn) { unsew(c.sh); Object.assign(c, cornersOf(c.sh)); d.r0 = [...c.r]; } }
    const s = C.info.frame.s, r = [...d.r0], dr = along * d.sinH / 10;          // 0.1 mm -> mm
    for (const i of cornerTargets(c, d.i)) r[i] = Math.max(0, Math.min((d.r0[i] || 0) + dr, cornerMax(c.base, i) * s));
    setCorners(c.sh, c.base, r, c.style);
    repaint();
    if (!$("#cornerMenu").hidden) updateCornerMenu();
    return;
  }
  if (d.mode === "draw") {
    d.path = shapeOutline(C.tool.slice(6), d.start, d.cur, ev.shiftKey);
    repaint();
    return;
  }
  if (d.mode === "box") {       // every piece whose middle is inside the box
    const [x0, x1] = [Math.min(d.start[0], d.cur[0]), Math.max(d.start[0], d.cur[0])];
    const [y0, y1] = [Math.min(d.start[1], d.cur[1]), Math.max(d.start[1], d.cur[1])];
    const inside = allPieces().filter((k) => { const [a, b, c, e] = bbox(ringsOf(k)); const mx = (a + c) / 2, my = (b + e) / 2; return mx >= x0 && mx <= x1 && my >= y0 && my <= y1; });
    C.sels = [...new Set([...d.keep, ...inside])];
    repaint();
    return;
  }
  const [c0, c1] = d.c;
  if (d.mode === "scale") {    // a side: that way only; a corner: both, freely; shift: in proportion
    const [px, py] = d.anchor, sx = d.start[0] - px, sy = d.start[1] - py;
    const rx = d.hx && Math.abs(sx) > 1 ? (d.cur[0] - px) / sx : 1, ry = d.hy && Math.abs(sy) > 1 ? (d.cur[1] - py) / sy : 1;
    let fx = rx, fy = ry;
    if (ev.shiftKey) {
      const f = d.hx && d.hy ? ((d.cur[0] - px) * sx + (d.cur[1] - py) * sy) / Math.max(1, sx * sx + sy * sy) : d.hx ? rx : ry;
      fx = fy = f;
    }
    d.fx = Math.min(20, Math.max(0.05, fx)); d.fy = Math.min(20, Math.max(0.05, fy));
  }
  if (d.mode === "rotate") {
    let a = Math.atan2(d.cur[1] - c1, d.cur[0] - c0) - Math.atan2(d.start[1] - c1, d.start[0] - c0);
    if (ev.shiftKey) a = Math.round(a / (Math.PI / 12)) * (Math.PI / 12);        // shift: 15° steps
    d.a = a;
  }
  repaint();
});
function endDrag() {
  if (C.tool === "hand") { E.drag = null; $("#canvas").style.cursor = "grab"; return; }
  if (C.tool === "pen") { E.drag = null; return; }
  if (C.tool === "zoom") {
    const d = E.drag; E.drag = null;
    if (d && !d.moved) zoomAt(d.out ? 1 / 1.5 : 1.5, d.pt);
    return;
  }
  const d = E.drag;
  E.drag = null;
  if (!d) return;
  if (d.mode === "draw") { addShape(d); return; }
  if (d.mode === "corner") {
    if (d.moved) markDirty();
    else C.cornerSel = d.shift ? (C.cornerSel.includes(d.i) ? C.cornerSel.filter((x) => x !== d.i) : [...C.cornerSel, d.i]) : [d.i];
    repaint();
    return;
  }
  if (d.mode === "box") { repaint(); return; }
  const moved = Math.hypot(d.cur[0] - d.start[0], d.cur[1] - d.start[1]) > 2;      // 0.2 mm: a click, not a drag
  if (d.mode === "move" && moved) nudge(d.cur[0] - d.start[0], d.cur[1] - d.start[1]);
  else if (d.mode === "scale" && Math.max(Math.abs(d.fx - 1), Math.abs(d.fy - 1)) > 0.01) stretch(d.fx, d.fy, d.anchor);
  else if (d.mode === "rotate" && Math.abs(d.a) > 0.005) turn(d.a * 180 / Math.PI);
  else repaint();
}
cv.addEventListener("pointerup", endDrag);
cv.addEventListener("pointercancel", () => { E.drag = null; repaint(); });

// ---------------------------------------------------------------- keys (not while typing in a field)
document.addEventListener("keydown", (ev) => {
  const t = ev.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  if (!C.st || !C.view) return;
  const mod = ev.metaKey || ev.ctrlKey;
  if (mod && ev.key.toLowerCase() === "z") { ev.preventDefault(); ev.shiftKey ? redo() : undo(); return; }
  if (mod && ev.key.toLowerCase() === "y") { ev.preventDefault(); redo(); return; }
  if (C.tool === "pen" && E.pen) {             // the pen: Enter finishes a line, Backspace takes the last point back
    if (ev.key === "Enter") { ev.preventDefault(); penFinish(false); return; }
    if (ev.key === "Escape") { ev.preventDefault(); E.pen = null; repaint(); return; }
    if (ev.key === "Backspace" || ev.key === "Delete") { ev.preventDefault(); E.pen.pts.pop(); if (!E.pen.pts.length) E.pen = null; repaint(); return; }
  }
  if (mod && ev.key.toLowerCase() === "a") { ev.preventDefault(); C.sels = allPieces(); repaint(); return; }
  if (mod && (ev.code === "BracketRight" || ev.code === "BracketLeft")) {   // ⌘] ⌘[ (shift: all the way)
    ev.preventDefault();
    arrangePieces(ev.code === "BracketRight" ? (ev.shiftKey ? "front" : "forward") : (ev.shiftKey ? "back" : "backward"));
    return;
  }
  if (!mod && !ev.altKey && ev.key.toLowerCase() === "z" && !(C.tool === "pen" && E.pen)) { ev.preventDefault(); setTool(C.tool === "zoom" ? "select" : "zoom"); return; }
  if (!mod && !ev.altKey && ev.key.toLowerCase() === "h") { ev.preventDefault(); toggleHand(); return; }
  if (ev.key === "Escape" && C.tool !== "select") { setTool("select"); return; }
  if (!hasSel()) return;
  const step = ev.shiftKey ? 25 : 5;           // 0.1 mm: 0.5 mm, or 2.5 mm with shift
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
  if (ev.key === "Delete" || ev.key === "Backspace") { ev.preventDefault(); remove(); }
  else if (moves[ev.key]) { ev.preventDefault(); nudge(...moves[ev.key]); }
  else if (ev.key === "Escape") { C.sels = []; setTool("select"); repaint(); }
});

// ---------------------------------------------------------------- the tool strip
const tools = {
  toolTurnL: () => turn(15), toolTurnR: () => turn(-15), toolBigger: () => resize(1.1), toolSmaller: () => resize(1 / 1.1),
  toolColour: (ev) => recolourSel(ev.currentTarget), toolDelete: remove, toolUndo: undo, toolRedo: redo, toolReset: resetEdits,
};
for (const [id, fn] of Object.entries(tools)) $("#" + id).addEventListener("click", fn);
function updateTools() {
  $("#tools").hidden = !(C.st && (isDst() || C.digitized));
  for (const id of ["toolTurnL", "toolTurnR", "toolBigger", "toolSmaller", "toolColour", "toolDelete"]) $("#" + id).disabled = !hasSel();
  $("#toolUndo").disabled = !C.undo.length; $("#toolRedo").disabled = !C.redo.length;
  $("#toolReset").disabled = isDst() ? !C.undo.length : !(Object.keys(C.edits || {}).length || C.shapes.length);
  $("#toolSelect").setAttribute("aria-pressed", C.tool === "select");
  $("#toolShapes").setAttribute("aria-pressed", C.tool.startsWith("shape:"));
  $("#toolPen").setAttribute("aria-pressed", C.tool === "pen");
  $("#toolText").setAttribute("aria-pressed", !$("#textMenu").hidden);
  $("#toolHand").setAttribute("aria-pressed", C.tool === "hand");
  $("#toolAlign").setAttribute("aria-pressed", !$("#alignMenu").hidden);
  $("#toolCorners").disabled = isDst();
  $("#toolCorners").setAttribute("aria-pressed", !$("#cornerMenu").hidden);
  if (!$("#cornerMenu").hidden) updateCornerMenu();
  $("#toolArrange").setAttribute("aria-pressed", !$("#arrangeMenu").hidden);
  if (!$("#arrangeMenu").hidden) updateArrangeMenu();
  if (!$("#alignMenu").hidden) updateAlignMenu();
  $("#toolPathfinder").disabled = isDst();      // shapes drawn on a logo (a DST's pieces are stitches)
  $("#toolPathfinder").setAttribute("aria-pressed", !$("#pathMenu").hidden);
  if (!$("#pathMenu").hidden) updatePathMenu();
  $("#toolZoom").setAttribute("aria-pressed", C.tool === "zoom");
  $("#toolZoomOut").disabled = !(C.zoom > 1.001);
  $("#toolFit").disabled = !(C.zoom > 1.001 || C.cam);       // also after the hand moved the view
  $("#toolFit").title = `Fit: the whole design in view (now ${Math.round((C.zoom || 1) * 100)}%)`;
}

// ---------------------------------------------------------------- shapes and the pen
// an outline in a unit box [0, 1] x [0, 1] (y up)
function unitShape(kind) {
  const ring = (n, f) => Array.from({ length: n }, (_v, i) => f((i / n) * 2 * Math.PI));
  switch (kind) {
    case "circle": return ring(72, (a) => [0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)]);
    case "square": case "rectangle": return [[0, 0], [1, 0], [1, 1], [0, 1]];
    case "rounded": {
      const out = [], r = 0.2;
      for (const [cx, cy, a0] of [[1 - r, r, -90], [1 - r, 1 - r, 0], [r, 1 - r, 90], [r, r, 180]])
        for (let i = 0; i <= 8; i++) { const a = (a0 + i * 90 / 8) * Math.PI / 180; out.push([cx + r * Math.cos(a), cy + r * Math.sin(a)]); }
      return out;
    }
    case "triangle": return [[0, 0], [1, 0], [0.5, 1]];
    case "diamond": return [[0.5, 0], [1, 0.5], [0.5, 1], [0, 0.5]];
    case "hexagon": return ring(6, (a) => [0.5 + 0.5 * Math.cos(a), 0.5 + 0.5 * Math.sin(a)]);
    case "star": return Array.from({ length: 10 }, (_v, i) => {
      const a = Math.PI / 2 + i * Math.PI / 5, r = i % 2 ? 0.2 : 0.5;
      return [0.5 + r * Math.cos(a), 0.52 + r * Math.sin(a)];
    });
    case "heart": return ring(72, (t) => {
      const x = 16 * Math.sin(t) ** 3, y = 13 * Math.cos(t) - 5 * Math.cos(2 * t) - 2 * Math.cos(3 * t) - Math.cos(4 * t);
      return [0.5 + x / 34, 0.6 + y / 34];
    });
    case "arrow": return [[0, 0.32], [0.6, 0.32], [0.6, 0.05], [1, 0.5], [0.6, 0.95], [0.6, 0.68], [0, 0.68]];
  }
  return [[0, 0], [1, 0], [1, 1], [0, 1]];
}
// the shape dragged from a to b (0.1 mm); even: as wide as tall (circle, square, star, heart... always)
function shapeOutline(kind, a, b, even) {
  let w = b[0] - a[0], h = b[1] - a[1];
  if (even || !["rectangle", "rounded", "arrow"].includes(kind)) {
    const m = Math.max(Math.abs(w), Math.abs(h));
    w = Math.sign(w || 1) * m; h = Math.sign(h || 1) * m;
  }
  const x0 = Math.min(a[0], a[0] + w), y0 = Math.min(a[1], a[1] + h);
  return unitShape(kind).map(([u, v]) => [x0 + u * Math.abs(w), y0 + v * Math.abs(h)]);
}
function drawShapePath(g, path, closed, widthMm, hex, alpha) {
  if (!path || path.length < 2 || !C.view) return;
  const dpr = C.view.dpr;
  g.save();
  g.beginPath();
  path.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.globalAlpha = alpha;
  if (closed) { g.closePath(); g.fillStyle = hex; g.fill(); }
  else { g.strokeStyle = hex; g.lineCap = g.lineJoin = "round"; g.lineWidth = widthMm * 10 * C.view.k * dpr; g.stroke(); }
  g.globalAlpha = 1; g.setLineDash([4 * dpr, 3 * dpr]); g.strokeStyle = "rgba(10,132,255,.9)"; g.lineWidth = 1 * dpr;
  if (closed) g.stroke();
  g.restore();
}
function drawRings(g, rings, hex, alpha) {      // a shape with holes: filled even-odd, each outline dashed
  if (!C.view) return;
  const dpr = C.view.dpr;
  g.save();
  g.beginPath();
  for (const r of rings) r.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.globalAlpha = alpha; g.fillStyle = hex; g.fill("evenodd");
  g.globalAlpha = 1; g.setLineDash([4 * dpr, 3 * dpr]); g.strokeStyle = "rgba(10,132,255,.9)"; g.lineWidth = 1 * dpr;
  for (const r of rings) { g.beginPath(); r.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); g.closePath(); g.stroke(); }
  g.restore();
}
// the thread new shapes are sewn in: picked in the menu, else the first colour's
function drawThread() {
  if (C.drawThread) return C.drawThread;
  if (isDst()) return C.colors[0]?.thread || { num: "", name: "", hex: C.colors[0]?.hex || "#1d1d1b" };
  const c = C.plan.find((p) => thread(p));
  return c ? thread(c) : { num: "", name: "", hex: "#1d1d1b" };
}
const drawHex = () => drawThread().hex;
// a point of the design (0.1 mm, y up, as shown) as a pixel of the logo image (the digitizer's frame)
function fromPxFrame([X, Y]) {                  // toPxFrame turned back: image pixels -> 0.1 mm on the design
  const f = C.info.frame, t = (f.tilt || 0) * Math.PI / 180, a = X - f.cx, b = f.cy - Y;
  const u = a * Math.cos(t) - b * Math.sin(t), v = a * Math.sin(t) + b * Math.cos(t);
  return [(u - f.mx) * f.s * 10, ((v - f.my) * f.s + f.lift) * 10];
}
function toPxFrame([x, y]) {
  const f = C.info.frame, t = (f.tilt || 0) * Math.PI / 180;
  let X = x / 10 / f.s + f.mx, Y = (y / 10 - f.lift) / f.s + f.my;
  [X, Y] = [X * Math.cos(t) + Y * Math.sin(t), -X * Math.sin(t) + Y * Math.cos(t)];
  return [X + f.cx, -Y + f.cy];
}
function simplifyPath(pts, tol) {               // fewer points, the line kept within tol (0.1 mm)
  if (pts.length < 3) return pts;
  const keep = [pts[0]];
  let last = pts[0];
  for (let i = 1; i < pts.length - 1; i++) if (Math.hypot(pts[i][0] - last[0], pts[i][1] - last[1]) >= tol) { keep.push(pts[i]); last = pts[i]; }
  keep.push(pts[pts.length - 1]);
  return keep;
}
async function addShape(d) {     // d: {path, closed, width_mm}, or text: {rings (0.1 mm, even-odd), text}
  const path = d.rings ? d.rings.flat() : d.path;
  const [x0, y0, x1, y1] = bbox([path]);
  if (path.length < 2 || Math.max(x1 - x0, y1 - y0) < 15) { toast("Draw it larger: at least 1.5 mm."); repaint(); return; }
  const t = drawThread(), closed = !!d.rings || (d.closed && path.length >= 3);
  if (isDst()) {                // sewn now, as a colour of its own at the end
    busy(true, d.rings ? "Sewing the text…" : "Sewing the shape…");
    try {
      const r = await post("/api/cap/shape", { ...(d.rings ? { rings: d.rings } : { pts: path, closed, width_mm: d.width_mm }),
        options: { density: 0.4, pull_comp: 0.2, order: "center" } });
      const j = await r.json();
      if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
      remember();
      const piece = j.stitches.filter((p) => p[2] !== 4);
      const first = piece.find((p) => p[2] === 0);
      if (piece[0][2] !== 1) piece.unshift([first[0], first[1], 1]);
      let end = C.st.length;
      if (C.st[end - 1]?.[2] === 4) end -= 1;
      const at = C.st[end - 1];
      // in the thread of the last colour: sewn on in it (a trim, no colour change); else a colour of its own
      const same = C.colors[C.colors.length - 1]?.hex.toLowerCase() === t.hex.toLowerCase();
      C.st.splice(end, 0, [at[0], at[1], 2], ...(same ? [] : [[at[0], at[1], 3]]), ...piece);
      if (!same) C.colors.push({ id: `block${Date.now()}`, hex: t.hex, thread: t.num ? t : null, name: t.num ? `${t.num} ${t.name}` : `Colour ${C.colors.length + 1}` });
      C.changed = true;
      afterDst();
      const segs = segments();
      C.sels = segs.map((_g, k) => k).filter((k) => segs[k][0] >= end);       // the new shape's pieces
      setTool("select");
      repaint();
    } catch (e) { toast(e.message, true, 6000); repaint(); }
    finally { busy(false); }
    return;
  }
  // a logo: kept in the logo's own pixels, sewn when it is digitized again (the scale stays)
  remember();
  if (!C.lock) C.lock = C.info.mm_per_px;
  const id = (C.shapes.reduce((m, sh) => Math.max(m, sh.id), 0) || 0) + 1;
  if (t.num) C.shapeThreads[t.hex.toLowerCase()] = t;
  const shape = d.rings
    ? { view: d.rings[0], px: d.rings[0].map(toPxFrame), rings: d.rings, pxRings: d.rings.map((r) => r.map(toPxFrame)), text: d.text }
    : { view: path, px: path.map(toPxFrame) };
  C.shapes = [...C.shapes, { id, hex: t.hex.toLowerCase(), ...shape, closed,
                             width: (d.width_mm || 1.5) / C.lock, width_mm: d.width_mm || 1.5, sewn: false }];
  C.sels = ["draft:" + id];                     // selected, to move, resize, turn, recolour or delete
  setTool("select");
  markDirty();
  toast(`${d.rings ? "Text" : closed ? "Shape" : "Line"} added and selected. Click Update Digitizing to sew it.`);
}
// ---------------------------------------------------------------- text
// lettering in a font (the server turns it into outlines), placed in the middle of the view; a text
// not sewn yet, selected, is changed in place (its words, font, height) where it stands
function textDraft() {
  const sh = C.sels.length === 1 && draftOf(C.sels[0]);
  return sh && sh.text ? sh : null;
}
function textValues() {
  return { text: $("#textInput").value, font: $("#textFont").value, height_mm: +$("#textHeight").value || 8,
           spacing_mm: +$("#textSpacing").value || 0, align: $("#textAlign").value };
}
function showTextPreview() {
  const p = $("#textPreview"), v = textValues();
  p.style.fontFamily = `"emb-${v.font}", sans-serif`;
  p.style.letterSpacing = `${v.spacing_mm * 2}px`;
  p.style.textAlign = v.align;
  p.textContent = v.text.trim() ? v.text : "Your Text";
}
function openTextMenu() {
  for (const id of ["#drawMenu", "#penMenu", "#pathMenu", "#alignMenu", "#arrangeMenu", "#cornerMenu"]) $(id).hidden = true;
  const m = $("#textMenu"), r = $("#toolText").getBoundingClientRect(), sh = textDraft();
  if (sh) {                                     // the selected text: its settings, to change it
    $("#textInput").value = sh.text.text; $("#textFont").value = sh.text.font; $("#textHeight").value = sh.text.height_mm;
    $("#textSpacing").value = sh.text.spacing_mm; $("#textAlign").value = sh.text.align;
  }
  $("#textAdd").textContent = sh ? "Update text" : "Add text";
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  showThread(m); showTextPreview(); updateTools();
  $("#textInput").focus();
}
async function addText() {
  const v = textValues();
  if (!v.text.trim()) { toast("Type some text first."); $("#textInput").focus(); return; }
  if (!C.view) return;
  busy(true, "Setting the text…");
  let j;
  try {
    const r = await post("/api/cap/text", v);
    j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
  } catch (e) { toast(e.message, true, 6000); return; }
  finally { busy(false); }
  if (j.missing.length) toast(`This font has no ${j.missing.join(" ")}: left as a space.`, true, 6000);
  const old = textDraft();
  let cx, cy;
  if (old) {                                    // a text changed: where it stands now
    const [a, b, c, e] = bbox(old.rings); cx = (a + c) / 2; cy = (b + e) / 2;
  } else {                                      // a new one: the middle of the view (0.1 mm)
    const cv = $("#canvas");
    cx = C.view.x0 + cv.width / C.view.dpr / 2 / C.view.k; cy = C.view.y1 - cv.height / C.view.dpr / 2 / C.view.k;
  }
  const rings = j.rings.map((ring) => ring.map(([x, y]) => [cx + x * 10, cy + y * 10]));
  if (old) {
    remember();
    Object.assign(old, { view: rings[0], px: rings[0].map(toPxFrame), rings, pxRings: rings.map((r) => r.map(toPxFrame)), text: v });
    markDirty();
    toast("Text changed. Click Update Digitizing to sew it.");
    return;
  }
  await addShape({ rings, text: v });
  if (isDst()) toast(`Text sewn: ${j.width_mm} × ${j.height_mm} mm.`);
  $("#textMenu").hidden = true; updateTools();
}
for (const id of ["#textInput", "#textFont", "#textSpacing", "#textAlign"]) $(id).addEventListener("input", showTextPreview);
$("#textFont").addEventListener("change", showTextPreview);
$("#textAdd").addEventListener("click", addText);
$("#textInput").addEventListener("keydown", (ev) => { if (ev.key === "Enter" && (ev.metaKey || ev.ctrlKey)) { ev.preventDefault(); addText(); } });
$("#toolText").addEventListener("click", () => { if (!$("#textMenu").hidden) { $("#textMenu").hidden = true; updateTools(); return; } setTool("select"); openTextMenu(); });
$("#textClose").addEventListener("click", () => { $("#textMenu").hidden = true; updateTools(); });
$("#textThread").addEventListener("click", (ev) => openPalette(ev.currentTarget, (t) => { C.drawThread = t; showThread($("#textMenu")); }));
// ---------------------------------------------------------------- corners
C.cornerSel = [];                               // the corners picked (indices into the shape's points); none: all
const SHAPE_KEY = /^shape#[0-9a-f]{6}:s(\d+)(\.\d+)?$/;
// a sewn shape being changed (its corners) is a drawn shape again until Update Digitizing: its old piece hidden
function redrawnShape(k) {
  const m = SHAPE_KEY.exec(String(k));
  return !!(m && C.shapes.find((sh) => String(sh.id) === m[1] && !sh.sewn));
}
// the shape whose corners can be changed: the one shape selected, drawn or sewn, a closed outline with corners
function cornerShape() {
  if (isDst() || C.sels.length !== 1 || !C.info?.frame) return null;
  const k = C.sels[0], m = SHAPE_KEY.exec(String(k));
  const sh = draftOf(k) || (m && C.shapes.find((x) => x.sewn && String(x.id) === m[1]));
  if (!sh || !sh.closed || sh.rings || !sh.px || sh.px.length < 3) return null;
  const c = cornersOf(sh);
  return c.idx.length ? { sh, key: k, ...c } : null;
}
function cornersOf(sh) {        // the sharp outline (px), radii (mm), styles, and which points are corners
  const base = sh.corner?.base || sh.px, n = base.length;
  const r = sh.corner?.r || new Array(n).fill(0), style = sh.corner?.style || new Array(n).fill("round");
  const idx = [];
  for (let i = 0; i < n; i++) if (cornerGeom(base, i).turn > 20 * Math.PI / 180) idx.push(i);
  return { base, r, style, idx };
}
function cornerGeom(P, i) {      // at point i: the two ways along the outline, their lengths, the angle between
  const n = P.length, a = P[(i - 1 + n) % n], v = P[i], b = P[(i + 1) % n];
  const l1 = Math.hypot(a[0] - v[0], a[1] - v[1]) || 1e-9, l2 = Math.hypot(b[0] - v[0], b[1] - v[1]) || 1e-9;
  const u1 = [(a[0] - v[0]) / l1, (a[1] - v[1]) / l1], u2 = [(b[0] - v[0]) / l2, (b[1] - v[1]) / l2];
  const th = Math.acos(Math.max(-1, Math.min(1, u1[0] * u2[0] + u1[1] * u2[1])));
  return { v, u1, u2, l1, l2, th, turn: Math.PI - th };
}
const cornerMax = (P, i) => { const g = cornerGeom(P, i); return 0.5 * Math.min(g.l1, g.l2) * Math.tan(g.th / 2); };   // px
// the outline with its corners as set: each corner cut back along both sides and joined by an arc
// about a point inside it (round), a straight line (chamfer) or an arc about the corner (inverted)
function roundOutline(P, rPx, style) {
  const out = [];
  P.forEach((v, i) => {
    const g = cornerGeom(P, i), r = Math.min(rPx[i] || 0, cornerMax(P, i));
    if (g.turn <= 20 * Math.PI / 180 || r < 0.05) { out.push(v); return; }
    const t = r / Math.tan(g.th / 2), p1 = [v[0] + g.u1[0] * t, v[1] + g.u1[1] * t], p2 = [v[0] + g.u2[0] * t, v[1] + g.u2[1] * t];
    if (style[i] === "chamfer") { out.push(p1, p2); return; }
    let c, rad;
    if (style[i] === "inverted") { c = v; rad = t; }
    else {
      const bx = g.u1[0] + g.u2[0], by = g.u1[1] + g.u2[1], bl = Math.hypot(bx, by) || 1, d = r / Math.sin(g.th / 2);
      c = [v[0] + bx / bl * d, v[1] + by / bl * d]; rad = r;
    }
    const a1 = Math.atan2(p1[1] - c[1], p1[0] - c[0]);
    let da = Math.atan2(p2[1] - c[1], p2[0] - c[0]) - a1;
    while (da > Math.PI) da -= 2 * Math.PI;
    while (da < -Math.PI) da += 2 * Math.PI;
    const steps = Math.max(4, Math.ceil(Math.abs(da) / (Math.PI / 24)));
    for (let k = 0; k <= steps; k++) { const a = a1 + da * k / steps; out.push([c[0] + rad * Math.cos(a), c[1] + rad * Math.sin(a)]); }
  });
  return out;
}
// a sewn shape about to be changed: its move or resize (an edit of its piece) put into its own points,
// and it is a drawn shape again (sewn when Update Digitizing runs)
function unsew(sh) {
  if (!sh.sewn) return;
  const keys = Object.keys(C.edits).filter((k) => { const m = SHAPE_KEY.exec(k); return m && m[1] === String(sh.id); });
  const e = C.edits[`shape${sh.hex}:s${sh.id}`];
  const bake = (pts) => {
    if (!e) return pts;
    if (e.deleted) return pts;
    const [cx, cy] = centroid([pts]), [a, b, c, d] = mOf(e);
    return pts.map(([x, y]) => [cx + a * (x - cx) + b * (y - cy) + (e.dx || 0), cy + c * (x - cx) + d * (y - cy) + (e.dy || 0)]);
  };
  const f = e ? Math.sqrt(Math.abs(mOf(e)[0] * mOf(e)[3] - mOf(e)[1] * mOf(e)[2])) : 1;
  if (sh.corner) sh.corner = { ...sh.corner, base: bake(sh.corner.base), r: sh.corner.r.map((x) => x * f) };
  sh.px = bake(sh.px); sh.view = sh.px.map(fromPxFrame);
  const edits = { ...C.edits }; for (const k of keys) delete edits[k]; C.edits = edits;
  sh.sewn = false;
  C.sels = ["draft:" + sh.id];
}
// the corners set: the shape's outline made again from them
function setCorners(sh, base, r, style) {
  const s = C.info.frame.s;                     // mm per image pixel
  sh.corner = { base, r, style };
  sh.px = roundOutline(base, r.map((mm) => mm / s), style);
  sh.view = sh.px.map(fromPxFrame);
}
// the corners a drag or the panel changes: those picked, else all of them
const cornerTargets = (c, i) => (C.cornerSel.length ? (i === undefined || C.cornerSel.includes(i) ? C.cornerSel : [i]) : c.idx).filter((k) => c.idx.includes(k));
// each corner's dot (0.1 mm on the design): inside it, on the line halfway between its two sides
function cornerDots(c) {
  const s = C.info.frame.s, minOff = 16 / C.view.k;
  return c.idx.map((i) => {
    const g = cornerGeom(c.base.map(fromPxFrame), i), bx = g.u1[0] + g.u2[0], by = g.u1[1] + g.u2[1], bl = Math.hypot(bx, by) || 1;
    const rD = Math.min(c.r[i] || 0, cornerMax(c.base, i) * s) * 10;
    const d = Math.max(minOff, (c.style[i] === "round" ? rD / Math.sin(g.th / 2) : rD / Math.tan(g.th / 2)) * 0.9);
    return { i, v: g.v, bis: [bx / bl, by / bl], sinH: Math.sin(g.th / 2), at: [g.v[0] + bx / bl * d, g.v[1] + by / bl * d] };
  });
}
function cornerDotAt(ev) {
  const c = cornerShape();
  if (!c || C.tool !== "select") return null;
  const r = $("#canvas").getBoundingClientRect(), px = ev.clientX - r.left, py = ev.clientY - r.top;
  for (const d of cornerDots(c)) {
    const sx = (d.at[0] - C.view.x0) * C.view.k, sy = (C.view.y1 - d.at[1]) * C.view.k;
    if (Math.hypot(px - sx, py - sy) <= 7) return { c, d };
  }
  return null;
}
function drawCornerDots(g) {
  const c = cornerShape();
  if (!c || C.tool !== "select" || E.drag?.mode === "move" || E.drag?.mode === "scale" || E.drag?.mode === "rotate") return;
  const dpr = C.view.dpr;
  g.save();
  for (const d of cornerDots(c)) {
    const [x, y] = toScreen(d.at), on = C.cornerSel.includes(d.i);
    g.beginPath(); g.arc(x, y, 4.5 * dpr, 0, 7); g.fillStyle = on ? "#0a84ff" : "#ffffff"; g.fill();
    g.lineWidth = 1.5 * dpr; g.strokeStyle = "#0a84ff"; g.stroke();
    if (!on) { g.beginPath(); g.arc(x, y, 1.6 * dpr, 0, 7); g.fillStyle = "#0a84ff"; g.fill(); }
  }
  g.restore();
}
function openCornerMenu() {
  const m = $("#cornerMenu"), r = $("#toolCorners").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  updateCornerMenu();
}
function updateCornerMenu() {
  const c = cornerShape(), on = !!c;
  for (const el of ["#cornerRange", "#cornerMm", "#cornerStyle"]) $(el).disabled = !on;
  if (!c) { $("#cornerHint").textContent = "Select one shape you drew that has corners (a square, a triangle, a star, a shape drawn with the pen). Drag a dot in a corner to round every corner; click a dot to pick that corner only."; return; }
  const ts = cornerTargets(c), s = C.info.frame.s, max = Math.max(...ts.map((i) => cornerMax(c.base, i) * s));
  $("#cornerRange").max = String(Math.max(0.5, Math.ceil(max * 10) / 10));
  if (document.activeElement !== $("#cornerMm")) $("#cornerMm").value = String(Math.round((c.r[ts[0]] || 0) * 10) / 10);
  $("#cornerRange").value = String(c.r[ts[0]] || 0);
  $("#cornerStyle").value = c.style[ts[0]] || "round";
  $("#cornerHint").textContent = C.cornerSel.length ? `${ts.length} of ${c.idx.length} corners picked: these change. Click the shape for all of them.`
    : `All ${c.idx.length} corners change. Click a dot to change one corner only (shift-click for more).`;
}
// the panel: the radius (mm, at most what fits) or the style of the corners picked, else of all
function cornerPanel(what, value) {
  const c = cornerShape();
  if (!c) return;
  if (!E.cornerTaken) { remember(); E.cornerTaken = true; }
  if (c.sh.sewn) { unsew(c.sh); Object.assign(c, cornersOf(c.sh)); }     // its outline where it is now
  const s = C.info.frame.s, r = [...c.r], style = [...c.style];
  for (const i of cornerTargets(c)) {
    if (what === "r") r[i] = Math.max(0, Math.min(value, cornerMax(c.base, i) * s));
    else style[i] = value;
  }
  setCorners(c.sh, c.base, r, style);
  markDirty();
  updateCornerMenu();
}

// ---------------------------------------------------------------- the Pathfinder
// the shapes drawn on the page that are selected: a shape not digitized yet ("draft:<id>"), or one sewn
// already (its pieces "shape#hex:s<id>[.n]"), each once, back to front as they lie on the design
function selectedShapes() {
  const order = allPieces(), seen = new Map();
  for (const k of C.sels) {
    const m = draftOf(k) ? null : /^shape#[0-9a-f]{6}:s(\d+)(\.\d+)?$/.exec(String(k));
    const sh = draftOf(k) || (m && C.shapes.find((x) => x.sewn && String(x.id) === m[1]));
    if (!sh) continue;
    const z = order.indexOf(k);
    if (!seen.has(sh.id) || z < seen.get(sh.id).z) seen.set(sh.id, { sh, z });
  }
  return [...seen.values()].sort((a, b) => a.z - b.z).map((v) => v.sh);
}
function openPathMenu() {
  const m = $("#pathMenu"), r = $("#toolPathfinder").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  updatePathMenu();
}
function updatePathMenu() {
  const n = selectedShapes().length, others = C.sels.length - C.sels.filter((k) => draftOf(k) || /^shape#/.test(String(k))).length;
  for (const b of document.querySelectorAll("#pathMenu [data-op]")) b.disabled = n < 2;
  $("#pathHint").textContent = n >= 2 ? `${n} shapes selected${others ? " (the logo's own pieces are left as they are)" : ""}: pick how to combine them. The new shape is sewn when you click Update Digitizing.`
    : "Select two or more shapes you drew (shift-click or drag a box), then pick one. The new shape is sewn when you click Update Digitizing.";
}
async function pathfinder(op) {
  const list = selectedShapes();
  if (list.length < 2) { toast("Select two or more shapes you drew first."); return; }
  busy(true, "Combining the shapes…");
  try {
    const r = await post("/api/cap/pathfinder", { op, shapes: list.map(shapeToSend), edits: C.edits });
    const j = await r.json();
    if (!r.ok || j.error) throw new Error(j.error || `Failed (${r.status})`);
    remember();
    if (!C.lock) C.lock = C.info.mm_per_px;
    const keep = op === "minus" ? list[0] : list[list.length - 1];      // its thread: the back shape's for Minus Front, else the front one's
    const id = (C.shapes.reduce((m, sh) => Math.max(m, sh.id), 0) || 0) + 1, rings = j.rings.map((ring) => ring.map(fromPxFrame));
    const gone = new Set(list.map((sh) => sh.id));
    const edits = { ...C.edits };             // the sewn ones' pieces shown as going until Update Digitizing
    for (const p of C.info.pieces || []) {
      const m = /^shape#[0-9a-f]{6}:s(\d+)(\.\d+)?$/.exec(p.key);
      if (m && gone.has(+m[1])) edits[p.key] = { ...ID, ...(edits[p.key] || {}), deleted: true };
    }
    C.edits = edits;
    C.shapes = [...C.shapes.filter((sh) => !gone.has(sh.id)),
                { id, hex: keep.hex, view: rings[0], px: j.rings[0], rings, pxRings: j.rings, closed: true,
                  width: keep.width, width_mm: keep.width_mm, sewn: false }];
    C.sels = ["draft:" + id];
    markDirty();
    toast(`${{ unite: "United", minus: "Front shapes taken away", intersect: "Intersected", exclude: "Overlap cut out" }[op]}: one shape now. Click Update Digitizing to sew it.`);
  } catch (e) { toast(e.message, true, 6000); repaint(); }
  finally { busy(false); updatePathMenu(); }
}

function setTool(t) {
  if (t !== "pen" && t !== "hand") E.pen = null;            // the hand keeps a path being drawn
  if (t !== "pen") $("#penMenu").hidden = true;
  if (t === "hand" && C.tool !== "hand") C.beforeHand = C.tool;
  C.tool = t;
  for (const b of document.querySelectorAll("#drawMenu [data-shape]")) b.classList.toggle("on", t === "shape:" + b.dataset.shape);
  $("#canvas").style.cursor = t === "select" ? "default" : t === "zoom" ? "zoom-in" : t === "hand" ? "grab" : "crosshair";
  if (t === "select") $("#drawMenu").hidden = true;
  updateTools();
}
function openDrawMenu() {
  const m = $("#drawMenu"), r = $("#toolShapes").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  showThread(m);
}
function showThread(m) {
  const t = drawThread();
  m.querySelector(".sw").style.background = t.hex;
  m.querySelector(".nm").textContent = t.num ? `${t.num} ${t.name}` : "Pick";
}
function openPenMenu() {
  const m = $("#penMenu"), r = $("#toolPen").getBoundingClientRect();
  m.hidden = false;
  m.style.left = `${r.right + 8}px`; m.style.top = `${Math.max(8, Math.min(window.innerHeight - m.offsetHeight - 8, r.top))}px`;
  showThread(m);
}
$("#toolSelect").addEventListener("click", () => setTool("select"));
$("#toolCorners").addEventListener("click", () => { const m = $("#cornerMenu"); if (!m.hidden) { m.hidden = true; updateTools(); return; } for (const id of ["#drawMenu", "#penMenu", "#pathMenu", "#alignMenu", "#arrangeMenu"]) $(id).hidden = true; openCornerMenu(); updateTools(); });
$("#cornerClose").addEventListener("click", () => { $("#cornerMenu").hidden = true; updateTools(); });
$("#cornerRange").addEventListener("input", (e) => { $("#cornerMm").value = String(Math.round(+e.target.value * 10) / 10); cornerPanel("r", +e.target.value); });
$("#cornerMm").addEventListener("input", (e) => { if (e.target.value !== "") cornerPanel("r", Math.max(0, +e.target.value)); });
$("#cornerStyle").addEventListener("change", (e) => cornerPanel("style", e.target.value));
for (const id of ["#cornerRange", "#cornerMm", "#cornerStyle"]) $(id).addEventListener("change", () => { E.cornerTaken = false; });
$("#toolAlign").addEventListener("click", () => { const m = $("#alignMenu"); if (!m.hidden) { m.hidden = true; updateTools(); return; } $("#drawMenu").hidden = $("#penMenu").hidden = $("#pathMenu").hidden = $("#arrangeMenu").hidden = true; openAlignMenu(); updateTools(); });
$("#toolArrange").addEventListener("click", () => { const m = $("#arrangeMenu"); if (!m.hidden) { m.hidden = true; updateTools(); return; } $("#drawMenu").hidden = $("#penMenu").hidden = $("#pathMenu").hidden = $("#alignMenu").hidden = true; openArrangeMenu(); updateTools(); });
$("#arrangeClose").addEventListener("click", () => { $("#arrangeMenu").hidden = true; updateTools(); });
for (const b of document.querySelectorAll("#arrangeMenu [data-arrange]")) b.addEventListener("click", () => arrangePieces(b.dataset.arrange));
$("#alignClose").addEventListener("click", () => { $("#alignMenu").hidden = true; updateTools(); });
for (const b of document.querySelectorAll("#alignMenu [data-align]")) b.addEventListener("click", () => alignPieces(b.dataset.align));
$("#toolPathfinder").addEventListener("click", () => { const m = $("#pathMenu"); if (!m.hidden) { m.hidden = true; return; } $("#drawMenu").hidden = true; $("#penMenu").hidden = true; $("#alignMenu").hidden = true; $("#arrangeMenu").hidden = true; openPathMenu(); });
$("#pathClose").addEventListener("click", () => ($("#pathMenu").hidden = true));
for (const b of document.querySelectorAll("#pathMenu [data-op]")) b.addEventListener("click", () => pathfinder(b.dataset.op));
$("#toolShapes").addEventListener("click", () => { openDrawMenu(); if (!C.tool.startsWith("shape:")) setTool("shape:circle"); });
$("#toolPen").addEventListener("click", () => { $("#drawMenu").hidden = true; setTool(C.tool === "pen" ? "select" : "pen"); if (C.tool === "pen") openPenMenu(); });
for (const b of document.querySelectorAll("#drawMenu [data-shape]")) b.addEventListener("click", () => {
  setTool("shape:" + b.dataset.shape);
  $("#drawMenu").hidden = true;                 // out of the way: drag the shape on the design now
  toast(`${b.title}: drag on the design to draw it (shift: as wide as tall).`);
});
$("#drawClose").addEventListener("click", () => ($("#drawMenu").hidden = true));
$("#drawThread").addEventListener("click", (ev) => openPalette(ev.currentTarget, (t) => { C.drawThread = t; openDrawMenu(); }));
$("#penThread").addEventListener("click", (ev) => openPalette(ev.currentTarget, (t) => { C.drawThread = t; showThread($("#penMenu")); repaint(); }));
$("#penClose").addEventListener("click", () => ($("#penMenu").hidden = true));
cv.addEventListener("dblclick", () => { if (C.tool === "pen" && E.pen) penFinish(false); });

// ---------------------------------------------------------------- the pen: a path point by point
// Click to place a point (a corner); drag as you place it to pull its handles (a smooth curve). Click
// the first point to close the path (a filled shape); Enter or a double-click ends it as a line of the
// pen's width. Backspace takes the last point back; Esc drops the path. Option-click a point: its
// handles go (the last point: only the one going on, so the next line starts straight, as you want
// it).
E.pen = null;                   // {pts: [{p, h, hin}]} (h: the out-handle; hin: the in-handle, -h when not set)
const penIn = (pt) => pt.hin || [-pt.h[0], -pt.h[1]];
function penPointAt(ev) {       // the index of the point under the pointer, or -1
  if (!E.pen) return -1;
  const r = $("#canvas").getBoundingClientRect(), d = C.view.dpr, mx = (ev.clientX - r.left) * d, my = (ev.clientY - r.top) * d;
  for (let i = E.pen.pts.length - 1; i >= 0; i--) {
    const [x, y] = toScreen(E.pen.pts[i].p);
    if (Math.hypot(mx - x, my - y) <= 9 * d) return i;
  }
  return -1;
}
function penNearFirst(ev) {
  if (!E.pen || E.pen.pts.length < 3) return false;
  const [x, y] = toScreen(E.pen.pts[0].p), r = $("#canvas").getBoundingClientRect(), d = C.view.dpr;
  return Math.hypot((ev.clientX - r.left) * d - x, (ev.clientY - r.top) * d - y) <= 9 * d;
}
function penDown(ev) {
  const pt = toDesign(ev);
  if (ev.altKey && E.pen) {     // option on a point: its handles taken away (the last one: the one going on)
    const i = penPointAt(ev);
    if (i >= 0) {
      const q = E.pen.pts[i], last = i === E.pen.pts.length - 1;
      if (last) { q.hin = penIn(q); q.h = [0, 0]; }
      else { q.h = [0, 0]; q.hin = [0, 0]; }
      repaint();
      return;
    }
  }
  if (penNearFirst(ev)) { penFinish(true); return; }
  if (!E.pen) E.pen = { pts: [], cursor: pt };
  const last = E.pen.pts[E.pen.pts.length - 1];
  if (last && Math.hypot(pt[0] - last.p[0], pt[1] - last.p[1]) < 3) return;     // the second click of a double-click
  E.pen.pts.push({ p: pt, h: [0, 0] });
  E.drag = { mode: "pen", start: pt };
  try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
  repaint();
}
function penMove(ev) {
  const pt = toDesign(ev);
  cv.style.cursor = penNearFirst(ev) || (ev.altKey && penPointAt(ev) >= 0) ? "pointer" : "crosshair";
  if (!E.pen) return;
  E.pen.cursor = pt; E.pen.closing = penNearFirst(ev);
  if (E.drag?.mode === "pen") {                // dragging out the handles of the point just placed
    const last = E.pen.pts[E.pen.pts.length - 1];
    last.h = [pt[0] - last.p[0], pt[1] - last.p[1]];
  }
  repaint();
}
// the path as points (0.1 mm): each curve between two points cut into short straight steps
function penFlatten(pts, closed) {
  const out = [pts[0].p];
  const segs = pts.length - 1 + (closed ? 1 : 0);
  for (let i = 0; i < segs; i++) {
    const a = pts[i], b = pts[(i + 1) % pts.length];
    const bin = penIn(b), P1 = [a.p[0] + a.h[0], a.p[1] + a.h[1]], P2 = [b.p[0] + bin[0], b.p[1] + bin[1]];
    const curved = Math.hypot(...a.h) > 1 || Math.hypot(...bin) > 1, n = curved ? 24 : 1;
    for (let k = 1; k <= n; k++) {
      const t = k / n, u = 1 - t;
      out.push([0, 1].map((d) => u * u * u * a.p[d] + 3 * u * u * t * P1[d] + 3 * u * t * t * P2[d] + t * t * t * b.p[d]));
    }
  }
  if (closed) out.pop();                       // back at the first point
  return out;
}
function drawPen(g) {
  const P = E.pen, dpr = C.view.dpr;
  if (!P.pts.length) return;
  const preview = P.pts.concat(P.closing || E.drag ? [] : [{ p: P.cursor, h: [0, 0] }]);
  const path = penFlatten(preview, !!P.closing);
  // while tracing: the path as a thin line only (a closed one: its fill, faintly); the line's width
  // shows once it is finished
  if (P.closing) drawShapePath(g, path, true, 0, drawHex(), 0.3);
  g.save();
  g.strokeStyle = "#0a84ff"; g.lineWidth = 1 * dpr;
  g.beginPath(); path.forEach((p, i) => { const [x, y] = toScreen(p); i ? g.lineTo(x, y) : g.moveTo(x, y); }); if (P.closing) g.closePath(); g.stroke();
  P.pts.forEach((pt, i) => {                   // the points, and the handles of the last one
    const [x, y] = toScreen(pt.p), h = 3.5 * dpr;
    if (i === P.pts.length - 1) {
      for (const hv of [pt.h, penIn(pt)]) {
        if (Math.hypot(...hv) <= 1) continue;
        const [hx, hy] = toScreen([pt.p[0] + hv[0], pt.p[1] + hv[1]]);
        g.beginPath(); g.moveTo(x, y); g.lineTo(hx, hy); g.stroke();
        g.fillStyle = "#0a84ff"; g.beginPath(); g.arc(hx, hy, 3 * dpr, 0, 7); g.fill();
      }
    }
    g.fillStyle = i === 0 && P.closing ? "#0a84ff" : "#ffffff";
    g.fillRect(x - h, y - h, 2 * h, 2 * h); g.strokeRect(x - h, y - h, 2 * h, 2 * h);
  });
  g.restore();
}
function penFinish(closed) {
  const P = E.pen;
  E.pen = null; E.drag = null;
  if (!P || P.pts.length < (closed ? 3 : 2)) { repaint(); return; }
  addShape({ path: penFlatten(P.pts, closed), closed, width_mm: +$("#penWidth").value });
}

// ---------------------------------------------------------------- zoom
// zoom by f about the design point pt (0.1 mm), which stays under the pointer; 1x: the whole design
function zoomAt(f, pt) {
  if (!C.view) return;
  const z0 = C.zoom || 1, z = Math.min(40, Math.max(1, z0 * f));
  if (z <= 1.001) {             // 1x (Fit): the whole design, also after the hand moved it
    const was = z0 > 1.001 || C.cam;
    C.zoom = 1; C.cam = null;
    if (was) draw();
    return;
  }
  if (Math.abs(z - z0) < 1e-6) return;
  const v = C.view, cvr = $("#canvas").getBoundingClientRect();
  pt = pt || [v.x0 + cvr.width / 2 / v.k, v.y1 - cvr.height / 2 / v.k];      // the middle of the view
  const fit = C.fit || v.k / z0, k1 = fit * z, [W, H] = stageRoom();
  if (z0 <= 1.001 && !C.cam) C.cam = pt;        // from the whole design: centred on the point
  else {                                        // keep the point where it is on screen
    const sx = (pt[0] - v.x0) * v.k, sy = (v.y1 - pt[1]) * v.k;
    const x0 = pt[0] - sx / k1, y1 = pt[1] + sy / k1;
    C.cam = [x0 + W / 2 / k1, y1 - H / 2 / k1];
  }
  C.zoom = z;
  draw();
}
$("#toolZoom").addEventListener("click", () => setTool(C.tool === "zoom" ? "select" : "zoom"));
$("#toolHand").addEventListener("click", toggleHand);
function toggleHand() { setTool(C.tool === "hand" ? (C.beforeHand && C.beforeHand !== "hand" ? C.beforeHand : "select") : "hand"); }
// the hand: the view where the design was when the drag began, moved with the pointer (at any zoom:
// at 1x the view is then the whole stage, centred where you left it, until Fit)
function handDown(ev) {
  const v = C.view, r = $("#canvas").getBoundingClientRect();
  const cam = C.cam || [v.x0 + r.width / 2 / v.k, v.y1 - r.height / 2 / v.k];
  E.drag = { mode: "hand", sx: ev.clientX, sy: ev.clientY, cam, k: v.k };
  $("#canvas").style.cursor = "grabbing";
  try { cv.setPointerCapture(ev.pointerId); } catch (_e) { /* a pointer the page did not see start */ }
}
function handMove(ev) {
  const d = E.drag;
  if (d?.mode !== "hand") return;
  C.cam = [d.cam[0] - (ev.clientX - d.sx) / d.k, d.cam[1] + (ev.clientY - d.sy) / d.k];
  draw();
}
$("#toolZoomIn").addEventListener("click", () => zoomAt(1.5));
$("#toolZoomOut").addEventListener("click", () => zoomAt(1 / 1.5));
$("#toolFit").addEventListener("click", () => zoomAt(0));
// a pinch or ⌘/ctrl-scroll zooms at the pointer; a scroll moves around a zoomed design
cv.addEventListener("wheel", (ev) => {
  if (!C.view) return;
  if (ev.ctrlKey || ev.metaKey) { ev.preventDefault(); zoomAt(Math.exp(-ev.deltaY * 0.01), toDesign(ev)); return; }
  if (C.zoom > 1.001) {
    ev.preventDefault();
    C.cam = [C.cam[0] + ev.deltaX / C.view.k, C.cam[1] - ev.deltaY / C.view.k];
    draw();
  }
}, { passive: false });
document.addEventListener("keydown", (ev) => { if (C.tool === "zoom") $("#canvas").style.cursor = ev.altKey ? "zoom-out" : "zoom-in"; });
document.addEventListener("keyup", (ev) => { if (C.tool === "zoom") $("#canvas").style.cursor = ev.altKey ? "zoom-out" : "zoom-in"; });
