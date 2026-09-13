#!/usr/bin/env python3
"""Command-line front end for the packing engine.

Runs without FastAPI, exactly as the engine did before there was a web app:

    python -m mosaic_fill.cli samples/Velvet.svg --scale 2.0 --gap 1.0 \
        --out filled.svg --json placements.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .library import discover_libraries
from .packer import PackParams, occupancy_overlaps, pack
from .svgdoc import CalibrationError, parse_panel, select_shapes, shapes_to_mm
from .svgout import build_filled_svg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mosaic_fill",
        description="Fill a panel SVG with embroidery pieces.",
    )
    parser.add_argument("panel", type=Path, help="panel SVG containing an id='calib' element")
    parser.add_argument("--library", default="marble", help="library id (default: marble)")
    parser.add_argument("--library-dir", type=Path, default=None,
                        help="override the libraries folder")
    parser.add_argument("--calib-mm", type=float, default=100.0,
                        help="real-world width of the calib element in mm (default: 100)")
    parser.add_argument("--units-per-mm", type=float, default=None,
                        help="supply units/mm directly when the file has no calib element")
    parser.add_argument("--scale", type=float, default=2.0, help="piece scale multiplier")
    parser.add_argument("--gap", type=float, default=1.0, help="minimum gap in mm")
    parser.add_argument("--coverage", type=float, default=0.56, help="target coverage, 0-1")
    parser.add_argument("--seed", type=int, default=20260913)
    parser.add_argument("--grid-res", type=float, default=2.0, help="occupancy cells per mm")
    parser.add_argument("--rotation-steps", type=int, default=24)
    parser.add_argument("--bands", type=int, default=1, help="colour bands")
    parser.add_argument("--band-angle", type=float, default=0.0)
    parser.add_argument("--band-jitter", type=float, default=0.0)
    parser.add_argument("--edge-clearance", type=float, default=0.0,
                        help="keep pieces this many mm clear of the panel edge")
    parser.add_argument("--shape-id", action="append", default=None,
                        help="restrict the fill to these element ids (repeatable)")
    parser.add_argument("--compact", action="store_true",
                        help="write <defs> + <use> instead of plain paths; smaller, "
                             "but some readers (Illustrator) draw nothing for a "
                             "<use> reference")
    parser.add_argument("--attach-dots", action="store_true",
                        help="mark each piece's stitch-down points in the exported SVG")
    parser.add_argument("--attach-radius", type=float, default=0.45,
                        help="attachment dot radius in mm (default: 0.45)")
    parser.add_argument("--out", type=Path, default=None, help="write the filled SVG here")
    parser.add_argument("--json", type=Path, default=None, help="write placement JSON here")
    parser.add_argument("--check-overlaps", action="store_true",
                        help="rebuild the occupancy grid and report overlapping cells")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    libraries = discover_libraries(args.library_dir)
    if args.library not in libraries:
        known = ", ".join(sorted(libraries)) or "none found"
        print(f"unknown library {args.library!r}; available: {known}", file=sys.stderr)
        return 2
    library = libraries[args.library]

    doc = parse_panel(args.panel.read_text(encoding="utf-8"))
    if args.units_per_mm is not None:
        units_per_mm = args.units_per_mm
    else:
        try:
            units_per_mm = doc.units_per_mm(args.calib_mm)
        except CalibrationError as exc:
            print(f"{exc}. Pass --units-per-mm to set the scale directly.", file=sys.stderr)
            return 2

    shapes = shapes_to_mm(select_shapes(doc, args.shape_id), units_per_mm)
    params = PackParams(
        piece_scale=args.scale,
        min_gap_mm=args.gap,
        target_coverage=args.coverage,
        seed=args.seed,
        grid_res=args.grid_res,
        rotation_steps=args.rotation_steps,
        bands=args.bands,
        band_angle_deg=args.band_angle,
        band_jitter_mm=args.band_jitter,
        edge_clearance_mm=args.edge_clearance,
    )

    started = time.time()
    result = pack(shapes, library, params, units_per_mm)
    elapsed = time.time() - started

    stats = result.stats
    print(f"library    : {library.name} ({len(library.pieces)} pieces)")
    print(f"units/mm   : {units_per_mm:.6f}")
    print(f"region     : {stats['region_mm2'] / 1e6:.4f} m^2")
    print(f"pieces     : {stats['count']}")
    print(f"coverage   : {stats['coverage'] * 100:.2f}%")
    if args.attach_dots:
        per_piece = {p.id: len(p.attach) for p in library.pieces}
        total = sum(per_piece.get(p.piece, 0) for p in result.placements)
        print(f"attach pts : {total} across {stats['count']} pieces")
    print(f"pack time  : {elapsed:.2f}s")

    if args.check_overlaps:
        overlaps = occupancy_overlaps(result.placements, library, params, shapes)
        print(f"overlaps   : {overlaps} cells")

    if args.json:
        args.json.write_text(json.dumps(result.to_json()), encoding="utf-8")
        print(f"wrote {args.json}")
    if args.out:
        filled = build_filled_svg(
            doc.source, result.placements, library, params.piece_scale, units_per_mm,
            show_attach=args.attach_dots, attach_dot_radius_mm=args.attach_radius,
            expand=not args.compact,
        )
        args.out.write_text(filled, encoding="utf-8")
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
