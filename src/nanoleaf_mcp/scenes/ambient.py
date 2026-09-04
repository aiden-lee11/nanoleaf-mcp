"""Ambient scenes: fire, water, colour flows."""
from __future__ import annotations

import math

from . import Geo, Panel, hsb, mix, scene, to_rgb


def _heat_colour(h: float) -> tuple[int, int, int]:
    h = max(0.0, min(1.0, h))
    return hsb(45 * h ** 1.4, 100 - 30 * max(0.0, h - 0.75) / 0.25, 6 + 94 * h ** 0.9)


def ember(x: float, v: float, t: float, loop: float = 8.0, seed: float = 0.0) -> tuple[int, int, int]:
    """Flicker from layered sines whose periods divide the loop, so it wraps seamlessly."""
    w = 2 * math.pi / loop
    p1, p2, p3 = x * 0.021 + seed, x * 0.047 + 1.3 + seed, x * 0.013 + 2.9 + seed
    n = (0.55 * math.sin(2 * w * t + p1) + 0.3 * math.sin(3 * w * t + p2 + v * 2.0)
         + 0.25 * math.sin(5 * w * t + p3) + 0.15 * math.sin(8 * w * t + p1 * 3.1))
    base = 1.05 - 0.75 * v
    return _heat_colour(base + 0.32 * n * (0.6 + 0.8 * v))


@scene("ember_fire", "Ember Fire", "Ambient fire: heat rises from the bottom row, cooler flickering tips above.",
       tags=("ambient", "warm"), params={"loop_s": 8.0}, param_docs={"loop_s": "seconds per seamless loop"})
def ember_fire(geo: Geo, loop_s: float = 8.0):
    def fn(t: float, p: Panel):
        return ember(p.x, p.v, t, loop_s, 0.4)
    return fn, loop_s


@scene("fireplace", "Fireplace", "Logs along the bottom, tongues of flame rising and falling on their own timing, sparks.",
       tags=("ambient", "warm"), params={"loop_s": 8.0}, min_rows=2)
