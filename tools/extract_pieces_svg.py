#!/usr/bin/env python3
"""Extract a library's base geometry to a clean pieces.svg.

The output separates what a piece *is* from how the file happens to look:

  * Every piece is one ``<g id="mpNN">`` in ``<defs>``, holding the outline as
    a path in the library's own coordinates — millimetres, centred on the
    piece's centroid. That is the canonical geometry, and it is what a loader
    reads.
  * Attachment points ride inside the same group as ``<circle class="attach">``,
    so they stay attached to the piece they belong to.
  * The visible contact sheet below is ``<use>`` references only. It exists so
    the file can be opened and looked at; deleting it loses no data.

The previous reference sheet baked its grid offsets straight into the path
coordinates, which made it a picture of the library rather than the library.

Usage:
    python tools/extract_pieces_svg.py                    # marble -> pieces.svg
    python tools/extract_pieces_svg.py --library marble --out somewhere.svg
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from mosaic_fill.library import Library, discover_libraries  # noqa: E402

PIECE_CLASS = "piece"
ATTACH_CLASS = "attach"
ATTACH_DOT_R_MM = 0.45


def _fmt(value: float, places: int = 4) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def _path_data(rings) -> str:
    parts = []
    for ring in rings:
        if len(ring) < 3:
            continue
        points = [f"{_fmt(x)},{_fmt(y)}" for x, y in ring]
        parts.append(f"M{' L'.join(points)} Z")
    return " ".join(parts)


def build_pieces_svg(library: Library, columns: int = 6, gutter_mm: float = 3.0) -> str:
    """Render `library` as a clean pieces.svg."""
    pieces = library.pieces
    if not pieces:
        raise ValueError("library has no pieces")

    cell = max(p.size_mm for p in pieces) + gutter_mm
    rows = math.ceil(len(pieces) / columns)
    width = columns * cell
    height = rows * cell

    defs: list[str] = []
    uses: list[str] = []
    for index, piece in enumerate(pieces):
        data = _path_data(piece.rings)
        if not data:
            continue
        body = [f'    <path d="{data}"/>']
        for x, y in piece.attach:
            body.append(
                f'    <circle class="{ATTACH_CLASS}" cx="{_fmt(x)}" cy="{_fmt(y)}" '
                f'r="{_fmt(ATTACH_DOT_R_MM)}"/>'
            )
        defs.append(
            f'  <g id="{piece.id}" class="{PIECE_CLASS}">\n'
            + "\n".join(body) + "\n  </g>"
        )

        cx = (index % columns) * cell + cell / 2
        cy = (index // columns) * cell + cell / 2
        uses.append(f'    <use href="#{piece.id}" x="0" y="0" '
                    f'transform="translate({_fmt(cx)} {_fmt(cy)})"/>')

    lo, hi = library.size_range_mm
    attach_total = sum(len(p.attach) for p in pieces)

    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  {library.name} - base geometry.

  Canonical data lives in <defs>: one <g class="{PIECE_CLASS}"> per piece, outline
  in millimetres, centred on the piece's own centroid. Attachment points are the
  circles marked class="{ATTACH_CLASS}" inside each group.

  The class markers are what a loader keys on, so a wrapper or layer group can
  never be mistaken for a piece, nor a stitch point for geometry.

  The contact sheet below is <use> references only - presentation, not data.
  Editing a piece means editing its <defs> entry; the sheet follows.

  {len(pieces)} pieces, {_fmt(lo, 2)}-{_fmt(hi, 2)} mm at scale 1.0, {attach_total} attachment points.
-->
<svg xmlns="http://www.w3.org/2000/svg"
     width="{_fmt(width, 2)}mm" height="{_fmt(height, 2)}mm"
     viewBox="0 0 {_fmt(width, 2)} {_fmt(height, 2)}">
  <title>{library.name} - {len(pieces)} pieces</title>
  <desc>Base geometry in millimetres, each piece centred on its centroid.</desc>

<defs>
{chr(10).join(defs)}
</defs>

  <g fill="none" stroke="#1c1c1c" stroke-width="0.25"
     stroke-linejoin="round" stroke-linecap="round">
{chr(10).join(uses)}
  </g>
  <style>
    .{ATTACH_CLASS} {{ fill: #c0392b; stroke: none; }}
  </style>
</svg>
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--library", default="marble")
    parser.add_argument("--library-dir", type=Path,
                        default=REPO_ROOT / "backend" / "libraries")
    parser.add_argument("--out", type=Path, default=None,
                        help="default: <library folder>/pieces.svg")
    parser.add_argument("--columns", type=int, default=6)
    args = parser.parse_args(argv)

    libraries = discover_libraries(args.library_dir)
    if args.library not in libraries:
        known = ", ".join(sorted(libraries)) or "none found"
        print(f"unknown library {args.library!r}; available: {known}", file=sys.stderr)
        return 2
    library = libraries[args.library]

    out = args.out or (args.library_dir / args.library / "pieces.svg")
    out.write_text(build_pieces_svg(library, args.columns), encoding="utf-8")

    lo, hi = library.size_range_mm
    print(f"wrote {out}")
    print(f"  pieces      : {len(library.pieces)}")
    print(f"  size range  : {lo:.2f} - {hi:.2f} mm at 1.0x")
    print(f"  attach pts  : {sum(len(p.attach) for p in library.pieces)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
