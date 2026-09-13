"""Reading a panel SVG: scale calibration and fillable-region extraction.

The only scale convention this tool accepts is an element with ``id="calib"``.
Its bounding-box width in user units, divided by the real width the user types
in millimetres, gives units/mm. Nothing here guesses: when there is no such
element the caller is told so and must supply units/mm directly.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

from .matrix import Matrix, IDENTITY, parse_transform, multiply, transform_ring
from .svgpath import DEFAULT_TOLERANCE, Ring, ring_area, rings_bbox, shape_to_rings

SVG_NS = "http://www.w3.org/2000/svg"

# Elements whose contents are definitions, not drawn content.
_NON_RENDERING = {
    "defs", "clipPath", "mask", "marker", "symbol", "pattern",
    "linearGradient", "radialGradient", "filter", "metadata", "title", "desc",
}
_GEOMETRY = {"path", "rect", "circle", "ellipse", "polygon", "polyline", "line"}


class CalibrationError(ValueError):
    """Raised when the document cannot be scaled from its own contents."""


@dataclass
class Shape:
    """One filled region in millimetres."""

    element_id: str
    tag: str
    rings: list[Ring]
    fill_rule: str = "nonzero"

    def area(self) -> float:
        return abs(sum(ring_area(r) for r in self.rings))

    def bbox(self) -> tuple[float, float, float, float]:
        return rings_bbox(self.rings)


@dataclass
class PanelDocument:
    """A parsed panel, with everything needed to pack it."""

    source: str
    width_units: float
    height_units: float
    view_box: tuple[float, float, float, float] | None
    calib_width_units: float | None
    shapes: list[Shape] = field(default_factory=list)
    candidates: list[dict] = field(default_factory=list)

    def units_per_mm(self, calib_width_mm: float) -> float:
        if self.calib_width_units is None:
            raise CalibrationError("no element with id='calib' in this document")
        if calib_width_mm <= 0:
            raise CalibrationError("calibration width must be greater than zero")
        return self.calib_width_units / calib_width_mm


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style_map(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    out: dict[str, str] = {}
    for part in raw.split(";"):
        if ":" in part:
            key, _, value = part.partition(":")
            out[key.strip().lower()] = value.strip()
    return out


def _resolve(attrs: dict[str, str], name: str) -> str | None:
    """Presentation attribute with the inline `style` declaration winning."""
    style = _style_map(attrs.get("style"))
    return style.get(name, attrs.get(name))


_LENGTH = re.compile(r"\s*([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)\s*([a-z%]*)", re.I)

# CSS absolute units per inch, with the SVG default of 96 user units per inch.
_UNIT_SCALE = {
    "": 1.0, "px": 1.0, "pt": 96.0 / 72.0, "pc": 16.0,
    "in": 96.0, "cm": 96.0 / 2.54, "mm": 96.0 / 25.4, "q": 96.0 / 101.6,
}


def parse_length(raw: str | None, default: float = 0.0) -> float:
    if not raw:
        return default
    match = _LENGTH.match(raw)
    if not match:
        return default
    value = float(match.group(1))
    unit = match.group(2).lower()
    if unit == "%":
        return default
    return value * _UNIT_SCALE.get(unit, 1.0)


def _is_hidden(attrs: dict[str, str]) -> bool:
    if (_resolve(attrs, "display") or "").strip().lower() == "none":
        return True
    return (_resolve(attrs, "visibility") or "").strip().lower() in ("hidden", "collapse")


def _has_fill(attrs: dict[str, str]) -> bool:
    fill = (_resolve(attrs, "fill") or "").strip().lower()
    if fill in ("none", "transparent"):
        return False
    opacity = _resolve(attrs, "fill-opacity")
    if opacity is not None:
        try:
            if float(opacity) <= 0.0:
                return False
        except ValueError:
            pass
    return True


def parse_panel(svg_text: str, tolerance: float = DEFAULT_TOLERANCE) -> PanelDocument:
    """Parse a panel SVG into calibration data and candidate fill shapes.

    Shapes are returned in user units; converting to millimetres is deferred
    until units/mm is known, because that can come from the caller instead of
    the document.
    """
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:  # pragma: no cover - surfaced to the API
        raise ValueError(f"not a parsable SVG document: {exc}") from exc
    if _local(root.tag) != "svg":
        raise ValueError("root element is not <svg>")

    view_box: tuple[float, float, float, float] | None = None
    raw_vb = root.get("viewBox")
    if raw_vb:
        nums = [float(v) for v in re.findall(
            r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", raw_vb)]
        if len(nums) >= 4:
            view_box = (nums[0], nums[1], nums[2], nums[3])

    width = parse_length(root.get("width"), view_box[2] if view_box else 0.0)
    height = parse_length(root.get("height"), view_box[3] if view_box else 0.0)

    doc = PanelDocument(
        source=svg_text,
        width_units=width,
        height_units=height,
        view_box=view_box,
        calib_width_units=None,
    )

    def walk(node: ET.Element, ctm: Matrix, hidden: bool) -> None:
        for child in node:
            tag = _local(child.tag)
            if tag in _NON_RENDERING:
                continue
            attrs = dict(child.attrib)
            local_ctm = multiply(ctm, parse_transform(attrs.get("transform")))
            child_hidden = hidden or _is_hidden(attrs)
            if tag in ("g", "a", "svg", "switch"):
                walk(child, local_ctm, child_hidden)
                continue
            if tag not in _GEOMETRY:
                continue

            rings = shape_to_rings(tag, attrs, tolerance)
            if not rings:
                continue
            rings = [transform_ring(local_ctm, r) for r in rings]
            element_id = attrs.get("id", "")

            if element_id == "calib":
                min_x, _, max_x, _ = rings_bbox(rings)
                doc.calib_width_units = max_x - min_x
                continue
            if child_hidden or not _has_fill(attrs):
                continue

            fill_rule = (_resolve(attrs, "fill-rule") or "nonzero").strip().lower()
            if fill_rule not in ("nonzero", "evenodd"):
                fill_rule = "nonzero"
            doc.shapes.append(Shape(element_id, tag, rings, fill_rule))

    walk(root, IDENTITY, False)

    doc.candidates = [
        {
            "id": s.element_id,
            "tag": s.tag,
            "index": i,
            "area_units": s.area(),
            "bbox": list(s.bbox()),
        }
        for i, s in enumerate(doc.shapes)
    ]
    # Largest first: the panel outline is nearly always the biggest shape, so a
    # caller that just takes the first entry gets the sensible default.
    doc.candidates.sort(key=lambda c: -c["area_units"])
    return doc


def shapes_to_mm(shapes: list[Shape], units_per_mm: float) -> list[Shape]:
    """Rescale shapes from user units into millimetres."""
    if units_per_mm <= 0 or not math.isfinite(units_per_mm):
        raise CalibrationError("units/mm must be a positive finite number")
    inv = 1.0 / units_per_mm
    return [
        Shape(
            s.element_id,
            s.tag,
            [[(x * inv, y * inv) for x, y in ring] for ring in s.rings],
            s.fill_rule,
        )
        for s in shapes
    ]


def select_shapes(doc: PanelDocument, ids: list[str] | None) -> list[Shape]:
    """Pick the shapes to fill; `None` or empty means every filled shape."""
    if not ids:
        return list(doc.shapes)
    wanted = set(ids)
    chosen = [s for s in doc.shapes if s.element_id in wanted]
    return chosen or list(doc.shapes)
