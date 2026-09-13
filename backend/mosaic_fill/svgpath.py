"""SVG path-data and basic-shape flattening.

Pure geometry: no numpy, no FastAPI, no DOM. Every shape in a document is
reduced to a list of closed polygon rings expressed as ``[(x, y), ...]`` in
user units. Curves are flattened by recursive subdivision against a flatness
tolerance so that a tight curve gets the points it needs and a lazy one does
not pay for them.
"""

from __future__ import annotations

import math
import re
from typing import Iterable, Sequence

Point = tuple[float, float]
Ring = list[Point]

# Matches a path command letter or a number in any SVG-legal spelling,
# including the "1.5.5" run-on form and exponents.
_TOKEN = re.compile(r"[MmZzLlHhVvCcSsQqTtAa]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")

_ARG_COUNT = {
    "M": 2, "L": 2, "H": 1, "V": 1, "C": 6, "S": 4,
    "Q": 4, "T": 4, "A": 7, "Z": 0,
}

DEFAULT_TOLERANCE = 0.05


def tokenize_path(d: str) -> list[str]:
    return _TOKEN.findall(d or "")


def _flatten_cubic(
    out: Ring, x0: float, y0: float, x1: float, y1: float,
    x2: float, y2: float, x3: float, y3: float, tol: float, depth: int = 0,
) -> None:
    """Append the cubic's interior points to `out`; the endpoint is added by
    the caller so that shared endpoints are never duplicated."""
    if depth >= 20:
        out.append((x3, y3))
        return
    # Flatness: how far the control points stray from the chord. d1 and d2 are
    # cross products, so each is (distance from chord) * (chord length); the
    # test is therefore squared on both sides against tol * chord length, which
    # makes `tol` a true distance in user units.
    dx = x3 - x0
    dy = y3 - y0
    d1 = abs((x1 - x3) * dy - (y1 - y3) * dx)
    d2 = abs((x2 - x3) * dy - (y2 - y3) * dx)
    span = dx * dx + dy * dy
    if span > 0.0:
        if (d1 + d2) ** 2 <= tol * tol * span:
            out.append((x3, y3))
            return
    else:
        # Endpoints coincide, so there is no chord to measure against; fall
        # back to how far the control points reach.
        spread = max(abs(x1 - x0), abs(y1 - y0), abs(x2 - x0), abs(y2 - y0))
        if spread <= tol:
            out.append((x3, y3))
            return
    x01, y01 = (x0 + x1) / 2, (y0 + y1) / 2
    x12, y12 = (x1 + x2) / 2, (y1 + y2) / 2
    x23, y23 = (x2 + x3) / 2, (y2 + y3) / 2
    xa, ya = (x01 + x12) / 2, (y01 + y12) / 2
    xb, yb = (x12 + x23) / 2, (y12 + y23) / 2
    xm, ym = (xa + xb) / 2, (ya + yb) / 2
    _flatten_cubic(out, x0, y0, x01, y01, xa, ya, xm, ym, tol, depth + 1)
    _flatten_cubic(out, xm, ym, xb, yb, x23, y23, x3, y3, tol, depth + 1)


def _quad_to_cubic(
    x0: float, y0: float, cx: float, cy: float, x1: float, y1: float,
) -> tuple[float, float, float, float]:
    return (
        x0 + 2.0 / 3.0 * (cx - x0), y0 + 2.0 / 3.0 * (cy - y0),
        x1 + 2.0 / 3.0 * (cx - x1), y1 + 2.0 / 3.0 * (cy - y1),
    )


