"""Places: landscapes and landmarks."""
from __future__ import annotations

import math

from . import Geo, Panel, hsb, scene


def _noise(*k: int) -> float:
    """Deterministic 0..1 per cell, so the scenery is the same every loop."""
    h = 2166136261
    for v in k:
        h = ((h ^ (v & 0xFFFF)) * 16777619) & 0xFFFFFFFF
    return (h % 1000) / 999.0


@scene("multnomah_falls", "Multnomah Falls", "Oregon's two-tier waterfall: water pours down the middle of a mossy basalt cliff, "
       "the Benson Bridge crosses it part way down, and mist breathes over the pool at the bottom.",
       tags=("place", "water", "oregon"), params={"period_s": 3.0, "width": 2},
       param_docs={"period_s": "seconds for the water to travel top to bottom", "width": "waterfall width in panels (1-3)"})
def multnomah_falls(geo: Geo, period_s: float = 3.0, width: int = 2):
    width = max(1, min(3, int(width)))
    left = (geo.ncols - width) // 2
    falls_cols = set(range(left, left + width))
    top, rows = geo.nrows - 1, geo.nrows
    bridge_row = 1 if rows >= 4 else (rows // 2 if rows >= 3 else -1)     # upper falls, bridge, lower falls, pool
    mist_period = period_s * 2
    loop = mist_period

    def fn(t: float, p: Panel):
        r, c = p.row, p.col
        in_falls = c in falls_cols
        if in_falls and r == bridge_row:
            return hsb(210, 10, 62)                                          # the bridge deck, in front of the water
        if r == bridge_row and (c == left - 1 or c == left + width):
            return hsb(30, 15, 34)                                           # stone footings either end
        if in_falls:
            lane = (c - left) / max(1, width - 1) if width > 1 else 0.0
            drop = (top - r) / max(1, top)                                   # 0 at the lip .. 1 at the pool
            band = 0.5 * (1 + math.cos(2 * math.pi * (t / period_s - drop * 1.4 - 0.35 * lane)))
            lip = 1.0 if r == top else 0.0
            return hsb(200, 22 - 10 * lip - 6 * band, 60 + 38 * band ** 1.5 + 8 * lip)
        if r == 0 and abs(c - (left + (width - 1) / 2)) <= width / 2 + 1.1:
            breath = 0.5 * (1 + math.sin(2 * math.pi * t / mist_period - 0.4 * abs(c - left)))
            return hsb(195, 25, 22 + 26 * breath)                            # mist rolling off the pool
        n = _noise(r, c)
        if n > 0.82:
            return hsb(25, 12, 15)                                            # bare basalt showing through the moss
        edge = min(c, geo.ncols - 1 - c) / max(1, geo.ncols / 2)              # darker toward the sides
        return hsb(128 + 14 * n, 75, 14 + 16 * n + 8 * edge + (5 if r == top else 0))
    return fn, loop
