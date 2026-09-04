"""Mood presets: palette + on-device plugin combinations that need no computer once applied.

Each preset maps to one `create_effect` call (or a white-temperature `set_color`). They are the fastest way for
an agent to answer "make it cosy" / "bedtime" / "party" without designing a palette from scratch.
"""
from __future__ import annotations

PRESETS: dict[str, dict] = {
    "bedtime": {"title": "Bedtime", "description": "Near-black purples with rare dim violet glows; very low brightness.",
                "colors": ["hsb(270,100,6)", "hsb(268,100,18)", "hsb(280,90,12)", "hsb(255,100,10)", "hsb(290,70,8)"],
                "plugin": "Highlight", "options": {"mainColorProb": 82, "transTime": 140, "delayTime": 50}, "brightness": 25},
    "sunset": {"title": "Sunset", "description": "Gold through orange and coral into dusky purple, flowing slowly downward.",
               "colors": ["#ffb300", "#ff7a00", "#ff3d00", "#ff5e62", "#e0357c", "#7b2d8e"],
               "plugin": "Flow", "options": {"transTime": 110, "delayTime": 15, "linDirection": "down"}},
    "seafoam": {"title": "Seafoam Tide", "description": "Turquoise and seafoam greens drifting sideways.",
                "colors": ["turquoise", "seafoam green", "#2ec4b6", "#b8f2d8", "dark turquoise"],
                "plugin": "Flow", "options": {"transTime": 80, "delayTime": 10, "linDirection": "right"}},
    "purple_red_pulse": {"title": "Purple Red Pulse", "description": "Purple and red mood lighting that ripples to music (needs a Rhythm module).",
                         "colors": ["deep purple", "purple", "red", "dark red"], "plugin": "Ripple", "options": {}, "brightness": 60},
    "party": {"title": "Party", "description": "Saturated colours firing to the bass (needs a Rhythm module).",
              "colors": ["#ff0055", "#ffaa00", "#00ff88", "#00aaff", "#aa00ff", "#ffffff"], "plugin": "Fireworks", "options": {}, "brightness": 100},
    "flame_streaks": {"title": "Flame Streaks", "description": "Sound-reactive streaks in rocket-exhaust colours (needs a Rhythm module).",
                      "colors": ["rgb(255,255,240)", "rgb(255,230,80)", "rgb(255,140,0)", "rgb(230,60,10)", "rgb(255,200,60)"],
                      "plugin": "Streaking Notes", "options": {}},
    "forest": {"title": "Forest", "description": "Deep greens with the occasional shaft of sunlight.",
               "colors": ["#0b3d0b", "#1f7a1f", "#2e8b57", "#9acd32", "#ffe680"],
               "plugin": "Highlight", "options": {"mainColorProb": 75, "transTime": 60, "delayTime": 20}},
    "candlelight": {"title": "Candlelight", "description": "Warm amber flicker for a dim room.",
                    "colors": ["hsb(32,100,46)", "hsb(39,100,37)", "hsb(39,100,73)"],
                    "plugin": "Highlight", "options": {"mainColorProb": 80, "transTime": 7, "delayTime": 0}, "brightness": 40},
    "focus": {"title": "Focus", "description": "Neutral white for working.", "white": "4000K", "brightness": 90},
    "relax": {"title": "Relax", "description": "Warm white, dimmed.", "white": "2700K", "brightness": 45},
}


def list_presets() -> list[dict]:
    return [{"name": k, **{kk: v for kk, v in p.items() if kk in ("title", "description", "plugin", "white", "brightness")}}
            for k, p in PRESETS.items()]


def get(name: str) -> tuple[str, dict]:
    key = name.strip().lower().replace(" ", "_").replace("-", "_")
    if key in PRESETS:
        return key, PRESETS[key]
    hits = [k for k in PRESETS if key in k]
    if len(hits) == 1:
        return hits[0], PRESETS[hits[0]]
    raise LookupError(f"unknown preset {name!r}; available: {', '.join(PRESETS)}")
