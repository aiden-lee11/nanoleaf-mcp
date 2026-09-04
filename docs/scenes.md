# Writing a scene

A scene is a function `fn(t, panel) -> colour`, built for the panels it will run on by a factory you register
with `@scene(...)`. Because it is written against normalised coordinates and grid cells, the same scene runs on a
12-panel strip, a 30-panel block, or two controllers placed side by side, and can be stored on the controller,
streamed live, previewed, or mocked on a layout you haven't built.

```python
# src/nanoleaf_mcp/scenes/mine.py   (add "mine" to _load_builtin() in scenes/__init__.py, or import it yourself)
import math
from nanoleaf_mcp.scenes import scene, Geo, Panel, hsb

@scene("pulse", "Pulse", "Everything breathes in one colour.",
       tags=("ambient",), params={"period_s": 4.0, "hue": 280},
       param_docs={"period_s": "seconds per breath", "hue": "0-360"})
def pulse(geo: Geo, period_s: float = 4.0, hue: float = 280):
    def fn(t: float, p: Panel):
        return hsb(hue, 90, 30 + 60 * (0.5 + 0.5 * math.sin(2 * math.pi * t / period_s)))
    return fn, period_s            # (function, loop length in seconds)
```

Then: `uv run nanoleaf render --scene pulse --at 1.0`, `uv run nanoleaf save-scene pulse`, or
`uv run nanoleaf live --scene pulse --param hue=30`.

## What a `Panel` knows

| field | meaning |
|---|---|
| `u`, `v` | 0..1 across the whole space (`v` = 0 at the bottom) |
| `row`, `col` | grid cell: rows are one triangle height, columns are half a triangle width |
| `up` | the triangle points up (down-pointing ones make good "darker facets") |
| `top`, `bottom` | upper / lower half of its own controller (both true on a one-row strip) |
| `x`, `y` | centroid in Nanoleaf units (side = 150) in the shared space |
| `device`, `id`, `key` | which controller, its panelId, and `(device, id)` |

`Geo` adds `nrows`, `ncols`, `cells`, `by_cell[(row, col)]`, `nearest(u, v)` (the panel closest to a point, so a
character is always drawn somewhere), `blob(p, u, v, radius)` (soft coverage), `adjacency` (edge neighbours plus a
bridge between neighbouring controllers) and `longest_path(...)` for anything that walks the grid.

## Conventions

* Return `(r, g, b)` tuples or any colour string `effects.parse_color` accepts (`hsb(h,s,b)`, `#hex`, names).
* Make loops seamless: build motion from `t % period` or from sines whose periods divide the loop.
* `loop=False` marks a one-shot (plays once, holds the last frame; fire it with `play-once` / `sync-play`).
* `static=True` marks a design; `t` is ignored and it is saved as a static effect.
* `min_rows` hints which layouts suit the scene; the mock player shows every scene on every layout anyway.
* Keep per-frame work cheap: live streaming calls `fn` for every panel 20 times a second.
