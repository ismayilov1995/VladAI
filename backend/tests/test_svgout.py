"""Tests for the exported SVG, including the attachment-point dots.

The structure here is load-bearing rather than cosmetic, so it is worth
pinning: pieces are defined once in <defs> and referenced, colour rides on
attributes because CSS cannot cross the <use> shadow boundary, and the
uploaded document comes through untouched.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mosaic_fill.packer import Placement
from mosaic_fill.svgout import (
    DEFAULT_ATTACH_RADIUS_MM, DEFAULT_PALETTE, build_defs, build_filled_svg,
)

ORIGINAL = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 400 400">\n'
    '  <rect id="calib" width="100" height="4" fill="none"/>\n'
    '  <rect id="panel" x="20" y="20" width="340" height="340" fill="#333"/>\n'
    '</svg>\n'
)

PLACEMENTS = [
    Placement(piece="mp01", x=50.0, y=60.0, angle=0.0, cls="A"),
    Placement(piece="mp02", x=90.0, y=120.0, angle=45.0, cls="B"),
]


def count(pattern: str, text: str) -> int:
    return len(re.findall(pattern, text))


def point_in_ring(ring: list[tuple[float, float]], px: float, py: float) -> bool:
    inside = False
    ax, ay = ring[-1]
    for bx, by in ring:
        if (ay > py) != (by > py):
            t = (py - ay) / (by - ay)
            if px < ax + t * (bx - ax):
                inside = not inside
        ax, ay = bx, by
    return inside


class TestLibraryAttachPoints:
    def test_every_piece_defines_at_least_one_attach_point(self, marble):
        missing = [p.id for p in marble.pieces if not p.attach]
        assert not missing, f"pieces with no stitch point: {missing}"

    def test_attach_points_lie_inside_their_piece(self, marble):
        """A stitch point off the piece would be unsewable."""
        strays: list[str] = []
        for piece in marble.pieces:
            outer = max(piece.rings, key=len)
            for x, y in piece.attach:
                if not point_in_ring(outer, x, y):
                    strays.append(f"{piece.id} at ({x:.2f}, {y:.2f})")
        assert not strays, f"attach points outside their outline: {strays}"

    def test_bigger_pieces_get_more_stitch_points(self, marble):
        """A large tessera needs more than one point or it swivels."""
        smallest = min(marble.pieces, key=lambda p: p.size_mm)
        largest = max(marble.pieces, key=lambda p: p.size_mm)
        assert len(largest.attach) > len(smallest.attach)

    def test_attach_points_are_centroid_relative_like_the_outline(self, marble):
        """Points must share the piece's origin, or rotation would fling them."""
        for piece in marble.pieces:
            for x, y in piece.attach:
                assert abs(x) <= piece.width_mm
                assert abs(y) <= piece.height_mm


class TestDefs:
    def test_one_group_per_piece(self, marble):
        defs, symbols = build_defs(marble, 2.0, 1.0)
        assert count(r'<g id="mp\d+"', defs) == len(marble.pieces)
        assert len(symbols) == len(marble.pieces)

    def test_no_dots_unless_asked(self, marble):
        defs, _ = build_defs(marble, 2.0, 1.0, show_attach=False)
        assert "<circle" not in defs

    def test_one_dot_per_attach_point(self, marble):
        defs, _ = build_defs(marble, 2.0, 1.0, show_attach=True)
        expected = sum(len(p.attach) for p in marble.pieces)
        assert count(r"<circle", defs) == expected

    def test_dots_use_currentcolor_so_they_take_the_thread_colour(self, marble):
        defs, _ = build_defs(marble, 2.0, 1.0, show_attach=True)
        assert 'fill="currentColor"' in defs
        # An explicit stroke="none" stops a dot inheriting the piece outline.
        assert 'stroke="none"' in defs

    def test_dot_radius_does_not_change_with_piece_scale(self, marble):
        """The dot marks a needle point, so it is a fixed physical size."""
        radii = set()
        for scale in (1.0, 2.0, 3.0):
            defs, _ = build_defs(marble, scale, 4.0, show_attach=True)
            radii.update(re.findall(r'<circle[^>]*r="([\d.]+)"', defs))
        assert len(radii) == 1
        assert float(radii.pop()) == pytest.approx(DEFAULT_ATTACH_RADIUS_MM * 4.0, rel=1e-3)

    def test_dot_positions_do_change_with_piece_scale(self, marble):
        """Positions are features of the piece, so they scale with it."""
        def first_cx(scale: float) -> float:
            defs, _ = build_defs(marble, scale, 1.0, show_attach=True)
            found = re.findall(r'<circle cx="(-?[\d.]+)"', defs)
            return float(next(c for c in found if float(c) != 0.0))

        assert first_cx(2.0) == pytest.approx(first_cx(1.0) * 2.0, rel=1e-6)


