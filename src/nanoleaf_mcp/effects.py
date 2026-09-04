"""Building blocks for Nanoleaf effects: colour parsing, palettes, plugin/static/custom effect bodies.

Effect JSON as the firmware stores it (sent as {"write": {"command": "add"|"display"|"displayTemp", ...effect}}):

  plugin effect (animated; a palette rendered by a motion plugin):
    {"version": "2.0", "animName": "...", "animType": "plugin", "colorType": "HSB",
     "palette": [{"hue": 0-360, "saturation": 0-100, "brightness": 0-100, "probability": 0.0}, ...],
     "pluginType": "color" | "rhythm", "pluginUuid": "...", "hasOverlay": false,
     "pluginOptions": [{"name": "transTime", "value": 10}, ...]}      # colour plugins only; rhythm plugins take none

  static effect (one fixed colour per panel) — firmware 5.x insists on the version-2.0 envelope here too:
    {"version": "2.0", "animName": "...", "animType": "static", "animData": "<nPanels> [<panelId> 1 R G B W T]...",
     "palette": [], "colorType": "HSB", "hasOverlay": false}

  custom effect (keyframes per panel):
    {"version": "2.0", "animName": "...", "animType": "custom", "animData": "<nPanels> [<panelId> <nFrames> [R G B W T]...]...",
     "loop": bool, "palette": [], "colorType": "HSB", "hasOverlay": false}
  T = transition time in tenths of a second.
"""
from __future__ import annotations

import colorsys
import json
import re
from pathlib import Path
from typing import Any, Iterable

# ---------------------------------------------------------------- plugin catalogue --------------
_CATALOG_PATH = Path(__file__).with_name("plugins_catalog.json")


def bundled_plugins() -> list[dict]:
    """Plugins enumerated from real Light Panels controllers (fallback when requestPlugins is unavailable)."""
    data = json.loads(_CATALOG_PATH.read_text())
    out = []
    for p in data["plugins"]:
        q = dict(p)
        q["verified"] = "bundled"
        out.append(q)
    return out


OPTION_DOCS = {
    "transTime": "tenths of a second per colour transition: 1-10 energetic, 20-60 relaxed, 100+ very slow/moody",
    "delayTime": "tenths of a second to hold a colour before moving on",
    "loop": "repeat the animation forever",
    "linDirection": "left | right | up | down",
    "radDirection": "in | out",
    "rotDirection": "cw | ccw",
    "nColorsPerFrame": "how many palette colours are visible across the layout at once",
    "mainColorProb": "0-100, how dominant the FIRST palette colour is (Highlight)",
}

SPEED_PRESETS = {"very slow": 200, "slow": 90, "medium": 30, "normal": 30, "fast": 10, "very fast": 3}


def normalise_plugins(raw: Any) -> list[dict]:
    """Flatten a requestPlugins response into the catalogue shape used everywhere else."""
    items: list = []
    if isinstance(raw, dict):
        items = raw.get("plugins") or raw.get("pluginList") or []
    elif isinstance(raw, list):
        items = raw
    out = []
    for p in items:
        if not isinstance(p, dict):
            continue
        uuid = p.get("uuid") or p.get("pluginUuid")
        if not uuid:
            continue
        options = []
        for o in p.get("pluginConfig") or []:
            if isinstance(o, dict):
                options.append({"name": o.get("name"), "type": o.get("type"),
                                "default": o.get("defaultValue"), "min": o.get("minValue"),
                                "max": o.get("maxValue"), "values": o.get("strings")})
        out.append({"uuid": uuid, "name": p.get("name") or uuid, "type": p.get("type") or "color",
                    "description": (p.get("description") or "").strip(),
                    "tags": [t.strip() for t in p.get("tags") or []], "features": p.get("features") or [],
                    "options": options, "verified": "device"})
    return out


def find_plugin(plugins: list[dict], ref: str) -> dict | None:
    r = ref.strip().lower()
    for p in plugins:
        if p["uuid"].lower() == r:
            return p
    for p in plugins:
        if p["name"].lower() == r:
            return p
    rn = re.sub(r"[^a-z0-9]", "", r)
    for p in plugins:
        if rn and rn in re.sub(r"[^a-z0-9]", "", p["name"].lower()):
            return p
    aliases = {"explode": "burst", "music": "streaking notes", "beat": "fireworks", "bass": "fireworks",
               "soundbar": "sound bar", "northern lights": "rhythmic northern lights", "aurora": "rhythmic northern lights"}
    if r in aliases:
        return find_plugin(plugins, aliases[r])
    return None