def _flatten_arc(
    out: Ring, x0: float, y0: float, rx: float, ry: float, rotation: float,
    large_arc: bool, sweep: bool, x1: float, y1: float, tol: float,
) -> None:
    """Endpoint-parameterised arc -> centre parameterisation -> polyline.

    Follows the out-of-range radii correction in SVG 1.1 Appendix F.6.6.
    """
    if rx == 0.0 or ry == 0.0 or (x0 == x1 and y0 == y1):
        out.append((x1, y1))
        return
    rx, ry = abs(rx), abs(ry)
    phi = math.radians(rotation)
    cos_p, sin_p = math.cos(phi), math.sin(phi)

    dx2, dy2 = (x0 - x1) / 2.0, (y0 - y1) / 2.0
    x1p = cos_p * dx2 + sin_p * dy2
    y1p = -sin_p * dx2 + cos_p * dy2

    # Scale up radii that are too small to span the chord.
    lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
    if lam > 1.0:
        s = math.sqrt(lam)
        rx *= s
        ry *= s

    denom = rx * rx * y1p * y1p + ry * ry * x1p * x1p
    num = rx * rx * ry * ry - denom
    coef = math.sqrt(max(0.0, num / denom)) if denom else 0.0
    if large_arc == sweep:
        coef = -coef
    cxp = coef * rx * y1p / ry
    cyp = -coef * ry * x1p / rx

    cx = cos_p * cxp - sin_p * cyp + (x0 + x1) / 2.0
    cy = sin_p * cxp + cos_p * cyp + (y0 + y1) / 2.0

    def angle_of(ux: float, uy: float) -> float:
        return math.atan2(uy, ux)

    theta1 = angle_of((x1p - cxp) / rx, (y1p - cyp) / ry)
    theta2 = angle_of((-x1p - cxp) / rx, (-y1p - cyp) / ry)
    delta = theta2 - theta1
    if sweep and delta < 0:
        delta += 2 * math.pi
    elif not sweep and delta > 0:
        delta -= 2 * math.pi

    # Segment count from the sagitta of each step against the tolerance.
    r_max = max(rx, ry)
    if r_max <= tol:
        steps = 1
    else:
        max_step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tol / r_max)))
        steps = max(1, int(math.ceil(abs(delta) / max(max_step, 1e-6))))
    steps = min(steps, 512)

    for i in range(1, steps + 1):
        t = theta1 + delta * (i / steps)
        ex = rx * math.cos(t)
        ey = ry * math.sin(t)
        out.append((cos_p * ex - sin_p * ey + cx, sin_p * ex + cos_p * ey + cy))


