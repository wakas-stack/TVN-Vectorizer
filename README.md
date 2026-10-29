# EMB Pros

A local image-to-vector converter modelled on the features of [vectorizer.ai](https://vectorizer.ai).
Upload a PNG, JPG, GIF, BMP or WebP image and get an editable, layered SVG (or PDF, EPS, DXF, PNG).
Everything runs on this Mac; images never leave it.


The interface is branded EMB Pros (`static/emb-pros-logo.svg`: an embroidery hoop with a needle
making running stitches, the name beside it). The header has the logo on the left and the tools as
tabs: Logo Vectorizer, Pantone Match, Thread Match, Patch Mockup, Gang Sheet Maker and DST Maker
(Cap DST), the open one in orange; each tool's buttons sit in a row at the top of its work area.

## Website (PHP)

`make_web.py` builds `web/dist/emb-pros-web.zip`, the same tools as a website: `public_html/`
(PHP pages with the shared EMB Pros header, `api.php` passing `/api/...` to the engine, `.htaccess`
for the same addresses, `.user.ini` for 48 MB uploads) and `engine/` (this Python code, run as a
cPanel "Setup Python App" or with gunicorn on a VPS). `DEPLOY.md` in the zip has the steps. Off
macOS, gang sheets use `gang_portable.py` (pypdfium2 and pikepdf) instead of Quartz; the engine's
`EMB_KEEP` keeps more logos for many visitors and `EMB_ENGINE_KEY` lets only the site use it.
Tested on this Mac with PHP's server and with Apache + PHP-FPM: DST, stitches, traced SVG and
patch mockups byte for byte the same as the app.
## Start

```bash
cd ~/Desktop/image-vectorizer
./start.sh
```

It opens http://127.0.0.1:8765. Press Ctrl+C in that terminal to stop it.

Command line, for batches:

```bash
./vectorize logo.png                         # -> logo.svg
./vectorize photo.jpg -f pdf --colors 24     # -> photo.pdf
./vectorize *.png -o out/ --stacking stacked --group-by layer
./vectorize -h                               # every option
```

## Desktop app (copy to any Mac)

`dist/EMB-Pros-Mac.zip` holds `EMB Pros (Mac)/`: the app and `READ-ME-FIRST.txt`.
Copy it to another Mac (Apple Silicon or Intel, macOS 11+), double-click
**EMB Pros.app**, and it opens in its own window; close the window to quit.
It carries its own Python 3.12 and libraries for both Mac types, so nothing is installed
and no internet is needed. The read-me explains the one-time "could not verify" step
macOS shows for apps that arrive by AirDrop, download or email.

Rebuild it after changing the code:

```bash
./build_app.sh
```

`desktop.py` runs the window (pywebview, macOS WebKit); `desktop.py --selftest` opens it,
checks tracing, every export and the Pantone page, and prints the result.

## What it does

| vectorizer.ai feature | Here |
| --- | --- |
| Drop, paste (⌘V) or pick an image | Same |
| Free preview: zoom, compare pixels and vectors | Vectors / Compare (slider) / Pixels views, wheel zoom, pan |
| Palette control, automatic colour count | Detects the colours (anti-aliasing blends are ignored; photos get more colours). Set a maximum, recolour, merge, remove or add colours |
| Whole-shape fitting | Circles, ellipses, rectangles and rounded rectangles, also for holes |
| Sub-pixel precision | Traced at up to 4× resolution, coordinates in original pixels |
| Shape stacking: cut-outs / stacked | Same |
| Group by none / colour / parent / layer | Same; groups are named Inkscape layers (Illustrator imports them as named groups) |
| Gap filler, clip overflow, non-scaling strokes | Same; strokes only along shared edges, in the average colour |
| Draw style: fill shapes / stroke shapes / stroke edges | Same; stroke edges draws each edge once (for cutters) |
| Background removal, click to keep or remove | Remove background button (also the background colour inside letters) + Background tool |
| Region editing (recolour, merge, remove shapes) | Edit shapes tool, undo, layer show/hide |
| Pre-crop | Crop tool |
| SVG 1.0 / 1.1 / Tiny 1.2, fixed size, output size, units, DPI | Same |
| PDF, EPS, PNG (4×) output | PDF and EPS written directly; PNG drawn in the page |
| DXF: lines only / lines & arcs / splines | Same, one CAD layer per group |
| Presets: editing, cutting & engraving | Editing, Cutting & engraving, Print |

## Pantone match

http://127.0.0.1:8765/pantone, or **Pantone match** in the header. Type or pick one or more
hex codes (or paste a list) and it lists the closest Pantone colours with their CIEDE2000
difference (ΔE: under 1 looks the same, under 2 near identical, above 5 a different colour).
In the vectorizer, **Match palette to Pantone** opens it with the image's colours.
The **Hex / RGB / CMYK** buttons switch to RGB (0-255) or CMYK (0-100 %) boxes; pasting
"228, 0, 43" into one box fills them all, and the address keeps them (`?rgb=…`, `?cmyk=…`).
CMYK is read as printed with the **Coated FOGRA39 (ISO 12647-2:2004)** press profile:
`static/cmyk-fogra39.json` is a 17-step-per-ink table made from Adobe's `CoatedFOGRA39.icc` by
`make_cmyk_table.py` (Little CMS, through Pillow). The Pantone page matches its Lab (relative
colorimetric, Adobe's default); the hex shown, and the Thread page, use its screen colour
(sRGB with black point compensation, as Adobe apps and macOS show it). Measured: the table is
within ΔE2000 0.34 on average (max 1.1) of converting through the profile directly, and its
screen colours are within 2 RGB units of macOS ColorSync (100% K → #1D1D1B). If the table
cannot be loaded, the plain formula is used and the page says so.

- Books: Solid Coated and Uncoated, Metallics, Premium Metallics, Pastels & Neons, Color
  Bridge, Extended Gamut, and Fashion, Home + Interiors TCX/TPX (14,378 colours).
- Matching is done in CIE Lab (D50), the space the Pantone values are stored in, not by
  comparing hex codes. The hex shown for a Pantone colour is its nearest screen colour.
- Data: `static/pantone-data.json`, built from the npm package `color-books` 0.1.2 (Lab values
  from Adobe colour books). It is unofficial; check final choices against a physical Pantone
  guide or Pantone Connect. Pantone's colour data is proprietary, so keep this to personal or
  internal use. PANTONE® is a trademark of Pantone LLC.

## Thread match

http://127.0.0.1:8765/thread, or **Thread match** in the header. Type or pick one or more
hex codes and it lists the closest **Isacord 40** (390 colours) and **Madeira Polyneon 40**
(412 colours) threads, with the best thread in each chart side by side, ranked by CIEDE2000
like the Pantone page. In the vectorizer, **Match to thread** opens it with the image's colours.
RGB and CMYK input work as on the Pantone page.

- Data: `static/thread-data.json`, from the DigitEMB Thread Color Matcher
  (https://digitemb.com/tools/thread-color-matcher, fetched 2026-10-27), which compiled it from
  the makers' reference charts. The full lists, with the source notes, are also in
  `thread-colors/` (JSON and one CSV per chart).
- Thread hex values are screen approximations; check against a physical thread card. Keep to
  personal or internal use. Thread brand names belong to their owners.

## Patch mockup

http://127.0.0.1:8765/patch, or **Patch mockup** in the header (in the Vectorizer,
**Patch mockup ↗** sends the open image there). Drop a logo (PNG, JPG, WebP, GIF, BMP or
SVG) and see it as an **embroidered**, **woven**, **dye-sublimated** or **leather** patch:

- Colours: each logo colour is the fabric, raised thread (printed / pressed for the other
  styles) or hidden, and can be recoloured. A thin outline around the logo and an image
  background are listed separately and start hidden.
- Embroidered: each colour is digitized like a real design. Narrow parts become satin columns,
  every stitch one thread straight across the stroke and turning with it; wide parts (wider
  than about 8 % of the logo) become a tatami fill at the stitch angle, rows of short stitches
  with the needle points moved a third of a stitch each row. Threads catch the light by their
  direction, so parts stitched at different angles shade differently. The fabric twill shows
  only where no thread lies on top.
- Shape "Logo only": **Outline** None or **Filled outline**, an even band round the logo
  (width 1-8 %, colour; embroidered it is stitched as satin; leather is cut to it).
- Faux/Leather turns a colour logo into one solid logo: every logo colour becomes "Logo"
  (background-coloured holes stay open); the roles for other patch types come back on leaving it.
- **Download PDF** (Faux/Leather): a layered vector PDF for production, 4 in on its longest side.
- PVC Rubber: moulded soft PVC; flat solid colours, each logo colour a raised layer (Relief: how
  high) with rounded moulded edges and a fine groove where colours meet, semi-gloss; Border: Raised
  rim or None. Silicone: the same build, softer and domed, satin-matte, slightly translucent at
  the edges; Logo only by default (pressed straight onto the garment). Suede: a soft matte nap,
  no shine; the logo debossed, embossed or laser engraved as on Faux/Leather (one solid logo, a
  stitched seam or none; the suede colour from the same swatches). HTV (heat transfer vinyl): flat
  cut vinyl pressed on, a crisp thin edge, an even satin sheen, the garment's weave faint through
  it; Logo only, no border; for bold letters and simple logos (the hint says so).
- Border **Thickness** (Shape & border, 0.3-2.5×, next to Width): how thick the merrow or satin
  edge and the PVC/silicone rim stand, or how dark and wide a laser-cut edge is; leather and suede
  seams keep their own thread Thickness. 1× is the look as before.
- The backing's colour (Shape & border: **Fabric** for the textile types, **Base colour** for PVC,
  silicone and HTV) can always be picked, also over a logo colour that is the fabric; Automatic
  takes the logo's fabric colour, or a colour that contrasts with it. PVC and Silicone start with
  every logo colour raised (the roles for other types come back on leaving them), so a dark logo
  is not lost on a base of its own colour.
  Layers (PDF optional content, shown as layers in Illustrator and Acrobat): *Shape* (the patch
  in white with a black hairline outline, 0.072 pt / 0.001 in; not with "Logo only" and no outline), *Logo* (every logo
  colour as one solid black shape, holes open) and *Stitch lines* (the seam as stroked vector
  dashes, dots or a line, spaced exactly as in the mockup). Made by `patch.leather_pdf`.
- Thread numbers (embroidered): choose **Isacord 40** or **Madeira Polyneon 40** under Colours,
  then type a thread number under each thread colour, or click **Use** for the nearest thread
  shown there. Switching brand changes picked threads to the other brand's nearest number
  (measured from the thread you chose, so switching back gives your number again) and warns
  when one has no close match (ΔE 5 or more). With 100% embroidered the fabric gets a thread
  number too. Data: `static/thread-data.json` (see Thread match).
- Faux/Leather: the **Leatherette** list has Lone Star Adhesive's 29 Heritage Collection
  Durra-Bull leatherette sheets (used with the owner's permission). A sheet uses its photo
  texture (`static/leatherette/*.jpg`, cropped and evened out by `make_leatherette.py` from the
  blank-sheet photos) and sets the logo to laser engraved, showing the sheet's core colour
  (black, silver, gold or copper). Saddle Tan has no blank photo and is drawn in its colour.
- **Logo size** (50-150 %) scales the logo inside the patch shape; the shape keeps its size.
- Leather seam: **Stitch** (square dashes with gaps as long as the dashes, dotted, or a plain
  line), **Thickness** (0.4-2.4×) and **Colour** (picking a colour turns "Black thread" off).
  The seam is flat, with no relief or shadow; dashes are four times as long as they are thick,
  spaced evenly along the seam line itself and follow its corners.
- Shape (follow the logo, circle, rounded rectangle, rectangle), border (merrow, satin,
  laser-cut, none; stitched seam for leather), border colour and width.
- Relief, thread density, stitch angle, light direction, gloss, 100% embroidered; leather
  colour and finish (debossed, embossed, laser engraved).
- White (the default), transparent or coloured background, no drop shadow; PNG export up to 3000 px.

**Choose logo** asks before replacing a patch that is being worked on ("Keep working" or
"Discard and choose logo"); the current patch stays until a new logo is actually picked.

It is a mockup for showing or ordering, made from the logo's vector shapes (`patch.py`), not a
photo and not a machine stitch file (DST/PES).

## Gang sheet

http://127.0.0.1:8765/gang, or **Gang sheet** in the header. Add one or more logos and set
the sheet size (Letter, Tabloid, A4, A3, DTF 22 in wide... or custom, in in/cm/mm). Each logo
has its own size (proportions kept) and a quantity, or **Fill the rest** (one logo at a time):
the sheet places the logos with a quantity first, tallest first, each into the first row with
room, then the filling logo into every gap left, inside the margin, the gap apart, the block
centred. A logo is turned 90 degrees when that fits more. Clicking the + of an empty place (or
an empty row) asks which logo (one on the sheet or a new one), its size and how many. The sheet
border is optional, and so is a box round each logo (off unless ticked; 0.5 pt black lines).

- Logos: PDF and AI (Illustrator's PDF-compatible AI, the default) are placed as their own vector
  page, trimmed to the artwork; SVG is written as a vector PDF first; PNG, JPG, WebP, TIFF are
  placed as images (transparent edges trimmed). EPS cannot be read: macOS no longer has a
  PostScript reader (checked: no `pstopdf`, Quartz's PostScript converter does not run).
- Downloads: PDF and AI (a PDF-based .ai file Illustrator opens) are vector for vector logos; PNG
  and TIFF transparent, JPG white, at 150/300/600 dpi; EPS has the logo's vector paths for SVG
  logos, and otherwise holds the sheet as an image (macOS cannot write PostScript from PDF).
- Removing logos: click a logo on the preview to leave its place empty; the round buttons
  beside the rows do a whole row; "Put all logos back". The sheet and every
  other place stay the same, in the preview and in every download. Changing the layout (sheet,
  logo size, gap, margin, turning) puts the removed logos back, as the places change.
- Undo: Cmd+Z / Ctrl+Z or **Undo** takes back the last edit (a logo or row taken off or put
  back, a sheet or logo setting), up to 50 times; typing in one box is one edit, and a box
  being typed in keeps its own text undo. A new logo starts a new history.
- Made with Quartz (Core Graphics) in `gang.py`; the app saves large files straight from the
  local server (`Api.save_url`).

## Cap DST

http://127.0.0.1:8765/cap, or **Cap DST** in the header. Drop a logo (PNG, JPG or PDF), choose
the size on the cap (front panel 4.5 x 2.25 in by default; the logo is fitted inside it, then width and height show the logo's own size, and changing one changes the other in its proportions), and
download a Tajima .DST file for Tajima and Happy cap machines, plus a preview PNG with the
threads in sewing order.

- Auto-digitizing (`digitize.py`): the logo is traced into colour regions (as for the patch
  mockup). Each part is cut into strokes the way a digitizer splits a letter: at its inside
  corners (a T into bar and stem, a W into four strokes; a hole that is not an even ring is cut
  open), after smoothing the jags of tracing. Each stroke is sewn as satin across it:
  - a turning satin that follows the stroke (an S, a C, the bowl of an R): a centre line from
    one end to the other, each stitch at right angles to it, edge to edge (on a tight bend,
    to the nearest edge point on each side);
  - a narrow straight stroke (a stem, leg or crossbar under 3 mm) as lettering is sewn: level
    stitches across stems and legs, up-and-down on bars;
  - strokes wider than 5 mm (up to 12 mm) as split satin: each stitch split into pieces of
    4 mm or less, the splits staggered (like Wilcom's auto split);
  - rings (a border, an O) round the ring; anything else tatami fill (vertical, 3.5 mm).
  Underlay: a centre run there and back on narrow strokes, an edge walk up one side and down
  the other on wide ones (plus a zigzag over 5 mm), as in a Wilcom file. A stroke across the
  centre line is sewn in two halves from the centre out. Pull compensation (0.2 mm).
- Studied against a Wilcom EmbroideryStudio cap file (Beth logo, 2.02 x 1.44 in: 2,421
  stitches, 8 trims, turning satin with centre-run and edge-walk underlay): traced from its
  preview, this gives 2,123 stitches and 15 trims, the swoosh as one turning satin.
- Cap sequencing: by default from the centre of the design outwards, line by line, as lettering
  is sewn: the line nearest the centre first, in it the part nearest the centre line, then
  outwards to the right, then to the left (y o u r: u, r, then y), then the next line, the
  nearest first. Lines are found from where most of each part is, so a y's or g's tail reaching
  into the next line does not join the lines. Inside a letter the pieces that join the others (a
  star's middle) are sewn after them, so the needle runs under them from piece to piece, and an
  arm is sewn out and back (underlay out, satin back) to where the next piece starts: no trim
  inside a letter or a star. The cap is pushed away from the centre seam; or, as
  chosen, rows of parts from the bottom up, in each row the part nearest the centre, then
  outwards to the right, then to the left. Fills and satin bars that cross the centre are
  sewn from the centre outwards, each half on its own. Rings (a border, a circle, an O) get a
  satin column that follows them, from the bottom centre up the right side, then up the left.
- Machine start: the file starts at the centre of the design (or, as chosen, its bottom
  centre, so all stitching is above the needle) and jumps back there at the end ("start center,
  return center"; the Wilcom file does the same).
- Rings with something standing out of them (the ear of a g) are cut there: the ring is sewn
  round, the ear on its own; a short piece (a serif, an ear, a star's point) is a satin at one
  angle, not a turning satin that fans out.
- A letter with a stroke wider than a cap's satin (5 mm: a bold font sewn large) is one even fill
  over the whole letter, not split satin (a seam down each stem) or pieces at their own angles (a
  patchwork). The fill travels between its sections along its edge ("travel on edge", as
  Wilcom's fills), so it needs no trims inside the letter.
- Across colours, from the centre: along a line, where the next part of a colour lies past
  another colour's part (the red o between u and y), that part is sewn there, in its thread (a
  colour change more, as the next block "<id>~n"), so no gap is left between them; only parts
  that touch no other colour move (layering stays). Parts at a line's ends keep their colour's turn.
- Small lettering (strokes under 2 mm in a part under 16 mm) gets half the pull compensation, so
  its letters stay slim and apart; holes under 1 mm2 (a tiny e's eye) cannot be sewn open and are
  filled, so the letter is cut into clean strokes round them.
- Sewing starts: at the centre, the default (the part nearest the middle first, its line first, the stroke
  there cut and sewn outwards both ways, then outwards; Wilcom's 3D WTS file starts there), or
  at the bottom (the lowest row first, its middle part, then right, then left, as the Wilcom
  file sews MAYNARD: N, A, R, D, then Y, A, M). Either
  way 2 mm beside the centre seam, so the first slow stitches do not land in it (Gunold).
- The DST is written as the Wilcom file is: a trim is at least three jumps on the way to the
  next stitch (the machine trims on three jumps in a row), the needle going in where they
  arrive; jumps in steps of 6.3 mm or less; tie-offs of four 0.7 mm stitches; no stitch under
  0.3 mm.
- Worksheet PDF: the production sheet, laid out like Wilcom's. Page 1: the design with the
  start (1) and end (2) cross lines and the first stitch; stitches, colours, colour changes,
  stops, machine, trims, left / right / up / down, end X / Y, longest and shortest stitch,
  longest jump, the colourway and the threads in needle order (needle, stitches, name, code,
  brand), total bobbin, the cap settings and the notes. Page 2 ("Color Film"): each colour on
  its own with its stitches and thread used. Thread is estimated at 2.1 x (top) and 0.8 x
  (bobbin) the length sewn, calibrated on the Wilcom sheet. No barcode.
- No background behind the logo: the page, the preview PNG and the worksheet show the stitches
  on white, as Wilcom's sheet does; a light thread (white) is drawn a shade darker so it shows.
- Preview drawn as Wilcom's realistic view: the stitches drawn in sewing order, each over 1 mm on a
  base 0.44 mm wide in its thread's shade (a satin's or a fill's stitches lie 0.2-0.4 mm apart and
  thread spreads when sewn), with a fine thread line (0.12 mm) and a sheen over it, lit by the way
  it lies and a shade lighter or darker; the thin triangle between a satin stitch and the next one
  going back across filled too; so satins and fills show solid, with no gaps; a soft shadow under
  the design.
- Satin with no bare wedges: where a satin's stitches turn sharply (round a tight bend, or where an
  end's angle is held), stitches are added that walk the edge with the gap, fanning round the turn
  as Wilcom's short stitches do.
- Workflow: a logo opened is shown as it is; **Digitize** makes the stitches. After that every change
  (a setting, a thread, an edit on the design) waits: the button turns to **Update Digitizing**,
  and the logo is digitized again when it is clicked (or before a file is saved). A piece's
  pending edit shows on the design (where it will be, in its new thread) until then.
- Threads: each colour row has a palette button with every thread of the chart (Isacord 40: 390),
  searchable by number or name; the Colour tool gives a single piece its own thread (sewn with the
  logo colour that has it, or as a colour of its own right after the one it came from).
- Choose logo (or a drop or paste) with work on the page asks first: Save writes the DST, the
  worksheet PDF and the preview PNG (into one folder the app asks for; in a browser, to Downloads),
  Discard clears the page, Cancel keeps it.
- A .DST file opens to view and edit: its stitches drawn as thread, the details row, a colour for
  each colour block (pick a thread from the palette); its pieces are the runs of stitches between
  trims and colour changes (a letter, a swoosh: the objects Wilcom shows); click one to move,
  resize, turn, recolour or delete it (a piece given another thread becomes a colour block of its
  own, sewn right after the one it came from); the width and height scale every stitch (more than 20% warns: the density
  changes); undo and redo; Download DST, Preview PNG and Worksheet PDF write it again.
- Digitizing fixes after Wilcom's "your logo here" (28 Oct 2026): a shape with a spiky hole (a
  circle with a star in it) is cut from each point of the hole straight out into wedges, each a
  satin at one angle straight out from the hole's centre; a stroke's ends (serifs, feet, flags)
  are sewn at the angle the stroke has where it is regular, not fanned; a stem and its foot are
  one column; a straight stroke of any width is sewn at one angle (level on stems, upright on
  bars), long stitches split; the centre start cuts only straight strokes.
- Zoom (tool strip): the zoom tool (Z picks it, Z again goes back to Select): click to zoom in 1.5x,
  option-click to zoom out, drag to move around; zoom in, zoom out and Fit buttons; a pinch or
  ⌘-scroll zooms at the pointer, a scroll moves around a zoomed design. Up to 40x; selecting and
  editing work at any zoom; a new file starts with the whole design in view.
- Hand (tool strip, H): drag to move the view around, at any zoom; H again goes back to the tool
  before (a pen path being drawn is kept). Fit brings the whole design back.
- Arrange (tool strip): Bring to Front (⇧⌘]), Bring Forward (⌘]), Send Backward (⌘[), Send to Back
  (⇧⌘[). In embroidery the front is what is sewn last, so these set the sewing order: an opened
  DST's stitches are sewn again in the new order at once; a logo's pieces when you click Update
  Digitizing (`arrange` in the options). A colour whose pieces no longer come together is sewn in
  blocks ("<id>~1"...), each a colour change, with the colour's thread. Puff colours stay last.
- Pen line width: 0.5, 1, 1.5, 2, 3 or 4 mm.
- Align (tool strip), as Illustrator's Align panel: Align Objects lines the selected pieces up by
  their left edges, horizontal centres, right edges, centres both ways, top edges, vertical centres
  or bottom edges (to each other; one piece: on the whole design); Distribute Objects spaces three
  or more evenly by their top edges, middles, bottom edges, left edges, centres or right edges. Each
  is one undo; works on a logo's pieces, shapes drawn and an opened DST's pieces.
- Corners (live, as Illustrator's): select a shape you drew (a square, rectangle, triangle,
  diamond, hexagon, star, arrow, or a closed pen shape) and a dot shows inside each corner (a point
  where the outline turns by more than 20°). Drag a dot into the corner to round every corner; click
  a dot to pick that corner only (shift-click for more), click the shape to work on all of them
  again. The Corners panel (tool strip) sets the radius in mm, up to as round as the sides allow,
  and the corner: Round, Chamfer or Inverted round. The sharp outline is kept with the shape, so the
  corners can be changed again at any time; a shape already sewn becomes a drawn shape again (where
  it was moved to) and is sewn with its new corners on Update Digitizing.
- Text (tool strip, T): type lettering (Return for more lines), pick a font, the capital letters'
  height in mm (as Wilcom sizes lettering), letter spacing, line alignment and the thread, and Add
  text: it goes in the middle of the view, selected, to move, resize, turn or recolour like a shape,
  and is sewn with the logo (on an opened DST, at once). A text not sewn yet, selected, is changed
  in the same panel (Update text). The server turns it into outlines with fontTools
  (`digitize.text_outline`, `/api/cap/text`), and they are digitized as a drawn shape is: satin on
  strokes, fill where wide. The 14 fonts (`static/fonts`) are open fonts (SIL Open Font License,
  licences in `static/fonts/licenses`) in the styles of Wilcom's lettering: Block, Condensed Block,
  Narrow Sans, Tall Block, Serif, Slab Serif, Varsity / College, Script, Handwriting, Casual Script,
  Brush Script, Old English, Western and Rounded. Wilcom's own (ESA) fonts are licensed with
  EmbroideryStudio and cannot be shipped.
- Pathfinder (tool strip): select two or more shapes you drew (drawn or already sewn), then Unite
  (one shape), Minus Front (the back shape less the ones in front), Intersect (only the overlap) or
  Exclude (the overlap cut out), as Illustrator's. The result is one new shape, with holes where
  there are any, in the front shape's thread (Minus Front: the back one's); it is sewn when you
  click Update Digitizing, and undo brings the shapes back. The shapes are combined by the engine
  (`/api/cap/pathfinder`, shapely). The logo's own pieces are not combined.
- Pen points: option-click a point to take its handles away; on the last point only the handle
  going on goes (the curve coming in stays), so the next line starts straight.
- Shapes and pen (tool strip): Shapes opens a menu of circle, square, rectangle, rounded rectangle,
  triangle, diamond, hexagon, star, heart and arrow; pick one (the menu closes) and drag it out on
  the design (shift: as wide as tall). The pen draws a path point by point: click to place a corner,
  drag while placing a point to curve the line through it; click the first point to close a filled
  shape, or press Enter (or double-click) to end it as a line of the pen's width (0.5-4 mm), sewn as a
  satin that follows it; Backspace takes the last point back, Esc drops the path. Each menu picks the
  thread (any of the chart's). A new drawing is selected at once and the tool goes back to Select:
  move, resize, turn, recolour or delete it straight away. On a logo it shows in its thread until
  Update Digitizing, then it is digitized like the logo (satin where narrow, fill where wide) as a
  colour of its own after the logo's, and stays a piece to edit. On a DST it is sewn at once, in the
  last colour when the thread is the same, else as a new colour at the end.
- Selecting several pieces: drag a box over empty space (every piece whose middle is inside is
  selected), shift-click to add or take one away, ⌘A for all; moving, resizing, turning, recolouring
  and deleting then act on the whole selection (resized and turned about its centre).
- A DST piece resized keeps its look: its stitches are spaced again as they were. A satin (stitches
  going back and forth across) has its two edges walked again at the old spacing, so it keeps its
  density; a run (underlay, travel) has its stretched stitches split back to their old length. The
  size fields do the same for the whole design.
- Editing (`static/cap-edit.js`), as Wilcom's Select tool: click a piece of the logo (a letter, a
  star: each separate shape of a colour) to select it; drag it to move it, a corner to resize it,
  the knob above it to turn it (shift: 15° steps); the tool strip turns it 15°, makes it 10%
  bigger or smaller, deletes it, and undoes, redoes or resets every edit; arrows nudge it 0.5 mm
  (shift: 2.5 mm), Delete removes it, ⌘Z / ⇧⌘Z undo and redo, Esc deselects. Each edit is kept per
  piece and the logo is digitized again; while edits exist the scale stays fixed, so the rest of
  the design does not move or change size, and the width and height show the design as edited.
  The DST, PNG and worksheet include the edits. A new logo starts with none.
- Travel: the thread runs inside this colour where stitches are still to come, or under colours
  sewn later; short hops (up to 3 mm) may cross finished stitches of the same colour; otherwise
  it is trimmed (three jumps in the DST). A way that would leave the area (two letters less than
  about a millimetre apart) is refused, and a fill row that starts past the end of the last row
  (a T's bar onto its stem) is reached along the rows, not straight across the bare cap.
- Crown: with the crown height chosen, the height is kept about 1/2 in clear of the top and
  bottom (a 2.5 in crown takes a design about 1.5 in tall; Gunold).
- Turn: side logos can be turned 10, 12 or 15 degrees either way, to counter the slope of the
  cap's side (Gunold: "normally 10 to 15 degrees"). No source says which way; sew one and check.
- Tack-down underlay (option): a light tatami (rows 3 mm apart, 4 mm stitches) over the whole
  design, 0.8 mm inside it, sewn first in the first colour's thread, centre-out and bottom-up.
  For stiff or slippery caps (Gunold: "add the tack down underlay, over as much as you can").
  Areas under about 5 x 5 mm are left out; each separate area costs a trim.
- Fewer stitches (option): tatami underlay rows 3 mm apart (2 mm), satin underlay 2.5 mm (2 mm),
  fill 10% sparser with 4 mm stitches (3.5 mm). Saves about 12% on a fill logo, little on satin.
- Threads: the nearest Isacord 40, Madeira Polyneon 40 or Robison-Anton Polyester 40 thread
  (CIEDE2000) for each colour; pick another, skip a colour, or change the sewing order. The
  logo's background colour is sewn only inside the logo (white stripes, a white star).
- 3D puff: tick Puff on each colour to raise. Puff colours sew after the flat ones. Built to
  match a Wilcom 3D puff cap file (the WTS logo, 4.00 x 1.96 in, 5,686 stitches, 11 trims;
  decoded 28 Oct 2026). For each puff colour:
  - a centre run (1.5 mm stitches) down each stroke holds the cap to its backing, as Wilcom's
    file sews before its stop; a part with no centre line gets an edge run;
  - a stop (a colour change to the same thread): lay the foam;
  - each stroke is one satin at 0.15 mm on each side (Wilcom's file: 0.15), with no underlay;
    stitches up to 12 mm across (Wilcom's file: up to 11.5 mm), no splits;
  - a straight stroke is sewn level across a stem or leg and upright across a bar (as Wilcom's
    T and i); a curved one turns with it (Wilcom's S); a short piece (a dot) at one angle, with
    end caps 1.2 mm deep where its satin runs along the edge;
  - the run and the satin both start at the stroke nearest the start point and go on to the
    nearest next stroke (Wilcom's: W, i, T, the dot, S).

  Letters are cut into strokes at their inside corners (a T into its bar and stem). A part with
  a piece wider than 12 mm is sewn flat before the foam, with a note. Wilcom's file sews its
  centre run in a thread matching the cap (black) and the puff in 30-weight thread; here both are
  the puff colour's thread. The preview draws puff satin as one lit surface, as Wilcom's does.
- Notes on the page: parts under 0.25 in or 0.8 mm wide, and sizes beyond a front panel.
  Auto-digitized files suit simple logos and text; sew one cap before a run.
- Checked against a professionally digitized flag (1.51 x 1.06 in, 5,544 stitches, 19 trims):
  this gives 4,033 stitches and 35 trims at the same size (28 Oct 2026, with turning satin).

## What is different

vectorizer.ai's tracing engine runs on its own servers and is closed source, so this
cannot be the same engine. Tracing here (Method: **Precise**, the default, in `precise.py` and
`planar.py`):

1. **Palette.** Colours are found as before; anti-aliasing blends are dropped, and so are the
   fringes a JPEG leaves round its edges (a colour close to another that fills no flat area and
   draws no lines of its own). The image's compression noise is measured, and merging widens
   with it, so a JPEG logo gets its real colours and a clean PNG keeps close shades apart.
2. **Colour shares.** Every anti-aliased edge pixel is split between its two neighbouring
   colours in proportion; a mild unsharp mask on the shares undoes some of the anti-aliasing
   blur, so strokes thinner than a pixel survive.
3. **Supersampling.** The shares are enlarged up to 8x (bicubic, about 4 million cells at most,
   at least 2x) and each cell takes its strongest colour, so outlines follow the true edges to a
   fraction of a pixel and small shapes have enough points to find their corners.
4. **Planar map** (`planar.py`). The boundaries between colours form one network: junctions
   where three colours meet, and edges between two colours. Each edge is fitted **once** and
   both shapes beside it use that same fitted line, so neighbouring shapes meet exactly, with no
   gaps or overlaps. Junctions blur over a pixel or two, so each one is moved to where its edges,
   followed straight on, meet.
5. **Fitting.** Corners are found where an outline turns sharply over 2 px and as sharply over
   1 px (a circle's turn halves). Pixels round corners off, so each corner is rebuilt where its
   two sides, followed straight on, meet. Straight sides become lines, the rest cubic Beziers
   (Schneider) within 0.2 px of the outline (Smoothing 0-100 sets 0.1-0.3 px).

0. **AI upscale** (`upscale.py`, images up to 1000 px). A small or blurred logo does not hold
   its finest shapes (12 px lettering, the gap between two strokes). Real-ESRGAN x4plus anime 6B
   (open source, made for drawings and flat colour) redraws the image larger with crisp edges, on
   this Mac with onnxruntime; the tracer works on that (at twice the size) and scales the shapes
   back. The colours still come from the image's own pixels. The model is
   `models/realesrgan_anime6b_x4.onnx`, made from the official weights by
   `tools/esrgan_to_onnx.py`; without it (or onnxruntime) tracing works as before. It adds about
   10 s for a 440 px image on an Intel Mac (about 40 s for 1000 px on Apple Silicon); editing the
   palette afterwards reuses it. Patch Mockup and DST Maker trace without it (they need the
   logo's shapes, not its finest detail). The website ships without the model, so it traces
   without it too. scipy (the planar map) and onnxruntime need macOS 12 on Apple Silicon (11 on
   Intel); on an older Mac the app still runs, tracing each colour on its own without AI.

Measured with `bench/run.py` (below), against the tracer before these changes: pixels
clearly wrong 1.89 % -> 0.88 %, edge error 24.0 -> 10.4, with about the same number of nodes.
**Classic** uses the open-source [VTracer](https://github.com/visioncortex/vtracer) on an
upscaled, palette-snapped copy; it is quicker on photos. Shape fitting, layering and export
are written in `engine.py` and `export.py`. Results are
similar for logos and flat artwork, and less refined than vectorizer.ai's deep-learning
engine on photos, very small text and soft shadows. Symmetry modelling, corner-by-corner
control and centerline tracing are not implemented (vectorizer.ai has no centerline
tracing either). Inputs above 3 megapixels are scaled down first.

## Accuracy benchmark

```bash
.venv/bin/python bench/run.py                  # table + bench/out/sheet.png (truth | input | result)
.venv/bin/python bench/run.py star text        # some cases only
.venv/bin/python bench/run.py --opts "{'fit_tolerance': 0.15}"   # try an option
```

Each case in `bench/cases.py` is an exact SVG. It is drawn small (64 or 128 px, also as a
JPEG), vectorized, and the result is drawn at 512 px and compared with the true SVG drawn at
512 px: **bad%** pixels clearly the wrong colour, **edge** mean colour error near the true
edges, **nodes** path segments written. Run it before and after a change to the tracer.

`bench/holes.py` checks every case, and every image in `bench/real/`, for holes: parts of the
source that no traced shape covers (drawn without the gap filler, which would hide them). It
exits with an error when it finds one; run it after every change to the tracer. Put real images
that once went wrong in `bench/real/` so they stay checked.

## Files

- `engine.py` - palette, tracing, shape fitting, layers, SVG writing
- `precise.py` - the Precise tracer: colour shares, supersampling, corner-aware line and Bezier fitting
- `planar.py` - the planar map: shared edges between colours, junctions, outlines from shared edges
- `upscale.py`, `models/`, `tools/esrgan_to_onnx.py` - AI upscale before tracing (Real-ESRGAN, onnxruntime)
- `bench/` - accuracy benchmark (`run.py`, cases in `cases.py`), timing (`speed.py`), every mode through the API (`robust.py`)
- `gang.py`, `static/gang.html`, `gang.js`, `gang.css` - Gang sheet
- `digitize.py`, `static/cap.html`, `cap.js`, `cap.css` - Cap DST (auto-digitizing, DST writer)
- `worksheet.py` - the Cap DST worksheet PDF
- `export.py` - PDF, EPS, PNG and DXF output
- `app.py` - local web server; `static/` - the pages
- `static/pantone.html`, `pantone.js`, `pantone.css`, `color.js` (Lab and CIEDE2000), `pantone-data.json` - Pantone match
- `static/colorinput.js` - the Hex / RGB / CMYK input on both match pages
- `static/cmyk-fogra39.json`, `make_cmyk_table.py` - the FOGRA39 CMYK table and the script that makes it
- `static/leatherette/`, `make_leatherette.py` - leatherette textures and colour list for Faux/Leather
- `static/thread.html`, `thread.js`, `thread.css`, `thread-data.json` - Thread match (uses `color.js` and `pantone.css`)
- `vectorize.py`, `vectorize` - command line
- `.venv/` - Python 3.12 environment (VTracer, Pillow, NumPy, Shapely, Flask, CairoSVG, ezdxf); needs Homebrew `cairo`
