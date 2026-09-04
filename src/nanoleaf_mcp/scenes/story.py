"""Little stories: characters and scenery."""
from __future__ import annotations

import math

from . import Geo, Panel, hsb, mix, scene, tri


@scene("bunny_hop", "Bunny Hop", "A white bunny hops across a field and back: grass below, sky above, a cloud and a sun.",
       tags=("story", "cute"), params={"loop_s": 8.0, "hop_s": 0.8})
def bunny_hop(geo: Geo, loop_s: float = 8.0, hop_s: float = 0.8):
    hop_rows = max(1, min(2, geo.nrows - 2)) if geo.nrows >= 3 else (1 if geo.nrows == 2 else 0)
    top_row = geo.nrows - 1

    def where(t):
        u = 0.06 + 0.88 * tri(t, loop_s)
        v = (hop_rows / max(1, geo.nrows - 1)) * abs(math.sin(math.pi * t / hop_s)) if geo.nrows > 1 else 0.0
        return u, 0.02 + v

    def fn(t: float, p: Panel):
        here, before = geo.nearest(*where(t)), geo.nearest(*where(t - 0.22))
        if p is here:
            return (255, 250, 235)
        if p is before:
            base = (70, 150, 80) if p.row == 0 else (90, 160, 255)
            return mix(base, (255, 250, 235), 0.4)
        if p.row == 0 and geo.nrows > 1:
            return hsb(125, 75, 55 if p.col % 2 else 68)
        if geo.nrows == 1:
            return hsb(125, 75, 45 if p.col % 2 else 60)
        if p.row == top_row and p.col >= geo.ncols - 2:
            return hsb(45, 90, 100)
        if p.row == top_row and p.col <= 1:
            return hsb(205, 12, 92)
        return hsb(208, 70 - 15 * p.v, 78 + 18 * p.v)
    return fn, loop_s


@scene("tennis_rally", "Tennis Rally", "A ball arcs over the net and back between a red and a green player; the court is below.",
       tags=("story", "sport"), params={"flight_s": 2.6, "rest_s": 0.6})
def tennis_rally(geo: Geo, flight_s: float = 2.6, rest_s: float = 0.6):
    loop = 2 * (flight_s + rest_s)
    net_col = geo.ncols // 2

    def ball(t):
        t %= loop
        legs = [(0.0, flight_s, 0.06, 0.94), (flight_s + rest_s, 2 * flight_s + rest_s, 0.94, 0.06)]
        for t0, t1, ua, ub in legs:
            if t0 <= t < t1:
                s = (t - t0) / (t1 - t0)
                return ua + (ub - ua) * s, 0.04 + 0.92 * 4 * s * (1 - s), s
        return (0.94 if t < flight_s + rest_s else 0.06), 0.04, None

    def fn(t: float, p: Panel):
        bu, bv, s = ball(t)
        bu2, bv2, _ = ball(t - 0.15)
        here, before = geo.nearest(bu, bv), geo.nearest(bu2, bv2)
        if p is here:
            return (220, 255, 0)
        if p is before and s is not None:
            return hsb(70, 60, 40)
        swing = s is not None and (s < 0.12 or s > 0.88)
        lower = p.row <= 1
        if lower and p.col == 0:
            return hsb(15, 100, 100) if swing and bu < 0.5 else hsb(355, 85, 80)
        if lower and p.col == geo.ncols - 1:
            return hsb(25, 100, 100) if swing and bu > 0.5 else hsb(120, 75, 85)
        if p.col == net_col and p.row <= (geo.nrows - 1) // 2:
            return hsb(0, 0, 95)
        if p.row == 0:
            return hsb(215, 85, 75) if 1 < p.col < geo.ncols - 2 else hsb(205, 60, 95)
        return hsb(230, 80, 5)
    return fn, loop


@scene("fish", "Fish Swimming", "An aquarium: three fish at their own depths and speeds (one against the current), seaweed and bubbles.",
       tags=("story", "water"), params={"loop_s": 10.0})
def fish(geo: Geo, loop_s: float = 10.0):
    school = [  # (u0, v, seconds per crossing, direction, body, tail)
        (0.10, 0.70, loop_s, +1, (255, 140, 0), (200, 90, 0)),
        (0.60, 0.42, loop_s / 2, +1, (255, 220, 40), (190, 150, 20)),
        (0.30, 0.58, loop_s / 3, -1, (80, 170, 255), (40, 110, 200)),
    ]
    if geo.nrows == 1:
        school = [(u0, 0.0, T, d, b, tl) for (u0, _, T, d, b, tl) in school]

    def where(i, t):
        u0, v, T, d, *_ = school[i]
        u = (u0 + d * t / T) % 1.16 - 0.08
        return u, v + (0.05 * math.sin(2 * math.pi * t / (T / 2) + i) if geo.nrows > 1 else 0.0)

    def fn(t: float, p: Panel):
        for i, (_, _, T, d, body, tail) in enumerate(school):
            fu, fv = where(i, t)
            if p is geo.nearest(fu, fv):
                return body
            if 0.03 < fu < 0.97 and p is geo.nearest(fu - d * 0.11, fv):
                return tail
        if p.row == 0 and geo.nrows > 1 and p.col % 3 == 1:
            return hsb(140, 85, 45 + 20 * math.sin(2 * math.pi * t / 5 + p.col))
        if p.row > 0 and ((t * 0.45 + p.id * 0.37) % 1.0) < 0.06 and p.col % 4 == 2:
            return hsb(185, 30, 95)
        return hsb(205 - 15 * p.v, 90 - 20 * p.v, 22 + 40 * p.v)
    return fn, loop_s
