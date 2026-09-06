"""Layout-agnostic scenes.

A *scene* is a function ``scene(t, panel) -> colour`` built for a specific :class:`Geo` (the panels it will run
on) by a factory registered with :func:`scene`. ``Geo`` gives every panel normalised coordinates (``u``/``v`` in
0..1), a grid cell (``row``/``col``), whether it points up, which half of its own controller it sits in, and the
edge-adjacency graph, so one scene definition renders on a 12-panel strip, a 30-panel block, or several
controllers placed side by side.

Delivery is separate from authoring. The same scene can be

* sampled into keyframes and saved on the controller (``core.save_scene``: runs with no computer),
* streamed live from the computer (``core.start_live_scene``: exact sync across controllers, any motion),
* previewed in the terminal / as SVG (``core.preview_scene``), or
* mocked on a hypothetical layout you have not built yet (``mock.py``).

Writing a scene::

    from nanoleaf_mcp.scenes import scene, Geo, Panel, hsb

    @scene("pulse", "Pulse", "Everything breathes in one colour.", tags=("ambient",), params={"period_s": 4.0})
    def pulse(geo: Geo, period_s: float = 4.0):
        def fn(t: float, p: Panel):
            return hsb(280, 90, 30 + 60 * (0.5 + 0.5 * math.sin(2 * math.pi * t / period_s)))
        return fn, period_s          # (function, loop length in seconds)

Colours may be ``(r, g, b)`` tuples or any string ``effects.parse_color`` understands.
"""
from __future__ import annotations

import colorsys
import importlib
import math
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from ..effects import hsb_to_rgb, parse_color
from ..render import H, SIDE, oriented_triangles

Colour = "str | tuple[int, int, int]"
SceneFn = Callable[[float, "Panel"], Any]
HALF = SIDE / 2


# ---------------------------------------------------------------- geometry ----------------------------------
@dataclass
class Panel:
    device: str            # device key (or label) the panel belongs to
    id: int                # panelId on that controller
    x: float               # centroid in the shared layout space (Nanoleaf units, side = 150)
    y: float
    up: bool               # triangle points up
    u: float = 0.0         # 0 (left) .. 1 (right) across the whole space
    v: float = 0.0         # 0 (bottom) .. 1 (top)
    row: int = 0           # grid row from the bottom (0-based); rows are H = side*sqrt(3)/2 tall
    col: int = 0           # grid column (half-panel steps) from the left
    top: bool = True       # upper half of its own controller's layout (True everywhere on a one-row layout)
    bottom: bool = True    # lower half of its own controller's layout (True everywhere on a one-row layout)
    rows_in_device: int = 1

    @property
    def key(self) -> tuple[str, int]:
        return (self.device, self.id)


