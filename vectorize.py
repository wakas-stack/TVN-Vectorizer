"""Command line: vectorize one or more images without the web page.

    ./vectorize input.png                      -> input.svg
    ./vectorize logo.jpg -f pdf --colors 6     -> logo.pdf
    ./vectorize *.png -o out/ --stacking stacked --group-by layer
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import engine
import export


def main(argv=None):
    ap = argparse.ArgumentParser(description="Convert raster images to layered vector files.")
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("-o", "--output", type=Path, help="output file (one input) or folder")
    ap.add_argument("-f", "--format", default="svg", choices=["svg", "pdf", "eps", "dxf", "png"])
    ap.add_argument("--colors", type=int, default=0, help="maximum palette colours (0 = detect)")
    ap.add_argument("--stacking", default="cutouts", choices=["cutouts", "stacked"])
    ap.add_argument("--group-by", default="color", choices=["none", "color", "parent", "layer"])
    ap.add_argument("--draw-style", default="fill_shapes", choices=["fill_shapes", "stroke_shapes", "stroke_edges"])
    ap.add_argument("--detail", type=int, default=50, help="0..100")
    ap.add_argument("--smoothing", type=int, default=50, help="0..100")
    ap.add_argument("--corner-threshold", type=int, default=60, help="degrees")
    ap.add_argument("--no-fit-shapes", action="store_true", help="keep circles/rectangles as plain paths")
    ap.add_argument("--no-gap-filler", action="store_true")
    ap.add_argument("--remove-background", action="store_true")
    ap.add_argument("--dxf-level", default="lines", choices=["lines", "lines_arcs", "splines"])
    a = ap.parse_args(argv)

    opts = {"max_colors": a.colors, "shape_stacking": a.stacking, "group_by": a.group_by,
            "draw_style": a.draw_style, "detail": a.detail, "smoothing": a.smoothing,
            "corner_threshold": a.corner_threshold, "fit_shapes": not a.no_fit_shapes,
            "gap_filler": not a.no_gap_filler, "remove_background": a.remove_background}
    many = len(a.inputs) > 1 or (a.output and a.output.suffix == "")
    if many and a.output:
        a.output.mkdir(parents=True, exist_ok=True)
    for src in a.inputs:
        r = engine.trace(src.read_bytes(), opts)
        svg = r["svg"]
        data = {"svg": lambda: export.clean_svg(svg).encode(), "pdf": lambda: export.to_pdf(svg),
                "eps": lambda: export.to_eps(svg), "png": lambda: export.to_png(svg),
                "dxf": lambda: export.to_dxf(svg, a.dxf_level)}[a.format]()
        if many:
            dst = (a.output or src.parent) / (src.stem + "." + a.format)
        else:
            dst = a.output or src.with_suffix("." + a.format)
        dst.write_bytes(data)
        s = r["stats"]
        print(f"{src} -> {dst}  ({len(r['colors'])} colours, {s['shapes']} shapes, {s['groups']} layers/groups)")
        for n in r["notes"]:
            print("  note:", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
