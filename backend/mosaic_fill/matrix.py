"""2-D affine transforms in SVG's ``matrix(a b c d e f)`` ordering."""

from __future__ import annotations

import math
import re
from typing import Sequence

Matrix = tuple[float, float, float, float, float, float]
Point = tuple[float, float]

IDENTITY: Matrix = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def multiply(m: Matrix, n: Matrix) -> Matrix:
    return (
        m[0] * n[0] + m[2] * n[1],
        m[1] * n[0] + m[3] * n[1],
        m[0] * n[2] + m[2] * n[3],
        m[1] * n[2] + m[3] * n[3],
        m[0] * n[4] + m[2] * n[5] + m[4],
        m[1] * n[4] + m[3] * n[5] + m[5],
    )


def translate(tx: float, ty: float) -> Matrix:
    return (1.0, 0.0, 0.0, 1.0, tx, ty)


def scale(sx: float, sy: float | None = None) -> Matrix:
    return (sx, 0.0, 0.0, sx if sy is None else sy, 0.0, 0.0)


def rotate(degrees: float, cx: float = 0.0, cy: float = 0.0) -> Matrix:
    r = math.radians(degrees)
    cos, sin = math.cos(r), math.sin(r)
    m: Matrix = (cos, sin, -sin, cos, 0.0, 0.0)
    if cx == 0.0 and cy == 0.0:
        return m
    return multiply(translate(cx, cy), multiply(m, translate(-cx, -cy)))


def apply_to_point(m: Matrix, x: float, y: float) -> Point:
    return (m[0] * x + m[2] * y + m[4], m[1] * x + m[3] * y + m[5])


def transform_ring(m: Matrix, ring: Sequence[Point]) -> list[Point]:
    a, b, c, d, e, f = m
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in ring]


_FUNC = re.compile(r"([a-zA-Z]+)\s*\(([^)]*)\)")
_NUM = re.compile(r"[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?")


def parse_transform(value: str | None) -> Matrix:
    """Parse a `transform` attribute. Unrecognised functions are skipped so an
    exotic attribute degrades to no transform rather than failing the upload."""
    if not value:
        return IDENTITY
    result = IDENTITY
    for name, raw_args in _FUNC.findall(value):
        args = [float(v) for v in _NUM.findall(raw_args)]
        key = name.lower()
        m: Matrix | None = None
        if key == "matrix" and len(args) >= 6:
            m = (args[0], args[1], args[2], args[3], args[4], args[5])
        elif key == "translate" and args:
            m = translate(args[0], args[1] if len(args) > 1 else 0.0)
        elif key == "scale" and args:
            m = scale(args[0], args[1] if len(args) > 1 else args[0])
        elif key == "rotate" and args:
            m = rotate(args[0], args[1], args[2]) if len(args) >= 3 else rotate(args[0])
        elif key == "skewx" and args:
            m = (1.0, 0.0, math.tan(math.radians(args[0])), 1.0, 0.0, 0.0)
        elif key == "skewy" and args:
            m = (1.0, math.tan(math.radians(args[0])), 0.0, 1.0, 0.0, 0.0)
        if m is not None:
            result = multiply(result, m)
    return result