def path_to_rings(d: str, tolerance: float = DEFAULT_TOLERANCE) -> list[Ring]:
    """Flatten path data into closed rings.

    Open subpaths are closed implicitly, which is how SVG fills them. Subpaths
    with fewer than three distinct points carry no area and are dropped.
    """
    tokens = tokenize_path(d)
    rings: list[Ring] = []
    current: Ring = []
    i = 0
    cx = cy = 0.0        # current point
    sx = sy = 0.0        # subpath start
    last_cubic: Point | None = None
    last_quad: Point | None = None
    command = ""

    def finish() -> None:
        nonlocal current
        if len(current) >= 3:
            # Drop a duplicated closing point.
            if (abs(current[0][0] - current[-1][0]) < 1e-12
                    and abs(current[0][1] - current[-1][1]) < 1e-12):
                current = current[:-1]
            if len(current) >= 3:
                rings.append(current)
        current = []

    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            command = tok
            i += 1
            if command in ("Z", "z"):
                finish()
                cx, cy = sx, sy
                last_cubic = last_quad = None
                continue
        elif not command:
            break
        else:
            # Repeated coordinate set: M/m implicitly becomes L/l.
            if command == "M":
                command = "L"
            elif command == "m":
                command = "l"

        upper = command.upper()
        need = _ARG_COUNT.get(upper, 0)
        if i + need > len(tokens):
            break
        rel = command.islower()

        # Bail out rather than raise if a command is short of arguments or the
        # next token is another command letter. Path data arrives from files we
        # did not write, and prose can tokenise into command letters, so bad
        # input has to degrade to "no rings" instead of taking the request down.
        chunk = tokens[i:i + need]
        if len(chunk) < need or any(t.isalpha() for t in chunk):
            break
        try:
            args = [float(t) for t in chunk]
        except ValueError:
            break
        i += need

        if upper == "M":
            finish()
            nx, ny = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            cx, cy = nx, ny
            sx, sy = nx, ny
            current = [(cx, cy)]
            last_cubic = last_quad = None
            continue

        if not current:
            current = [(cx, cy)]

        if upper == "L":
            cx, cy = (cx + args[0], cy + args[1]) if rel else (args[0], args[1])
            current.append((cx, cy))
            last_cubic = last_quad = None
        elif upper == "H":
            cx = cx + args[0] if rel else args[0]
            current.append((cx, cy))
            last_cubic = last_quad = None
        elif upper == "V":
            cy = cy + args[0] if rel else args[0]
            current.append((cx, cy))
            last_cubic = last_quad = None
        elif upper == "C":
            if rel:
                x1, y1, x2, y2, x3, y3 = (
                    cx + args[0], cy + args[1], cx + args[2],
                    cy + args[3], cx + args[4], cy + args[5],
                )
            else:
                x1, y1, x2, y2, x3, y3 = args
            _flatten_cubic(current, cx, cy, x1, y1, x2, y2, x3, y3, tolerance)
            last_cubic = (x2, y2)
            last_quad = None
            cx, cy = x3, y3
        elif upper == "S":
            if rel:
                x2, y2, x3, y3 = cx + args[0], cy + args[1], cx + args[2], cy + args[3]
            else:
                x2, y2, x3, y3 = args
            if last_cubic is None:
                x1, y1 = cx, cy
            else:
                x1, y1 = 2 * cx - last_cubic[0], 2 * cy - last_cubic[1]
            _flatten_cubic(current, cx, cy, x1, y1, x2, y2, x3, y3, tolerance)
            last_cubic = (x2, y2)
            last_quad = None
            cx, cy = x3, y3
        elif upper == "Q":
            if rel:
                qx, qy, x3, y3 = cx + args[0], cy + args[1], cx + args[2], cy + args[3]
            else:
                qx, qy, x3, y3 = args
            x1, y1, x2, y2 = _quad_to_cubic(cx, cy, qx, qy, x3, y3)
            _flatten_cubic(current, cx, cy, x1, y1, x2, y2, x3, y3, tolerance)
            last_quad = (qx, qy)
            last_cubic = None
            cx, cy = x3, y3
        elif upper == "T":
            if rel:
                x3, y3 = cx + args[0], cy + args[1]
            else:
                x3, y3 = args[0], args[1]
            if last_quad is None:
                qx, qy = cx, cy
            else:
                qx, qy = 2 * cx - last_quad[0], 2 * cy - last_quad[1]
            x1, y1, x2, y2 = _quad_to_cubic(cx, cy, qx, qy, x3, y3)
            _flatten_cubic(current, cx, cy, x1, y1, x2, y2, x3, y3, tolerance)
            last_quad = (qx, qy)
            last_cubic = None
            cx, cy = x3, y3
        elif upper == "A":
            rx, ry, rot, laf, sf = args[0], args[1], args[2], args[3], args[4]
            if rel:
                x3, y3 = cx + args[5], cy + args[6]
            else:
                x3, y3 = args[5], args[6]
            _flatten_arc(current, cx, cy, rx, ry, rot, laf != 0, sf != 0, x3, y3, tolerance)
            last_cubic = last_quad = None
            cx, cy = x3, y3

    finish()
    return rings


def _num(attrs: dict[str, str], name: str, default: float = 0.0) -> float:
    raw = attrs.get(name)
    if raw is None:
        return default
    match = re.match(r"\s*([-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?)", raw)
    return float(match.group(1)) if match else default


