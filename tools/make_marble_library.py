#!/usr/bin/env python3
"""Generate the MARBLE mosaic piece library as data files.

STAND-IN. The real MARBLE library is traced by hand from the rapport image and
was not available when this was written; this script synthesises a 22-piece set
that matches MARBLE's documented envelope so the whole pipeline is exercisable
end to end:

  * 22 pieces
  * largest dimension spanning 9.4 mm - 24.9 mm at scale 1.0, which is the
    range implied by the published multiples (1.5x -> 14-37 mm,
    2x -> 19-50 mm, 3x -> 28-75 mm)
  * rapport coverage 56%

Replacing it is a data swap, not a code change: drop the real pieces.json and
mosaic-piece-library.svg into backend/libraries/marble/ and delete nothing else.

Usage:  python tools/make_marble_library.py
"""

from __future__ import annotations

import json
import math
import random
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent.parent / "backend" / "libraries" / "marble"
PIECE_COUNT = 22
SIZE_MIN_MM = 9.4
SIZE_MAX_MM = 24.9
RAPPORT_COVERAGE = 0.56
SEED = 20260913


def make_shard(rng: random.Random, target_size: float) -> list[tuple[float, float]]:
    """One irregular tessera: a convex-ish chip with uneven sides.

    Vertices are placed on jittered angles at jittered radii, then the whole
    chip is squashed along a random axis so the set does not read as a bag of
    identical blobs.
    """
    sides = rng.choice([4, 4, 5, 5, 5, 6, 6, 7])
    base = target_size / 2.0
    points: list[tuple[float, float]] = []
    for i in range(sides):
        span = 2 * math.pi / sides
        angle = i * span + rng.uniform(-0.32, 0.32) * span
        radius = base * rng.uniform(0.74, 1.0)
        points.append((radius * math.cos(angle), radius * math.sin(angle)))

    # Squash and rotate so pieces vary in proportion, not just in size.
    squash = rng.uniform(0.62, 0.95)
    tilt = rng.uniform(0, math.pi)
    cos_t, sin_t = math.cos(tilt), math.sin(tilt)
    shaped: list[tuple[float, float]] = []
    for x, y in points:
        sx, sy = x, y * squash
        shaped.append((sx * cos_t - sy * sin_t, sx * sin_t + sy * cos_t))

    # Normalise so the largest dimension is exactly target_size.
    xs = [p[0] for p in shaped]
    ys = [p[1] for p in shaped]
    extent = max(max(xs) - min(xs), max(ys) - min(ys))
    if extent <= 0:
        raise ValueError("degenerate shard")
    k = target_size / extent
    cx = (max(xs) + min(xs)) / 2
    cy = (max(ys) + min(ys)) / 2
    return [(round((x - cx) * k, 4), round((y - cy) * k, 4)) for x, y in shaped]


def point_in_ring(ring: list[tuple[float, float]], px: float, py: float) -> bool:
    """Ray-crossing test, used to keep generated attach points on the piece."""
    inside = False
    ax, ay = ring[-1]
    for bx, by in ring:
        if (ay > py) != (by > py):
            t = (py - ay) / (by - ay)
            if px < ax + t * (bx - ax):
                inside = not inside
        ax, ay = bx, by
    return inside


def ring_centroid(ring: list[tuple[float, float]]) -> tuple[float, float]:
    area = 0.0
    cx = cy = 0.0
    px, py = ring[-1]
    for x, y in ring:
        f = px * y - x * py
        area += f
        cx += (px + x) * f
        cy += (py + y) * f
        px, py = x, y
    if abs(area) < 1e-12:
        return (0.0, 0.0)
    return (cx / (3 * area), cy / (3 * area))


