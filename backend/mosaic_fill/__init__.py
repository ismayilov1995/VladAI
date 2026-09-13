"""Standalone embroidery packing engine.

Imports nothing from the web layer: the engine is usable from the command line
(``python -m mosaic_fill.cli``) and from the FastAPI service alike.
"""

from .library import Library, Piece, discover_libraries, load_library
from .packer import PackParams, PackResult, Placement, occupancy_overlaps, pack
from .svgdoc import CalibrationError, PanelDocument, Shape, parse_panel, select_shapes, shapes_to_mm
from .svgout import build_filled_svg

__all__ = [
    "Library", "Piece", "discover_libraries", "load_library",
    "PackParams", "PackResult", "Placement", "pack", "occupancy_overlaps",
    "CalibrationError", "PanelDocument", "Shape", "parse_panel",
    "select_shapes", "shapes_to_mm", "build_filled_svg",
]
