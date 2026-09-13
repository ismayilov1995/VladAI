"""Scanline polygon rasterisation onto a boolean occupancy grid.

The packer works on grids rather than polygon-distance tests: a panel becomes
an "inside" mask, every piece at every rotation becomes a stamp, and placement
is a masked window comparison. That makes overlap a property the grid can be
asked about directly, which is what the packing test asserts on.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

Point = tuple[float, float]
Ring = Sequence[Point]


def _edges(rings: Sequence[Ring]) -> tuple[np.ndarray, ...]:
    xs0: list[float] = []
    ys0: list[float] = []
    xs1: list[float] = []
    ys1: list[float] = []
    for ring in rings:
        n = len(ring)
        if n < 3:
            continue
        for i in range(n):
            ax, ay = ring[i]
            bx, by = ring[(i + 1) % n]
            if ay == by:
                continue  # Horizontal edges never cross a scanline.
            xs0.append(ax)
            ys0.append(ay)
            xs1.append(bx)
            ys1.append(by)
    if not xs0:
        empty = np.zeros(0, dtype=np.float64)
        return empty, empty, empty, empty
    return (
        np.asarray(xs0, dtype=np.float64),
        np.asarray(ys0, dtype=np.float64),
        np.asarray(xs1, dtype=np.float64),
        np.asarray(ys1, dtype=np.float64),
    )


def rasterize_rings(
    rings: Sequence[Ring],
    origin_x: float,
    origin_y: float,
    width: int,
    height: int,
    res: float,
    fill_rule: str = "nonzero",
    out: np.ndarray | None = None,
) -> np.ndarray:
    """Fill `rings` into a boolean grid of `width` x `height` cells.

    A cell is filled when its centre lies inside the rings, which keeps area
    unbiased: cells straddling the boundary are included exactly half the time
    on average, so the rasterised area converges on the true area from both
    sides rather than always over- or under-shooting.
    """
    grid = np.zeros((height, width), dtype=bool) if out is None else out
    x0, y0, x1, y1 = _edges(rings)
    if x0.size == 0 or width <= 0 or height <= 0:
        return grid

    inv = 1.0 / res
    direction = np.where(y1 > y0, 1, -1)
    dx = x1 - x0
    dy = y1 - y0
    ymin = np.minimum(y0, y1)
    ymax = np.maximum(y0, y1)

    # Only scan rows the geometry actually spans.
    first = max(0, int(np.floor((ymin.min() - origin_y) * res - 0.5)))
    last = min(height - 1, int(np.ceil((ymax.max() - origin_y) * res + 0.5)))
    evenodd = fill_rule == "evenodd"

    for row in range(first, last + 1):
        yc = origin_y + (row + 0.5) * inv
        hit = (ymin <= yc) & (ymax > yc)
        if not hit.any():
            continue
        t = (yc - y0[hit]) / dy[hit]
        xs = x0[hit] + t * dx[hit]
        if evenodd:
            xs = np.sort(xs)
            spans = zip(xs[0::2], xs[1::2])
        else:
            order = np.argsort(xs, kind="stable")
            xs = xs[order]
            winding = np.cumsum(direction[hit][order])
            # A span runs from a crossing that leaves winding non-zero to the
            # next crossing; keep only the non-zero stretches.
            spans = [
                (xs[i], xs[i + 1])
                for i in range(len(xs) - 1)
                if winding[i] != 0
            ]
        for span_start, span_end in spans:
            if span_end <= span_start:
                continue
            # Cell centres inside [span_start, span_end).
            lo = int(np.ceil((span_start - origin_x) * res - 0.5))
            hi = int(np.floor((span_end - origin_x) * res - 0.5))
            if hi < lo:
                continue
            lo = max(lo, 0)
            hi = min(hi, width - 1)
            if hi >= lo:
                grid[row, lo:hi + 1] = True
    return grid


def rasterize_shapes(
    shapes: Sequence[tuple[Sequence[Ring], str]],
    origin_x: float,
    origin_y: float,
    width: int,
    height: int,
    res: float,
) -> np.ndarray:
    """Union of several shapes, each rasterised under its own fill rule."""
    grid = np.zeros((height, width), dtype=bool)
    scratch = np.zeros((height, width), dtype=bool)
    for rings, fill_rule in shapes:
        scratch[:] = False
        rasterize_rings(rings, origin_x, origin_y, width, height, res, fill_rule, scratch)
        grid |= scratch
    return grid


def dilate(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    """Grow a mask by a disc of `radius_cells`, used to enforce the minimum gap.

    Implemented as a union of shifts against a disc structuring element. The
    stamps this runs on are small, so a direct approach beats pulling in SciPy.
    """
    if radius_cells <= 0:
        return mask.copy()
    r = int(radius_cells)
    h, w = mask.shape
    # The result grows by r on every side; callers must offset by (-r, -r).
    out = np.zeros((h + 2 * r, w + 2 * r), dtype=bool)
    r_sq = (radius_cells + 0.5) ** 2
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r_sq:
                continue
            out[r + dy:r + dy + h, r + dx:r + dx + w] |= mask
    return out


def erode(mask: np.ndarray, radius_cells: int) -> np.ndarray:
    """Shrink a mask by a disc, keeping the original shape.

    Used to hold pieces clear of the panel edge. Outside the array counts as
    empty, so the border erodes inward as it should.
    """
    if radius_cells <= 0:
        return mask.copy()
    r = int(radius_cells)
    h, w = mask.shape
    padded = np.zeros((h + 2 * r, w + 2 * r), dtype=bool)
    padded[r:r + h, r:r + w] = mask
    out = np.ones((h, w), dtype=bool)
    r_sq = (radius_cells + 0.5) ** 2
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if dx * dx + dy * dy > r_sq:
                continue
            out &= padded[r + dy:r + dy + h, r + dx:r + dx + w]
    return out


def mask_bounds(mask: np.ndarray) -> tuple[int, int, int, int] | None:
    """Tight (row0, col0, row1, col1) bounds of the True cells, end-exclusive."""
    rows = np.flatnonzero(mask.any(axis=1))
    if rows.size == 0:
        return None
    cols = np.flatnonzero(mask.any(axis=0))
    return int(rows[0]), int(cols[0]), int(rows[-1]) + 1, int(cols[-1]) + 1