class Geo:
    """Every panel with normalised coordinates plus grid and graph helpers."""

    def __init__(self, panels: list[Panel]):
        if not panels:
            raise ValueError("Geo needs at least one panel")
        self.panels = panels
        xs = [p.x for p in panels]; ys = [p.y for p in panels]
        self.x0, self.x1, self.y0, self.y1 = min(xs), max(xs), min(ys), max(ys)
        self.w, self.h = max(1.0, self.x1 - self.x0), max(1.0, self.y1 - self.y0)
        for p in panels:
            p.u = (p.x - self.x0) / self.w if self.x1 > self.x0 else 0.5
            p.v = (p.y - self.y0) / self.h if self.y1 > self.y0 else 0.0
        self.devices: list[str] = []
        for p in panels:
            if p.device not in self.devices:
                self.devices.append(p.device)
        self.nrows = max(p.row for p in panels) + 1
        self.ncols = max(p.col for p in panels) + 1
        self.by_cell: dict[tuple[int, int], Panel] = {(p.row, p.col): p for p in panels}
        self.cells = set(self.by_cell)
        self.by_key: dict[tuple[str, int], Panel] = {p.key: p for p in panels}
        self._adj: dict[tuple[str, int], list[tuple[str, int]]] | None = None

    # -- lookups -----------------------------------------------------------
    def point(self, u: float, v: float) -> tuple[float, float]:
        return self.x0 + u * self.w, self.y0 + v * self.h

    def nearest(self, u: float, v: float) -> Panel:
        X, Y = self.point(u, v)
        return min(self.panels, key=lambda q: (q.x - X) ** 2 + (q.y - Y) ** 2)

    def blob(self, p: Panel, u: float, v: float, radius: float = 0.6) -> float:
        """0..1 coverage of panel p by a soft dot at normalised (u, v); radius in row heights."""
        X, Y = self.point(u, v)
        return math.exp(-(math.hypot(p.x - X, p.y - Y) / (radius * H)) ** 2)

    def of_device(self, device: str) -> list[Panel]:
        return [p for p in self.panels if p.device == device]

    # -- graph -------------------------------------------------------------
    @property
    def adjacency(self) -> dict[tuple[str, int], list[tuple[str, int]]]:
        """Edge-neighbours (centroids exactly 2H/3 apart) within a controller, plus one bridge edge between the
        closest panels of neighbouring controllers so paths can cross the gap."""
        if self._adj is None:
            adj: dict[tuple[str, int], list[tuple[str, int]]] = {p.key: [] for p in self.panels}
            for a in self.panels:
                for b in self.panels:
                    if a is not b and a.device == b.device and abs(math.hypot(a.x - b.x, a.y - b.y) - 2 * H / 3) < 2:
                        adj[a.key].append(b.key)
            for d1, d2 in zip(self.devices, self.devices[1:]):
                pa, pb = self.of_device(d1), self.of_device(d2)
                a, b = min(((a, b) for a in pa for b in pb), key=lambda ab: math.hypot(ab[0].x - ab[1].x, ab[0].y - ab[1].y))
                adj[a.key].append(b.key); adj[b.key].append(a.key)
            self._adj = adj
        return self._adj

    def longest_path(self, start: tuple[str, int], allowed: set | None = None, target: tuple[str, int] | None = None,
                     budget: int = 60000) -> list[tuple[str, int]]:
        """Warnsdorff-ordered DFS for the longest simple path from start (ending at target if given)."""
        adj = self.adjacency
        allowed = allowed if allowed is not None else set(adj)
        best: list = []
        left = [budget]

        def dfs(path, seen):
            if (target is None or path[-1] == target) and len(path) > len(best):
                best[:] = path
            if len(best) == len(allowed) or left[0] <= 0:
                return
            left[0] -= 1
            nxt = [n for n in adj[path[-1]] if n in allowed and n not in seen]
            nxt.sort(key=lambda n: sum(1 for m in adj[n] if m in allowed and m not in seen))
            for n in nxt:
                seen.add(n); path.append(n); dfs(path, seen); path.pop(); seen.discard(n)
                if len(best) == len(allowed) or left[0] <= 0:
                    return
        dfs([start], {start})
        return best or [start]


ALIGNMENTS = ("top", "bottom", "middle")


def geo_from_layouts(layouts: list[tuple[str, list[dict], float]], gap_widths: float = 2.0, align: str = "top") -> Geo:
    """layouts: [(device, positionData, globalOrientation)] in left-to-right physical order.
    gap_widths: distance between neighbouring controllers in triangle widths. align: how later controllers sit
    vertically relative to the first ('top' edges level, 'bottom', or 'middle')."""
    if align not in ALIGNMENTS:
        raise ValueError(f"align must be one of {ALIGNMENTS}")
    panels: list[Panel] = []
    cursor = 0.0
    ref: tuple[float, float] | None = None
    for device, pos, go in layouts:
        tris = oriented_triangles(pos, go)
        if not tris:
            continue
        vx = [v[0] for t in tris for v in t["verts"]]; vy = [v[1] for t in tris for v in t["verts"]]
        x_min, y_min, y_max = min(vx), min(vy), max(vy)
        if ref is None:
            ref = (y_min, y_max); dy = -y_min
        elif align == "top":
            dy = ref[1] - y_max
        elif align == "bottom":
            dy = ref[0] - y_min
        else:
            dy = (ref[0] + ref[1]) / 2 - (y_min + y_max) / 2
        cys = [t["cy"] for t in tris]
        mid = (max(cys) + min(cys)) / 2
        multi_row = (max(cys) - min(cys)) > H * 0.5
        for t in tris:
            above = sum(1 for v in t["verts"] if v[1] > t["cy"])
            panels.append(Panel(device=device, id=t["id"], x=t["cx"] - x_min + cursor, y=t["cy"] + dy, up=(above == 1),
                                top=(not multi_row) or t["cy"] > mid, bottom=(not multi_row) or t["cy"] <= mid,
                                rows_in_device=int(round((max(cys) - min(cys)) / H)) + 1 if multi_row else 1))
        cursor += (max(vx) - x_min) + gap_widths * SIDE
    # grid cells: rows from the bottom edge of the space, columns in half-panel steps
    bottoms = {}
    for p in panels:
        bottoms[p.key] = p.y - (H / 3 if p.up else 2 * H / 3)
    b0 = min(bottoms.values()); x0 = min(p.x for p in panels)
    for p in panels:
        p.row = int(round((bottoms[p.key] - b0) / H))
        p.col = int(round((p.x - x0) / HALF))
    return Geo(panels)


