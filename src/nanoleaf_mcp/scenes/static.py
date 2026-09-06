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


@scene("heart", "Pixel Heart", "A pixel-art heart: red with a pink highlight on a dark background.",
       tags=("static", "design", "pixel"), static=True,
       params={"color": "#ff1e3c", "highlight": True, "scale": 1.0},
       param_docs={"color": "heart colour", "highlight": "pink glint on the upper-left lobe", "scale": "1.0 fills the layout; smaller shrinks the heart"})
def heart(geo: Geo, color: str = "#ff1e3c", highlight: bool = True, scale: float = 1.0):
    import math
    base = to_rgb(color)
    pink = tuple(min(255, int(c * 0.55 + 255 * 0.45)) for c in base)
    # implicit heart curve (x^2 + y^2 - 1)^3 - x^2 y^3 <= 0, mapped over the layout's bounding box
    def inside(u, v):
        x = (u - 0.5) * 2.6 / scale
        y = (v - 0.45) * 2.5 / scale
        return (x * x + y * y - 1) ** 3 - x * x * y ** 3 <= 0
    lit = {p.key for p in geo.panels if inside(p.u, p.v)}
    if geo.nrows == 4 and geo.ncols == 8:                  # hand-tuned pixel mask for the 4-row-by-8 block
        mask = {(3, 1), (3, 2), (3, 5), (3, 6), (2, 0), (2, 1), (2, 2), (2, 3), (2, 4), (2, 5), (2, 6), (2, 7),
                (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (0, 3), (0, 4)}
        lit = {p.key for p in geo.panels if (p.row, p.col) in mask}
    glint = None
    if highlight and lit:
        cands = [p for p in geo.panels if p.key in lit and p.u < 0.5]
        glint = max(cands, key=lambda p: p.v - 0.3 * abs(p.u - 0.28)).key if cands else None

    def fn(t: float, p: Panel):
        if p.key == glint:
            return pink
        return base if p.key in lit else (0, 0, 0)
    return fn, 0.0
