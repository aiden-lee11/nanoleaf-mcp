"""Motion scenes: things that travel across the layout."""
from __future__ import annotations

import math
import random

from . import Geo, Panel, hsb, scene


@scene("shooting_star", "Shooting Star", "A white star streaks left to right along the top with a gold-to-ember tail; a dim reflection below.",
       tags=("motion", "night", "multi"), params={"period_s": 4.0}, param_docs={"period_s": "seconds per star"})
def shooting_star(geo: Geo, period_s: float = 4.0):
    def fn(t: float, p: Panel):
        head = ((t % period_s) / period_s) * 1.3 - 0.15
        d = p.u - head
        twinkle = 1.0 if ((t * 0.6 + p.id * 0.37) % 1.0) < 0.04 else 0.0
        if p.top:
            if abs(d) < 0.035:
                return (255, 255, 245)
            if -0.28 < d < 0:
                k = -d / 0.28
                return hsb(48 - 40 * k, 90, 100 * (1 - k) ** 1.6 + 2)
            return hsb(225, 80, 3 + 25 * twinkle)
        return hsb(215, 90, 4 + 30 * math.exp(-(d / 0.09) ** 2))
    return fn, period_s


@scene("rocket_launch", "Rocket Launch", "Countdown on the pad, ignition, then the rocket climbs with a flame tail and smoke while an exhaust cloud rolls along the ground. One-shot.",
       tags=("motion", "story"), loop=False, params={"countdown": 3})
def rocket_launch(geo: Geo, countdown: int = 3):
    SPACE, RED, HEAD = (0, 0, 0), (220, 20, 20), (255, 255, 240)
    FLAME = [(255, 230, 80), (255, 120, 0), (200, 40, 10)]
    SMOKE = [(110, 110, 125), (70, 70, 85), (35, 35, 48), (14, 14, 28)]
    STAR = (140, 150, 200)
    steps: list[tuple[dict, float]] = []          # (overrides by key, seconds)

    def scene_step(over=None, secs=0.1):
        steps.append((dict(over or {}), secs))

    if geo.nrows >= 3:                             # tall layout: straight up the middle column
        mid = (geo.ncols - 1) / 2
        col_keys = [p.key for p in geo.panels if abs(p.col - mid) <= 0.6]
        path = sorted(col_keys, key=lambda k: geo.by_key[k].row)
        pad = path[0]
        ground = [p.key for p in geo.panels if p.row == 0 and p.key != pad]
        plume_dist = {k: abs(geo.by_key[k].col - mid) for k in ground}
    else:                                          # low layout: up from the bottom-left pad, then across the top
        pad = min(geo.panels, key=lambda p: (round(p.x / 20), p.y)).key
        top_row = sorted((p for p in geo.panels if p.top and p.key != pad), key=lambda p: p.x)
        path = [pad] + [p.key for p in top_row]
        ground = [p.key for p in geo.panels if p.bottom and p.key != pad and not p.top]
        plume_dist = {k: (geo.by_key[k].x - geo.by_key[pad].x) / (geo.w / max(1, len(ground))) for k in ground}
    for _ in range(countdown):
        scene_step({pad: RED}, 0.3); scene_step({}, 0.2)
    scene_step({pad: (255, 255, 255)}, 0.1)
    if len(path) > 1:
        scene_step({pad: FLAME[0], path[1]: FLAME[1]}, 0.2)
    n = len(path)
    for k in range(n + len(FLAME) + len(SMOKE)):
        over = {}
        for i, key in enumerate(path):
            d = k - i
            if d == 0: over[key] = HEAD
            elif 1 <= d <= len(FLAME): over[key] = FLAME[d - 1]
            elif len(FLAME) < d <= len(FLAME) + len(SMOKE): over[key] = SMOKE[d - len(FLAME) - 1]
        for key in ground:
            d = k - int(round(plume_dist[key]))
            if 0 <= d < len(SMOKE): over[key] = SMOKE[d]
        scene_step(over, max(0.1, round(0.4 - 0.3 * min(k, n - 1) / max(1, n - 1), 1)))
    rng = random.Random(5)
    sky = [p.key for p in geo.panels if p.top]
    for key in rng.sample(sky, min(3, len(sky))):
        scene_step({}, 0.3); scene_step({key: STAR}, 0.2)
    scene_step({}, 0.5)
    starts, acc = [], 0.0
    for _, secs in steps:
        starts.append(acc); acc += secs
    duration = acc

    def fn(t: float, p: Panel):
        if t >= duration:
            return SPACE
        i = max(0, min(len(steps) - 1, _bisect(starts, t)))
        return steps[i][0].get(p.key, SPACE)
    return fn, duration


