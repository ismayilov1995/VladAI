"""Unit tests for the geometry the packer stands on."""

from __future__ import annotations

import math

import numpy as np
import pytest

from mosaic_fill.matrix import IDENTITY, apply_to_point, parse_transform, rotate
from mosaic_fill.raster import dilate, erode, rasterize_rings
from mosaic_fill.svgdoc import parse_panel
from mosaic_fill.svgpath import path_to_rings, ring_area, ring_centroid, shape_to_rings


class TestPathParsing:
    def test_absolute_square(self):
        rings = path_to_rings("M0,0 L10,0 L10,10 L0,10 Z")
        assert len(rings) == 1
        assert ring_area(rings[0]) == pytest.approx(100.0)

    def test_relative_commands_match_absolute(self):
        absolute = path_to_rings("M0,0 L10,0 L10,10 L0,10 Z")
        relative = path_to_rings("m0,0 l10,0 l0,10 l-10,0 z")
        assert ring_area(relative[0]) == pytest.approx(ring_area(absolute[0]))

    def test_horizontal_and_vertical_shorthand(self):
        rings = path_to_rings("M0,0 H10 V10 H0 Z")
        assert ring_area(rings[0]) == pytest.approx(100.0)

    def test_implicit_lineto_after_moveto(self):
        # A second coordinate pair after M is an implicit L.
        rings = path_to_rings("M0,0 10,0 10,10 0,10 Z")
        assert ring_area(rings[0]) == pytest.approx(100.0)

    def test_multiple_subpaths_become_multiple_rings(self):
        rings = path_to_rings("M0,0 H10 V10 H0 Z M20,0 H30 V10 H20 Z")
        assert len(rings) == 2

    def test_cubic_curve_is_flattened_accurately(self):
        """Flattened area should match a densely sampled reference.

        This is the test that would catch a flattening tolerance that is too
        loose: a polyline that cuts the corners encloses visibly less area.
        """
        def bezier(t: float) -> tuple[float, float]:
            u = 1 - t
            x = 3 * u * t * t * 10 + t ** 3 * 10
            y = 3 * u * u * t * 10 + 3 * u * t * t * 10
            return x, y

        reference = abs(ring_area([bezier(i / 4000) for i in range(4001)]))
        rings = path_to_rings("M0,0 C0,10 10,10 10,0 Z")
        assert len(rings[0]) > 4
        # The sign of a shoelace area reports winding, so compare magnitudes.
        # An inscribed polyline always undershoots a convex curve; at the
        # default tolerance on a chord this short that is about 0.16%.
        assert abs(ring_area(rings[0])) == pytest.approx(reference, rel=2e-3)

    def test_tightening_the_tolerance_tightens_the_fit(self):
        """The tolerance argument has to actually drive the subdivision."""
        def bezier(t: float) -> tuple[float, float]:
            u = 1 - t
            return 3 * u * t * t * 10 + t ** 3 * 10, 3 * u * u * t * 10 + 3 * u * t * t * 10

        reference = abs(ring_area([bezier(i / 4000) for i in range(4001)]))
        coarse = path_to_rings("M0,0 C0,10 10,10 10,0 Z", 0.05)[0]
        fine = path_to_rings("M0,0 C0,10 10,10 10,0 Z", 0.001)[0]
        assert len(fine) > len(coarse)
        assert abs(abs(ring_area(fine)) - reference) < abs(abs(ring_area(coarse)) - reference)
        assert abs(ring_area(fine)) == pytest.approx(reference, rel=1e-4)

    def test_smooth_cubic_reflects_the_previous_control_point(self):
        explicit = path_to_rings("M0,0 C0,5 5,5 5,0 C5,-5 10,-5 10,0 Z")
        smooth = path_to_rings("M0,0 C0,5 5,5 5,0 S10,-5 10,0 Z")
        assert ring_area(smooth[0]) == pytest.approx(ring_area(explicit[0]), rel=1e-6)

    def test_quadratic_matches_its_cubic_equivalent(self):
        quad = path_to_rings("M0,0 Q5,10 10,0 Z")
        # A quadratic raised to a cubic has control points at 2/3 of the way.
        cubic = path_to_rings("M0,0 C3.3333,6.6667 6.6667,6.6667 10,0 Z")
        assert ring_area(quad[0]) == pytest.approx(ring_area(cubic[0]), rel=1e-3)

    def test_arc_half_circle_area(self):
        rings = path_to_rings("M0,0 A10,10 0 1 1 20,0 Z")
        assert ring_area(rings[0]) == pytest.approx(math.pi * 100 / 2, rel=0.01)

    def test_arc_with_too_small_radii_is_scaled_up(self):
        # Radii that cannot span the chord must be grown, not rejected.
        rings = path_to_rings("M0,0 A1,1 0 0 1 20,0 Z")
        assert rings and ring_area(rings[0]) == pytest.approx(math.pi * 100 / 2, rel=0.02)

    def test_unclosed_subpath_is_closed_implicitly(self):
        rings = path_to_rings("M0,0 L10,0 L10,10 L0,10")
        assert ring_area(rings[0]) == pytest.approx(100.0)

    def test_garbage_does_not_raise(self):
        # Prose tokenises into command letters (t, a, h, l are all commands),
        # so this has to degrade to no rings rather than raise.
        assert path_to_rings("not a path at all") == []
        assert path_to_rings("") == []

    def test_truncated_command_does_not_raise(self):
        assert path_to_rings("M0,0 L10,0 C5") == []

    def test_valid_prefix_survives_trailing_junk(self):
        rings = path_to_rings("M0,0 H10 V10 H0 Z L oops")
        assert len(rings) == 1
        assert ring_area(rings[0]) == pytest.approx(100.0)


