"""MCP server: the communication layer between an AI agent and Nanoleaf panels.

Run:  uv run nanoleaf-mcp            (stdio transport, for Claude Code / Claude Desktop / any MCP client)
"""
from __future__ import annotations

import logging
import sys
from typing import Any

from mcp.server.mcpserver import MCPServer

from .core import Nanoleaf

logging.basicConfig(level=logging.INFO, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

mcp = MCPServer(
    "nanoleaf",
    instructions=(
        "Controls the user's Nanoleaf light panels over the local network. Start with list_devices (or get_status) to "
        "learn device labels; pass device='all' to address every controller. Three ways to light the room: "
        "apply_preset for a mood in one call; create_effect for a custom palette rendered by an on-device plugin "
        "(list_plugins: 'rhythm' plugins react to music, 'color' plugins animate on their own); save_scene or "
        "start_live_scene for pictures and games from list_scenes (bunny hop, rocket launch, snake, fire...). "
        "Read nanoleaf://guide before designing. Colours accept names, #hex, rgb(), hsb()."
    ),
)
nl = Nanoleaf()

GUIDE = """# Lighting the room with Nanoleaf panels (agent guide)

## Devices
Each controller is one *device*; `list_devices` gives their labels (set with `set_device_label`, e.g. "desk",
"hallway"). Use `device="all"` to address every controller. `get_status` shows power, brightness, the current
effect and whether a Rhythm (microphone) module is attached.

## Three ways to make light
1. **Presets** (`list_presets`, `apply_preset`): moods in one call (bedtime, sunset, party, focus...). Fastest.
2. **Effects** (`create_effect`): a **palette** (up to 20 colours, order matters) rendered by an on-device
   **plugin** (`list_plugins`). `pluginType: "color"` plugins animate on their own; `"rhythm"` plugins react to
   sound through the Rhythm module and take no options. Stored on the controller; runs with no computer.
3. **Scenes** (`list_scenes`, `preview_scene`, `save_scene`, `start_live_scene`): layout-agnostic animations
   and designs (fire, waves, shooting star, bunny hop, tennis, rocket launch, snake, pong, space shooter,
   mosaics). `save_scene` stores keyframes on the controller (no computer needed after); `start_live_scene`
   streams from this computer (exact sync across several controllers, unlimited motion, computer must stay on).

## Choosing a plugin for a vibe (effects)
| Ask | Plugin | Notes |
|---|---|---|
| calm / mood / ambient | Fade (transTime 60-200) or Flow (40-120) | palette_brightness 30-60 for moody |
| dominant colour with accents | Highlight | first palette colour dominates; mainColorProb 70-90 |
| gradient sweep | Wheel (nColorsPerFrame 2-6, linDirection) | transTime 2-10 = energetic |
| sparkle / random | Random | |
| **music, EDM / bass** | Fireworks, Streaking Notes (pitch -> colour), Pulse Pop Beats | Rhythm module needed |
| **music, chill** | Sound Bar (first two colours), Ripple, Rhythmic Northern Lights, Paint Splatter | |
Rhythm plugins: 3-6 colours spanning a few brightness levels look best. The Rhythm module cannot trigger
custom animations; for "when I clap, play X" use `start_sound_trigger` (this computer's microphone).

## Several controllers as one canvas
Scenes span controllers: pass `devices` as labels in **left-to-right physical order** plus `gap_widths`
(distance between sets in triangle widths) and `align` ("top" | "bottom" | "middle"). Stored scenes on several
controllers are started together with `sync_play` (one-shots) or `activate=True` (loops).

## Seeing before doing
`render_layout` draws a layout in ASCII; `preview_scene` draws a scene at a moment in time; `build_mock_player`
writes an HTML page that animates every scene on hypothetical layouts (for planning a rebuild).

## Recipes
- "purple and red mood lighting that reacts to music": `apply_preset("purple_red_pulse")` or
  `create_effect(colors=["deep purple","purple","red","dark red"], plugin="Ripple")`.
- "ambient fire": `save_scene("ember_fire")` or `save_scene("fireplace")` (needs 2+ rows).
- "something for bedtime": `apply_preset("bedtime")` or `save_scene("breathe")` + `set_brightness(20)`.
- "a rocket launch when I clap": `save_scene("rocket_launch")` then `start_sound_trigger("Rocket Launch")`.
- "a snake game across both sets": `start_live_scene("snake", devices=[left, right], brightness=30)`.
"""


@mcp.resource("nanoleaf://guide")
def guide() -> str:
    """How to light the room: presets vs effects vs scenes, plugin choice, multi-controller layouts, recipes."""
    return GUIDE


@mcp.prompt()
def design_scene(request: str) -> str:
    """Turn a natural-language lighting request into Nanoleaf tool calls."""
    return (f"The user wants this lighting: {request!r}.\n"
            "Read nanoleaf://guide and get_status(device='all'). Decide between a preset, a palette+plugin effect "
            "(rhythm plugin if it should react to music) or a scene (pictures, games, fire, waves). Preview when "
            "unsure (preview_scene / create_effect mode='preview'), apply it, set a brightness that suits the mood, "
            "and finish by telling the user the effect name and how it behaves.")


# ---------------------------------------------------------------- devices
@mcp.tool()
def list_devices() -> list[dict]:
    """Registered Nanoleaf controllers (label, ip, model, paired). Labels are what other tools accept as `device`."""
    return nl.list_devices()


@mcp.tool()
def discover_devices(timeout_s: float = 4.0) -> list[dict]:
    """Scan the LAN (mDNS) for Nanoleaf controllers and register any new ones (unpaired)."""
    return nl.discover(timeout_s)


@mcp.tool()
def import_desktop_app_tokens() -> dict:
    """macOS: reuse auth tokens from the Nanoleaf Desktop app so no button pressing is needed."""
    return nl.import_desktop_app_tokens()


@mcp.tool()
def pair_device(device: str) -> dict:
    """Pair with a controller. The user must hold its power button 5-7 s until the LEDs flash, then call this within 30 s."""
    return nl.pair(device)


@mcp.tool()
def set_device_label(device: str, label: str) -> dict:
    """Give a controller a friendly label (e.g. 'desk', 'hallway') used in `device` arguments and results."""
    return nl.set_friendly_name(device, label)


@mcp.tool()
def get_status(device: str = "all") -> dict:
    """Power, brightness, colour mode, current effect, panel count and rhythm (music) module state per device."""
    return nl.each(device, nl.status)


@mcp.tool()
def identify(device: str = "all") -> dict:
    """Flash the panels so the user can tell which controller is which."""
    return nl.identify(device)


# ---------------------------------------------------------------- simple state
@mcp.tool()
def set_power(on: bool, device: str = "all") -> dict:
    """Turn panels on or off."""
    return nl.set_power(device, on)


@mcp.tool()
def set_brightness(brightness: int, device: str = "all", fade_s: float = 0) -> dict:
    """Set overall brightness 0-100, optionally fading over fade_s seconds."""
    return nl.set_brightness(device, brightness, fade_s)


@mcp.tool()
def set_color(color: str, device: str = "all", brightness: int | None = None) -> dict:
    """Solid colour on all panels: names (purple, dark red), #hex, rgb(), hsb(), or a white temperature ('2700K', 'warm', 'daylight')."""
    return nl.set_color(device, color, brightness)


# ---------------------------------------------------------------- presets & effects
@mcp.tool()
def list_presets() -> list[dict]:
    """Mood presets (bedtime, sunset, party, focus...): palette + on-device plugin in one call."""
    return nl.list_presets()


@mcp.tool()
def apply_preset(name: str, device: str = "all", brightness: int | None = None) -> dict:
    """Apply a mood preset from list_presets; it is saved on the controller and activated."""
    return nl.apply_preset(device, name, brightness)


@mcp.tool()
def list_effects(device: str = "all") -> dict:
    """Saved effects (scenes) on each device and which one is selected."""
    return nl.each(device, nl.effects)


@mcp.tool()
def get_effect(name: str, device: str = "all") -> dict:
    """Full JSON definition of a saved effect (palette, plugin, options). Useful as a template."""
    return nl.each(device, lambda d, c: nl.effect_detail(d, c, name))


@mcp.tool()
def activate_effect(name: str, device: str = "all") -> dict:
    """Switch to a saved effect by name (case-insensitive, substring ok if unique) and turn the panels on."""
    return nl.activate(device, name)


@mcp.tool()
def delete_effect(name: str, device: str = "all") -> dict:
    """Delete a saved effect."""
    return nl.delete(device, name)


@mcp.tool()
def rename_effect(old_name: str, new_name: str, device: str = "all") -> dict:
    """Rename a saved effect."""
    return nl.rename(device, old_name, new_name)


@mcp.tool()
def list_plugins(device: str = "all", refresh: bool = False) -> dict:
    """Motion plugins on each device: name, type ('color' = ambient animation, 'rhythm' = music reactive), description, option schema."""
    return nl.each(device, lambda d, c: nl.plugins(d, c, refresh))


@mcp.tool()
def create_effect(name: str, colors: list[Any], plugin: str, device: str = "all", options: dict[str, Any] | None = None,
                  mode: str = "save", duration_s: int | None = None, activate: bool = True,
                  palette_brightness: int | None = None, device_brightness: int | None = None) -> dict:
    """Create an effect: a palette of colours animated by an on-device plugin (runs with no computer).

    colors: 1-20 colour specs, order matters (first = main colour for Highlight; low->high notes for Streaking
      Notes/Meteor Shower; first two for Sound Bar). Names ('purple', 'dark red'), '#hex', 'rgb(...)', 'hsb(h,s,b)',
      or {"color": spec, "probability": 0-1}.
    plugin: name or uuid from list_plugins (Fade, Flow, Wheel, Highlight, Random, Burst, Streaking Notes,
      Fireworks, Ripple, Sound Bar, Pulse Pop Beats, Paint Splatter, Meteor Shower...).
    options: colour plugins only, e.g. {"transTime": 40, "delayTime": 0, "linDirection": "left",
      "nColorsPerFrame": 3, "mainColorProb": 80} or shortcuts {"speed": "slow"|"medium"|"fast", "direction": "up"}.
    mode: 'save' (store + activate), 'preview' (show without saving), 'flash' (show for duration_s, then revert).
    palette_brightness: override every colour's brightness 0-100 (moody = 30-60). device_brightness: panel brightness.
    """
    return nl.create_effect(device, name, colors, plugin, options, mode, duration_s, activate, palette_brightness, device_brightness)


@mcp.tool()
def apply_effect_json(effect: dict[str, Any], device: str = "all", mode: str = "save", activate: bool = True) -> dict:
    """Escape hatch: send a raw effect body (any animType) exactly as the Nanoleaf OpenAPI expects."""
    return nl.apply_effect_json(device, effect, mode, activate)


# ---------------------------------------------------------------- scenes
@mcp.tool()
def list_scenes() -> list[dict]:
    """Built-in layout-agnostic scenes: animations (fire, waves, shooting star, bunny hop, tennis, rocket launch,
    rain, fish), games (snake, pong, space shooter) and static designs (gem mosaic, spectrum facets), with parameters."""
    return nl.list_scenes()


@mcp.tool()
def preview_scene(scene: str, devices: list[str] | None = None, at_s: float = 0.0, params: dict[str, Any] | None = None,
                  gap_widths: float = 2.0, align: str = "top", width: int = 90) -> dict:
    """ASCII picture of each device's layout coloured by the scene at time at_s. devices: labels in left-to-right
    physical order (default: all). Use it to check a design before saving or streaming."""
    return nl.preview_scene(devices, scene, at_s, params, gap_widths, align, False, width)


@mcp.tool()
def save_scene(scene: str, devices: list[str] | None = None, name: str | None = None, params: dict[str, Any] | None = None,
               gap_widths: float = 2.0, align: str = "top", activate: bool = False, max_seconds: float = 60.0) -> dict:
    """Store a scene on the controller(s) as an effect (keyframes for animations, a static effect for designs). Runs
    with no computer. Loops can then be activated with activate_effect (or activate=True); one-shots (e.g.
    rocket_launch) play with play_once / sync_play. devices: labels in left-to-right order for multi-controller scenes."""
    return nl.save_scene(devices, scene, name, params, gap_widths, align, 1, activate, max_seconds)


@mcp.tool()
def play_once(effect: str, device: str) -> dict:
    """Play a saved custom keyframe animation once (no loop); the panels then hold its final frame."""
    return nl.play_once(device, effect)


@mcp.tool()
def sync_play(effect: str, device: str = "all") -> dict:
    """Start a saved one-shot animation on every matching device at the same instant (for scenes saved across controllers)."""
    return nl.sync_play({d.label: effect for d in nl.targets(device)})


@mcp.tool()
def start_live_scene(scene: str = "ombre", devices: list[str] | None = None, params: dict[str, Any] | None = None,
                     gap_widths: float = 2.0, align: str = "top", fps: float = 20, seconds: float | None = None,
                     brightness: int | None = None) -> dict:
    """Stream a scene from this computer to the controllers (exact sync across several, any motion; needs the computer
    on). devices: labels in left-to-right physical order (default: all). params: scene parameters from list_scenes,
    e.g. {"colors": ["red", "gold"], "period_s": 6}. Runs in the background until stop_live_scene or `seconds`."""
    return nl.start_live_scene(devices, scene, params, gap_widths, align, fps, seconds, brightness)


@mcp.tool()
def stop_live_scene() -> dict:
    """Stop the background live stream; each controller returns to what it showed before."""
    return nl.stop_live_scene()


@mcp.tool()
def live_status() -> dict:
    """Whether a live stream is running and where its log is."""
    return nl.live_status()


@mcp.tool()
def build_mock_player(out_path: str, layouts: list[str] | None = None, scenes: list[str] | None = None, fps: int = 15) -> dict:
    """Write an HTML page that animates scenes on hypothetical layouts ('4x8-2' = 4 rows of 8 minus two corners,
    '5x6', '3x10'...), for planning a rebuild before moving panels. Open the file in a browser."""
    from .mock import build_player
    html = build_player(layouts or ["4x8-2", "5x6", "3x10"], scenes, fps)
    open(out_path, "w").write(html)
    return {"written": out_path, "kb": len(html) // 1024, "layouts": layouts or ["4x8-2", "5x6", "3x10"]}


# ---------------------------------------------------------------- layout & per-panel
@mcp.tool()
def get_layout(device: str = "all") -> dict:
    """Panel ids with x/y positions and orientation, plus the rhythm module position. Needed for per-panel work."""
    return nl.each(device, nl.layout)


@mcp.tool()
def render_layout(device: str = "all", panel_colors: dict[str, Any] | None = None, effect: str | None = None, width: int = 90) -> dict:
    """ASCII picture of each layout as it hangs (app orientation) with panel ids; pass panel_colors or a saved static
    effect name to preview colours before applying them."""
    return nl.each(device, lambda d, c: nl.render(d, c, panel_colors, effect, ansi=False, width=width))


@mcp.tool()
def create_static_scene(panel_colors: dict[str, Any], device: str, name: str | None = None, fill: str | None = None,
                        transition_s: float = 1.0, mode: str = "preview") -> dict:
    """Paint fixed colours per panel: panel_colors = {"<panelId>": colour}. `fill` colours the rest. mode 'save' needs a name."""
    return nl.static_scene(device, panel_colors, name, transition_s, mode, fill)


@mcp.tool()
def create_custom_animation(name: str, panel_frames: dict[str, list[dict[str, Any]]], device: str, loop: bool = True,
                            mode: str = "save") -> dict:
    """Keyframe animation stored on the device: panel_frames = {"<panelId>": [{"color": spec, "transition": tenths_of_s}, ...]}."""
    return nl.custom_animation(device, name, panel_frames, loop, mode)


@mcp.tool()
def stream_frame(panel_colors: dict[str, Any], device: str, transition_tenths: int = 1, fill: str | None = None) -> dict:
    """Live control: push one frame of per-panel colours over UDP (external control). The device stays in streaming mode until stop_streaming."""
    return nl.stream_frame(device, panel_colors, transition_tenths, fill)


@mcp.tool()
def stream_animation(frames: list[Any], device: str, fps: float = 10.0, transition_tenths: int = 1) -> dict:
    """Live control: play a list of frames ({"<panelId>": colour, ...} or {"panels": {...}, "transition": t}) at fps (max 30, max 1800 frames)."""
    return nl.stream_animation(device, frames, fps, transition_tenths)


@mcp.tool()
def stop_streaming(device: str = "all", restore: bool = True) -> dict:
    """Leave external-control mode and restore the effect/colour that was showing before streaming started."""
    return nl.stop_streaming(device, restore)


# ---------------------------------------------------------------- sound trigger
@mcp.tool()
def start_sound_trigger(effect: str, device: str, sensitivity_db: float = 18, min_db: float = -30, cooldown_s: float = 8,
                        input_device: str | None = None) -> dict:
    """Background listener on this computer's microphone (built-in by default) that plays `effect` (a saved one-shot
    animation) on the panels whenever it hears a clap-like spike above the quiet floor. The panels' own Rhythm module
    cannot trigger custom animations. Needs the 'sound' extra installed."""
    return nl.start_sound_trigger(device, effect, sensitivity_db, min_db, cooldown_s, input_device)


@mcp.tool()
def stop_sound_trigger(device: str = "all") -> dict:
    """Stop the clap listener(s)."""
    return nl.stop_sound_trigger(device)


@mcp.tool()
def sound_trigger_status(device: str = "all") -> dict:
    """Whether a clap listener is running for each device, and where its log is."""
    return nl.sound_trigger_status(device)


# ---------------------------------------------------------------- rhythm & raw
@mcp.tool()
def set_rhythm_mode(mode: str, device: str = "all") -> dict:
    """Sound source for music-reactive effects: 'microphone' (default) or 'aux'."""
    return nl.set_rhythm_mode(device, mode)


@mcp.tool()
def raw_request(method: str, path: str, device: str = "all", body: dict[str, Any] | None = None) -> dict:
    """Escape hatch: call any Nanoleaf OpenAPI path (relative to /api/v1/<token>), e.g. GET /state, PUT /effects {"select": "Flames"}."""
    return nl.raw(device, method, path, body)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