def validate_options(plugin: dict, options: dict[str, Any] | None) -> tuple[list[dict], list[str]]:
    """Map agent-supplied options onto the plugin's real config: aliases, clamping, dropping unknowns."""
    warnings: list[str] = []
    options = dict(options or {})
    schema = {o["name"]: o for o in plugin.get("options", [])}
    # friendly aliases
    if "speed" in options:
        v = options.pop("speed")
        if isinstance(v, str):
            v = SPEED_PRESETS.get(v.strip().lower())
            if v is None:
                warnings.append("speed must be one of " + ", ".join(SPEED_PRESETS))
        if v is not None:
            options.setdefault("transTime", v)
    if "direction" in options:
        options.setdefault("linDirection", options.pop("direction"))
    if "delay" in options:
        options.setdefault("delayTime", options.pop("delay"))
    out: list[dict] = []
    if not schema:
        if options:
            warnings.append(f"{plugin['name']} takes no options; ignored {sorted(options)}")
        return out, warnings
    for k, v in options.items():
        if k not in schema:
            warnings.append(f"{plugin['name']} has no option {k!r}; ignored (valid: {sorted(schema)})")
            continue
        s = schema[k]
        t = s.get("type")
        try:
            if t == "bool":
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "yes", "on")
            elif t == "int":
                v = int(round(float(v)))
                if s.get("min") is not None and v < s["min"]:
                    warnings.append(f"{k}={v} raised to min {s['min']}"); v = s["min"]
                if s.get("max") is not None and v > s["max"]:
                    warnings.append(f"{k}={v} lowered to max {s['max']}"); v = s["max"]
            elif t == "double":
                v = float(v)
                if s.get("min") is not None: v = max(float(s["min"]), v)
                if s.get("max") is not None: v = min(float(s["max"]), v)
            elif t == "string":
                v = str(v).lower()
                if s.get("values") and v not in s["values"]:
                    warnings.append(f"{k}={v!r} invalid; using {s.get('default')!r} (valid: {s['values']})")
                    v = s.get("default")
        except (TypeError, ValueError):
            warnings.append(f"{k}={v!r} is not a valid {t}; ignored")
            continue
        out.append({"name": k, "value": v})
    # fill sensible defaults for anything the device requires
    for k, s in schema.items():
        if not any(o["name"] == k for o in out) and s.get("default") is not None:
            out.append({"name": k, "value": s["default"]})
    return out, warnings


# ---------------------------------------------------------------- colours ------------------------
NAMED_COLORS: dict[str, str] = {
    "red": "#ff0000", "crimson": "#dc143c", "scarlet": "#ff2400", "maroon": "#800000", "burgundy": "#800020",
    "orange": "#ff7f00", "amber": "#ffbf00", "gold": "#ffd700", "yellow": "#ffff00",
    "lime": "#80ff00", "green": "#00ff00", "forest": "#228b22", "emerald": "#50c878", "mint": "#98ff98",
    "teal": "#008080", "turquoise": "#40e0d0", "seafoam": "#9fe2bf", "seafoamgreen": "#9fe2bf", "seagreen": "#2e8b57", "cyan": "#00ffff", "aqua": "#00ffff", "sky": "#87ceeb",
    "blue": "#0000ff", "royalblue": "#4169e1", "navy": "#000080", "indigo": "#4b0082",
    "purple": "#8000ff", "violet": "#8f00ff", "lavender": "#b57edc", "magenta": "#ff00ff", "plum": "#8e4585",
    "fuchsia": "#ff00ff", "pink": "#ff69b4", "hotpink": "#ff1493", "rose": "#ff007f", "salmon": "#fa8072",
    "coral": "#ff7f50", "peach": "#ffcba4", "white": "#ffffff", "warmwhite": "#fff4e5",
    "coolwhite": "#eaf4ff", "black": "#000000", "off": "#000000", "brown": "#8b4513",
}