class TestBasicShapes:
    def test_rect(self):
        rings = shape_to_rings("rect", {"x": "1", "y": "2", "width": "10", "height": "4"})
        assert ring_area(rings[0]) == pytest.approx(40.0)

    def test_rounded_rect_is_smaller_than_its_square_version(self):
        square = shape_to_rings("rect", {"width": "10", "height": "10"})
        rounded = shape_to_rings("rect", {"width": "10", "height": "10", "rx": "3"})
        assert abs(ring_area(rounded[0])) < abs(ring_area(square[0]))

    def test_circle_area(self):
        rings = shape_to_rings("circle", {"cx": "0", "cy": "0", "r": "10"})
        assert abs(ring_area(rings[0])) == pytest.approx(math.pi * 100, rel=0.01)

    def test_ellipse_area(self):
        rings = shape_to_rings("ellipse", {"rx": "10", "ry": "5"})
        assert abs(ring_area(rings[0])) == pytest.approx(math.pi * 50, rel=0.01)

    def test_polygon(self):
        rings = shape_to_rings("polygon", {"points": "0,0 10,0 10,10 0,10"})
        assert ring_area(rings[0]) == pytest.approx(100.0)

    def test_line_has_no_fillable_area(self):
        assert shape_to_rings("line", {"x1": "0", "y1": "0", "x2": "10", "y2": "10"}) == []

    def test_zero_size_rect_is_dropped(self):
        assert shape_to_rings("rect", {"width": "0", "height": "10"}) == []


class TestCentroid:
    def test_square_centroid(self):
        cx, cy = ring_centroid([(0, 0), (10, 0), (10, 10), (0, 10)])
        assert (cx, cy) == pytest.approx((5.0, 5.0))

    def test_degenerate_ring_falls_back_to_bbox_centre(self):
        cx, cy = ring_centroid([(0, 0), (10, 0), (5, 0)])
        assert (cx, cy) == pytest.approx((5.0, 0.0))


class TestTransforms:
    def test_no_transform_is_identity(self):
        assert parse_transform(None) == IDENTITY
        assert parse_transform("") == IDENTITY

    def test_translate(self):
        assert apply_to_point(parse_transform("translate(3 4)"), 0, 0) == pytest.approx((3, 4))

    def test_translate_with_one_argument_leaves_y_alone(self):
        assert apply_to_point(parse_transform("translate(3)"), 0, 0) == pytest.approx((3, 0))

    def test_scale_uniform_and_separate(self):
        assert apply_to_point(parse_transform("scale(2)"), 1, 1) == pytest.approx((2, 2))
        assert apply_to_point(parse_transform("scale(2 3)"), 1, 1) == pytest.approx((2, 3))

    def test_rotate_about_a_centre(self):
        x, y = apply_to_point(rotate(90, 5, 5), 5, 0)
        assert (x, y) == pytest.approx((10, 5))

    def test_chained_transforms_apply_left_to_right(self):
        m = parse_transform("translate(10 0) scale(2)")
        assert apply_to_point(m, 1, 0) == pytest.approx((12, 0))

    def test_unknown_function_is_skipped_not_fatal(self):
        m = parse_transform("wobble(3) translate(1 2)")
        assert apply_to_point(m, 0, 0) == pytest.approx((1, 2))


