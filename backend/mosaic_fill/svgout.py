"""Building the filled SVG from a placement list.

The frontend builds the download from the same placement JSON, in TypeScript;
this is the reference implementation and what the CLI writes. Both follow the
same shape, and the reasons for that shape are worth stating:

  * One ``<g id="mpNN">`` per library piece in ``<defs>``, centred on its own
    centroid, so ``rotate()`` on a ``<use>`` spins the piece in place.
  * ``transform="translate(x y) rotate(a)"`` per placement, in that order:
    rotate first about the piece's own origin, then move it.
  * Colour goes on the ``stroke`` attribute of each ``<use>``. It has to be an
    attribute, not a stylesheet rule: a ``<use>`` clones its referent into a
    shadow tree that outside selectors do not reach, so ``#mosaic .A path {}``
    matches nothing. Inherited presentation attributes on the ``<use>`` itself
    do cross into the clone, which is why this works and CSS does not.
  * The uploaded document is never modified; the fill is appended as one new
    group that can be deleted in one action.
"""

from __future__ import annotations

import re
from typing import Iterable, Sequence

from .library import Library
from .packer import Placement

FILL_GROUP_ID = "mosaic-fill"
DEFAULT_PALETTE = ["#1d1d1f", "#8c7851", "#b08d57", "#d9c7a7", "#5c6b73", "#a63d40"]


def _fmt(value: float, places: int = 3) -> str:
    text = f"{value:.{places}f}".rstrip("0").rstrip(".")
    return text if text and text != "-0" else "0"


def piece_path_data(rings: Sequence[Sequence[tuple[float, float]]], scale: float) -> str:
    """Path data for one piece, scaled, still centred on its centroid."""
    parts: list[str] = []
    for ring in rings:
        if len(ring) < 3:
            continue
        points = [f"{_fmt(x * scale)},{_fmt(y * scale)}" for x, y in ring]
        parts.append(f"M{' L'.join(points)} Z")
    return " ".join(parts)


def build_defs(
    library: Library, piece_scale: float, units_per_mm: float,
) -> tuple[str, dict[str, str]]:
    """The ``<defs>`` block, plus a map from piece id to its symbol id.

    Piece scale and units/mm are baked into the geometry here, which is what
    lets each ``<use>`` carry nothing but a translate and a rotate.
    """
    factor = piece_scale * units_per_mm
    symbols: dict[str, str] = {}
    parts: list[str] = []
    for index, piece in enumerate(library.pieces, start=1):
        symbol_id = f"mp{index:02d}"
        symbols[piece.id] = symbol_id
        data = piece_path_data(piece.rings, factor)
        if not data:
            continue
        parts.append(
            f'  <g id="{symbol_id}"><path fill="none" d="{data}"/></g>'
        )
    return "\n".join(parts), symbols


def build_fill_group(
    placements: Iterable[Placement],
    symbols: dict[str, str],
    units_per_mm: float,
    palette: Sequence[str] | None = None,
    stroke_width_mm: float = 0.25,
) -> str:
    colours = list(palette) if palette else DEFAULT_PALETTE
    width = stroke_width_mm * units_per_mm
    rows: list[str] = []
    for placement in placements:
        symbol_id = symbols.get(placement.piece)
        if symbol_id is None:
            continue
        index = max(0, ord(placement.cls[:1] or "A") - ord("A"))
        colour = colours[index % len(colours)] if colours else "#000000"
        x = _fmt(placement.x * units_per_mm)
        y = _fmt(placement.y * units_per_mm)
        angle = _fmt(placement.angle, 2)
        transform = f"translate({x} {y})"
        if angle != "0":
            transform += f" rotate({angle})"
        rows.append(
            f'  <use href="#{symbol_id}" transform="{transform}" stroke="{colour}"/>'
        )
    return (
        f'<g id="{FILL_GROUP_ID}" fill="none" stroke-width="{_fmt(width)}"\n'
        f'   stroke-linejoin="round" stroke-linecap="round">\n'
        + "\n".join(rows)
        + "\n</g>"
    )


_CLOSING_SVG = re.compile(r"</svg\s*>\s*$", re.IGNORECASE)


def build_filled_svg(
    original_svg: str,
    placements: Sequence[Placement],
    library: Library,
    piece_scale: float,
    units_per_mm: float,
    palette: Sequence[str] | None = None,
    stroke_width_mm: float = 0.25,
) -> str:
    """Return the original document with one fill group appended.

    Everything already in the file is passed through untouched: the fill is
    additive, so removing the one appended group restores the upload exactly.
    """
    defs, symbols = build_defs(library, piece_scale, units_per_mm)
    group = build_fill_group(placements, symbols, units_per_mm, palette, stroke_width_mm)
    addition = f"<defs>\n{defs}\n</defs>\n{group}\n"

    match = _CLOSING_SVG.search(original_svg)
    if not match:
        # No closing tag to insert before; appending keeps the output usable
        # rather than silently dropping the fill.
        return original_svg + "\n" + addition
    return original_svg[:match.start()] + addition + "</svg>\n"
