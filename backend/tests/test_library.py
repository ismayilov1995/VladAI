"""Library loading, and the clean pieces.svg format.

The format's whole point is that geometry and presentation are separable: the
canonical outlines live in <defs> in the library's own millimetre coordinates,
and the visible contact sheet is <use> references that carry no data. These
tests pin that, and pin the two things the markers exist to prevent - a stitch
point read as a piece, and a wrapper group read as a piece.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from mosaic_fill.library import (
    ATTACH_CLASS, PIECE_CLASS, _pieces_from_svg, discover_libraries, load_library,
)

BACKEND_ROOT = Path(__file__).resolve().parent.parent
MARBLE_DIR = BACKEND_ROOT / "libraries" / "marble"
PIECES_SVG = MARBLE_DIR / "pieces.svg"


def write_library(folder: Path, index: dict, **files: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.json").write_text(json.dumps(index), encoding="utf-8")
    for name, body in files.items():
        (folder / name.replace("_", ".")).write_text(body, encoding="utf-8")
    return folder


class TestMarbleFiles:
    def test_library_folder_holds_exactly_what_it_needs(self):
        names = {p.name for p in MARBLE_DIR.iterdir()}
        assert names == {"index.json", "pieces.json", "pieces.svg"}

    def test_index_points_at_pieces_svg(self):
        index = json.loads((MARBLE_DIR / "index.json").read_text())
        assert index["reference_svg"] == "pieces.svg"
        assert (MARBLE_DIR / index["reference_svg"]).is_file()

    def test_pieces_svg_is_valid_xml(self):
        assert ET.parse(PIECES_SVG).getroot().tag.endswith("svg")


def _elements(svg_root, wanted_class: str) -> list:
    """Elements actually carrying `wanted_class` - parsed, not string-matched,
    so the header comment documenting the markers does not count as one."""
    return [
        element for element in svg_root.iter()
        if wanted_class in (element.get("class") or "").split()
    ]


@pytest.fixture(scope="module")
def svg() -> str:
    return PIECES_SVG.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def root():
    return ET.parse(PIECES_SVG).getroot()


class TestPiecesSvgStructure:
    def test_one_marked_group_per_piece(self, root, marble):
        groups = _elements(root, PIECE_CLASS)
        assert len(groups) == len(marble.pieces)
        assert all(g.tag.endswith("g") for g in groups)

    def test_one_marked_circle_per_attachment_point(self, root, marble):
        circles = _elements(root, ATTACH_CLASS)
        assert len(circles) == sum(len(p.attach) for p in marble.pieces)
        assert all(c.tag.endswith("circle") for c in circles)

    def test_attachment_circles_sit_inside_their_piece_group(self, root, marble):
        by_id = {p.id: p for p in marble.pieces}
        for group in _elements(root, PIECE_CLASS):
            inside = [c for c in group if "circle" in c.tag]
            assert len(inside) == len(by_id[group.get("id")].attach)

    def test_geometry_lives_in_defs(self, svg):
        head, _, tail = svg.partition("</defs>")
        assert head.count("<path") == svg.count("<path")
        assert "<path" not in tail

    def test_the_visible_sheet_is_use_references_only(self, svg, marble):
        _, _, tail = svg.partition("</defs>")
        assert tail.count("<use ") == len(marble.pieces)

    def test_piece_coordinates_are_centred_not_laid_out(self, marble):
        """The old sheet baked grid offsets into the path data; this must not."""
        for piece in _pieces_from_svg(PIECES_SVG, 1.0):
            xs = [x for ring in piece.rings for x, _ in ring]
            ys = [y for ring in piece.rings for _, y in ring]
            # A centroid-centred piece straddles the origin on both axes.
            assert min(xs) < 0 < max(xs)
            assert min(ys) < 0 < max(ys)
            assert max(abs(v) for v in xs + ys) <= piece.size_mm

    def test_every_piece_keeps_its_id(self, marble):
        from_svg = _pieces_from_svg(PIECES_SVG, 1.0)
        assert [p.id for p in from_svg] == [p.id for p in marble.pieces]


class TestRoundTrip:
    def test_svg_reproduces_the_json_geometry(self, marble):
        """Extraction must be lossless, or pieces.svg is not the library."""
        from_svg = _pieces_from_svg(PIECES_SVG, 1.0)
        assert len(from_svg) == len(marble.pieces)
        for source, extracted in zip(marble.pieces, from_svg):
            assert source.id == extracted.id
            assert len(source.rings) == len(extracted.rings)
            for a, b in zip(source.rings, extracted.rings):
                assert len(a) == len(b)
                for (x1, y1), (x2, y2) in zip(a, b):
                    assert x1 == pytest.approx(x2, abs=1e-9)
                    assert y1 == pytest.approx(y2, abs=1e-9)
            assert source.area_mm2 == pytest.approx(extracted.area_mm2, abs=1e-9)

    def test_svg_reproduces_the_attachment_points(self, marble):
        for source, extracted in zip(marble.pieces, _pieces_from_svg(PIECES_SVG, 1.0)):
            assert len(source.attach) == len(extracted.attach)
            for (x1, y1), (x2, y2) in zip(source.attach, extracted.attach):
                assert x1 == pytest.approx(x2, abs=1e-9)
                assert y1 == pytest.approx(y2, abs=1e-9)

    def test_a_library_can_ship_as_svg_alone(self, tmp_path, marble):
        """The README promises this; it has to actually work."""
        folder = write_library(
            tmp_path / "svgonly",
            {"id": "svgonly", "name": "SVG only", "unit": "mm",
             "reference_svg": "pieces.svg"},
            pieces_svg=PIECES_SVG.read_text(encoding="utf-8"),
        )
        library = load_library(folder)
        assert len(library.pieces) == len(marble.pieces)
        assert sum(len(p.attach) for p in library.pieces) == \
            sum(len(p.attach) for p in marble.pieces)


class TestMarkersPreventMisreading:
    def test_attachment_dots_are_never_read_as_pieces(self, tmp_path):
        """A 0.45 mm dot read as a piece is what the old sheet did."""
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg">
          <defs>
            <g id="mp01" class="{PIECE_CLASS}">
              <path d="M-5,-5 L5,-5 L5,5 L-5,5 Z"/>
              <circle class="{ATTACH_CLASS}" cx="0" cy="0" r="0.45"/>
              <circle class="{ATTACH_CLASS}" cx="2" cy="2" r="0.45"/>
            </g>
          </defs>
        </svg>"""
        path = tmp_path / "x.svg"
        path.write_text(svg, encoding="utf-8")
        pieces = _pieces_from_svg(path, 1.0)
        assert len(pieces) == 1
        assert len(pieces[0].attach) == 2
        assert pieces[0].area_mm2 == pytest.approx(100.0)

    def test_a_wrapper_group_is_not_read_as_one_giant_piece(self, tmp_path):
        """Marking is why a layer holding every piece cannot be misread."""
        svg = f"""<svg xmlns="http://www.w3.org/2000/svg">
          <g id="layer1">
            <g id="mp01" class="{PIECE_CLASS}"><path d="M-5,-5 L5,-5 L5,5 L-5,5 Z"/></g>
            <g id="mp02" class="{PIECE_CLASS}"><path d="M-2,-2 L2,-2 L2,2 L-2,2 Z"/></g>
          </g>
        </svg>"""
        path = tmp_path / "x.svg"
        path.write_text(svg, encoding="utf-8")
        pieces = _pieces_from_svg(path, 1.0)
        assert [p.id for p in pieces] == ["mp01", "mp02"]
        assert pieces[0].area_mm2 == pytest.approx(100.0)
        assert pieces[1].area_mm2 == pytest.approx(16.0)

    def test_an_unmarked_sheet_still_loads_one_piece_per_shape(self, tmp_path):
        """A hand-traced SVG says nothing about itself; read it the old way."""
        svg = """<svg xmlns="http://www.w3.org/2000/svg">
          <g fill="none" stroke="#000">
            <path id="a" d="M0,0 L10,0 L10,10 L0,10 Z"/>
            <path id="b" d="M20,0 L26,0 L26,6 L20,6 Z"/>
          </g>
        </svg>"""
        path = tmp_path / "x.svg"
        path.write_text(svg, encoding="utf-8")
        pieces = _pieces_from_svg(path, 1.0)
        assert [p.id for p in pieces] == ["a", "b"]
        assert all(not p.attach for p in pieces)


class TestDiscovery:
    def test_marble_is_discovered(self, marble):
        assert marble.id == "marble"
        assert len(marble.pieces) == 22

    def test_a_broken_folder_is_skipped_not_fatal(self, tmp_path):
        write_library(tmp_path / "broken", {"id": "broken", "name": "Broken"})
        write_library(
            tmp_path / "good",
            {"id": "good", "name": "Good", "reference_svg": "pieces.svg"},
            pieces_svg='<svg xmlns="http://www.w3.org/2000/svg">'
                       '<path d="M0,0 L10,0 L10,10 L0,10 Z"/></svg>',
        )
        found = discover_libraries(tmp_path)
        assert set(found) == {"good"}

    def test_unit_declaration_is_honoured(self, tmp_path):
        folder = write_library(
            tmp_path / "cm",
            {"id": "cm", "name": "cm", "unit": "cm", "reference_svg": "pieces.svg"},
            pieces_svg='<svg xmlns="http://www.w3.org/2000/svg">'
                       '<path d="M0,0 L1,0 L1,1 L0,1 Z"/></svg>',
        )
        library = load_library(folder)
        assert library.pieces[0].size_mm == pytest.approx(10.0)