class TestRasteriser:
    def test_square_area_is_exact_on_grid(self):
        grid = rasterize_rings([[(0, 0), (10, 0), (10, 10), (0, 10)]], 0, 0, 80, 80, 8.0)
        assert grid.sum() == 10 * 10 * 64

    def test_circle_area_converges(self):
        circle = [(5 + 4 * math.cos(2 * math.pi * i / 256),
                   5 + 4 * math.sin(2 * math.pi * i / 256)) for i in range(256)]
        grid = rasterize_rings([circle], 0, 0, 160, 160, 16.0)
        assert grid.sum() / 16.0 ** 2 == pytest.approx(math.pi * 16, rel=0.01)

    def test_counter_wound_inner_ring_is_a_hole(self):
        outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
        inner = [(3, 3), (3, 7), (7, 7), (7, 3)]
        grid = rasterize_rings([outer, inner], 0, 0, 80, 80, 8.0)
        assert grid.sum() / 64.0 == pytest.approx(100 - 16)

    def test_evenodd_treats_any_nested_ring_as_a_hole(self):
        outer = [(0, 0), (10, 0), (10, 10), (0, 10)]
        inner = [(3, 3), (7, 3), (7, 7), (3, 7)]  # same winding as the outer
        nonzero = rasterize_rings([outer, inner], 0, 0, 80, 80, 8.0, "nonzero")
        evenodd = rasterize_rings([outer, inner], 0, 0, 80, 80, 8.0, "evenodd")
        assert nonzero.sum() / 64.0 == pytest.approx(100.0)
        assert evenodd.sum() / 64.0 == pytest.approx(84.0)

    def test_geometry_outside_the_grid_is_clipped_not_wrapped(self):
        grid = rasterize_rings([[(-50, -50), (5, -50), (5, 5), (-50, 5)]], 0, 0, 20, 20, 1.0)
        assert grid[:5, :5].all()
        assert not grid[6:, 6:].any()


class TestMorphology:
    def test_dilate_grows_by_a_disc(self):
        mask = np.zeros((9, 9), dtype=bool)
        mask[4, 4] = True
        grown = dilate(mask, 2)
        assert grown.shape == (13, 13)
        assert grown.sum() == 21  # cells within radius 2.5 of the centre

    def test_dilate_by_zero_is_a_copy(self):
        mask = np.zeros((4, 4), dtype=bool)
        mask[1, 1] = True
        assert np.array_equal(dilate(mask, 0), mask)

    def test_erode_shrinks_by_a_disc(self):
        mask = np.zeros((11, 11), dtype=bool)
        mask[2:9, 2:9] = True
        assert erode(mask, 1).sum() == 25  # a 7x7 block loses its border ring

    def test_erode_keeps_the_original_shape(self):
        mask = np.ones((6, 7), dtype=bool)
        assert erode(mask, 1).shape == (6, 7)


class TestPanelParsing:
    SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 200">
      <rect id="calib" x="0" y="0" width="50" height="5" fill="none"/>
      <rect id="panel" x="10" y="10" width="100" height="80" fill="#333"/>
      <rect id="hidden" x="0" y="0" width="10" height="10" fill="#333" display="none"/>
      <rect id="unfilled" x="0" y="0" width="10" height="10" fill="none"/>
    </svg>"""

    def test_calib_sets_the_scale(self):
        doc = parse_panel(self.SVG)
        assert doc.calib_width_units == pytest.approx(50.0)
        assert doc.units_per_mm(100.0) == pytest.approx(0.5)

    def test_calib_is_not_itself_a_fill_shape(self):
        doc = parse_panel(self.SVG)
        assert "calib" not in {s.element_id for s in doc.shapes}

    def test_hidden_and_unfilled_shapes_are_excluded(self):
        doc = parse_panel(self.SVG)
        assert {s.element_id for s in doc.shapes} == {"panel"}

    def test_missing_calib_is_reported_not_guessed(self):
        doc = parse_panel(
            '<svg xmlns="http://www.w3.org/2000/svg"><rect width="9" height="9" fill="#000"/></svg>'
        )
        assert doc.calib_width_units is None
        with pytest.raises(Exception):
            doc.units_per_mm(100.0)

    def test_group_transforms_reach_the_calib_element(self):
        doc = parse_panel(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<g transform="scale(2)"><rect id="calib" width="50" height="5" fill="none"/></g>'
            "</svg>"
        )
        assert doc.calib_width_units == pytest.approx(100.0)

    def test_shapes_inside_defs_are_ignored(self):
        doc = parse_panel(
            '<svg xmlns="http://www.w3.org/2000/svg">'
            '<defs><rect id="template" width="10" height="10" fill="#000"/></defs>'
            '<rect id="real" width="10" height="10" fill="#000"/></svg>'
        )
        assert {s.element_id for s in doc.shapes} == {"real"}

    def test_non_svg_input_raises(self):
        with pytest.raises(ValueError):
            parse_panel("<html><body>nope</body></html>")
