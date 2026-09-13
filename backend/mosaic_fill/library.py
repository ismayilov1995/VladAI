"""Embroidery piece libraries.

A library is a folder under ``libraries/`` containing an ``index.json``.
Adding one means dropping a folder in; nothing here needs editing. Geometry
comes from a ``pieces.json`` when present, and otherwise straight from the
reference SVG named by the index, so a library can start life as a traced SVG
alone.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from .svgpath import (
    DEFAULT_TOLERANCE, Ring, ring_area, ring_centroid, rings_bbox, shape_to_rings,
)
from .svgdoc import SVG_NS  # noqa: F401  (re-exported for callers)

import xml.etree.ElementTree as ET

DEFAULT_LIBRARY_DIR = Path(__file__).resolve().parent.parent / "libraries"


@dataclass
class Piece:
    """One embroidery motif, in millimetres, centred on its own centroid.

    Centring matters downstream: the exported SVG places every piece with
    ``translate(x y) rotate(a)``, so a piece must already sit around its own
    origin for that rotation to spin it in place.
    """

    id: str
    rings: list[Ring]
    area_mm2: float
    width_mm: float
    height_mm: float
    attach: list[tuple[float, float]] = field(default_factory=list)

    @property
    def size_mm(self) -> float:
        return max(self.width_mm, self.height_mm)

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "rings": [[coord for point in ring for coord in point] for ring in self.rings],
            "area_mm2": round(self.area_mm2, 4),
            "width_mm": round(self.width_mm, 4),
            "height_mm": round(self.height_mm, 4),
            "attach": [[round(x, 4), round(y, 4)] for x, y in self.attach],
        }


@dataclass
class Library:
    id: str
    name: str
    pieces: list[Piece]
    rapport_coverage: float = 0.56
    unit: str = "mm"
    description: str = ""
    provenance: str = ""
    reference_svg: str | None = None

    @property
    def size_range_mm(self) -> tuple[float, float]:
        if not self.pieces:
            return (0.0, 0.0)
        sizes = [p.size_mm for p in self.pieces]
        return (min(sizes), max(sizes))

    def piece_index(self) -> dict[str, Piece]:
        return {p.id: p for p in self.pieces}

    def to_json(self) -> dict:
        lo, hi = self.size_range_mm
        return {
            "id": self.id,
            "name": self.name,
            "unit": self.unit,
            "description": self.description,
            "provenance": self.provenance,
            "rapport_coverage": self.rapport_coverage,
            "piece_count": len(self.pieces),
            "size_range_mm": [round(lo, 3), round(hi, 3)],
            "pieces": [p.to_json() for p in self.pieces],
        }

    def summary_json(self) -> dict:
        lo, hi = self.size_range_mm
        return {
            "id": self.id,
            "name": self.name,
            "unit": self.unit,
            "description": self.description,
            "provenance": self.provenance,
            "rapport_coverage": self.rapport_coverage,
            "piece_count": len(self.pieces),
            "size_range_mm": [round(lo, 3), round(hi, 3)],
        }


def _centre_piece(piece_id: str, rings: list[Ring], attach: list[tuple[float, float]]) -> Piece:
    """Translate rings so the outer ring's centroid sits at the origin."""
    if not rings:
        raise ValueError(f"piece {piece_id!r} has no geometry")
    outer = max(rings, key=lambda r: abs(ring_area(r)))
    cx, cy = ring_centroid(outer)
    moved = [[(x - cx, y - cy) for x, y in ring] for ring in rings]
    min_x, min_y, max_x, max_y = rings_bbox(moved)
    area = abs(sum(ring_area(r) for r in moved))
    return Piece(
        id=piece_id,
        rings=moved,
        area_mm2=area,
        width_mm=max_x - min_x,
        height_mm=max_y - min_y,
        attach=[(x - cx, y - cy) for x, y in attach],
    )


def _pieces_from_json(data: dict, scale_to_mm: float) -> list[Piece]:
    pieces: list[Piece] = []
    for entry in data.get("pieces", []):
        piece_id = str(entry.get("id") or f"mp{len(pieces) + 1:02d}")
        rings: list[Ring] = []
        for ring in entry.get("rings", []):
            if not ring:
                continue
            if isinstance(ring[0], (int, float)):
                flat = [float(v) * scale_to_mm for v in ring]
                pts = [(flat[i], flat[i + 1]) for i in range(0, len(flat) - 1, 2)]
            else:
                pts = [(float(p[0]) * scale_to_mm, float(p[1]) * scale_to_mm) for p in ring]
            if len(pts) >= 3:
                rings.append(pts)
        if not rings and entry.get("d"):
            rings = [
                [(x * scale_to_mm, y * scale_to_mm) for x, y in r]
                for r in shape_to_rings("path", {"d": entry["d"]}, DEFAULT_TOLERANCE)
            ]
        if not rings:
            continue
        attach = [
            (float(p[0]) * scale_to_mm, float(p[1]) * scale_to_mm)
            for p in entry.get("attach", [])
        ]
        pieces.append(_centre_piece(piece_id, rings, attach))
    return pieces


# Markers used by the clean pieces.svg format (see tools/extract_pieces_svg.py).
# They are what the loader keys on, so a wrapper or layer group is never
# mistaken for a piece, nor a stitch point for geometry.
PIECE_CLASS = "piece"
ATTACH_CLASS = "attach"

_GEOMETRY_TAGS = ("path", "rect", "circle", "ellipse", "polygon")


def _local_tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _classes(attrs: dict[str, str]) -> set[str]:
    return set((attrs.get("class") or "").split())