def fireplace(geo: Geo, loop_s: float = 8.0):
    w = 2 * math.pi / loop_s
    n_tongues = max(3, geo.ncols // 2 + 1)
    bases = [(i + 0.5) / n_tongues for i in range(n_tongues)]

    def tongue(i, t):
        u = bases[i] + 0.035 * math.sin(3 * w * t + i * 1.9)
        h = (0.40 + 0.22 * math.sin(2 * w * t + i * 1.7) + 0.16 * math.sin(5 * w * t + i * 0.8)
             + 0.12 * math.sin(7 * w * t + i * 2.6))
        return u, max(0.15, min(0.98, h))

    def fn(t: float, p: Panel):
        if p.row == 0 and geo.nrows > 1:
            glow = 0.5 + 0.5 * math.sin(2 * w * t + p.u * 9) * math.sin(3 * w * t + p.u * 4)
            return hsb(22, 95, 22 + 30 * glow) if p.col % 2 else hsb(30, 85, 14 + 12 * glow)
        heat = 0.0
        for i in range(n_tongues):
            tu, th = tongue(i, t)
            lateral = math.exp(-((p.u - tu) / 0.075) ** 2)
            vertical = 1.0 if p.v <= th else max(0.0, 1.0 - (p.v - th) / 0.16)
            heat += lateral * vertical * (1.0 - 0.3 * p.v)
        heat = min(1.0, heat)
        if ((t * 0.9 + p.id * 0.618) % 1.0) < 0.05 and p.v > 0.45 and heat < 0.5:
            return hsb(45, 70, 100)
        if heat < 0.08:
            return hsb(15, 90, 3 + 30 * heat)
        return hsb(6 + 44 * heat * (1 - 0.45 * p.v), 100 - 30 * max(0.0, heat - 0.8) * 5, 20 + 80 * heat)
    return fn, loop_s


@scene("ocean_wave", "Ocean Wave", "A swell rolls left to right through the water below; foam breaks along the top.",
       tags=("ambient", "water"), params={"period_s": 3.6}, param_docs={"period_s": "seconds per wave pass"})
def ocean_wave(geo: Geo, period_s: float = 3.6):
    wavelength = geo.w * 1.15

    def fn(t: float, p: Panel):
        phase = ((p.x - geo.x0) / wavelength - t / period_s) % 1.0
        swell = 0.5 * (1 + math.cos(2 * math.pi * phase))
        if p.bottom:
            return hsb(210 - 30 * swell, 95 - 25 * swell, 20 + 65 * swell)
        foam = math.exp(-((phase - 0.08) / 0.09) ** 2)
        spray = math.exp(-((phase - 0.25) / 0.12) ** 2) * 0.35
        f = min(1.0, foam + spray)
        return hsb(195, 25 * (1 - f) + 5, 4 + 96 * f)
    return fn, period_s


@scene("crashing_wave", "Crashing Wave", "A swell builds on the left, rolls right and breaks into foam that races along the right-hand side.",
       tags=("ambient", "water", "multi"), params={"period_s": 6.0})
def crashing_wave(geo: Geo, period_s: float = 6.0):
    def fn(t: float, p: Panel):
        phase = (p.u - t / period_s) % 1.0
        swell = 0.5 * (1 + math.cos(2 * math.pi * phase))
        breaking = min(1.0, max(0.0, (p.u - 0.55) / 0.45))
        if p.bottom:
            h, s, b = 210 - 30 * swell, 95 - 25 * swell, 18 + 62 * swell
            if breaking:
                foam = math.exp(-((phase - 0.1) / 0.14) ** 2)
                s, b = s * (1 - foam * breaking), max(b, 100 * foam * breaking)
            return hsb(h, s, b)
        foam = math.exp(-((phase - 0.08) / 0.09) ** 2)
        spray = 0.35 * math.exp(-((phase - 0.25) / 0.12) ** 2)
        f = min(1.0, foam + spray) * (1 - 0.5 * breaking)
        return hsb(195, 25 * (1 - f) + 5, 3 + 97 * f)
    return fn, period_s


@scene("ombre", "Ombre Ring", "A seamless blend through your colours scrolling left to right and wrapping around, like a ring buffer.",
       tags=("ambient", "colour", "multi"), params={"colors": ["#ff3cac", "#784ba0", "#2b86c5"], "period_s": 8.0, "span": 0.85},
       param_docs={"colors": "2+ colours (names, #hex, rgb(), hsb())", "period_s": "seconds per full cycle",
                   "span": "fraction of one colour cycle visible across the whole wall"})
def ombre(geo: Geo, colors=("#ff3cac", "#784ba0", "#2b86c5"), period_s: float = 8.0, span: float = 0.85):
    rgb = [to_rgb(c) for c in colors]
    n = len(rgb)
    if n < 2:
        raise ValueError("ombre needs at least two colours")

    def fn(t: float, p: Panel):
        u = (p.u * span - t / period_s) % 1.0
        i = int(u * n) % n
        f = u * n - int(u * n)
        f = f * f * (3 - 2 * f)
        return mix(rgb[i], rgb[(i + 1) % n], f)
    return fn, period_s


@scene("rainbow", "Rainbow Scroll", "The full spectrum scrolling left to right.", tags=("ambient", "colour", "multi"),
       params={"period_s": 8.0, "span": 0.85})
def rainbow(geo: Geo, period_s: float = 8.0, span: float = 0.85):
    def fn(t: float, p: Panel):
        return hsb(((p.u * span - t / period_s) % 1.0) * 360, 100, 100)
    return fn, period_s


@scene("breathe", "Breathe", "Slow, dim glows drifting in and out of near-black. A bedtime scene.",
       tags=("ambient", "sleep"), params={"colors": ["hsb(268,100,18)", "hsb(255,100,12)", "hsb(290,70,10)"], "period_s": 14.0},
       param_docs={"colors": "the dim glow colours (keep brightness low)", "period_s": "seconds per breath"})
def breathe(geo: Geo, colors=("hsb(268,100,18)", "hsb(255,100,12)", "hsb(290,70,10)"), period_s: float = 14.0):
    rgb = [to_rgb(c) for c in colors]
    loop = period_s * 3

    def fn(t: float, p: Panel):
        c = rgb[(p.id * 7 + int(t / loop)) % len(rgb)]
        phase = (t / period_s + (p.id * 0.618) % 1.0) % 1.0
        amt = max(0.0, math.sin(math.pi * phase)) ** 2.2
        return mix((2, 0, 4), c, amt)
    return fn, loop


@scene("sweep", "Rainbow Sweep (test)", "A fast rainbow sweep, handy for checking layout order and sync.", tags=("test", "multi"),
       params={"period_s": 3.0})
def sweep(geo: Geo, period_s: float = 3.0):
    def fn(t: float, p: Panel):
        return hsb(((p.u - t / period_s) % 1.0) * 360, 100, 100)
    return fn, period_s