def make_layout(nrows: int, ncols: int, remove: Iterable[tuple[int, int]] = ()) -> list[dict]:
    """Synthetic positionData: rows of alternating up/down triangles with zigzag sides. remove: (row, col) cells."""
    remove = set(remove)
    pos, pid = [], 1
    for r in range(nrows):
        for k in range(ncols):
            if (r, k) in remove:
                continue
            up = (k % 2 == 0) if r % 2 == 0 else (k % 2 == 1)
            pos.append({"panelId": pid, "x": HALF + HALF * k, "y": r * H + (H / 3 if up else 2 * H / 3),
                        "o": 0 if up else 180, "shapeType": 0})
            pid += 1
    return pos


def parse_layout_spec(spec: str) -> tuple[str, list[dict]]:
    """'4x8' -> 4 rows of 8; '4x8-2' -> minus two opposite corners (bottom-left, top-right); '4x8-l' / '4x8-r' -> minus
    both left / both right corners (a symmetric block); '4x8-4' -> minus all four; '5x6-bl' / '5x6-tr' -> one corner."""
    s = spec.lower().strip()
    base, _, mod = s.partition("-")
    r, _, c = base.partition("x")
    nrows, ncols = int(r), int(c)
    remove: set[tuple[int, int]] = set()
    if mod == "2":
        remove = {(0, 0), (nrows - 1, ncols - 1)}
    elif mod == "bl":
        remove = {(0, 0)}
    elif mod == "tr":
        remove = {(nrows - 1, ncols - 1)}
    elif mod == "l":
        remove = {(0, 0), (nrows - 1, 0)}
    elif mod == "r":
        remove = {(0, ncols - 1), (nrows - 1, ncols - 1)}
    elif mod == "4":
        remove = {(0, 0), (0, ncols - 1), (nrows - 1, 0), (nrows - 1, ncols - 1)}
    elif mod:
        raise ValueError(f"unknown layout modifier {mod!r} (use 2, l, r, 4, bl or tr)")
    pos = make_layout(nrows, ncols, remove)
    what = {"2": "minus two opposite corners", "l": "minus both left corners", "r": "minus both right corners", "4": "minus all four corners",
            "bl": "minus the bottom-left corner", "tr": "minus the top-right corner"}.get(mod, "")
    return f"{nrows} rows of {ncols}" + (f" {what}" if what else "") + f" ({len(pos)} panels)", pos


# ---------------------------------------------------------------- colours -----------------------------------
def hsb(h: float, s: float, b: float) -> tuple[int, int, int]:
    return hsb_to_rgb(int(round(h)) % 360, max(0, min(100, int(round(s)))), max(0, min(100, int(round(b)))))


def mix(a: tuple, b: tuple, f: float) -> tuple[int, int, int]:
    f = max(0.0, min(1.0, f))
    return tuple(int(round(a[i] + (b[i] - a[i]) * f)) for i in range(3))  # type: ignore[return-value]


def tri(t: float, period: float) -> float:
    """0 -> 1 -> 0 triangle wave."""
    s = (t % period) / period
    return 2 * s if s < 0.5 else 2 - 2 * s


def to_rgb(c: Any) -> tuple[int, int, int]:
    if isinstance(c, tuple):
        return (max(0, min(255, int(c[0]))), max(0, min(255, int(c[1]))), max(0, min(255, int(c[2]))))
    return hsb_to_rgb(*parse_color(c))


# ---------------------------------------------------------------- registry ----------------------------------
@dataclass
class SceneSpec:
    name: str
    title: str
    description: str
    factory: Callable[..., tuple[SceneFn, float]]
    tags: tuple[str, ...] = ()
    loop: bool = True              # False = one-shot (plays once, holds the last frame)
    static: bool = False           # True = time-independent design (saved as a static effect)
    params: dict[str, Any] = field(default_factory=dict)   # name -> default; documented in `param_docs`
    param_docs: dict[str, str] = field(default_factory=dict)
    min_rows: int = 1              # best on layouts with at least this many rows

    def public(self) -> dict:
        return {"name": self.name, "title": self.title, "description": self.description, "tags": list(self.tags),
                "loop": self.loop, "static": self.static, "min_rows": self.min_rows,
                "params": {k: {"default": v, "doc": self.param_docs.get(k, "")} for k, v in self.params.items()}}


