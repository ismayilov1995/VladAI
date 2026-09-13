"""The packing engine.

Pieces are packed onto a boolean occupancy grid rather than by polygon-distance
tests. Each piece at each rotation is pre-rasterised twice: a solid stamp that
claims cells and marks coverage, and a stamp grown by the minimum gap that is
tested against everything already placed. Because distance >= gap is equivalent
to "grow one side by gap and check for intersection", one dilation per stamp
buys the whole spacing rule, and overlap becomes something the grid can be
queried about directly.

This module imports nothing from FastAPI and is runnable on its own; see
``cli.py``.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, asdict, replace
from typing import Sequence

import numpy as np

from .library import Library, Piece
from .raster import dilate, erode, mask_bounds, rasterize_rings, rasterize_shapes
from .svgdoc import Shape
from .svgpath import Ring, rings_bbox

# Cap on the working grid so a badly calibrated upload cannot allocate the box
# out of memory. 60 million cells is ~60 MB of bool.
MAX_GRID_CELLS = 60_000_000
# Below this the gap and coverage numbers stop meaning much.
MIN_GRID_RES = 1.0
# Upper bound on lattice points proposed in a single pass.
MAX_CANDIDATES = 1_500_000
# Consecutive failed candidates before a pass is judged saturated.
MAX_CONSECUTIVE_MISSES = 9_000


@dataclass
class PackParams:
    """Everything that changes the output. The cache key is a hash of this."""

    piece_scale: float = 2.0
    min_gap_mm: float = 1.0
    target_coverage: float = 0.56
    seed: int = 20260913
    grid_res: float = 2.0          # occupancy cells per millimetre
    rotation_steps: int = 24       # 0 or 1 disables rotation
    max_passes: int = 8
    edge_clearance_mm: float = 0.0
    bands: int = 1
    band_angle_deg: float = 0.0
    band_jitter_mm: float = 0.0
    attempts_per_candidate: int = 5

    def normalised(self) -> "PackParams":
        """Clamp to sane ranges so the engine cannot be driven off a cliff."""
        return PackParams(
            piece_scale=_clamp(self.piece_scale, 0.1, 20.0),
            min_gap_mm=_clamp(self.min_gap_mm, 0.0, 100.0),
            target_coverage=_clamp(self.target_coverage, 0.01, 0.95),
            seed=int(self.seed) & 0x7FFFFFFF,
            grid_res=_clamp(self.grid_res, 0.5, 20.0),
            rotation_steps=int(_clamp(self.rotation_steps, 0, 360)),
            max_passes=int(_clamp(self.max_passes, 1, 24)),
            edge_clearance_mm=_clamp(self.edge_clearance_mm, 0.0, 100.0),
            bands=int(_clamp(self.bands, 1, 26)),
            band_angle_deg=float(self.band_angle_deg) % 360.0,
            band_jitter_mm=_clamp(self.band_jitter_mm, 0.0, 500.0),
            attempts_per_candidate=int(_clamp(self.attempts_per_candidate, 1, 40)),
        )


def _clamp(value: float, low: float, high: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return low
    if math.isnan(v):
        return low
    return max(low, min(high, v))


@dataclass
class Placement:
    piece: str
    x: float      # centroid position in millimetres
    y: float
    angle: float  # degrees, clockwise on screen
    cls: str      # colour class, "A".."Z"

    def to_json(self) -> dict:
        return {
            "piece": self.piece,
            "x": round(self.x, 3),
            "y": round(self.y, 3),
            "angle": round(self.angle, 2),
            "cls": self.cls,
        }


@dataclass
class PackResult:
    units_per_mm: float
    panels: list[dict]
    placements: list[Placement]
    stats: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {
            "units_per_mm": self.units_per_mm,
            "panels": self.panels,
            "placements": [p.to_json() for p in self.placements],
            "stats": self.stats,
        }


@dataclass
class _Stamp:
    """A piece at one rotation, pre-rasterised."""

    piece_id: str
    angle: float
    mask: np.ndarray        # solid footprint
    off_r: int              # mask[0,0] sits at grid row (centre_row + off_r)
    off_c: int
    gap_mask: np.ndarray    # footprint grown by the minimum gap
    gap_off_r: int
    gap_off_c: int
    cells: int              # solid cell count, i.e. the piece's area in cells
    size_mm: float
    probes: tuple[tuple[int, int], ...] = ()  # interior cells, for early rejection


def _rotate_rings(rings: Sequence[Ring], scale: float, degrees: float) -> list[Ring]:
    r = math.radians(degrees)
    cos, sin = math.cos(r), math.sin(r)
    out: list[Ring] = []
    for ring in rings:
        out.append([
            ((x * scale) * cos - (y * scale) * sin, (x * scale) * sin + (y * scale) * cos)
            for x, y in ring
        ])
    return out


def _build_stamp(
    piece: Piece, angle: float, scale: float, res: float, gap_cells: int,
) -> _Stamp | None:
    rings = _rotate_rings(piece.rings, scale, angle)
    min_x, min_y, max_x, max_y = rings_bbox(rings)
    # Rasterise on a lattice aligned to the piece centre so the cell offset is
    # an exact integer and placement introduces no drift.
    pad = 2
    half_c = int(math.ceil(max(abs(min_x), abs(max_x)) * res)) + pad
    half_r = int(math.ceil(max(abs(min_y), abs(max_y)) * res)) + pad
    width, height = half_c * 2, half_r * 2
    if width <= 0 or height <= 0:
        return None
    grid = rasterize_rings(
        rings, -half_c / res, -half_r / res, width, height, res, "nonzero",
    )
    bounds = mask_bounds(grid)
    if bounds is None:
        return None
    r0, c0, r1, c1 = bounds
    mask = np.ascontiguousarray(grid[r0:r1, c0:c1])
    off_r = r0 - half_r
    off_c = c0 - half_c

    gap_mask = dilate(mask, gap_cells) if gap_cells > 0 else mask
    gap_off_r = off_r - (gap_cells if gap_cells > 0 else 0)
    gap_off_c = off_c - (gap_cells if gap_cells > 0 else 0)

    return _Stamp(
        piece_id=piece.id,
        angle=angle,
        mask=mask,
        off_r=off_r,
        off_c=off_c,
        gap_mask=gap_mask,
        gap_off_r=gap_off_r,
        gap_off_c=gap_off_c,
        cells=int(mask.sum()),
        size_mm=piece.size_mm * scale,
        probes=_probe_cells(mask),
    )


def _probe_cells(mask: np.ndarray, count: int = 12) -> tuple[tuple[int, int], ...]:
    """A spread of cells that are solid in `mask`, for cheap early rejection.

    Testing a dozen scalars costs a fraction of a full masked comparison, and
    in a crowded panel most candidate positions are refuted by one of them. The
    cells are spread evenly through the footprint rather than clustered, so a
    blockage anywhere in the piece is likely to hit one.
    """
    rows, cols = np.nonzero(mask)
    if rows.size == 0:
        return ()
    step = max(1, rows.size // count)
    picked = range(0, rows.size, step)
    return tuple((int(rows[i]), int(cols[i])) for i in picked)[:count]


def _build_stamps(
    library: Library, params: PackParams, gap_cells: int,
) -> dict[str, list[_Stamp]]:
    steps = max(1, params.rotation_steps)
    angles = [i * 360.0 / steps for i in range(steps)] if steps > 1 else [0.0]
    stamps: dict[str, list[_Stamp]] = {}
    for piece in library.pieces:
        built = [
            s for s in (
                _build_stamp(piece, a, params.piece_scale, params.grid_res, gap_cells)
                for a in angles
            ) if s is not None and s.cells > 0
        ]
        if built:
            stamps[piece.id] = built
    return stamps


def _assign_class(
    x: float, y: float, params: PackParams, bbox: tuple[float, float, float, float],
    rng: random.Random,
) -> str:
    """Colour blocking: project onto the band axis and slice into bands."""
    if params.bands <= 1:
        return "A"
    min_x, min_y, max_x, max_y = bbox
    theta = math.radians(params.band_angle_deg)
    ux, uy = math.cos(theta), math.sin(theta)
    # Projection range of the panel bbox corners onto the band axis.
    corners = [(min_x, min_y), (max_x, min_y), (min_x, max_y), (max_x, max_y)]
    projections = [cx * ux + cy * uy for cx, cy in corners]
    lo, hi = min(projections), max(projections)
    span = hi - lo
    if span <= 0:
        return "A"
    value = x * ux + y * uy
    if params.band_jitter_mm > 0:
        value += rng.uniform(-params.band_jitter_mm, params.band_jitter_mm)
    t = (value - lo) / span
    index = int(t * params.bands)
    index = max(0, min(params.bands - 1, index))
    return chr(ord("A") + index)


def pack(
    shapes: Sequence[Shape],
    library: Library,
    params: PackParams,
    units_per_mm: float,
) -> PackResult:
    """Fill `shapes` (already in millimetres) with `library` pieces.

    Returns placements only; rendering is the caller's job, which is what lets
    the preview canvas and the downloaded SVG come from one computation.
    """
    params = params.normalised()
    rng = random.Random(params.seed)
    res = params.grid_res

    if not shapes:
        return PackResult(units_per_mm, [], [], _stats(0, 0.0, 0.0, 0.0, "no fillable shapes"))

    min_x, min_y, max_x, max_y = rings_bbox([r for s in shapes for r in s.rings])
    if not all(map(math.isfinite, (min_x, min_y, max_x, max_y))) or max_x <= min_x:
        return PackResult(units_per_mm, [], [], _stats(0, 0.0, 0.0, 0.0, "panel has no extent"))

    margin = 1.0
    origin_x = min_x - margin
    origin_y = min_y - margin

    # A big panel at a fine grid can ask for an unreasonable allocation. Back
    # the resolution off until it fits rather than refusing the job; the chosen
    # value is reported in stats so a result is always reproducible.
    span_x = max_x - min_x + 2 * margin
    span_y = max_y - min_y + 2 * margin
    while res > MIN_GRID_RES and math.ceil(span_x * res) * math.ceil(span_y * res) > MAX_GRID_CELLS:
        res /= 2.0
    width = int(math.ceil(span_x * res))
    height = int(math.ceil(span_y * res))
    if width * height > MAX_GRID_CELLS:
        raise ValueError(
            f"panel needs {width * height:,} grid cells even at {res} cells/mm; "
            "check the scale calibration - this panel reads as "
            f"{span_x / 1000:.1f} x {span_y / 1000:.1f} m"
        )
    params = replace(params, grid_res=res)

    inside = rasterize_shapes(
        [(s.rings, s.fill_rule) for s in shapes], origin_x, origin_y, width, height, res,
    )
    region_cells = int(inside.sum())
    if region_cells == 0:
        return PackResult(units_per_mm, _panels_json(shapes), [],
                          _stats(0, 0.0, 0.0, 0.0, "panel rasterised to nothing"))

    placeable = inside
    clearance_cells = int(round(params.edge_clearance_mm * res))
    if clearance_cells > 0:
        placeable = erode(inside, clearance_cells)

    gap_cells = int(round(params.min_gap_mm * res))
    stamps = _build_stamps(library, params, gap_cells)
    if not stamps:
        return PackResult(units_per_mm, _panels_json(shapes), [],
                          _stats(0, 0.0, 0.0, region_cells / (res * res),
                                 "library produced no usable stamps"))

    # Largest first: big pieces need the open space, small ones fill what is left.
    order = sorted(stamps.keys(), key=lambda pid: -stamps[pid][0].size_mm)

    # One grid drives the whole search. It starts as "everywhere a piece may not
    # go" and each placement stamps its gap-grown footprint into it, so a single
    # masked test per attempt enforces the panel edge and the minimum gap at
    # once. Keeping a piece's solid mask clear of another's gap-grown mask is
    # exactly the condition "these two are at least gap apart".
    blocked = ~placeable
    lattice_rng = np.random.default_rng(params.seed)

    placements: list[Placement] = []
    occupied_cells = 0
    target_cells = params.target_coverage * region_cells

    for pass_index in range(params.max_passes):
        if occupied_cells >= target_cells:
            break
        # Each pass sweeps a finer lattice: the first lays down the big pieces,
        # later ones work the gaps between them.
        shrink = 0.62 ** pass_index
        biggest = stamps[order[0]][0].size_mm
        spacing_mm = max(biggest * 0.55 * shrink, 1.5 / res)
        spacing = max(1, int(round(spacing_mm * res)))

        candidates = _lattice_candidates(placeable, spacing, lattice_rng)
        if candidates.size == 0:
            continue

        # Later passes bias towards the smaller end of the library.
        window_lo = int(len(order) * (1.0 - shrink) * 0.7)
        pool = order[window_lo:] or order
        # Flattened so choosing a piece and a rotation is one draw instead of
        # two. Every piece carries the same number of rotations, so drawing
        # uniformly from this list still weights the pieces evenly.
        pool_stamps = [stamp for piece_id in pool for stamp in stamps[piece_id]]
        pool_size = len(pool_stamps)
        if pool_size == 0:
            continue

        placed_this_pass = 0
        misses = 0
        attempts = params.attempts_per_candidate
        random_float = rng.random
        for index in range(candidates.shape[0]):
            if occupied_cells >= target_cells:
                break
            # Once the panel is saturated every further candidate is a wasted
            # masked comparison, and the tail of a pass is almost all waste.
            # Give up on the pass after a long enough run of failures rather
            # than grinding through millions of hopeless positions.
            if misses >= MAX_CONSECUTIVE_MISSES:
                break
            row = int(candidates[index, 0])
            col = int(candidates[index, 1])
            if blocked[row, col]:
                misses += 1
                continue
            hit = False
            for _ in range(attempts):
                stamp = pool_stamps[int(random_float() * pool_size)]
                if _try_place(blocked, stamp, row, col):
                    occupied_cells += stamp.cells
                    placements.append(Placement(
                        piece=stamp.piece_id,
                        x=origin_x + (col + 0.5) / res,
                        y=origin_y + (row + 0.5) / res,
                        angle=stamp.angle,
                        cls="A",
                    ))
                    placed_this_pass += 1
                    hit = True
                    break
            misses = 0 if hit else misses + 1
        if placed_this_pass == 0 and pass_index > 0:
            break  # A pass that placed nothing means the panel is saturated.

    bbox = (min_x, min_y, max_x, max_y)
    class_rng = random.Random(params.seed ^ 0x5EED)
    for placement in placements:
        placement.cls = _assign_class(placement.x, placement.y, params, bbox, class_rng)

    region_area = region_cells / (res * res)
    coverage = occupied_cells / region_cells if region_cells else 0.0
    return PackResult(
        units_per_mm=units_per_mm,
        panels=_panels_json(shapes),
        placements=placements,
        stats=_stats(len(placements), coverage, occupied_cells / (res * res),
                     region_area, grid_res=res),
    )


def _try_place(blocked: np.ndarray, stamp: _Stamp, row: int, col: int) -> bool:
    """Place `stamp` centred on (row, col) if it fits; mutate `blocked` and report.

    One test covers both rules: `blocked` already holds the panel exterior and
    every previous piece grown by the gap, so a solid footprint that misses it
    entirely is both inside the panel and properly spaced.
    """
    h, w = blocked.shape
    r0 = row + stamp.off_r
    c0 = col + stamp.off_c
    r1 = r0 + stamp.mask.shape[0]
    c1 = c0 + stamp.mask.shape[1]
    if r0 < 0 or c0 < 0 or r1 > h or c1 > w:
        return False
    # Cheap refutation first: if any probe cell is already claimed the piece
    # cannot fit, and that settles most attempts without touching the mask.
    for dr, dc in stamp.probes:
        if blocked[r0 + dr, c0 + dc]:
            return False
    if (blocked[r0:r1, c0:c1] & stamp.mask).any():
        return False

    # Claim the footprint plus its gap halo. The halo may run off the grid at
    # the panel edge, so clip it rather than refusing an otherwise valid spot.
    gr0 = row + stamp.gap_off_r
    gc0 = col + stamp.gap_off_c
    gr1 = gr0 + stamp.gap_mask.shape[0]
    gc1 = gc0 + stamp.gap_mask.shape[1]
    sr0, sc0 = max(gr0, 0), max(gc0, 0)
    sr1, sc1 = min(gr1, h), min(gc1, w)
    if sr1 > sr0 and sc1 > sc0:
        blocked[sr0:sr1, sc0:sc1] |= stamp.gap_mask[
            sr0 - gr0:sr1 - gr0, sc0 - gc0:sc1 - gc0
        ]
    return True


def _lattice_candidates(
    placeable: np.ndarray, spacing: int, rng: np.random.Generator,
) -> np.ndarray:
    """Jittered lattice points inside the region, in shuffled order.

    A jittered lattice rather than pure random sampling: it covers the panel
    evenly without the clumping uniform sampling produces, and the shuffle
    afterwards keeps placement order unbiased. Built with array operations
    because the finest pass on a large panel proposes millions of points, which
    is far too many to walk in Python.
    """
    h, w = placeable.shape
    half = max(1, spacing // 2)
    rows = np.arange(half, h, spacing)
    cols = np.arange(half, w, spacing)
    if rows.size == 0 or cols.size == 0:
        return np.empty((0, 2), dtype=np.int32)

    grid_r, grid_c = np.meshgrid(rows, cols, indexing="ij")
    grid_r = grid_r.ravel()
    grid_c = grid_c.ravel()
    if grid_r.size > MAX_CANDIDATES:
        keep = rng.choice(grid_r.size, size=MAX_CANDIDATES, replace=False)
        grid_r = grid_r[keep]
        grid_c = grid_c[keep]

    jitter_r = rng.integers(-half, half + 1, size=grid_r.size)
    jitter_c = rng.integers(-half, half + 1, size=grid_c.size)
    r = np.clip(grid_r + jitter_r, 0, h - 1)
    c = np.clip(grid_c + jitter_c, 0, w - 1)

    keep = placeable[r, c]
    r = r[keep]
    c = c[keep]
    if r.size == 0:
        return np.empty((0, 2), dtype=np.int32)
    order = rng.permutation(r.size)
    return np.stack([r[order], c[order]], axis=1).astype(np.int32)


def _panels_json(shapes: Sequence[Shape]) -> list[dict]:
    """Panel outlines in millimetres, for the preview canvas and the export."""
    panels = []
    for index, shape in enumerate(shapes):
        min_x, min_y, max_x, max_y = shape.bbox()
        panels.append({
            "id": shape.element_id or f"shape{index}",
            "fill_rule": shape.fill_rule,
            "bbox": [round(v, 3) for v in (min_x, min_y, max_x, max_y)],
            "rings": [
                [round(coord, 3) for point in ring for coord in point]
                for ring in shape.rings
            ],
        })
    return panels


def _stats(
    count: int, coverage: float, covered_mm2: float, region_mm2: float, note: str = "",
    grid_res: float | None = None,
) -> dict:
    out = {
        "count": count,
        "coverage": round(coverage, 5),
        "covered_mm2": round(covered_mm2, 2),
        "region_mm2": round(region_mm2, 2),
    }
    if grid_res is not None:
        out["grid_res"] = grid_res
    if note:
        out["note"] = note
    return out


def occupancy_overlaps(
    placements: Sequence[Placement],
    library: Library,
    params: PackParams,
    shapes: Sequence[Shape],
) -> int:
    """Count grid cells claimed by more than one placement.

    Rebuilt from the placement list alone rather than reusing the packer's own
    grid, so it is an independent check of the result rather than a restatement
    of it. This is what the packing test asserts on.
    """
    params = params.normalised()
    res = params.grid_res
    min_x, min_y, max_x, max_y = rings_bbox([r for s in shapes for r in s.rings])
    margin = 1.0
    origin_x, origin_y = min_x - margin, min_y - margin
    span_x = max_x - min_x + 2 * margin
    span_y = max_y - min_y + 2 * margin
    while res > MIN_GRID_RES and math.ceil(span_x * res) * math.ceil(span_y * res) > MAX_GRID_CELLS:
        res /= 2.0
    width = int(math.ceil(span_x * res))
    height = int(math.ceil(span_y * res))

    counts = np.zeros((height, width), dtype=np.uint16)
    index = library.piece_index()
    cache: dict[tuple[str, float], _Stamp] = {}
    for placement in placements:
        piece = index.get(placement.piece)
        if piece is None:
            continue
        key = (placement.piece, placement.angle)
        stamp = cache.get(key)
        if stamp is None:
            built = _build_stamp(piece, placement.angle, params.piece_scale, res, 0)
            if built is None:
                continue
            cache[key] = stamp = built
        col = int((placement.x - origin_x) * res - 0.5 + 0.5)
        row = int((placement.y - origin_y) * res - 0.5 + 0.5)
        r0, c0 = row + stamp.off_r, col + stamp.off_c
        r1, c1 = r0 + stamp.mask.shape[0], c0 + stamp.mask.shape[1]
        if r0 < 0 or c0 < 0 or r1 > height or c1 > width:
            continue
        counts[r0:r1, c0:c1] += stamp.mask
    return int((counts > 1).sum())


def params_from_dict(data: dict) -> PackParams:
    """Build params from loose JSON, ignoring keys the engine does not know."""
    defaults = asdict(PackParams())
    merged = {k: data.get(k, v) for k, v in defaults.items()}
    return PackParams(**merged).normalised()
