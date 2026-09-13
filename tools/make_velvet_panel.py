#!/usr/bin/env python3
"""Generate samples/Velvet.svg, the reference panel.

STAND-IN. The real Velvet.svg was not available; this reconstructs a panel of
the documented kind - a gown front panel with a shaped hem, a neckline cut out
as a hole, and an id="calib" scale square - so the calibration convention, the
hole handling and the packing benchmark all have something real to run on.

The document is written in CSS pixels (96 per inch, so 3.779528 units per mm)
and carries a 100 mm calibration square, which is the app's default.

Usage:  python tools/make_velvet_panel.py
"""

from __future__ import annotations

import math
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "samples" / "Velvet.svg"

UNITS_PER_MM = 96.0 / 25.4          # 3.779528, CSS pixels
CALIB_MM = 100.0
PANEL_W_MM = 1560.0
PANEL_H_MM = 3260.0
MARGIN_MM = 90.0


def mm(value: float) -> float:
    return value * UNITS_PER_MM


def panel_outline() -> list[tuple[float, float]]:
    """Half-profile mirrored into a closed gown panel.

    The silhouette runs shoulder -> armhole -> waist -> flared hem, which gives
    the packer concave edges and a wide sweep rather than a friendly rectangle.
    """
    cx = PANEL_W_MM / 2
    # (y as a fraction of height, half-width in mm) down the right-hand side.
    profile = [
        (0.000, 250.0),   # shoulder
        (0.045, 292.0),   # shoulder point
        (0.110, 300.0),   # armhole top
        (0.190, 262.0),   # armhole scoop
        (0.270, 250.0),   # underarm
        (0.360, 232.0),   # ribcage
        (0.430, 214.0),   # waist
        (0.500, 236.0),   # high hip
        (0.580, 292.0),   # hip
        (0.680, 396.0),   # flare begins
        (0.790, 540.0),
        (0.890, 676.0),
        (0.960, 754.0),
        (1.000, 780.0),   # hem
    ]

    def sample(t: float) -> float:
        """Catmull-Rom through the profile, so the silhouette is smooth."""
        if t <= profile[0][0]:
            return profile[0][1]
        if t >= profile[-1][0]:
            return profile[-1][1]
        for i in range(len(profile) - 1):
            t0, w0 = profile[i]
            t1, w1 = profile[i + 1]
            if t0 <= t <= t1:
                u = (t - t0) / (t1 - t0)
                wm1 = profile[max(i - 1, 0)][1]
                wp2 = profile[min(i + 2, len(profile) - 1)][1]
                # Catmull-Rom basis.
                return 0.5 * (
                    (2 * w0)
                    + (-wm1 + w1) * u
                    + (2 * wm1 - 5 * w0 + 4 * w1 - wp2) * u * u
                    + (-wm1 + 3 * w0 - 3 * w1 + wp2) * u * u * u
                )
        return profile[-1][1]

    steps = 300
    right = [
        (cx + sample(i / steps), MARGIN_MM + (i / steps) * PANEL_H_MM)
        for i in range(steps + 1)
    ]
    # Hem sweep, then back up the mirrored left side.
    hem_y = MARGIN_MM + PANEL_H_MM
    hem_sag = 46.0
    hem_steps = 80
    hem = [
        (
            cx + sample(1.0) * math.cos(math.pi * i / hem_steps),
            hem_y + hem_sag * math.sin(math.pi * i / hem_steps),
        )
        for i in range(1, hem_steps)
    ]
    left = [(2 * cx - x, y) for x, y in reversed(right)]
    return right + hem + left


def neckline() -> list[tuple[float, float]]:
    """A scooped neckline, wound against the outline so it cuts a hole."""
    cx = PANEL_W_MM / 2
    top = MARGIN_MM - 6.0
    rx, ry = 168.0, 128.0
    steps = 120
    points = [
        (cx + rx * math.cos(math.pi * i / steps), top + ry * math.sin(math.pi * i / steps))
        for i in range(steps + 1)
    ]
    # The outline runs clockwise; reversing this ring makes it counter-clockwise
    # so the nonzero fill rule cuts it out instead of filling it.
    return list(reversed(points))


def to_path(points: list[tuple[float, float]]) -> str:
    coords = [f"{mm(x):.2f},{mm(y):.2f}" for x, y in points]
    return f"M{' L'.join(coords)} Z"


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    width_units = mm(PANEL_W_MM)
    height_units = mm(PANEL_H_MM + 2 * MARGIN_MM + 60)

    outline = panel_outline()
    hole = neckline()

    doc = f"""<?xml version="1.0" encoding="UTF-8"?>
<!-- Reference panel for the embroidery fill app.
     Scale convention: the element with id="calib" is {CALIB_MM:.0f} mm wide.
     Document units are CSS pixels, {UNITS_PER_MM:.6f} per mm. -->
<svg xmlns="http://www.w3.org/2000/svg"
     width="{width_units:.2f}" height="{height_units:.2f}"
     viewBox="0 0 {width_units:.2f} {height_units:.2f}">
  <title>Velvet - gown front panel</title>

  <!-- Scale reference. Real-world width: {CALIB_MM:.0f} mm. -->
  <rect id="calib" x="10" y="10"
        width="{mm(CALIB_MM):.4f}" height="{mm(10):.4f}"
        fill="none" stroke="#c0392b" stroke-width="2"/>

  <path id="panel" fill="#2f2a33" fill-rule="nonzero"
        d="{to_path(outline)} {to_path(hole)}"/>
</svg>
"""
    OUT.write_text(doc, encoding="utf-8")
    area = _area(outline) - _area(hole)
    print(f"wrote {OUT}")
    print(f"  panel  : {PANEL_W_MM:.0f} x {PANEL_H_MM:.0f} mm")
    print(f"  area   : {area / 1e6:.3f} m^2")
    print(f"  units/mm: {UNITS_PER_MM:.6f}")


def _area(ring: list[tuple[float, float]]) -> float:
    total = 0.0
    px, py = ring[-1]
    for x, y in ring:
        total += px * y - x * py
        px, py = x, y
    return abs(total / 2.0)


if __name__ == "__main__":
    main()
