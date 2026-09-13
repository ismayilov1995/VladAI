"""The packing gate.

Packs the reference panel at the documented settings - 2x piece scale, 1.0 mm
minimum gap - and checks the two properties that make a pack correct:

  * no two pieces share a cell in the occupancy grid, and
  * achieved coverage lands in the 52-57% band around MARBLE's 56% rapport.

The overlap check rebuilds the grid from the placement list alone rather than
reusing the packer's own grid, so it tests the output rather than restating the
packer's bookkeeping.
"""

from __future__ import annotations

import pytest

from mosaic_fill.packer import PackParams, occupancy_overlaps, pack
from mosaic_fill.svgdoc import shapes_to_mm

# The count the original script produced at these settings, kept as the
# reference point for the reconstructed panel and library.
REFERENCE_COUNT = 4906
COUNT_TOLERANCE = 0.08  # +/-8%

CALIB_MM = 100.0


@pytest.fixture(scope="module")
def velvet_pack(velvet_doc, marble):
    units_per_mm = velvet_doc.units_per_mm(CALIB_MM)
    shapes = shapes_to_mm(velvet_doc.shapes, units_per_mm)
    params = PackParams(piece_scale=2.0, min_gap_mm=1.0, target_coverage=0.56)
    result = pack(shapes, marble, params, units_per_mm)
    return result, params, shapes


def test_calibration_comes_from_the_calib_element(velvet_doc):
    assert velvet_doc.calib_width_units == pytest.approx(377.9528, rel=1e-6)
    # 100 mm wide at 96 dpi is 3.779528 user units per mm.
    assert velvet_doc.units_per_mm(CALIB_MM) == pytest.approx(3.779528, rel=1e-6)


def test_no_overlapping_cells_in_the_occupancy_grid(velvet_pack, marble):
    result, params, shapes = velvet_pack
    overlaps = occupancy_overlaps(result.placements, marble, params, shapes)
    assert overlaps == 0, f"{overlaps} grid cells are claimed by more than one piece"


def test_coverage_is_in_band(velvet_pack):
    result, _, _ = velvet_pack
    coverage = result.stats["coverage"]
    assert 0.52 <= coverage <= 0.57, f"coverage {coverage:.4f} is outside 52-57%"


def test_piece_count_is_near_the_reference(velvet_pack):
    result, _, _ = velvet_pack
    count = result.stats["count"]
    low = REFERENCE_COUNT * (1 - COUNT_TOLERANCE)
    high = REFERENCE_COUNT * (1 + COUNT_TOLERANCE)
    assert low <= count <= high, (
        f"{count} pieces is outside {low:.0f}-{high:.0f}, the band around the "
        f"reference count of {REFERENCE_COUNT}"
    )


def test_every_placement_names_a_real_piece(velvet_pack, marble):
    result, _, _ = velvet_pack
    known = set(marble.piece_index())
    unknown = {p.piece for p in result.placements} - known
    assert not unknown, f"placements reference pieces not in the library: {unknown}"


def test_placements_sit_inside_the_panel_bounding_box(velvet_pack):
    result, _, shapes = velvet_pack
    min_x = min(s.bbox()[0] for s in shapes)
    min_y = min(s.bbox()[1] for s in shapes)
    max_x = max(s.bbox()[2] for s in shapes)
    max_y = max(s.bbox()[3] for s in shapes)
    for placement in result.placements:
        assert min_x <= placement.x <= max_x
        assert min_y <= placement.y <= max_y


def test_pack_is_deterministic(velvet_doc, marble):
    units_per_mm = velvet_doc.units_per_mm(CALIB_MM)
    shapes = shapes_to_mm(velvet_doc.shapes, units_per_mm)
    params = PackParams(piece_scale=2.0, min_gap_mm=1.0, target_coverage=0.56,
                        max_passes=2)
    first = pack(shapes, marble, params, units_per_mm)
    second = pack(shapes, marble, params, units_per_mm)
    assert [p.to_json() for p in first.placements] == [p.to_json() for p in second.placements]


def test_a_different_seed_gives_a_different_layout(velvet_doc, marble):
    units_per_mm = velvet_doc.units_per_mm(CALIB_MM)
    shapes = shapes_to_mm(velvet_doc.shapes, units_per_mm)
    base = PackParams(piece_scale=2.0, min_gap_mm=1.0, max_passes=2)
    other = PackParams(piece_scale=2.0, min_gap_mm=1.0, max_passes=2, seed=base.seed + 1)
    first = pack(shapes, marble, base, units_per_mm)
    second = pack(shapes, marble, other, units_per_mm)
    assert [p.to_json() for p in first.placements] != [p.to_json() for p in second.placements]


def test_a_wider_gap_places_fewer_pieces(velvet_doc, marble):
    units_per_mm = velvet_doc.units_per_mm(CALIB_MM)
    shapes = shapes_to_mm(velvet_doc.shapes, units_per_mm)
    tight = PackParams(piece_scale=2.0, min_gap_mm=1.0, max_passes=2)
    loose = PackParams(piece_scale=2.0, min_gap_mm=6.0, max_passes=2)
    assert (pack(shapes, marble, loose, units_per_mm).stats["count"]
            < pack(shapes, marble, tight, units_per_mm).stats["count"])


def test_larger_pieces_mean_fewer_of_them(velvet_doc, marble):
    units_per_mm = velvet_doc.units_per_mm(CALIB_MM)
    shapes = shapes_to_mm(velvet_doc.shapes, units_per_mm)
    small = PackParams(piece_scale=1.5, min_gap_mm=1.0, max_passes=2)
    large = PackParams(piece_scale=3.0, min_gap_mm=1.0, max_passes=2)
    assert (pack(shapes, marble, large, units_per_mm).stats["count"]
            < pack(shapes, marble, small, units_per_mm).stats["count"])
