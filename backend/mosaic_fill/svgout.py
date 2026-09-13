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
  * Each ``<use>`` carries **both** ``xlink:href`` and ``href``. Plain ``href``
    is SVG 2; Illustrator reads SVG 1.1, where the attribute is ``xlink:href``,
    and silently draws nothing for a reference it does not recognise. Browsers
    take either, so a browser preview cannot catch this on its own.
  * ``expand`` is the default, and writes every placement as its own ``<path>``
    with no references anywhere. The ``<defs>``/``<use>`` form above is the
    ``expand=False`` option: it is the more elegant document, but a reference
    only helps if the reader resolves it, and Illustrator does not. It saves
    about 12% at working density (547 KB against 612 KB for a 4924-piece
    panel), which is not worth a file that opens empty.
  * The uploaded document is never modified; the fill is appended as one new
    group that can be deleted in one action.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

from .library import Library
from .packer import Placement

FILL_GROUP_ID = "mosaic-fill"
XLINK_NS = "http://www.w3.org/1999/xlink"
# Kept in step with frontend/src/lib/palette.ts: one palette serves the preview
# and the export, and every colour has to stay legible both on the preview's
# dark fabric and on the white artboard an exported SVG opens onto.
DEFAULT_PALETTE = [
    "#b08d57",  # antique gold
    "#a63d40",  # madder red
    "#5f7d8c",  # slate blue
    "#4a7c59",  # moss
    "#c06c3e",  # terracotta
    "#7a6a9b",  # lavender
    "#8c7851",  # bronze
    "#7d8c8a",  # sage
]
# Radius of an attachment dot, in millimetres on the finished piece.
DEFAULT_ATTACH_RADIUS_MM = 0.45


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
    show_attach: bool = False, attach_dot_radius_mm: float = DEFAULT_ATTACH_RADIUS_MM,
) -> tuple[str, dict[str, str]]:
    """The ``<defs>`` block, plus a map from piece id to its symbol id.

    Piece scale and units/mm are baked into the geometry here, which is what
    lets each ``<use>`` carry nothing but a translate and a rotate.

    Attachment dots go inside the same group as the outline, so they are
    translated and rotated with the piece for free rather than needing a second
    pass of per-placement transforms. They are filled with ``currentColor``,
    which the ``<use>`` sets via a ``color`` attribute: ``color`` is inherited,
    so like ``stroke`` it crosses into the shadow tree, and the dots take the
    thread colour of the piece they belong to.
    """
    factor = piece_scale * units_per_mm
    # The dot marks a needle penetration point, so it stays a fixed physical
    # size: its position scales with the piece, its radius does not.
    radius = attach_dot_radius_mm * units_per_mm
    symbols: dict[str, str] = {}
    parts: list[str] = []
    for index, piece in enumerate(library.pieces, start=1):
        symbol_id = f"mp{index:02d}"
        symbols[piece.id] = symbol_id
        data = piece_path_data(piece.rings, factor)
        if not data:
            continue
        body = f'<path fill="none" d="{data}"/>'
        if show_attach and piece.attach and radius > 0:
            dots = "".join(
                f'<circle cx="{_fmt(x * factor)}" cy="{_fmt(y * factor)}" '
                f'r="{_fmt(radius)}" fill="currentColor" stroke="none"/>'
                for x, y in piece.attach
            )
            body += dots
        parts.append(f'  <g id="{symbol_id}">{body}</g>')
    return "\n".join(parts), symbols