class TestFilledSvg:
    def test_original_document_is_preserved(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0)
        assert '<rect id="panel" x="20" y="20" width="340" height="340" fill="#333"/>' in filled
        assert '<rect id="calib" width="100" height="4" fill="none"/>' in filled

    def test_output_is_valid_xml(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, show_attach=True)
        root = ET.fromstring(filled)
        assert root.tag.endswith("svg")

    def test_removing_the_fill_group_restores_the_original(self, marble):
        """The fill is additive; deleting one group must undo it exactly."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, show_attach=True)
        stripped = re.sub(r"<defs>.*?</defs>\n", "", filled, flags=re.S)
        stripped = re.sub(r'<g id="mosaic-fill".*?</g>\n', "", stripped, flags=re.S)
        assert stripped == ORIGINAL

    def test_one_use_per_placement(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert count(r"<use ", filled) == len(PLACEMENTS)

    def test_transform_is_translate_then_rotate(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert 'transform="translate(90 120) rotate(45)"' in filled
        # A zero rotation is not worth the bytes.
        assert 'transform="translate(50 60)"' in filled

    def test_use_carries_xlink_href_for_svg_1_1_readers(self, marble):
        """Illustrator reads SVG 1.1 and draws nothing for a bare href."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert count(r'xlink:href="#mp', filled) == len(PLACEMENTS)

    def test_use_also_carries_plain_href_for_svg_2_readers(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert count(r'\shref="#mp', filled) == len(PLACEMENTS)

    def test_the_xlink_namespace_is_declared(self, marble):
        """An undeclared prefix makes the document invalid, not merely odd."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert 'xmlns:xlink="http://www.w3.org/1999/xlink"' in filled

    def test_every_reference_resolves_under_a_namespace_aware_parse(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        root = ET.fromstring(filled)
        svg, xlink = "{http://www.w3.org/2000/svg}", "{http://www.w3.org/1999/xlink}href"
        defined = {g.get("id") for g in root.iter(f"{svg}g") if g.get("id")}
        refs = [u.get(xlink) for u in root.iter(f"{svg}use")]
        assert refs and all(r and r.lstrip("#") in defined for r in refs)

    def test_the_namespace_is_declared_on_our_own_group_not_the_document(self, marble):
        """The upload's root element stays byte-for-byte as it arrived."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert ORIGINAL.splitlines()[0] in filled

    def test_colour_is_an_attribute_not_a_stylesheet_rule(self, marble):
        """CSS selectors do not cross the <use> shadow boundary."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert count(r'<use [^>]*stroke="#', filled) == len(PLACEMENTS)
        assert "<style" not in filled

    def test_colour_attribute_only_when_dots_are_shown(self, marble):
        plain = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0,
                                 show_attach=False, expand=False)
        dotted = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0,
                                  show_attach=True, expand=False)
        assert " color=" not in plain
        assert count(r'<use [^>]* color="#', dotted) == len(PLACEMENTS)

    def test_dots_are_defined_once_and_reused(self, marble):
        """Dots live in the defs, so placement count does not multiply them."""
        many = [
            Placement(piece="mp01", x=float(i), y=0.0, angle=0.0, cls="A")
            for i in range(500)
        ]
        filled = build_filled_svg(ORIGINAL, many, marble, 2.0, 1.0,
                                  show_attach=True, expand=False)
        expected = sum(len(p.attach) for p in marble.pieces)
        assert count(r"<circle", filled) == expected
        assert count(r"<use ", filled) == 500

    def test_dots_add_no_geometry_when_off(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, show_attach=False)
        assert "<circle" not in filled

    def test_unknown_piece_in_a_placement_is_skipped(self, marble):
        placements = [*PLACEMENTS, Placement(piece="nope", x=0, y=0, angle=0, cls="A")]
        filled = build_filled_svg(ORIGINAL, placements, marble, 2.0, 1.0, expand=False)
        assert count(r"<use ", filled) == len(PLACEMENTS)

    def test_a_document_without_a_closing_tag_still_gets_the_fill(self, marble):
        filled = build_filled_svg("<svg>", PLACEMENTS, marble, 2.0, 1.0, expand=False)
        assert "<use " in filled


class TestExpandedForm:
    """`expand=True` drops every reference, for consumers that mishandle <use>."""

    def test_it_is_the_default(self, marble):
        """A file that opens everywhere beats one that is 12% smaller."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0)
        assert "<use" not in filled
        assert count(r"<path ", filled) == len(PLACEMENTS)

    def test_no_references_at_all(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=True)
        assert "<use" not in filled
        assert "xlink" not in filled
        assert "<defs" not in filled

    def test_one_path_per_placement(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=True)
        # The original document contributes none; the panel there is a <rect>.
        assert count(r"<path ", filled) == len(PLACEMENTS)

    def test_it_still_parses(self, marble):
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=True)
        assert ET.fromstring(filled).tag.endswith("svg")

    def test_rotation_is_baked_into_the_coordinates(self, marble):
        """Nothing downstream has to honour a transform for the shape to be right."""
        filled = build_filled_svg(ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, expand=True)
        assert "rotate(" not in filled
        assert "transform=" not in filled.split("<g id=\"mosaic-fill\"")[1]

    def test_the_two_forms_place_pieces_in_the_same_spot(self, marble):
        """Same geometry either way, or the toggle would change the design."""
        placement = Placement(piece="mp05", x=70.0, y=40.0, angle=30.0, cls="A")
        expanded = build_filled_svg(ORIGINAL, [placement], marble, 2.0, 1.0, expand=True)
        coords = re.findall(r"d=\"M([-\d.]+),([-\d.]+)", expanded)
        assert coords
        piece = marble.piece_index()["mp05"]
        angle = math.radians(placement.angle)
        first = piece.rings[0][0]
        x = first[0] * 2.0 * math.cos(angle) - first[1] * 2.0 * math.sin(angle) + placement.x
        y = first[0] * 2.0 * math.sin(angle) + first[1] * 2.0 * math.cos(angle) + placement.y
        assert float(coords[0][0]) == pytest.approx(x, abs=0.01)
        assert float(coords[0][1]) == pytest.approx(y, abs=0.01)

    def test_attachment_dots_survive_expansion(self, marble):
        filled = build_filled_svg(
            ORIGINAL, PLACEMENTS, marble, 2.0, 1.0, show_attach=True, expand=True)
        expected = sum(len(marble.piece_index()[p.piece].attach) for p in PLACEMENTS)
        assert count(r"<circle", filled) == expected


