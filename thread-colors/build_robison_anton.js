// Adds Robison-Anton Polyester 40 to static/thread-data.json:
//   colours: swatch colours from thethreadexchange.com (robison-anton-polyester-swatches.txt)
//   pms:     the store's Pantone (PMS) to R-A chart (pantone-to-robison-anton.txt)
// A thread on the PMS chart with no swatch takes the screen colour of its Pantone (Solid Coated).
const fs = require("fs"), path = require("path");
const C = require("../static/color.js");
const here = __dirname, rows = (f) => fs.readFileSync(path.join(here, f), "utf8").split(/[;\n]/).map((r) => r.split("|").map((x) => x.trim())).filter((r) => r[0]);
const sw = rows("robison-anton-polyester-swatches.txt"), pms = rows("pantone-to-robison-anton.txt");
const solid = JSON.parse(fs.readFileSync(path.join(here, "../static/pantone-data.json"))).books.find((b) => b.id === "solid-c").colors;
const pantone = new Map(solid.map(([n, L, a, b]) => [n.toUpperCase(), [L, a, b]]));

const colors = new Map(sw.filter((r) => r[2]).map(([num, name, hex]) => [num, [num, name, hex]]));
const fromPms = {};
for (const [p, num, name] of pms) {
  if (colors.has(num)) continue;
  const lab = pantone.get(p.toUpperCase());
  if (!lab) { console.warn("no Pantone colour for", p, num); continue; }
  colors.set(num, [num, name, C.rgbToHex(C.labToRgb(lab).rgb).toUpperCase()]);
  fromPms[num] = p;
}
const book = {
  id: "robison-anton-polyester", title: "Robison-Anton Polyester 40",
  colors: [...colors.values()].sort((a, b) => a[0].localeCompare(b[0])),
  // [PMS, thread number, the PMS's screen colour (null when the Pantone book lacks it)]
  pms: pms.map(([p, num]) => { const lab = pantone.get(p.toUpperCase()); return [p, num, lab ? C.rgbToHex(C.labToRgb(lab).rgb).toUpperCase() : null]; }),
  colorFromPms: fromPms,
  source: "thethreadexchange.com: Pantone To R/A Polyester Conversion, and R/A Polyester swatches (October 2026)",
};
const f = path.join(here, "../static/thread-data.json"), d = JSON.parse(fs.readFileSync(f, "utf8"));
d.books = d.books.filter((b) => b.id !== book.id).concat(book);
fs.writeFileSync(f, JSON.stringify(d));
console.log(`${book.colors.length} colours (${Object.keys(fromPms).length} from their Pantone), ${book.pms.length} PMS matches; no colour: ${sw.filter((r) => !r[2] && !colors.has(r[0])).map((r) => r[0] + " " + r[1]).join(", ")}`);