def build_fill_group(
    placements: Iterable[Placement],
    symbols: dict[str, str],
    units_per_mm: float,
    palette: Sequence[str] | None = None,
    stroke_width_mm: float = 0.25,
    show_attach: bool = False,
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
        # `color` feeds the dots' currentColor fill; it is only worth emitting
        # when there are dots to colour.
        tint = f' color="{colour}"' if show_attach else ""
        # Both spellings: xlink:href for SVG 1.1 readers such as Illustrator,
        # href for SVG 2. A reader that knows only one ignores the other.
        rows.append(
            f'  <use xlink:href="#{symbol_id}" href="#{symbol_id}" '
            f'transform="{transform}" stroke="{colour}"{tint}/>'
        )
    return (
        f'<g id="{FILL_GROUP_ID}" xmlns:xlink="{XLINK_NS}" fill="none"\n'
        f'   stroke-width="{_fmt(width)}" stroke-linejoin="round" stroke-linecap="round">\n'
        + "\n".join(rows)
        + "\n</g>"
    )


def build_expanded_group(
    placements: Iterable[Placement],
    library: Library,
    piece_scale: float,
    units_per_mm: float,
    palette: Sequence[str] | None = None,
    stroke_width_mm: float = 0.25,
    show_attach: bool = False,
    attach_dot_radius_mm: float = DEFAULT_ATTACH_RADIUS_MM,
) -> str:
    """Every placement as its own ``<path>``, with no references anywhere.

    Bigger than the ``<use>`` form and equivalent to it on screen; the point is
    that nothing has to resolve a reference to draw it.
    """
    colours = list(palette) if palette else DEFAULT_PALETTE
    width = stroke_width_mm * units_per_mm
    radius = attach_dot_radius_mm * units_per_mm
    factor = piece_scale * units_per_mm
    index = library.piece_index()
    rows: list[str] = []

    for placement in placements:
        piece = index.get(placement.piece)
        if piece is None:
            continue
        cls_index = max(0, ord(placement.cls[:1] or "A") - ord("A"))
        colour = colours[cls_index % len(colours)] if colours else "#000000"
        radians = math.radians(placement.angle)
        cos, sin = math.cos(radians), math.sin(radians)
        ox = placement.x * units_per_mm
        oy = placement.y * units_per_mm

        def place(px: float, py: float) -> tuple[float, float]:
            sx, sy = px * factor, py * factor
            return (sx * cos - sy * sin + ox, sx * sin + sy * cos + oy)

        parts: list[str] = []
        for ring in piece.rings:
            if len(ring) < 3:
                continue
            points = [f"{_fmt(x)},{_fmt(y)}" for x, y in (place(px, py) for px, py in ring)]
            parts.append(f"M{' L'.join(points)} Z")
        if not parts:
            continue
        rows.append(f'  <path stroke="{colour}" d="{" ".join(parts)}"/>')

        if show_attach and radius > 0:
            for px, py in piece.attach:
                cx, cy = place(px, py)
                rows.append(
                    f'  <circle cx="{_fmt(cx)}" cy="{_fmt(cy)}" r="{_fmt(radius)}" '
                    f'fill="{colour}" stroke="none"/>'
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
    show_attach: bool = False,
    attach_dot_radius_mm: float = DEFAULT_ATTACH_RADIUS_MM,
    expand: bool = True,
) -> str:
    """Return the original document with one fill group appended.

    Everything already in the file is passed through untouched: the fill is
    additive, so removing the one appended group restores the upload exactly.
    """
    if expand:
        addition = build_expanded_group(
            placements, library, piece_scale, units_per_mm, palette,
            stroke_width_mm, show_attach, attach_dot_radius_mm,
        ) + "\n"
    else:
        defs, symbols = build_defs(
            library, piece_scale, units_per_mm, show_attach, attach_dot_radius_mm,
        )
        group = build_fill_group(
            placements, symbols, units_per_mm, palette, stroke_width_mm, show_attach,
        )
        addition = f"<defs>\n{defs}\n</defs>\n{group}\n"

    match = _CLOSING_SVG.search(original_svg)
    if not match:
        # No closing tag to insert before; appending keeps the output usable
        # rather than silently dropping the fill.
        return original_svg + "\n" + addition
    return original_svg[:match.start()] + addition + "</svg>\n"