def parse_color(value: Any) -> tuple[int, int, int]:
    """Accepts '#rrggbb', 'rgb(r,g,b)', 'hsb(h,s,b)'/'hsv(...)', a colour name (with dark/light/deep/pale
    modifiers), a {hue,saturation,brightness} dict, an {r,g,b} dict or an (r,g,b) tuple.
    Returns (hue 0-360, saturation 0-100, brightness 0-100)."""
    if isinstance(value, dict):
        if "hue" in value:
            return (int(value["hue"]) % 360, _clamp(value.get("saturation", 100), 0, 100),
                    _clamp(value.get("brightness", 100), 0, 100))
        if "r" in value:
            return rgb_to_hsb(int(value["r"]), int(value["g"]), int(value["b"]))
        if "h" in value:
            return (int(value["h"]) % 360, _clamp(value.get("s", 100), 0, 100),
                    _clamp(value.get("b", value.get("v", 100)), 0, 100))
    if isinstance(value, (tuple, list)) and len(value) == 3:
        return rgb_to_hsb(*[int(x) for x in value])
    s = str(value).strip().lower()
    m = re.fullmatch(r"#?([0-9a-f]{6})", s)
    if m:
        h = m.group(1)
        return rgb_to_hsb(int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    m = re.fullmatch(r"#?([0-9a-f]{3})", s)
    if m:
        h = m.group(1)
        return rgb_to_hsb(int(h[0] * 2, 16), int(h[1] * 2, 16), int(h[2] * 2, 16))
    m = re.fullmatch(r"rgb\s*\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
    if m:
        return rgb_to_hsb(*[int(x) for x in m.groups()])
    m = re.fullmatch(r"hs[bv]\s*\(\s*(\d+)\s*,\s*(\d+)\s*%?\s*,\s*(\d+)\s*%?\s*\)", s)
    if m:
        h, sa, b = (int(x) for x in m.groups())
        return (h % 360, _clamp(sa, 0, 100), _clamp(b, 0, 100))
    key = re.sub(r"[\s_-]", "", s)
    if key in NAMED_COLORS:
        return parse_color(NAMED_COLORS[key])
    m = re.fullmatch(r"(dark|deep|dim|light|pale|soft|bright|neon)\s*(.+)", s)
    if m and re.sub(r"[\s_-]", "", m.group(2)) in NAMED_COLORS:
        h, sa, b = parse_color(m.group(2))
        mod = m.group(1)
        if mod in ("dark", "deep", "dim"):
            return (h, sa, max(15, b - 55))
        if mod in ("light", "pale", "soft"):
            return (h, max(25, sa - 45), b)
        return (h, 100, 100)
    raise ValueError(f"Unrecognised colour {value!r}. Use #rrggbb, rgb(r,g,b), hsb(h,s,b) or a name like purple / dark red.")


def rgb_to_hsb(r: int, g: int, b: int) -> tuple[int, int, int]:
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return (round(h * 360) % 360, round(s * 100), round(v * 100))


def hsb_to_rgb(h: int, s: int, b: int) -> tuple[int, int, int]:
    r, g, bb = colorsys.hsv_to_rgb((h % 360) / 360, s / 100, b / 100)
    return (round(r * 255), round(g * 255), round(bb * 255))


def _clamp(v: Any, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(round(float(v)))))


def build_palette(colors: Iterable[Any], brightness: int | None = None) -> list[dict]:
    """Colour specs (optionally {"color": spec, "probability": p}) -> Nanoleaf HSB palette."""
    palette = []
    for c in colors:
        prob = 0.0
        if isinstance(c, dict) and "color" in c:
            prob = float(c.get("probability") or 0.0)
            c = c["color"]
        h, s, b = parse_color(c)
        if brightness is not None:
            b = _clamp(brightness, 0, 100)
        palette.append({"hue": h, "saturation": s, "brightness": b, "probability": prob})
    if not palette:
        raise ValueError("A palette needs at least one colour.")
    if len(palette) > 20:
        raise ValueError("Palettes are limited to 20 colours.")
    return palette


# ---------------------------------------------------------------- effect bodies ------------------
def plugin_effect(name: str, palette: list[dict], plugin: dict, options: dict[str, Any] | None = None) -> tuple[dict, list[str]]:
    opts, warnings = validate_options(plugin, options)
    body = {
        "version": "2.0",
        "animName": name,
        "animType": "plugin",
        "colorType": "HSB",
        "palette": palette,
        "pluginType": plugin["type"],
        "pluginUuid": plugin["uuid"],
        "hasOverlay": False,
    }
    if opts:
        body["pluginOptions"] = opts
    return body, warnings


def encode_anim_data(panels: dict[int, list[tuple[int, int, int, int, int]]]) -> str:
    """panels: {panelId: [(r, g, b, w, t_tenths), ...]} -> animData string."""
    parts = [str(len(panels))]
    for pid, frames in panels.items():
        if not frames:
            raise ValueError(f"panel {pid} has no frames")
        parts.append(str(int(pid)))
        parts.append(str(len(frames)))
        for (r, g, b, w, t) in frames:
            parts += [str(_clamp(r, 0, 255)), str(_clamp(g, 0, 255)), str(_clamp(b, 0, 255)),
                      str(_clamp(w, 0, 255)), str(int(t))]
    return " ".join(parts)


def static_effect(name: str, panel_colors: dict[int, Any], transition_tenths: int = 10) -> dict:
    panels = {}
    for pid, c in panel_colors.items():
        r, g, b = hsb_to_rgb(*parse_color(c))
        panels[int(pid)] = [(r, g, b, 0, transition_tenths)]
    return {"version": "2.0", "animName": name, "animType": "static", "animData": encode_anim_data(panels),
            "palette": [], "colorType": "HSB", "hasOverlay": False}


def custom_effect(name: str, panel_frames: dict[int, list[dict]], loop: bool = True) -> dict:
    """panel_frames: {panelId: [{"color": <spec>, "transition": <tenths>}, ...]}"""
    panels = {}
    for pid, frames in panel_frames.items():
        seq = []
        for f in frames:
            r, g, b = hsb_to_rgb(*parse_color(f.get("color", "black")))
            seq.append((r, g, b, 0, int(f.get("transition", 10))))
        panels[int(pid)] = seq
    return {"version": "2.0", "animName": name, "animType": "custom", "animData": encode_anim_data(panels),
            "loop": bool(loop), "palette": [], "colorType": "HSB", "hasOverlay": False}
