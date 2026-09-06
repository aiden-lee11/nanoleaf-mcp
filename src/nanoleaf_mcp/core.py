"""High-level operations shared by the MCP server and the CLI.

Every public method takes a `device` reference (friendly name from the Nanoleaf app, mDNS name, serial,
IP, or "all") and returns plain JSON-serialisable data, with per-device errors reported inline
instead of aborting a multi-device call.
"""
from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import effects as fx
from . import presets as _presets
from . import scenes as _scenes
from .client import NanoleafClient, NanoleafError
from .config import Device, Registry
from .discovery import discover
from .stream import Streamer
from .render import render as _render, render_svg as _render_svg, anim_data_colors, anim_data_frames, anim_loop_tenths, colors_at

log = logging.getLogger("nanoleaf")

MAX_STORED_EFFECTS = 50   # Light Panels firmware 5.x rejects the 51st stored effect with a bare HTTP 400

DESKTOP_APP_DATA = Path.home() / "Library/Application Support/Nanoleaf Desktop/appData.json"


class Nanoleaf:
    def __init__(self, registry: Registry | None = None):
        self.reg = registry or Registry()
        self._clients: dict[str, NanoleafClient] = {}
        self._plugins: dict[str, list[dict]] = {}
        self._streams: dict[str, Streamer] = {}
        self._pre_stream: dict[str, dict] = {}

    # ------------------------------------------------------------------ plumbing
    def client(self, dev: Device) -> NanoleafClient:
        c = self._clients.get(dev.key)
        if c is None or c.token != dev.token or c.ip != dev.ip:
            c = NanoleafClient(dev.ip, dev.port, dev.token)
            self._clients[dev.key] = c
        return c

    def targets(self, device: str | None, paired_only: bool = True) -> list[Device]:
        devs = self.reg.resolve(device, paired_only=paired_only)
        if not devs:
            raise LookupError(self._no_match(device, paired_only))
        return devs

    def _no_match(self, device: str | None, paired_only: bool) -> str:
        known = ", ".join(f"{d.label} ({'paired' if d.paired else 'not paired'})" for d in self.reg.devices.values())
        return (f"No {'paired ' if paired_only else ''}device matches {device!r}. Known: {known or 'none'}. "
                "Run discover_devices / import_desktop_app_tokens / pair_device first.")

    def each(self, device: str | None, fn: Callable[[Device, NanoleafClient], Any]) -> dict[str, Any]:
        """Apply fn to every matching device; returns {label: result | {"error": msg}}."""
        out: dict[str, Any] = {}
        for dev in self.targets(device):
            try:
                out[dev.label] = fn(dev, self.client(dev))
            except (NanoleafError, LookupError, ValueError) as e:
                out[dev.label] = {"error": str(e)}
        return out

    def one(self, device: str | None) -> tuple[Device, NanoleafClient]:
        dev = self.reg.resolve_one(device, paired_only=True)
        return dev, self.client(dev)

    # ------------------------------------------------------------------ registry / pairing
    def list_devices(self) -> list[dict]:
        return [d.public() for d in self.reg.devices.values()]

    def discover(self, timeout: float = 4.0) -> list[dict]:
        found = discover(timeout)
        for f in found:
            self.reg.upsert(Device(name=f.name, ip=f.ip, port=f.port, host=f.host, model=f.model, firmware=f.firmware,
                                   extra={"mac": f.txt.get("id")}))
        self.reg.save()
        return [f.as_dict() | {"paired": any(d.ip == f.ip and d.paired for d in self.reg.devices.values())} for f in found]

    def pair(self, device: str | None) -> dict:
        devs = self.reg.resolve(device, paired_only=False)
        if len(devs) != 1:
            raise LookupError(self._no_match(device, False) if not devs else f"{device!r} matches several devices; be specific")
        dev = devs[0]
        c = NanoleafClient(dev.ip, dev.port)
        c.pair()
        dev.token = c.token
        self._fill_identity(dev, c)
        self.reg.upsert(dev)
        self.reg.save()
        self._clients.pop(dev.key, None)
        return {"paired": True, "device": dev.public()}

    def import_desktop_app_tokens(self) -> dict:
        """The Nanoleaf Desktop app (macOS) keeps its OpenAPI tokens in appData.json; reuse them."""
        if not DESKTOP_APP_DATA.exists():
            return {"imported": 0, "error": f"{DESKTOP_APP_DATA} not found (Nanoleaf Desktop not installed or never opened)"}
        data = json.loads(DESKTOP_APP_DATA.read_text())
        imported, skipped = [], []
        for home in data.get("homes", {}).values():
            for room in home.get("rooms", {}).values():
                for serial, d in room.get("devices", {}).items():
                    info = d.get("info", {})
                    ip = (info.get("addresses") or [None])[0]
                    tok = d.get("token")
                    if not ip or not tok:
                        skipped.append(serial); continue
                    dev = Device(name=info.get("name") or serial, ip=ip, token=tok, serial=serial,
                                 model=d.get("model") or info.get("model"),
                                 extra={"friendly_name": d.get("name"), "mac": d.get("mac_address")})
                    c = NanoleafClient(ip, token=tok)
                    try:
                        c.state()
                    except NanoleafError as e:
                        skipped.append(f"{serial}: token rejected ({e.status})"); continue
                    self._fill_identity(dev, c)
                    self.reg.upsert(dev)
                    imported.append(dev.label)
        self.reg.save()
        self._clients.clear()
        return {"imported": len(imported), "devices": imported, "skipped": skipped}

    def _fill_identity(self, dev: Device, c: NanoleafClient) -> None:
        try:
            info = c.info()
            dev.name = info.get("name") or dev.name
            dev.serial = info.get("serialNo") or dev.serial
            dev.model = info.get("model") or dev.model
            dev.firmware = info.get("firmwareVersion") or dev.firmware
        except NanoleafError:
            pass

    def set_friendly_name(self, device: str, friendly: str) -> dict:
        dev, _ = self.one(device)
        old = dev.key
        dev.extra["friendly_name"] = friendly
        self.reg.devices.pop(old, None)
        self.reg.devices[dev.key] = dev
        self.reg.save()
        return dev.public()

    # ------------------------------------------------------------------ state
    @staticmethod
    def _val(state: dict, k: str) -> Any:
        v = state.get(k)
        return v.get("value") if isinstance(v, dict) else v

    def status(self, dev: Device, c: NanoleafClient) -> dict:
        info = c.info()
        st = info.get("state", {})
        rh = info.get("rhythm") or {}
        lay = info.get("panelLayout", {}).get("layout", {})
        return {
            "label": dev.label, "name": info.get("name"), "ip": dev.ip, "model": info.get("model"),
            "firmware": info.get("firmwareVersion"), "serial": info.get("serialNo"),
            "on": self._val(st, "on"), "brightness": self._val(st, "brightness"),
            "colorMode": self._val(st, "colorMode"), "hue": self._val(st, "hue"), "sat": self._val(st, "sat"),
            "ct": self._val(st, "ct"),
            "current_effect": info.get("effects", {}).get("select"),
            "effects_count": len(info.get("effects", {}).get("effectsList", [])),
            "panels": lay.get("numPanels"), "panel_ids": [p["panelId"] for p in lay.get("positionData", [])],
            "rhythm": {"connected": rh.get("rhythmConnected"), "active": rh.get("rhythmActive"),
                       "mode": {0: "microphone", 1: "aux"}.get(rh.get("rhythmMode"), rh.get("rhythmMode")),
                       "aux_available": rh.get("auxAvailable")} if rh else None,
            "streaming": dev.key in self._streams,
        }

    def snapshot(self, dev: Device, c: NanoleafClient) -> dict:
        info = c.info()
        st = info.get("state", {})
        return {"on": self._val(st, "on"), "brightness": self._val(st, "brightness"), "colorMode": self._val(st, "colorMode"),
                "hue": self._val(st, "hue"), "sat": self._val(st, "sat"), "ct": self._val(st, "ct"),
                "effect": info.get("effects", {}).get("select")}

    def restore(self, dev: Device, c: NanoleafClient, snap: dict) -> None:
        mode = snap.get("colorMode")
        if mode == "effect" and snap.get("effect") and not str(snap["effect"]).startswith("*"):
            c.select_effect(snap["effect"])
        elif mode == "ct":
            c.set_state(ct=snap.get("ct"))
        else:
            c.set_state(hue=snap.get("hue"), sat=snap.get("sat"))
        c.set_state(brightness=snap.get("brightness"), on=snap.get("on"))

    def set_power(self, device: str | None, on: bool) -> dict:
        return self.each(device, lambda d, c: (c.set_state(on=bool(on)), {"on": bool(on)})[1])

    def set_brightness(self, device: str | None, brightness: int, duration_s: float = 0) -> dict:
        b = max(0, min(100, int(brightness)))
        def go(d, c):
            c.set_state(brightness=(b, duration_s) if duration_s else b)
            return {"brightness": b}
        return self.each(device, go)

    def set_color(self, device: str | None, color: str, brightness: int | None = None) -> dict:
        """Solid colour (hue/sat) or colour temperature: 'ct:4000', '4000K', 'warm', 'cool', 'daylight'."""
        ct = _parse_ct(color)
        def go(d, c):
            if ct:
                c.set_state(on=True, ct=ct, brightness=brightness)
                return {"ct": ct, "brightness": brightness}
            h, s, b = fx.parse_color(color)
            c.set_state(on=True, hue=h, sat=s, brightness=brightness if brightness is not None else b)
            return {"hue": h, "sat": s, "brightness": brightness if brightness is not None else b}
        return self.each(device, go)

    def identify(self, device: str | None) -> dict:
        return self.each(device, lambda d, c: (c.identify(), {"identified": True})[1])

    # ------------------------------------------------------------------ effects
    def effects(self, dev: Device, c: NanoleafClient) -> dict:
        return {"selected": c.selected_effect(), "effects": c.effects_list()}

    def effect_detail(self, dev: Device, c: NanoleafClient, name: str) -> dict:
        return c.request_effect(name)

    def activate(self, device: str | None, name: str) -> dict:
        def go(d, c):
            names = c.effects_list()
            target = _match_name(names, name)
            if not target:
                raise LookupError(f"No effect named {name!r} on {d.label}. Available: {names}")
            c.select_effect(target)
            c.set_state(on=True)
            return {"activated": target}
        return self.each(device, go)

    def delete(self, device: str | None, name: str) -> dict:
        def go(d, c):
            target = _match_name(c.effects_list(), name)
            if not target:
                raise LookupError(f"No effect named {name!r} on {d.label}")
            c.delete_effect(target)
            return {"deleted": target}
        return self.each(device, go)

    def rename(self, device: str | None, old: str, new: str) -> dict:
        def go(d, c):
            target = _match_name(c.effects_list(), old)
            if not target:
                raise LookupError(f"No effect named {old!r} on {d.label}")
            c.rename_effect(target, new)
            return {"renamed": target, "to": new}
        return self.each(device, go)

    def plugins(self, dev: Device, c: NanoleafClient, refresh: bool = False) -> list[dict]:
        if refresh or dev.key not in self._plugins:
            try:
                self._plugins[dev.key] = fx.normalise_plugins(c.request_plugins()) or fx.bundled_plugins()
            except NanoleafError as e:
                log.warning("requestPlugins failed on %s (%s); using bundled catalogue", dev.label, e)
                self._plugins[dev.key] = fx.bundled_plugins()
        return self._plugins[dev.key]

    def build_effect(self, dev: Device, c: NanoleafClient, name: str, colors: list, plugin: str,
                     options: dict | None, palette_brightness: int | None) -> tuple[dict, dict, list[str]]:
        plugins = self.plugins(dev, c)
        p = fx.find_plugin(plugins, plugin)
        if p is None:
            raise LookupError(f"Unknown plugin {plugin!r} on {dev.label}. Available: "
                              + ", ".join(f"{q['name']} ({q['type']})" for q in plugins))
        palette = fx.build_palette(colors, palette_brightness)
        body, warnings = fx.plugin_effect(name, palette, p, options)
        return body, p, warnings

    def create_effect(self, device: str | None, name: str, colors: list, plugin: str, options: dict | None = None,
                      mode: str = "save", duration_s: int | None = None, activate: bool = True,
                      palette_brightness: int | None = None, device_brightness: int | None = None) -> dict:
        mode = (mode or "save").lower()
        if mode not in ("save", "preview", "flash"):
            raise ValueError("mode must be save | preview | flash")
        def go(d, c):
            body, p, warnings = self.build_effect(d, c, name, colors, plugin, options, palette_brightness)
            if mode == "save":
                existing = _match_name(c.effects_list(), name, exact=True)
                if existing:
                    c.delete_effect(existing)
                    warnings.append(f"replaced existing effect {existing!r}")
                c.add_effect(body)
                if activate:
                    c.select_effect(name)
            elif mode == "preview":
                c.display_effect(body)
            else:
                c.display_effect(body, duration_s or 10)
            if activate or mode != "save":
                c.set_state(on=True, brightness=device_brightness)
            return {"effect": name, "plugin": p["name"], "plugin_type": p["type"], "mode": mode,
                    "palette": body["palette"], "options": body.get("pluginOptions", []),
                    "warnings": warnings, "saved": mode == "save", "active": activate or mode != "save"}
        return self.each(device, go)

    def apply_effect_json(self, device: str | None, effect: dict, mode: str = "save", activate: bool = True) -> dict:
        """Escape hatch: send a hand-written effect body (any animType)."""
        def go(d, c):
            if mode == "save":
                c.add_effect(effect)
                if activate:
                    c.select_effect(effect["animName"])
            else:
                c.display_effect(effect)
            return {"effect": effect.get("animName"), "mode": mode}
        return self.each(device, go)

    def static_scene(self, device: str | None, panel_colors: dict, name: str | None = None,
                     transition_s: float = 1.0, mode: str = "preview", fill: str | None = None) -> dict:
        def go(d, c):
            ids = [p["panelId"] for p in c.layout().get("positionData", [])]
            colors = {int(k): v for k, v in panel_colors.items()}
            unknown = [k for k in colors if k not in ids]
            if unknown:
                raise ValueError(f"{d.label} has no panels {unknown}; its panel ids are {ids}")
            if fill:
                for pid in ids:
                    colors.setdefault(pid, fill)
            body = fx.static_effect(name or "Static scene", colors, int(transition_s * 10))
            if mode == "save":
                if not name:
                    raise ValueError("name is required to save")
                existing = _match_name(c.effects_list(), name, exact=True)
                if existing:
                    c.delete_effect(existing)
                c.add_effect(body)
                c.select_effect(name)
            else:
                c.display_effect(body)
            c.set_state(on=True)
            return {"panels_set": sorted(colors), "mode": mode}
        return self.each(device, go)

    def custom_animation(self, device: str | None, name: str, panel_frames: dict, loop: bool = True,
                         mode: str = "save") -> dict:
        def go(d, c):
            body = fx.custom_effect(name, {int(k): v for k, v in panel_frames.items()}, loop)
            if mode == "save":
                existing = _match_name(c.effects_list(), name, exact=True)
                if existing:
                    c.delete_effect(existing)
                c.add_effect(body)
                c.select_effect(name)
            else:
                c.display_effect(body)
            c.set_state(on=True)
            return {"effect": name, "mode": mode, "frames": {k: len(v) for k, v in panel_frames.items()}}
        return self.each(device, go)

    # ------------------------------------------------------------------ layout / rhythm
    def layout(self, dev: Device, c: NanoleafClient) -> dict:
        lay = c.layout()
        pos = lay.get("positionData", [])
        xs = [p["x"] for p in pos] or [0]; ys = [p["y"] for p in pos] or [0]
        orient = c.global_orientation()
        rh = c.rhythm() or {}
        return {"label": dev.label, "num_panels": lay.get("numPanels"), "side_length": lay.get("sideLength"),
                "global_orientation": orient.get("value") if isinstance(orient, dict) else orient,
                "bounds": {"min_x": min(xs), "max_x": max(xs), "min_y": min(ys), "max_y": max(ys)},
                "panels": sorted(pos, key=lambda p: (p["x"], p["y"])),
                "rhythm_position": rh.get("rhythmPos"),
                "note": "x grows to the right, y grows upward; o is the panel rotation in degrees. Triangles have shapeType 0."}

    def set_rhythm_mode(self, device: str | None, mode: str) -> dict:
        m = {"mic": 0, "microphone": 0, "0": 0, "aux": 1, "1": 1}.get(str(mode).lower())
        if m is None:
            raise ValueError("mode must be 'microphone' or 'aux'")
        return self.each(device, lambda d, c: (c.set_rhythm_mode(m), {"rhythm_mode": "aux" if m else "microphone"})[1])

    # ------------------------------------------------------------------ streaming (external control)
    def _streamer(self, dev: Device, c: NanoleafClient) -> Streamer:
        s = self._streams.get(dev.key)
        if s is None:
            self._pre_stream[dev.key] = self.snapshot(dev, c)
            s = Streamer(c)
            s.start()
            self._streams[dev.key] = s
        return s

    def stream_frame(self, device: str | None, panel_colors: dict, transition_tenths: int = 1, fill: str | None = None) -> dict:
        def go(d, c):
            s = self._streamer(d, c)
            frame = {}
            if fill:
                for p in c.layout().get("positionData", []):
                    r, g, b = fx.hsb_to_rgb(*fx.parse_color(fill))
                    frame[p["panelId"]] = (r, g, b, transition_tenths)
            for pid, col in panel_colors.items():
                r, g, b = fx.hsb_to_rgb(*fx.parse_color(col))
                frame[int(pid)] = (r, g, b, transition_tenths)
            s.send(frame)
            return {"streamed_panels": len(frame), "protocol": s.version}
        return self.each(device, go)

    def stream_animation(self, device: str | None, frames: list, fps: float = 10.0, transition_tenths: int = 1) -> dict:
        fps = max(0.5, min(30.0, float(fps)))
        if len(frames) > 1800:
            raise ValueError("Max 1800 frames per call (60 s at 30 fps); call again to continue.")
        def go(d, c):
            s = self._streamer(d, c)
            def gen():
                for f in frames:
                    if isinstance(f, dict) and "panels" in f:
                        t = int(f.get("transition", transition_tenths)); pc = f["panels"]
                    else:
                        t = transition_tenths; pc = f
                    yield {int(pid): (*fx.hsb_to_rgb(*fx.parse_color(col)), t) for pid, col in pc.items()}
            n = s.play(gen(), fps)
            return {"frames_sent": n, "fps": fps, "protocol": s.version}
        return self.each(device, go)

    def stop_streaming(self, device: str | None, restore: bool = True) -> dict:
        def go(d, c):
            s = self._streams.pop(d.key, None)
            if s:
                s.close()
            snap = self._pre_stream.pop(d.key, None)
            if restore and snap:
                self.restore(d, c, snap)
                return {"stopped": True, "restored": snap.get("effect") or snap.get("colorMode")}
            return {"stopped": bool(s)}
        return self.each(device, go)

    # ------------------------------------------------------------------ rendering
    def render(self, dev: Device, c: NanoleafClient, panel_colors: dict | None = None, effect: str | None = None,
               ansi: bool = False, width: int = 100, svg_path: str | None = None, labels: bool | None = None,
               at_s: float | None = None) -> str:
        """ASCII picture of the layout (app orientation). Colours from panel_colors, or from a saved static effect.
        With svg_path, also writes the same picture as an SVG file."""
        lay = c.layout(); go = c.global_orientation()["value"]
        colors = dict(panel_colors or {})
        if effect:
            target = _match_name(c.effects_list(), effect)
            if not target:
                raise LookupError(f"No effect named {effect!r} on {dev.label}")
            body = c.request_effect(target)
            if body.get("animType") in ("static", "custom") and body.get("animData"):
                colors = (colors_at(anim_data_frames(body["animData"]), at_s * 10) if at_s is not None
                          else anim_data_colors(body["animData"]))
            else:
                raise ValueError(f"{target!r} is a {body.get('animType')} effect; only static/custom effects have fixed panel colours")
        header = f"{dev.label} — {lay.get('numPanels')} panels, rotated {go}° as in the app" + (f", effect {effect!r}" if effect else "")
        if at_s is not None:
            header += f" at {at_s:.1f}s"
        if svg_path:
            Path(svg_path).expanduser().write_text(_render_svg(lay["positionData"], go, colors))
            header += f" (svg: {svg_path})"
        return header + "\n" + _render(lay["positionData"], go, colors, width=width, ansi=ansi, labels=labels)

    def play(self, dev: Device, c: NanoleafClient, effect: str, fps: float = 10.0, loops: int = 2,
             width: int = 100, ansi: bool = True, labels: bool | None = None):
        """Yield (frame_text, seconds) for a saved custom animation so a terminal can animate it."""
        target = _match_name(c.effects_list(), effect)
        if not target:
            raise LookupError(f"No effect named {effect!r} on {dev.label}")
        body = c.request_effect(target)
        if body.get("animType") not in ("static", "custom") or not body.get("animData"):
            raise ValueError(f"{target!r} is a {body.get('animType')} effect; only custom/static effects can be played back")
        frames = anim_data_frames(body["animData"])
        total = anim_loop_tenths(frames) / 10 or 1.0
        lay = c.layout(); go = c.global_orientation()["value"]
        step = 1.0 / max(1.0, fps)
        t = 0.0
        while t < total * loops:
            colors = colors_at(frames, (t % total) * 10)
            yield (f"{dev.label} — {target!r}  t={t % total:4.1f}s / {total:.1f}s loop\n"
                   + _render(lay["positionData"], go, colors, width=width, ansi=ansi, legend=False, labels=labels)), step
            t += step

    # ------------------------------------------------------------------ one-shot playback & sound trigger
    def one_shot_body(self, c: NanoleafClient, effect: str) -> tuple[dict, float]:
        """A saved custom animation as a non-looping body, plus its duration in seconds."""
        target = _match_name(c.effects_list(), effect)
        if not target:
            raise LookupError(f"No effect named {effect!r}")
        body = c.request_effect(target)
        if body.get("animType") != "custom" or not body.get("animData"):
            raise ValueError(f"{target!r} is a {body.get('animType')} effect; one-shot playback needs a custom keyframe animation")
        body = {k: v for k, v in body.items() if k != "animName"} | {"animName": target, "loop": False}
        return body, anim_loop_tenths(anim_data_frames(body["animData"])) / 10

    def idle_body_for(self, body: dict) -> dict:
        """Static scene equal to the animation's final frame (what the panels hold after a one-shot)."""
        frames = anim_data_frames(body["animData"])
        colors = {pid: "#%02x%02x%02x" % seq[-1][0] for pid, seq in frames.items()}
        return fx.static_effect(body["animName"] + " (idle)", colors, 5)

    def play_once(self, device: str | None, effect: str) -> dict:
        def go(d, c):
            body, dur = self.one_shot_body(c, effect)
            c.display_effect(body)
            c.set_state(on=True)
            return {"played": body["animName"], "duration_s": dur}
        return self.each(device, go)

    def show_idle(self, device: str | None, effect: str) -> dict:
        def go(d, c):
            body, _ = self.one_shot_body(c, effect)
            c.display_effect(self.idle_body_for(body))
            c.set_state(on=True)
            return {"idle_for": body["animName"]}
        return self.each(device, go)

    # background listener processes (survive MCP server restarts via pid files)
    def _pidfile(self, dev: Device) -> Path:
        return self.reg.path.parent / f"listen-{dev.key}.pid"

    def start_sound_trigger(self, device: str, effect: str, sensitivity_db: float = 18, min_db: float = -30,
                            cooldown_s: float = 8, input_device: str | None = None) -> dict:
        devs = self.targets(device)
        for dev in devs:
            self.one_shot_body(self.client(dev), effect)   # validate on every device before spawning
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            raise RuntimeError("the clap listener needs the 'sound' extra: uv sync --extra sound")
        self.stop_sound_trigger(device)
        log_path = self.reg.path.parent / f"listen-{devs[0].key}.log"
        cmd = [sys.executable, "-m", "nanoleaf_mcp.cli", "-d", device or "all", "listen", "--effect", effect,
               "--sensitivity", str(sensitivity_db), "--min-db", str(min_db), "--cooldown", str(cooldown_s)]
        if input_device:
            cmd += ["--input", input_device]
        proc = subprocess.Popen(cmd, stdout=open(log_path, "ab"), stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        for dev in devs:
            self._pidfile(dev).write_text(str(proc.pid))
        return {"listening": True, "pid": proc.pid, "devices": [d.label for d in devs], "effect": effect, "log": str(log_path),
                "note": "This computer's microphone is the sound source; the animation starts on every device at once on each clap."}

    def stop_sound_trigger(self, device: str | None = "all") -> dict:
        out = {}
        killed: set[int] = set()
        for dev in self.targets(device):
            pf = self._pidfile(dev)
            if not pf.exists():
                out[dev.label] = {"listening": False}
                continue
            try:
                pid = int(pf.read_text().strip())
                if pid not in killed:
                    os.killpg(pid, signal.SIGTERM)
                    killed.add(pid)
                out[dev.label] = {"stopped": True, "pid": pid}
            except (ValueError, ProcessLookupError, PermissionError) as e:
                out[dev.label] = {"stopped": False, "error": str(e)}
            pf.unlink(missing_ok=True)
        return out

    def sound_trigger_status(self, device: str | None = "all") -> dict:
        out = {}
        for dev in self.targets(device):
            pf = self._pidfile(dev)
            alive = False
            if pf.exists():
                try:
                    os.kill(int(pf.read_text().strip()), 0); alive = True
                except (ValueError, ProcessLookupError, PermissionError):
                    alive = False
            out[dev.label] = {"listening": alive, "log": str(self.reg.path.parent / f"listen-{dev.key}.log")}
        return out

    # ------------------------------------------------------------------ multi-controller scenes
    def sync_play(self, effect_by_device: dict[str, str], bodies: dict[str, tuple[dict, float]] | None = None) -> dict:
        """Start one-shot playback of the given effect on each device at the same instant (parallel threads
        released by a barrier). Returns per-device results and the spread between send times in ms.
        bodies: optional pre-fetched {device: (body, duration)} so a trigger fires without an extra round trip."""
        plan = []
        for q, effect in effect_by_device.items():
            dev, c = self.one(q)
            body, dur = bodies[q] if bodies and q in bodies else self.one_shot_body(c, effect)
            plan.append((dev, c, body, dur))
        if not plan:
            raise ValueError("no devices to play on")
        barrier = threading.Barrier(len(plan))
        results: dict[str, Any] = {}
        sent: dict[str, float] = {}

        def fire(dev, c, body, dur):
            try:
                barrier.wait(timeout=5)
            except threading.BrokenBarrierError:
                pass
            sent[dev.label] = time.perf_counter()
            try:
                c.display_effect(body)
                c.set_state(on=True)
                results[dev.label] = {"played": body["animName"], "duration_s": dur}
            except NanoleafError as e:
                results[dev.label] = {"error": str(e)}

        threads = [threading.Thread(target=fire, args=p, daemon=True) for p in plan]
        for th in threads: th.start()
        for th in threads: th.join()
        spread_ms = (max(sent.values()) - min(sent.values())) * 1000 if len(sent) > 1 else 0.0
        return {"devices": results, "start_spread_ms": round(spread_ms, 1)}

    # ------------------------------------------------------------------ scenes (layout-agnostic animations)
    def geo_for(self, devices: list[str] | None, gap_widths: float = 2.0, align: str = "top"):
        """Shared coordinate space over the given devices (labels in left-to-right physical order; default: every
        registered device in registry order). Returns (geo, devices, clients, layouts)."""
        labels = devices or [d.label for d in self.targets("all")]
        devs, clients, layouts, specs = [], {}, {}, []
        for q in labels:
            dev, c = self.one(q)
            if dev.key in clients:
                continue
            devs.append(dev); clients[dev.key] = c
            lay = c.layout(); go = c.global_orientation()["value"]
            layouts[dev.key] = (lay["positionData"], go)
            specs.append((dev.key, lay["positionData"], go))
        return _scenes.geo_from_layouts(specs, gap_widths, align), devs, clients, layouts

    def list_scenes(self) -> list[dict]:
        return _scenes.list_scenes()

    def preview_scene(self, devices: list[str] | None, scene: str, at_s: float = 0.0, params: dict | None = None,
                      gap_widths: float = 2.0, align: str = "top", ansi: bool = False, width: int = 90,
                      labels: bool | None = None, svg_path: str | None = None) -> dict:
        """Render each device's layout with the scene's colours at time at_s (ASCII/ANSI, optional SVG)."""
        geo, devs, clients, layouts = self.geo_for(devices, gap_widths, align)
        fn, duration, spec = _scenes.build(scene, geo, params)
        cols = _scenes.colours_at(geo, fn, at_s)
        out = {}
        for d in devs:
            pos, go = layouts[d.key]
            header = f"{d.label} — {spec.title} at {at_s:.1f}s" + (f" of {duration:.1f}s" if duration else "")
            if svg_path:
                path = Path(svg_path).expanduser()
                if len(devs) > 1:
                    path = path.with_name(f"{path.stem}-{d.key}{path.suffix}")
                path.write_text(_render_svg(pos, go, cols[d.key]))
                header += f" (svg: {path})"
            out[d.label] = header + "\n" + _render(pos, go, cols[d.key], width=width, ansi=ansi, labels=labels, legend=False)
        return out

    def _save_effect_quietly(self, dev: Device, c: NanoleafClient, body: dict) -> dict:
        """Add (or replace) an effect without changing what is showing. Firmware 5.x switches to a freshly
        added effect, so the previous display is put back afterwards."""
        name = body["animName"]
        names = c.effects_list()
        existing = _match_name(names, name, exact=True)
        before = self.snapshot(dev, c)
        if existing:
            if before.get("effect") == existing:
                c.select_effect(existing)  # will be replaced below; keep it selected afterwards
            c.delete_effect(existing)
        elif len(names) >= MAX_STORED_EFFECTS:
            raise NanoleafError(f"{dev.label} already stores {len(names)} effects, the controller's limit is {MAX_STORED_EFFECTS}; "
                                f"delete some (delete_effect) before saving {name!r}", 400)
        try:
            c.add_effect(body)
        except NanoleafError as e:
            if e.status == 400 and len(names) >= MAX_STORED_EFFECTS - 1:
                raise NanoleafError(f"{dev.label} refused the effect; it stores {len(names)} effects and the controller's limit is "
                                    f"{MAX_STORED_EFFECTS}. Delete some with delete_effect and retry.", 400) from e
            raise
        res: dict[str, Any] = {"saved": name}
        if before.get("effect") == existing and existing:
            c.select_effect(name)
            res["replaced_showing"] = True
        elif c.selected_effect() != before.get("effect"):
            prev = before.get("effect") or ""
            if before.get("colorMode") in ("ct", "hs") or (prev and not prev.startswith("*")):
                self.restore(dev, c, before)          # a saved effect, a solid colour or a white temperature
                res["restored"] = prev if not prev.startswith("*") else before.get("colorMode")
            else:
                c.set_state(on=before.get("on"))
                res["warning"] = f"the controller switched to {name!r}; the previous unsaved display ({prev}) cannot be restored"
        return res

    def save_scene(self, devices: list[str] | None, scene: str, name: str | None = None, params: dict | None = None,
                   gap_widths: float = 2.0, align: str = "top", step_tenths: int = 1, activate: bool = False,
                   max_seconds: float = 60.0) -> dict:
        """Sample a scene into keyframes (or a static design) and store it on each controller as an effect named
        `name` (default: the scene title). Stored effects run with no computer; across several controllers start
        them together with sync_play (one-shots) or activate=True (loops)."""
        geo, devs, clients, _ = self.geo_for(devices, gap_widths, align)
        fn, duration, spec = _scenes.build(scene, geo, params)
        name = name or spec.title
        out: dict[str, Any] = {"scene": spec.name, "effect": name, "loop": spec.loop, "static": spec.static,
                               "duration_s": round(duration, 1), "devices": {}}
        if spec.static:
            cols = _scenes.colours_at(geo, fn, 0.0)
            bodies = {d.key: fx.static_effect(name, cols[d.key], 10) for d in devs}
        else:
            if duration <= 0:
                raise ValueError(f"{spec.title} has no duration")
            secs = min(duration, max_seconds)
            if secs < duration:
                out["warning"] = f"loop truncated to {secs:.0f}s of {duration:.1f}s (raise max_seconds to keep more)"
            frames = _scenes.sample_keyframes(geo, fn, secs, step_tenths)
            bodies = {d.key: fx.custom_effect(name, frames[d.key], spec.loop) for d in devs}
            out["keyframes"] = {d.label: sum(len(v) for v in frames[d.key].values()) for d in devs}
        for d in devs:
            try:
                out["devices"][d.label] = self._save_effect_quietly(d, clients[d.key], bodies[d.key])
                if activate:
                    clients[d.key].select_effect(name); clients[d.key].set_state(on=True)
                    out["devices"][d.label]["active"] = True
            except (NanoleafError, LookupError, ValueError) as e:
                out["devices"][d.label] = {"error": str(e)}
        return out

    # ------------------------------------------------------------------ presets (palette + on-device plugin)
    def list_presets(self) -> list[dict]:
        return _presets.list_presets()

    def apply_preset(self, device: str | None, name: str, brightness: int | None = None) -> dict:
        key, p = _presets.get(name)
        b = brightness if brightness is not None else p.get("brightness")
        if "white" in p:
            return {"preset": key, **self.set_color(device, p["white"], b)}
        res = self.create_effect(device, p["title"], p["colors"], p["plugin"], p.get("options"), "save", None, True, None, b)
        return {"preset": key, **res}

    # ------------------------------------------------------------------ live streaming across controllers
    def live_show(self, devices: list[str] | None, scene: str = "ombre", params: dict | None = None,
                  gap_widths: float = 2.0, align: str = "top", fps: float = 20.0, seconds: float | None = None,
                  brightness: int | None = None) -> dict:
        """Render `scene` on this computer over the shared space and stream it to every controller until `seconds`
        elapse (or forever). Restores each controller's previous display afterwards."""
        from . import live
        geo, devs, clients, _ = self.geo_for(devices, gap_widths, align)
        fn, duration, spec = _scenes.build(scene, geo, params)
        snaps = {d.key: self.snapshot(d, clients[d.key]) for d in devs}
        if brightness is not None:
            for d in devs:
                clients[d.key].set_state(brightness=max(0, min(100, int(brightness))))
        show = live.LiveShow(devs, clients, geo, fn, fps)
        try:                                   # a plain kill (SIGTERM) must still restore the previous scenes
            signal.signal(signal.SIGTERM, lambda *_: show.stop.set())
        except ValueError:
            pass                               # not on the main thread
        try:
            stats = show.run(seconds)
        finally:
            for d in devs:
                try:
                    self.restore(d, clients[d.key], snaps[d.key])
                except NanoleafError:
                    pass
        return {"scene": spec.name, "devices": [d.label for d in devs], "panels": len(geo.panels), **stats}

    def _live_pidfile(self) -> Path:
        return self.reg.path.parent / "live.pid"

    def start_live_scene(self, devices: list[str] | None, scene: str = "ombre", params: dict | None = None,
                         gap_widths: float = 2.0, align: str = "top", fps: float = 20.0, seconds: float | None = None,
                         brightness: int | None = None) -> dict:
        """Run live_show in a background process (survives MCP restarts; see stop_live_scene / live_status)."""
        geo, devs, _, _ = self.geo_for(devices, gap_widths, align)
        _scenes.build(scene, geo, params)                   # validate scene + params before spawning
        self.stop_live_scene()
        labels = [d.label for d in devs]
        log_path = self.reg.path.parent / "live.log"
        cmd = [sys.executable, "-m", "nanoleaf_mcp.cli", "live", *labels, "--scene", scene, "--gap", str(gap_widths),
               "--align", align, "--fps", str(fps)]
        if params:
            cmd += ["--params", json.dumps(params)]
        if seconds:
            cmd += ["--seconds", str(seconds)]
        if brightness is not None:
            cmd += ["--brightness", str(int(brightness))]
        proc = subprocess.Popen(cmd, stdout=open(log_path, "ab"), stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                start_new_session=True)
        self._live_pidfile().write_text(str(proc.pid))
        return {"streaming": True, "pid": proc.pid, "scene": scene, "devices": labels, "fps": fps,
                "seconds": seconds or "until stopped", "log": str(log_path),
                "note": "Frames come from this computer; the panels return to their previous scene when stopped."}

    def stop_live_scene(self) -> dict:
        pf = self._live_pidfile()
        if not pf.exists():
            return {"streaming": False}
        try:
            pid = int(pf.read_text().strip())
            os.killpg(pid, signal.SIGINT)          # SIGINT lets the show restore the previous displays
            for _ in range(30):
                time.sleep(0.1)
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
            out = {"stopped": True, "pid": pid}
        except (ValueError, ProcessLookupError, PermissionError) as e:
            out = {"stopped": False, "error": str(e)}
        pf.unlink(missing_ok=True)
        return out

    def live_status(self) -> dict:
        pf = self._live_pidfile()
        alive = False
        if pf.exists():
            try:
                os.kill(int(pf.read_text().strip()), 0); alive = True
            except (ValueError, ProcessLookupError, PermissionError):
                alive = False
        return {"streaming": alive, "log": str(self.reg.path.parent / "live.log")}

    # ------------------------------------------------------------------ raw
    def raw(self, device: str | None, method: str, path: str, body: Any = None) -> dict:
        return self.each(device, lambda d, c: {"response": c.request(method.upper(), path, body)})


def _match_name(names: list[str], query: str, exact: bool = False) -> str | None:
    q = query.strip().lower()
    for n in names:
        if n.strip().lower() == q:
            return n
    if exact:
        return None
    hits = [n for n in names if q in n.lower()]
    return hits[0] if len(hits) == 1 else None


def _parse_ct(color: str) -> int | None:
    s = str(color).strip().lower()
    import re
    m = re.fullmatch(r"(?:ct[:=]?\s*)?(\d{4})\s*k?", s)
    if m:
        return max(1200, min(6500, int(m.group(1))))
    presets = {"candle": 2000, "warm": 2700, "warm white": 2700, "soft white": 3000, "neutral": 4000,
               "natural": 4000, "cool": 5000, "cool white": 5000, "daylight": 6500}
    return presets.get(s)