def _bisect(starts: list[float], t: float) -> int:
    lo, hi = 0, len(starts)
    while lo < hi:
        m = (lo + hi) // 2
        if starts[m] <= t:
            lo = m + 1
        else:
            hi = m
    return lo - 1


@scene("rain", "Rain", "Drops fall down each column at their own timing and splash on the bottom row.",
       tags=("motion", "weather"), params={"loop_s": 4.0}, min_rows=2)
def rain(geo: Geo, loop_s: float = 4.0):
    def fn(t: float, p: Panel):
        phase = (t * 1.6 + p.col * 0.37) % 1.0
        d = p.v - (1.0 - phase)
        if p.row == 0 and 0.0 < phase < 0.18:
            return hsb(190, 60, 90)
        if 0 <= d < 0.12:
            return hsb(200, 90, 100)
        if 0.12 <= d < 0.4:
            return hsb(210, 90, 70 * (1 - (d - 0.12) / 0.28))
        return hsb(220, 90, 5)
    return fn, loop_s


@scene("gunshot", "Gunshot", "Muzzle flash at the left, a tracer round races left to right along the top and hits the right end with a burst; smoke lingers at the muzzle. Best across two controllers.",
       tags=("motion", "action", "multi"), params={"period_s": 4.0, "travel_s": 0.6},
       param_docs={"period_s": "seconds between shots", "travel_s": "seconds for the round to cross"})
def gunshot(geo: Geo, period_s: float = 4.0, travel_s: float = 0.6):
    from . import H
    v_top = 1.0 if geo.nrows > 1 else 0.0
    t_hit = 0.05 + travel_s
    width_rows = geo.w / H

    def fn(t: float, p: Panel):
        lt = t % period_s
        if lt < 0.12 and p.u < 0.1:                                     # muzzle flash
            return (255, 240, 180) if lt < 0.06 else (255, 160, 40)
        if 0.05 <= lt < t_hit:                                          # tracer with a hot tail
            bu = (lt - 0.05) / travel_s
            if p is geo.nearest(bu, v_top):
                return (255, 255, 220)
            if p is geo.nearest(bu - 0.06, v_top) and bu > 0.06:
                return (255, 200, 80)
            if p is geo.nearest(bu - 0.12, v_top) and bu > 0.12:
                return (200, 90, 20)
        if t_hit <= lt < t_hit + 0.5:                                   # impact burst spreading from the right edge
            f = (lt - t_hit) / 0.5
            d = (1.0 - p.u) * width_rows
            r = 0.5 + 3.5 * f
            if d < r:
                k = min(1.0, d / r)
                base = hsb(40 - 35 * k, 90 + 10 * k, 100 * (1 - f) ** 0.7)
                return base
        if 0.12 <= lt < 2.4 and p.u < 0.14:                             # smoke drifting up at the muzzle
            f = (lt - 0.12) / 2.3
            lift = 0.6 + 0.4 * p.v
            return hsb(0, 0, max(0.0, 42 * (1 - f) * lift))
        if t_hit + 0.5 <= lt < t_hit + 2.0 and p.u > 0.9:               # embers at the impact
            f = (lt - t_hit - 0.5) / 1.5
            return hsb(12, 100, 45 * (1 - f))
        return hsb(230, 40, 3)
    return fn, period_s