def _piece_from_group(
    group: ET.Element, scale_to_mm: float, fallback_index: int,
) -> Piece | None:
    """One ``<g class="piece">``: its geometry, plus any attachment points."""
    rings: list[Ring] = []
    attach: list[tuple[float, float]] = []
    for child in group:
        tag = _local_tag(child)
        if tag not in _GEOMETRY_TAGS:
            continue
        attrs = dict(child.attrib)
        if ATTACH_CLASS in _classes(attrs):
            attach.append((
                float(attrs.get("cx", 0.0)) * scale_to_mm,
                float(attrs.get("cy", 0.0)) * scale_to_mm,
            ))
            continue
        for ring in shape_to_rings(tag, attrs, DEFAULT_TOLERANCE):
            rings.append([(x * scale_to_mm, y * scale_to_mm) for x, y in ring])
    if not rings:
        return None
    piece_id = group.get("id") or f"mp{fallback_index:02d}"
    return _centre_piece(piece_id, rings, attach)


def _pieces_from_svg(svg_path: Path, scale_to_mm: float) -> list[Piece]:
    """Read pieces from an SVG.

    Two shapes are understood. A file written by the extractor marks each piece
    as ``<g class="piece">`` and each stitch point as ``<circle class="attach">``,
    and that is read exactly. Any other SVG - a hand-traced sheet, say - falls
    back to treating every drawable element as its own piece, which is the only
    sensible reading when the file says nothing about its own structure.
    """
    root = ET.fromstring(svg_path.read_text(encoding="utf-8"))

    marked = [
        element for element in root.iter()
        if _local_tag(element) == "g" and PIECE_CLASS in _classes(dict(element.attrib))
    ]
    if marked:
        pieces: list[Piece] = []
        for group in marked:
            piece = _piece_from_group(group, scale_to_mm, len(pieces) + 1)
            if piece is not None:
                pieces.append(piece)
        if pieces:
            return pieces

    pieces = []
    for element in root.iter():
        tag = _local_tag(element)
        if tag not in _GEOMETRY_TAGS:
            continue
        attrs = dict(element.attrib)
        # An unmarked file has no stitch points, but one converted from the
        # marked format might still carry the marker; never read it as a piece.
        if ATTACH_CLASS in _classes(attrs):
            continue
        rings = shape_to_rings(tag, attrs, DEFAULT_TOLERANCE)
        if not rings:
            continue
        rings = [[(x * scale_to_mm, y * scale_to_mm) for x, y in r] for r in rings]
        piece_id = attrs.get("id") or f"mp{len(pieces) + 1:02d}"
        pieces.append(_centre_piece(piece_id, rings, []))
    return pieces


def load_library(folder: Path) -> Library:
    """Load one library folder. Raises if `index.json` is missing or unusable."""
    index_path = folder / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(f"{folder} has no index.json")
    index = json.loads(index_path.read_text(encoding="utf-8"))

    unit = str(index.get("unit", "mm")).lower()
    scale_to_mm = {"mm": 1.0, "cm": 10.0, "m": 1000.0, "in": 25.4}.get(unit, 1.0)

    pieces: list[Piece] = []
    pieces_file = index.get("pieces_file", "pieces.json")
    if pieces_file and (folder / pieces_file).is_file():
        data = json.loads((folder / pieces_file).read_text(encoding="utf-8"))
        pieces = _pieces_from_json(data, scale_to_mm)
    if not pieces and index.get("reference_svg"):
        svg_path = folder / str(index["reference_svg"])
        if svg_path.is_file():
            pieces = _pieces_from_svg(svg_path, scale_to_mm)
    if not pieces:
        raise ValueError(f"library {folder.name!r} defines no usable pieces")

    coverage = float(index.get("rapport_coverage", 0.56))
    if not (0.0 < coverage <= 1.0):
        coverage = 0.56
    return Library(
        id=str(index.get("id", folder.name)),
        name=str(index.get("name", folder.name)),
        pieces=pieces,
        rapport_coverage=coverage,
        unit="mm",
        description=str(index.get("description", "")),
        provenance=str(index.get("provenance", "")),
        reference_svg=index.get("reference_svg"),
    )


def discover_libraries(root: Path | None = None) -> dict[str, Library]:
    """Load every library folder under `root`, skipping any that fail.

    A broken folder must not take the whole service down with it, so failures
    are swallowed per folder; the loader is strict, the discovery is not.
    """
    base = Path(root) if root is not None else DEFAULT_LIBRARY_DIR
    found: dict[str, Library] = {}
    if not base.is_dir():
        return found
    for child in sorted(base.iterdir()):
        if not child.is_dir() or not (child / "index.json").is_file():
            continue
        try:
            library = load_library(child)
        except (ValueError, OSError, json.JSONDecodeError, ET.ParseError):
            continue
        found[library.id] = library
    return found


def library_fingerprint(library: Library) -> str:
    """Stable digest of a library's geometry, mixed into the pack cache key."""
    import hashlib

    digest = hashlib.sha256()
    digest.update(library.id.encode("utf-8"))
    for piece in library.pieces:
        digest.update(piece.id.encode("utf-8"))
        for ring in piece.rings:
            for x, y in ring:
                digest.update(f"{x:.5f},{y:.5f};".encode("ascii"))
    return digest.hexdigest()[:16]


def piece_scaled_rings(piece: Piece, scale: float) -> list[Ring]:
    return [[(x * scale, y * scale) for x, y in ring] for ring in piece.rings]


def piece_max_radius(piece: Piece) -> float:
    """Distance from the centroid to the furthest point, for sizing stamps."""
    best = 0.0
    for ring in piece.rings:
        for x, y in ring:
            best = max(best, math.hypot(x, y))
    return best