def attach_points(ring: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Where the piece is stitched down.

    A tessera is tacked at one point if it is small enough not to swivel, and at
    two or three spread along its long axis if it is not. Points are placed on
    that axis through the centroid and then pulled inward until they sit inside
    the outline, so an irregular or concave chip cannot end up with a stitch
    point off the piece.
    """
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)
    size = max(width, height)
    count = 1 if size < 14.0 else (2 if size < 20.0 else 3)

    cx, cy = ring_centroid(ring)
    if not point_in_ring(ring, cx, cy):
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2

    if count == 1:
        return [(round(cx, 4), round(cy, 4))]

    # Unit vector along the longer bounding dimension.
    ux, uy = (1.0, 0.0) if width >= height else (0.0, 1.0)
    half = size / 2.0
    offsets = [-0.44, 0.44] if count == 2 else [-0.5, 0.0, 0.5]

    points: list[tuple[float, float]] = []
    for fraction in offsets:
        reach = fraction * half
        # Walk in from the intended offset until the point is on the piece.
        for shrink in (1.0, 0.8, 0.6, 0.45, 0.3, 0.15, 0.0):
            x = cx + ux * reach * shrink
            y = cy + uy * reach * shrink
            if point_in_ring(ring, x, y):
                points.append((round(x, 4), round(y, 4)))
                break
    # Collapse points that converged on the same spot.
    unique: list[tuple[float, float]] = []
    for point in points:
        if all(math.dist(point, kept) > 0.6 for kept in unique):
            unique.append(point)
    return unique or [(round(cx, 4), round(cy, 4))]


def polygon_area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    px, py = ring[-1]
    for x, y in ring:
        total += px * y - x * py
        px, py = x, y
    return abs(total / 2.0)


def main() -> None:
    rng = random.Random(SEED)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Skew the size distribution towards the small end, the way a real mosaic
    # rapport is built: many chips, a few statement pieces.
    sizes = [
        SIZE_MIN_MM + (SIZE_MAX_MM - SIZE_MIN_MM) * ((i / (PIECE_COUNT - 1)) ** 1.6)
        for i in range(PIECE_COUNT)
    ]

    pieces = []
    for index, size in enumerate(sizes, start=1):
        ring = make_shard(rng, size)
        pieces.append({
            "id": f"mp{index:02d}",
            "rings": [[coord for point in ring for coord in point]],
            "attach": [[x, y] for x, y in attach_points(ring)],
        })

    (OUT_DIR / "pieces.json").write_text(
        json.dumps({"unit": "mm", "pieces": pieces}, indent=1) + "\n",
        encoding="utf-8",
    )

    index_doc = {
        "id": "marble",
        "name": "MARBLE mosaic",
        "unit": "mm",
        "rapport_coverage": RAPPORT_COVERAGE,
        "pieces_file": "pieces.json",
        "reference_svg": "pieces.svg",
        "description": (
            "Irregular marble tesserae, 22 pieces. Rapport density 56%, which is "
            "the designer's intended coverage and the app's default target."
        ),
        "provenance": (
            "SYNTHESISED STAND-IN generated by tools/make_marble_library.py. "
            "Matches MARBLE's documented size envelope and piece count but not its "
            "actual traced outlines. Replace pieces.json and mosaic-piece-library.svg "
            "with the real traced library; no code changes are needed."
        ),
    }
    (OUT_DIR / "index.json").write_text(
        json.dumps(index_doc, indent=1) + "\n", encoding="utf-8"
    )

    # The viewable library file is produced by the extractor, so there is one
    # definition of what a clean pieces.svg looks like rather than two.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from extract_pieces_svg import build_pieces_svg  # noqa: E402
    from mosaic_fill.library import load_library  # noqa: E402

    library = load_library(OUT_DIR)
    (OUT_DIR / "pieces.svg").write_text(build_pieces_svg(library), encoding="utf-8")

    areas = [polygon_area([(flat[j], flat[j + 1])
                          for j in range(0, len(flat), 2)])
             for flat in (p["rings"][0] for p in pieces)]
    dots = sum(len(p["attach"]) for p in pieces)
    print(f"wrote {len(pieces)} pieces to {OUT_DIR}")
    print(f"  size range : {min(sizes):.2f} - {max(sizes):.2f} mm")
    print(f"  mean area  : {sum(areas) / len(areas):.2f} mm^2")
    print(f"  attach pts : {dots} across {len(pieces)} pieces")


if __name__ == "__main__":
    main()
