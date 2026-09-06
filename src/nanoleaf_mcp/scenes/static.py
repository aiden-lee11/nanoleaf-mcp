"""Static designs (time-independent). Saved as static effects; `t` is ignored."""
from __future__ import annotations

from . import Geo, Panel, hsb, scene, to_rgb


@scene("gem_mosaic", "Gem Mosaic", "Stained-glass mosaic lit from the centre: a gold keystone, then mirrored pairs of jewel tones outward, fading toward the edges; down-pointing panels are darker facets.",
       tags=("static", "design"), static=True, params={"falloff": 0.5}, param_docs={"falloff": "how much darker the edges are (0-0.8)"})
def gem_mosaic(geo: Geo, falloff: float = 0.5):
    jewels = [(44, 90, 100), (278, 88, 100), (350, 100, 100), (152, 95, 100), (224, 100, 100), (28, 100, 100), (188, 92, 100), (340, 100, 100)]
    mid = (geo.ncols - 1) / 2

    def fn(t: float, p: Panel):
        d = abs(p.col - mid)
        k = int(round(d / 2)) + (p.row % 2)
        h, s, b = jewels[k % len(jewels)]
        glow = 1.0 - falloff * (abs(p.u - 0.5) * 2) ** 1.3
        facet = 1.0 if p.up else 0.82
        return hsb(h, s, max(15, min(100, b * glow * facet)))
    return fn, 0.0


@scene("spectrum_facets", "Spectrum Facets", "A left-to-right spectrum where every down-pointing panel is a darker facet, so the row reads as cut glass.",
       tags=("static", "design"), static=True, params={"colors": ["#ff00ff", "#ff0000", "#ffaa00", "#00ff40", "#00aaff"]},
       param_docs={"colors": "gradient stops left to right"})
def spectrum_facets(geo: Geo, colors=("#ff00ff", "#ff0000", "#ffaa00", "#00ff40", "#00aaff")):
    stops = [to_rgb(c) for c in colors]

    def fn(t: float, p: Panel):
        x = p.u * (len(stops) - 1)
        i = min(len(stops) - 2, int(x)); f = x - i
        r, g, b = (stops[i][k] + (stops[i + 1][k] - stops[i][k]) * f for k in range(3))
        dim = 1.0 if p.up else 0.7
        return (int(r * dim), int(g * dim), int(b * dim))
    return fn, 0.0


@scene("stained_glass", "Stained Glass", "Jewel-toned panes with the panel gaps as lead lines. 'rose' radiates rings from the centre; 'mosaic' colours the panes so no neighbours match. Slow sunlight drifts across the glass.",
       tags=("design", "ambient"), loop=True,
       params={"style": "rose", "colors": ["#c8102e", "#0033a0", "#f5b800", "#00843d", "#6a1b9a", "#ff6f00", "#00a3e0"],
               "sunlight": True, "period_s": 24.0, "segments": 6},
       param_docs={"style": "rose | mosaic", "colors": "pane colours (jewel tones work best)", "sunlight": "animate light drifting across",
                   "period_s": "seconds for the sunlight to cross", "segments": "rose window: wedges around the centre"})
def stained_glass(geo: Geo, style: str = "rose", colors=("#c8102e", "#0033a0", "#f5b800", "#00843d", "#6a1b9a", "#ff6f00", "#00a3e0"),
                  sunlight: bool = True, period_s: float = 24.0, segments: int = 6):
    import math
    from . import H
    panes = [to_rgb(c) for c in colors]
    n = len(panes)
    cx, cy = (geo.x0 + geo.x1) / 2, (geo.y0 + geo.y1) / 2
    assign: dict[tuple[str, int], int] = {}
    if style == "mosaic":                                  # greedy graph colouring: neighbours never match
        adj = geo.adjacency
        order = sorted(geo.panels, key=lambda p: (-len(adj[p.key]), p.x, p.y))
        used = [0] * n
        for p in order:
            taken = {assign[k] for k in adj[p.key] if k in assign}
            free = [i for i in range(n) if i not in taken] or list(range(n))
            i = min(free, key=lambda i: (used[i], (i * 7 + p.id) % n))
            assign[p.key] = i; used[i] += 1
    else:                                                  # rose window: rings x wedges, gold boss in the centre
        for p in geo.panels:
            d = math.hypot(p.x - cx, p.y - cy)
            ring = int(d / (H * 0.9))
            wedge = int(((math.atan2(p.y - cy, p.x - cx) + math.pi) / (2 * math.pi)) * segments) % max(1, segments)
            assign[p.key] = 2 if ring == 0 and d < H * 0.6 else (ring * 2 + (wedge % 2)) % n   # two colours per ring
    thickness = {p.key: 0.78 + 0.22 * (((p.id * 2654435761) % 1000) / 1000) for p in geo.panels}

    def fn(t: float, p: Panel):
        r, g, b = panes[assign[p.key]]
        light = thickness[p.key] * (1.0 if p.up else 0.86)
        if sunlight:
            su = (t / period_s) % 1.3 - 0.15                # a soft beam crossing left to right
            beam = math.exp(-((p.u - su) / 0.22) ** 2)
            clouds = 0.5 + 0.5 * math.sin(2 * math.pi * t / (period_s * 1.7) + p.u * 2)
            light *= 0.55 + 0.45 * (0.6 * beam + 0.4 * clouds)
        return (int(r * light), int(g * light), int(b * light))
    return fn, period_s * 1.7 * 10 if sunlight else 1.0   # sunlight loops when both cycles realign