SCENES: dict[str, SceneSpec] = {}


def scene(name: str, title: str, description: str, *, tags: tuple[str, ...] = (), loop: bool = True,
          static: bool = False, params: dict[str, Any] | None = None, param_docs: dict[str, str] | None = None,
          min_rows: int = 1):
    def deco(factory):
        SCENES[name] = SceneSpec(name, title, description, factory, tags, loop, static, dict(params or {}),
                                 dict(param_docs or {}), min_rows)
        return factory
    return deco


def _load_builtin() -> None:
    for mod in ("ambient", "motion", "story", "games", "arcade", "static"):
        importlib.import_module(f"{__name__}.{mod}")


def get(name: str) -> SceneSpec:
    _load_builtin()
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in SCENES:
        return SCENES[key]
    hits = [s for s in SCENES.values() if key in s.name or key in s.title.lower().replace(" ", "_")]
    if len(hits) == 1:
        return hits[0]
    raise LookupError(f"unknown scene {name!r}; available: {', '.join(sorted(SCENES))}")


def list_scenes() -> list[dict]:
    _load_builtin()
    return [s.public() for s in SCENES.values()]


def build(name: str, geo: Geo, params: dict[str, Any] | None = None) -> tuple[SceneFn, float, SceneSpec]:
    """Instantiate a scene for a Geo. Returns (fn, duration_s, spec)."""
    spec = get(name)
    kwargs = dict(spec.params)
    for k, v in (params or {}).items():
        if k not in spec.params:
            raise ValueError(f"{spec.name} has no parameter {k!r}; valid: {sorted(spec.params) or 'none'}")
        kwargs[k] = v
    fn, duration = spec.factory(geo, **kwargs)
    return fn, float(duration), spec


# ---------------------------------------------------------------- sampling ----------------------------------
def sample_keyframes(geo: Geo, fn: SceneFn, duration_s: float, step_tenths: int = 1, quant: int = 12,
                     min_delta: int = 20) -> dict[str, dict[int, list[dict]]]:
    """Sample fn every step_tenths (tenths of a second) into per-device keyframes
    {device: {panelId: [{"color": "rgb(r,g,b)", "transition": tenths}, ...]}}, merging runs of identical colour.
    Colour channels are rounded to multiples of `quant` first so near-identical samples merge (12 is invisible)."""
    steps = max(1, int(round(duration_s * 10 / step_tenths)))
    out: dict[str, dict[int, list[dict]]] = {}
    q = max(1, quant)
    for p in geo.panels:
        runs: list[list] = []                      # [colour, ticks, rgb] for each run of (nearly) identical colour
        for k in range(steps):
            rgb = to_rgb(fn(k * step_tenths / 10, p))
            # hysteresis: a slowly drifting colour only starts a new keyframe once it has moved by min_delta on
            # some channel, otherwise gentle gradients dither between two rounded values several times a second
            if runs and max(abs(rgb[i] - runs[-1][2][i]) for i in range(3)) < min_delta:
                runs[-1][1] += step_tenths
                continue
            r, g, b = rgb
            col = f"rgb({int(round(r / q)) * q},{int(round(g / q)) * q},{int(round(b / q)) * q})"
            if runs and runs[-1][0] == col:
                runs[-1][1] += step_tenths
            else:
                runs.append([col, step_tenths, rgb])
        # A keyframe's time is how long the panel takes to FADE INTO its colour. So a run of N ticks becomes a quick
        # fade in (one tick) followed by a hold (a keyframe of the same colour lasting the rest); one keyframe with
        # the whole run length would smear every change into a slow fade.
        seq = out.setdefault(p.device, {}).setdefault(p.id, [])
        for col, ticks, _ in runs:
            seq.append({"color": col, "transition": step_tenths})
            if ticks > step_tenths:
                seq.append({"color": col, "transition": ticks - step_tenths})
    return out


def colours_at(geo: Geo, fn: SceneFn, t: float) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for p in geo.panels:
        r, g, b = to_rgb(fn(t, p))
        out.setdefault(p.device, {})[p.id] = f"#{r:02x}{g:02x}{b:02x}"
    return out
