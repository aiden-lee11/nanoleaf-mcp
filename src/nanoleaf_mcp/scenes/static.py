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