@scene("heart", "Pixel Heart", "A pixel-art heart. style 'open' leaves the dip between the lobes dark; 'filled' fills it in a darker red and lightens the interior for depth.",
       tags=("static", "design", "pixel"), static=True,
       params={"color": "#ff1e3c", "style": "open", "scale": 1.0},
       param_docs={"color": "heart colour", "style": "open | filled", "scale": "1.0 fills the layout; smaller shrinks the heart"})
def heart(geo: Geo, color: str = "#ff1e3c", style: str = "open", scale: float = 1.0):
    import math
    base = to_rgb(color)
    light = tuple(min(255, int(c * 0.75 + 255 * 0.25)) for c in base)
    dark = tuple(int(c * 0.45) for c in base)
    def inside(u, v):
        x = (u - 0.5) * 2.6 / scale
        y = (v - 0.45) * 2.5 / scale
        return (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0
    lit = {p.key: base for p in geo.panels if inside(p.u, p.v)}
    if geo.nrows == 4 and geo.ncols == 8:                  # hand-tuned for the 4-row-by-8 block
        # a tip at column 3 with both sides running straight up the grid's 60-degree diagonals to the lobes,
        # and a one-panel V dip between the lobes; nothing outside the diagonals
        outline = {(3, 1), (3, 2), (3, 4), (3, 5), (2, 1), (2, 5), (1, 2), (1, 4), (0, 3)}
        interior = {(2, 2), (2, 3), (2, 4), (1, 3)}
        dip = {(3, 3)}
        lit = {}
        for p in geo.panels:
            cell = (p.row, p.col)
            if cell in outline:
                lit[p.key] = base
            elif cell in interior:
                lit[p.key] = light if style == "filled" else base
            elif cell in dip and style == "filled":
                lit[p.key] = dark

    def fn(t: float, p: Panel):
        return lit.get(p.key, (0, 0, 0))
    return fn, 0.0


# ---------------------------------------------------------------- pixel art on the 4-row block -------------------
# Designs drawn on a 4-row-by-8 triangle grid, (row, col) from the bottom-left. Row parity matters: even rows have
# up-pointing panels in even columns, odd rows in odd columns, which is what makes ears, peaks and tips work.
PIXEL_ART: dict[str, dict] = {
    "fox": {"title": "Fox", "cells": {
        (3, 1): "#ff7a1a", (3, 5): "#ff7a1a",                                        # ears (pointing up)
        (3, 2): "#ff7a1a", (3, 4): "#ff7a1a",
        (2, 0): "#ff7a1a", (2, 1): "#ff7a1a", (2, 2): "#1a1a2e", (2, 3): "#ff7a1a", (2, 4): "#1a1a2e", (2, 5): "#ff7a1a", (2, 6): "#ff7a1a",   # eyes dark
        (1, 1): "#fff4e6", (1, 2): "#ff7a1a", (1, 3): "#fff4e6", (1, 4): "#ff7a1a", (1, 5): "#fff4e6",   # white cheeks and snout
        (0, 3): "#111111"}},                                                          # nose
    "tree": {"title": "Christmas Tree", "cells": {
        (3, 3): "#ffd200",                                                            # star
        (2, 2): "#1f8a3a", (2, 3): "#ffd200", (2, 4): "#1f8a3a",
        (1, 1): "#1f8a3a", (1, 2): "#e5232e", (1, 3): "#1f8a3a", (1, 4): "#e5232e", (1, 5): "#1f8a3a",
        (0, 3): "#7a4a1e"}},                                                          # trunk
    "star": {"title": "Six-pointed Star", "cells": {c: "#ffd54a" for c in
        [(1, 3), (1, 4), (1, 5), (2, 3), (2, 4), (2, 5),                              # hexagon core
         (0, 4), (3, 4), (1, 2), (2, 2), (1, 6), (2, 6)]}},                           # six points
    "bolt": {"title": "Lightning Bolt", "cells": {c: "#ffe600" for c in
        [(3, 5), (3, 6), (2, 4), (2, 5), (1, 2), (1, 3), (1, 4), (1, 5), (0, 3)]}},
    "mountains": {"title": "Mountains and Sun", "cells": {
        (3, 1): "#ffffff", (3, 5): "#ffffff", (3, 3): "#ffb300",                       # snow peaks, sun
        (2, 0): "#6e7b8b", (2, 1): "#6e7b8b", (2, 2): "#6e7b8b", (2, 4): "#6e7b8b", (2, 5): "#6e7b8b", (2, 6): "#6e7b8b",
        (2, 3): "#3a4452",
        **{(1, c): "#2e7d32" for c in range(0, 8)}, **{(0, c): "#1b5e20" for c in range(1, 8)}}},
    "butterfly": {"title": "Butterfly", "cells": {
        (3, 3): "#222233", (2, 3): "#222233", (1, 3): "#222233",                       # body
        (3, 2): "#333355", (3, 4): "#333355",                                          # antennae
        (2, 0): "#ff3fa4", (2, 1): "#ff3fa4", (2, 2): "#00c2ff", (2, 4): "#00c2ff", (2, 5): "#ff3fa4", (2, 6): "#ff3fa4",
        (1, 1): "#ff3fa4", (1, 2): "#ff3fa4", (1, 4): "#ff3fa4", (1, 5): "#ff3fa4"}},
    "arrow": {"title": "Arrow Up", "cells": {c: "#00e5ff" for c in
        [(3, 3), (2, 2), (2, 3), (2, 4), (1, 3), (0, 3)]}},
    "cat": {"title": "Cat", "cells": {
        (3, 1): "#8d8d99", (3, 5): "#8d8d99", (3, 2): "#8d8d99", (3, 4): "#8d8d99",
        (2, 0): "#8d8d99", (2, 1): "#8d8d99", (2, 2): "#2bd36b", (2, 3): "#8d8d99", (2, 4): "#2bd36b", (2, 5): "#8d8d99", (2, 6): "#8d8d99",   # green eyes
        (1, 1): "#8d8d99", (1, 2): "#8d8d99", (1, 3): "#ffb6c1", (1, 4): "#8d8d99", (1, 5): "#8d8d99",   # pink nose
        (0, 2): "#8d8d99", (0, 3): "#8d8d99", (0, 4): "#8d8d99"}},                    # chin
    "letter_h": {"title": "Letter H", "cells": {**{(r, c): "#9b30ff" for r in range(4) for c in (1, 5)},   # thin uprights: one column each
                                                **{(r, c): "#9b30ff" for r in (1, 2) for c in (2, 4)}}},      # two-row crossbar, centre column dark
    "house": {"title": "House", "cells": {
        (3, 3): "#c62828", (2, 2): "#c62828", (2, 3): "#c62828", (2, 4): "#c62828",     # roof
        (1, 2): "#f5deb3", (1, 3): "#f5deb3", (1, 4): "#f5deb3",                       # walls
        (0, 2): "#f5deb3", (0, 3): "#5d4037", (0, 4): "#f5deb3",                       # door
        (1, 5): "#ffd54a"}},                                                           # lit window? (outside wall) -> lantern
}


@scene("pixel_art", "Pixel Art", "Hand-drawn pixel art for a 4-row block: fox, cat, christmas tree, six-pointed star, lightning bolt, mountains and sun, butterfly, arrow, house.",
       tags=("static", "design", "pixel"), static=True, params={"design": "fox"},
       param_docs={"design": " | ".join(PIXEL_ART)}, min_rows=4)
def pixel_art(geo: Geo, design: str = "fox"):
    key = design.strip().lower()
    if key not in PIXEL_ART:
        raise ValueError(f"unknown design {design!r}; choose from {', '.join(PIXEL_ART)}")
    cells = PIXEL_ART[key]["cells"]
    lit = {p.key: to_rgb(cells[(p.row, p.col)]) for p in geo.panels if (p.row, p.col) in cells}

    def fn(t: float, p: Panel):
        return lit.get(p.key, (0, 0, 0))
    return fn, 0.0
