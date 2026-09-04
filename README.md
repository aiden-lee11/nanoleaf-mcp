# nanoleaf-mcp

Let an AI agent run your Nanoleaf light panels. This is an [MCP](https://modelcontextprotocol.io) server plus a
CLI that speaks the panels' own local OpenAPI (HTTP on port 16021 and UDP external control), so you can say
things like

> create a scene with purple and red mood lighting that reacts to music

> show me a bunny hopping in a field

> a rocket launch when I clap

> a snake game across both sets of panels, at 30 % brightness

and the agent turns them into effects stored on the controller, keyframe animations, or live streams across
several controllers at once. Everything is layout-agnostic: the same scene renders on a 12-panel strip, a
30-panel block, or two controllers placed side by side.

## Quick start

```sh
uv sync                        # or: uv sync --extra sound  (adds the clap trigger)
uv run nanoleaf discover       # find controllers on the LAN (mDNS)
uv run nanoleaf pair -d "Light Panels 12:34:56"   # hold the controller's power button 5-7 s, then run this
#   macOS shortcut: uv run nanoleaf import-tokens  # reuse the Nanoleaf Desktop app's tokens, no button pressing
uv run nanoleaf label -d "Light Panels 12:34:56" "desk"   # optional friendly label
uv run nanoleaf status
uv run nanoleaf preset sunset
uv run nanoleaf save-scene bunny_hop --activate
```

Tokens and labels live in `~/.config/nanoleaf-mcp/devices.json` (mode 600). Nothing leaves your network.

### Hook it up to an agent

* **Claude Code**: `claude mcp add --scope user nanoleaf -- uv run --directory /path/to/nanoleaf-mcp nanoleaf-mcp`
* **Claude Desktop / other MCP clients**: add to the client's MCP config
  ```json
  {"mcpServers": {"nanoleaf": {"command": "uv", "args": ["run", "--directory", "/path/to/nanoleaf-mcp", "nanoleaf-mcp"]}}}
  ```

The server ships a `nanoleaf://guide` resource that tells the agent how to pick between presets, palette
effects and scenes, which plugin fits which mood, and how to span several controllers. Start a session and ask
for lighting in plain words.

## What the agent gets

| Tools | Purpose |
|---|---|
| `list_devices`, `discover_devices`, `pair_device`, `import_desktop_app_tokens`, `set_device_label` | inventory and pairing |
| `get_status`, `identify`, `set_power`, `set_brightness`, `set_color` | basics; colours as names, `#hex`, `rgb()`, `hsb()`, or `2700K` / `warm` / `daylight` |
| `list_presets`, `apply_preset` | moods in one call: bedtime, sunset, seafoam, party, candlelight, focus, relax... |
| `list_plugins`, `create_effect`, `list_effects`, `activate_effect`, `get_effect`, `rename_effect`, `delete_effect` | palette + on-device plugin effects (`color` plugins animate; `rhythm` plugins react to music) |
| `list_scenes`, `preview_scene`, `save_scene`, `play_once`, `sync_play` | layout-agnostic scenes stored on the controller: no computer needed after |
| `start_live_scene`, `stop_live_scene`, `live_status` | the same scenes streamed from the computer: exact sync across controllers, unlimited motion |
| `get_layout`, `render_layout`, `create_static_scene`, `create_custom_animation`, `stream_frame`, `stream_animation`, `stop_streaming` | per-panel control and raw streaming |
| `start_sound_trigger`, `stop_sound_trigger`, `sound_trigger_status` | clap trigger: the computer's microphone fires a one-shot animation |
| `build_mock_player` | HTML page animating every scene on hypothetical layouts, for planning a rebuild |
| `set_rhythm_mode`, `apply_effect_json`, `raw_request` | escape hatches |

`device` accepts a label, the mDNS name, serial, IP, or `all`.

## Scenes

Built in (`uv run nanoleaf scenes`):

| | |
|---|---|
| ambient | `ember_fire`, `fireplace`, `ocean_wave`, `crashing_wave`, `ombre` (a ring of your colours scrolling and wrapping), `rainbow`, `breathe` (bedtime) |
| motion | `shooting_star`, `rocket_launch` (one-shot with countdown), `rain` |
| stories | `bunny_hop`, `tennis_rally`, `fish` |
| games | `snake` (follows real panel adjacency, with get-ready, victory sweep and crash states), `pong`, `space_shooter` |
| static designs | `gem_mosaic`, `spectrum_facets` |

Each scene takes parameters (`--param period_s=6`, `--param colors='["red","gold"]'`) and reports which layouts
suit it. Adding your own is a ten-line function; see [docs/scenes.md](docs/scenes.md).

```sh
uv run nanoleaf render --scene fireplace --at 2.5              # preview in the terminal (24-bit colour)
uv run nanoleaf save-scene ember_fire --activate               # stored on the controller, loops forever
uv run nanoleaf save-scene rocket_launch                       # one-shot
uv run nanoleaf play-once "Rocket Launch"
uv run nanoleaf live --scene ombre --param colors='["#ff3cac","#784ba0","#2b86c5"]'   # streamed, Ctrl-C to stop
```

### Several controllers as one canvas

Give the device labels in left-to-right physical order, the gap between the sets in triangle widths, and how
they line up vertically. Both delivery modes use the same shared coordinate space:

| | stored (`save-scene` + `sync-play` / `--activate`) | live (`live`) |
|---|---|---|
| where it runs | keyframes on each controller, started together | rendered on the computer, streamed at 20 fps over UDP |
| sync at the seam | requests fired from a thread barrier: tens of ms | one clock for every panel: exact |
| long loops | controllers drift apart slowly; re-fire to resync | no drift |
| what it can show | anything that fits in an animation (`max_seconds` caps it) | anything a function of (x, y, t) can draw |
| needs a computer | only to start it | the whole time |

```sh
uv run nanoleaf live left-set right-set --scene shooting_star --gap 2 --align top
uv run nanoleaf save-scene crashing_wave --order left-set right-set --gap 2 --align top
uv run nanoleaf sync-play "Crashing Wave"
```

### Planning a rebuild

`uv run nanoleaf mock --layout 4x8-2 --layout 5x6 --layout 3x10 --out mock.html` writes a page that animates every
scene on those shapes (`4x8-2` = 4 rows of 8 minus two opposite corners). Nanoleaf's stated limit is 30 panels per
controller; triangles cannot form straight vertical sides, so a "rectangle" of them has zigzag left and right edges.

## Clap trigger

Nanoleaf's Rhythm module drives its built-in rhythm plugins only; nothing on the controller can start a custom
animation on a sound. So the listener runs on the computer: it tracks the room's noise floor and fires a saved
one-shot animation on a sharp spike.

```sh
uv sync --extra sound
uv run nanoleaf save-scene rocket_launch
uv run nanoleaf listen --effect "Rocket Launch" --meter     # or start_sound_trigger from the agent
```

If you want music reactivity with no computer, use a rhythm plugin (`apply_preset purple_red_pulse`).

## How it works

* `discovery.py`: mDNS browse (`_nanoleafapi._tcp`; Apple `dns-sd` on macOS, python-zeroconf elsewhere).
* `client.py`: the OpenAPI: `/state`, `/effects` (`select`, `write` commands `add` / `display` / `displayTemp` /
  `request` / `requestAll` / `requestPlugins` / `delete` / `rename`), `/panelLayout`, `/rhythm`, external control.
* `effects.py`: colour parsing, palettes, option validation against the plugin's real config, effect bodies
  (`plugin` / `static` / `custom` animData) and the plugin catalogue read off real Light Panels.
* `scenes/`: the scene registry and geometry (`Geo`, `Panel`), keyframe sampling, synthetic layouts.
* `live.py` and `stream.py`: external-control v1/v2 UDP streaming with a shared clock.
* `render.py`: ASCII / ANSI / SVG renderer of layouts, saved effects and scenes.
* `core.py`: the device registry and every operation, shared by `server.py` (MCP) and `cli.py`.

Effect JSON as firmware 5.x expects it (static and custom effects need the same `version: "2.0"` envelope):

```json
{"write": {"command": "add", "version": "2.0", "animName": "Purple Red Pulse", "animType": "plugin",
           "colorType": "HSB", "pluginType": "rhythm", "pluginUuid": "bc6fe7e0-36d4-4f95-aa21-52a386daa9dc",
           "palette": [{"hue": 270, "saturation": 100, "brightness": 45, "probability": 0}],
           "hasOverlay": false}}
```

### macOS "Local Network" permission

macOS 15+ blocks LAN sockets from non-Apple binaries unless the app that launched them has the *Local Network*
permission (System Settings > Privacy & Security > Local Network). Until you enable it for your terminal or the
Claude desktop app, the client transparently falls back to `/usr/bin/curl` for HTTP and `/usr/bin/nc` for UDP,
which are exempt, and logs a one-line hint. The clap listener likewise needs the Microphone permission.

## Tested on

Nanoleaf Light Panels (model NL22, firmware 5.2.2) with Rhythm modules, two controllers. Other Nanoleaf products
that expose the OpenAPI (Canvas, Shapes, Elements, Lines) should work for effects and streaming; scenes assume
triangles for the grid maths and will need a shape hook for squares and hexagons. Contributions welcome.

## License

MIT