def _points(raw: str | None) -> Ring:
    if not raw:
        return []
    nums = [float(v) for v in re.findall(
        r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", raw)]
    return [(nums[i], nums[i + 1]) for i in range(0, len(nums) - 1, 2)]


def _rounded_rect(
    x: float, y: float, w: float, h: float, rx: float, ry: float, tol: float,
) -> Ring:
    ring: Ring = []
    ring.append((x + rx, y))
    ring.append((x + w - rx, y))
    _flatten_arc(ring, x + w - rx, y, rx, ry, 0, False, True, x + w, y + ry, tol)
    ring.append((x + w, y + h - ry))
    _flatten_arc(ring, x + w, y + h - ry, rx, ry, 0, False, True, x + w - rx, y + h, tol)
    ring.append((x + rx, y + h))
    _flatten_arc(ring, x + rx, y + h, rx, ry, 0, False, True, x, y + h - ry, tol)
    ring.append((x, y + ry))
    _flatten_arc(ring, x, y + ry, rx, ry, 0, False, True, x + rx, y, tol)
    return ring


def shape_to_rings(
    tag: str, attrs: dict[str, str], tolerance: float = DEFAULT_TOLERANCE,
) -> list[Ring]:
    """Reduce any SVG geometry element to closed rings in its own user space."""
    tag = tag.rsplit("}", 1)[-1]
    if tag == "path":
        return path_to_rings(attrs.get("d", ""), tolerance)
    if tag == "rect":
        x, y = _num(attrs, "x"), _num(attrs, "y")
        w, h = _num(attrs, "width"), _num(attrs, "height")
        if w <= 0 or h <= 0:
            return []
        has_rx, has_ry = "rx" in attrs, "ry" in attrs
        rx = _num(attrs, "rx") if has_rx else (_num(attrs, "ry") if has_ry else 0.0)
        ry = _num(attrs, "ry") if has_ry else (_num(attrs, "rx") if has_rx else 0.0)
        rx, ry = min(rx, w / 2), min(ry, h / 2)
        if rx > 0 and ry > 0:
            return [_rounded_rect(x, y, w, h, rx, ry, tolerance)]
        return [[(x, y), (x + w, y), (x + w, y + h), (x, y + h)]]
    if tag in ("circle", "ellipse"):
        cx, cy = _num(attrs, "cx"), _num(attrs, "cy")
        if tag == "circle":
            rx = ry = _num(attrs, "r")
        else:
            rx, ry = _num(attrs, "rx"), _num(attrs, "ry")
        if rx <= 0 or ry <= 0:
            return []
        r_max = max(rx, ry)
        max_step = 2.0 * math.acos(max(-1.0, min(1.0, 1.0 - tolerance / r_max)))
        steps = max(8, min(1024, int(math.ceil(2 * math.pi / max(max_step, 1e-6)))))
        return [[
            (cx + rx * math.cos(2 * math.pi * i / steps),
             cy + ry * math.sin(2 * math.pi * i / steps))
            for i in range(steps)
        ]]
    if tag in ("polygon", "polyline"):
        pts = _points(attrs.get("points"))
        return [pts] if len(pts) >= 3 else []
    if tag == "line":
        return []  # No area to fill.
    return []


def ring_area(ring: Sequence[Point]) -> float:
    """Signed shoelace area; positive means clockwise with y pointing down."""
    n = len(ring)
    if n < 3:
        return 0.0
    total = 0.0
    px, py = ring[-1]
    for x, y in ring:
        total += px * y - x * py
        px, py = x, y
    return total / 2.0


def rings_bbox(rings: Iterable[Sequence[Point]]) -> tuple[float, float, float, float]:
    min_x = min_y = math.inf
    max_x = max_y = -math.inf
    for ring in rings:
        for x, y in ring:
            min_x = min(min_x, x)
            min_y = min(min_y, y)
            max_x = max(max_x, x)
            max_y = max(max_y, y)
    return (min_x, min_y, max_x, max_y)


def ring_centroid(ring: Sequence[Point]) -> Point:
    area = ring_area(ring)
    if abs(area) < 1e-12:
        min_x, min_y, max_x, max_y = rings_bbox([ring])
        return ((min_x + max_x) / 2, (min_y + max_y) / 2)
    cx = cy = 0.0
    px, py = ring[-1]
    for x, y in ring:
        f = px * y - x * py
        cx += (px + x) * f
        cy += (py + y) * f
        px, py = x, y
    return (cx / (6 * area), cy / (6 * area))