class TestPaletteLegibility:
    """Every thread colour must read on both grounds it lands on.

    The preview draws on dark fabric; an exported SVG opens on a white
    artboard. A colour tuned for one disappears on the other, and a download
    that looks like an empty panel is indistinguishable from a broken export.
    """

    FABRIC = "#2f2a33"
    PAPER = "#ffffff"
    FLOOR = 2.0

    @staticmethod
    def relative_luminance(colour: str) -> float:
        raw = colour.lstrip("#")
        channels = [int(raw[i:i + 2], 16) / 255 for i in (0, 2, 4)]
        linear = [
            c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
            for c in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    @classmethod
    def contrast(cls, a: str, b: str) -> float:
        la, lb = cls.relative_luminance(a), cls.relative_luminance(b)
        return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)

    @pytest.mark.parametrize("colour", DEFAULT_PALETTE)
    def test_colour_reads_on_the_preview_fabric(self, colour):
        assert self.contrast(colour, self.FABRIC) >= self.FLOOR

    @pytest.mark.parametrize("colour", DEFAULT_PALETTE)
    def test_colour_reads_on_a_white_artboard(self, colour):
        assert self.contrast(colour, self.PAPER) >= self.FLOOR

    def test_the_palettes_on_both_sides_match(self):
        """The download is built in TypeScript; a drift there is a visible bug."""
        ts = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "lib"
              / "palette.ts").read_text(encoding="utf-8")
        found = re.findall(r"'(#[0-9a-fA-F]{6})'", ts)
        assert found[:len(DEFAULT_PALETTE)] == DEFAULT_PALETTE
