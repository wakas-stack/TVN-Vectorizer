# Vectorizer Local

A local image-to-vector converter modelled on the features of [vectorizer.ai](https://vectorizer.ai).
Upload a PNG, JPG, GIF, BMP or WebP image and get an editable, layered SVG (or PDF, EPS, DXF, PNG).
Everything runs on this Mac; images never leave it.

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

`dist/Vectorizer-Local-Mac.zip` holds `Vectorizer Local (Mac)/`: the app and `READ-ME-FIRST.txt`.
Copy it to another Mac (Apple Silicon or Intel, macOS 11+), double-click
**Vectorizer Local.app**, and it opens in its own window; close the window to quit.
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
  line), **Thickness** (0.4-2.4×) and **Colour** (picking a colour turns "Cream thread" off).
  The seam is flat, with no relief or shadow; dashes are four times as long as they are thick,
  spaced evenly along the seam line itself and follow its corners.
- Shape (follow the logo, circle, rounded rectangle, rectangle), border (merrow, satin,
  laser-cut, none; stitched seam for leather), border colour and width.
- Relief, thread density, stitch angle, light direction, gloss, 100% embroidered; leather
  colour and finish (debossed, embossed, laser engraved).
- Transparent, white or coloured background, drop shadow; PNG export up to 3000 px.

**Choose logo** asks before replacing a patch that is being worked on ("Keep working" or
"Discard and choose logo"); the current patch stays until a new logo is actually picked.

It is a mockup for showing or ordering, made from the logo's vector shapes (`patch.py`), not a
photo and not a machine stitch file (DST/PES).

## Gang sheet

http://127.0.0.1:8765/gang, or **Gang sheet** in the header. Add one logo, set the sheet size
(Letter, Tabloid, A4, A3, DTF 22 in wide... or custom, in in/cm/mm) and the logo size (its
proportions kept), and the sheet is filled with as many logos as fit inside the margin, the gap
apart, the block centred; logos are turned 90 degrees when that fits more. The sheet border is
optional, and so is a box round each logo (off unless ticked; 0.5 pt black lines).

- Logos: PDF and AI (Illustrator's PDF-compatible AI, the default) are placed as their own vector
  page, trimmed to the artwork; SVG is written as a vector PDF first; PNG, JPG, WebP, TIFF are
  placed as images (transparent edges trimmed). EPS cannot be read: macOS no longer has a
  PostScript reader (checked: no `pstopdf`, Quartz's PostScript converter does not run).
- Downloads: PDF and AI (a PDF-based .ai file Illustrator opens) are vector for vector logos; PNG
  and TIFF transparent, JPG white, at 150/300/600 dpi; EPS has the logo's vector paths for SVG
  logos, and otherwise holds the sheet as an image (macOS cannot write PostScript from PDF).
- Removing logos: click a logo on the preview to leave its place empty (again to put it back);
  the round buttons beside the rows do a whole row; "Put all logos back". The sheet and every
  other place stay the same, in the preview and in every download. Changing the layout (sheet,
  logo size, gap, margin, turning) puts the removed logos back, as the places change.
- Undo: Cmd+Z / Ctrl+Z or **Undo** takes back the last edit (a logo or row taken off or put
  back, a sheet or logo setting), up to 50 times; typing in one box is one edit, and a box
  being typed in keeps its own text undo. A new logo starts a new history.
- Made with Quartz (Core Graphics) in `gang.py`; the app saves large files straight from the
  local server (`Api.save_url`).

## What is different

vectorizer.ai's tracing engine runs on its own servers and is closed source, so this
cannot be the same engine. Tracing here (Method: **Precise**, the default, in `precise.py`)
gives every anti-aliased edge pixel to its two neighbouring colours in proportion, finds each
colour's outline where it stops being the strongest colour to a fraction of a pixel (marching
squares; neighbouring colours share one line, so there are no gaps or rims), and fits it with
cubic Bezier curves (Schneider's method), keeping corners sharp. A pixel may only mix the
colours found around it, so compression fringes do not become colours of their own, and the
palette keeps a small colour (an overlap, a darker tip) when it fills a flat area of its own,
or when it draws strokes of its own (thin line art, an engraved heart or date): its pixels hang
together and see one other colour around them, where an edge blend sees two. Specks and
slivers that are dropped hand their area to the colours around them, so they leave no gaps.
On the bird test logo this halved the error along the edges against the old tracer
(edge-band difference 14.8 -> 7.6, pixels off by more than 40: 0.83 % -> 0.17 %).
**Classic** uses the open-source [VTracer](https://github.com/visioncortex/vtracer) on an
upscaled, palette-snapped copy; it is quicker on photos. Shape fitting, layering and export
are written in `engine.py` and `export.py`. Results are
similar for logos and flat artwork, and less refined than vectorizer.ai's deep-learning
engine on photos, very small text and soft shadows. Symmetry modelling, corner-by-corner
control and centerline tracing are not implemented (vectorizer.ai has no centerline
tracing either). Inputs above 3 megapixels are scaled down first.

## Files

- `engine.py` - palette, tracing, shape fitting, layers, SVG writing
- `precise.py` - the Precise tracer: colour shares, sub-pixel outlines, Bezier fitting
- `gang.py`, `static/gang.html`, `gang.js`, `gang.css` - Gang sheet
- `export.py` - PDF, EPS, PNG and DXF output
- `app.py` - local web server; `static/` - the pages
- `static/pantone.html`, `pantone.js`, `pantone.css`, `color.js` (Lab and CIEDE2000), `pantone-data.json` - Pantone match
- `static/colorinput.js` - the Hex / RGB / CMYK input on both match pages
- `static/cmyk-fogra39.json`, `make_cmyk_table.py` - the FOGRA39 CMYK table and the script that makes it
- `static/leatherette/`, `make_leatherette.py` - leatherette textures and colour list for Faux/Leather
- `static/thread.html`, `thread.js`, `thread.css`, `thread-data.json` - Thread match (uses `color.js` and `pantone.css`)
- `vectorize.py`, `vectorize` - command line
- `.venv/` - Python 3.12 environment (VTracer, Pillow, NumPy, Shapely, Flask, CairoSVG, ezdxf); needs Homebrew `cairo`
