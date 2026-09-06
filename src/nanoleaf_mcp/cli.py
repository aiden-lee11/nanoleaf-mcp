"""`nanoleaf` command line: the same operations the MCP server exposes, for setup, scripting and quick checks."""
from __future__ import annotations

import argparse
import json
import sys
import time

from .core import Nanoleaf


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _kv(pairs: list[str] | None) -> dict:
    out = {}
    for kv in pairs or []:
        k, _, v = kv.partition("=")
        try:
            out[k] = json.loads(v)
        except json.JSONDecodeError:
            out[k] = v
    return out


def _params(a) -> dict:
    p = json.loads(a.params) if getattr(a, "params", None) else {}
    p.update(_kv(getattr(a, "param", None)))
    return p


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="nanoleaf", description="Control Nanoleaf panels over the local OpenAPI")
    p.add_argument("-d", "--device", default="all", help="device label / name / ip / serial, or 'all' (default)")
    sub = p.add_subparsers(dest="cmd", required=True)

    # setup
    sub.add_parser("discover", help="scan the LAN and register controllers")
    sub.add_parser("import-tokens", help="reuse the Nanoleaf Desktop app's auth tokens (macOS)")
    sub.add_parser("pair", help="pair (hold the controller's power button 5-7 s first)")
    sub.add_parser("devices", help="list registered devices")
    lb = sub.add_parser("label", help="give a device a friendly label"); lb.add_argument("label")
    sub.add_parser("status", help="state, current effect, rhythm info")
    sub.add_parser("identify", help="flash the panels")

    # basic state
    sub.add_parser("on"); sub.add_parser("off")
    b = sub.add_parser("brightness"); b.add_argument("value", type=int); b.add_argument("--fade", type=float, default=0)
    c = sub.add_parser("color"); c.add_argument("color"); c.add_argument("--brightness", type=int)

    # saved effects
    sub.add_parser("effects", help="list saved effects")
    e = sub.add_parser("effect", help="activate a saved effect"); e.add_argument("name")
    g = sub.add_parser("show", help="print an effect's JSON"); g.add_argument("name")
    dl = sub.add_parser("delete"); dl.add_argument("name")
    pl = sub.add_parser("plugins", help="motion plugins on the device"); pl.add_argument("--refresh", action="store_true")
    cr = sub.add_parser("create", help="create a palette+plugin effect")
    cr.add_argument("name"); cr.add_argument("--plugin", required=True); cr.add_argument("--colors", nargs="+", required=True)
    cr.add_argument("--option", action="append", default=[], metavar="KEY=VALUE")
    cr.add_argument("--mode", choices=["save", "preview", "flash"], default="save")
    cr.add_argument("--duration", type=int); cr.add_argument("--palette-brightness", type=int); cr.add_argument("--brightness", type=int)
    sub.add_parser("presets", help="list mood presets")
    pr = sub.add_parser("preset", help="apply a mood preset (palette + on-device plugin)"); pr.add_argument("name"); pr.add_argument("--brightness", type=int)

    # layout & rendering
    sub.add_parser("layout")
    rd = sub.add_parser("render", help="picture of the layout, optionally coloured from an effect, colours, or a scene")
    rd.add_argument("--effect", help="colour it from a saved static/custom effect"); rd.add_argument("--colors", help='JSON {"panelId": colour}')
    rd.add_argument("--scene", help="colour it from a scene (see `scenes`)"); rd.add_argument("--param", action="append", metavar="KEY=VALUE")
    rd.add_argument("--at", type=float, help="time in seconds to sample (effects and scenes)")
    rd.add_argument("--play", action="store_true", help="animate a custom effect in the terminal")
    rd.add_argument("--fps", type=float, default=10); rd.add_argument("--loops", type=int, default=2)
    rd.add_argument("--width", type=int, default=100)
    rd.add_argument("--plain", action="store_true", help="shade blocks instead of ANSI colours")
    rd.add_argument("--color", action="store_true", help="force 24-bit ANSI colours even when piped")
    rd.add_argument("--svg", metavar="PATH", help="also write the picture as an SVG file")
    rd.add_argument("--ids", dest="ids", action="store_true", default=None, help="draw panel ids")
    rd.add_argument("--no-ids", dest="ids", action="store_false", help="hide panel ids")
    rd.add_argument("--order", nargs="+", help="device labels left to right (scenes spanning several controllers)")
    rd.add_argument("--gap", type=float, default=2.0); rd.add_argument("--align", choices=["top", "bottom", "middle"], default="top")

    # scenes
    sub.add_parser("scenes", help="list built-in scenes (layout-agnostic animations)")
    sv = sub.add_parser("save-scene", help="sample a scene into keyframes and store it on the controller(s)")
    sv.add_argument("scene"); sv.add_argument("--as", dest="name", help="effect name (default: scene title)")
    sv.add_argument("--order", nargs="+", help="device labels left to right (default: all registered)")
    sv.add_argument("--param", action="append", metavar="KEY=VALUE"); sv.add_argument("--params", help="JSON object of parameters")
    sv.add_argument("--gap", type=float, default=2.0); sv.add_argument("--align", choices=["top", "bottom", "middle"], default="top")
    sv.add_argument("--step", type=int, default=1, help="keyframe step in tenths of a second")
    sv.add_argument("--max-seconds", type=float, default=60.0); sv.add_argument("--activate", action="store_true")
    lv = sub.add_parser("live", help="stream a scene from this computer across controllers (Ctrl-C to stop)")
    lv.add_argument("order", nargs="*", help="device labels left to right (default: all registered)")
    lv.add_argument("--scene", default="ombre"); lv.add_argument("--param", action="append", metavar="KEY=VALUE"); lv.add_argument("--params")
    lv.add_argument("--gap", type=float, default=2.0); lv.add_argument("--align", choices=["top", "bottom", "middle"], default="top")
    lv.add_argument("--fps", type=float, default=20); lv.add_argument("--seconds", type=float); lv.add_argument("--brightness", type=int)
    sub.add_parser("live-stop", help="stop a background live stream")
    sp = sub.add_parser("sync-play", help="start a one-shot effect on all matching devices at the same instant"); sp.add_argument("effect")
    po = sub.add_parser("play-once", help="play a saved custom animation once, then hold its last frame"); po.add_argument("effect")
    mk = sub.add_parser("mock", help="HTML player: every scene on hypothetical layouts, for planning a rebuild")
    mk.add_argument("--layout", action="append", help="e.g. 4x8-2, 5x6, 3x10 (repeatable)")
    mk.add_argument("--scene", action="append", help="limit to these scenes"); mk.add_argument("--out", default="mock.html")
    mk.add_argument("--fps", type=int, default=15)

    # sound
    ls = sub.add_parser("listen", help="play a one-shot effect on the panels when this computer's mic hears a clap")
    ls.add_argument("--effect", required=True); ls.add_argument("--sensitivity", type=float, default=18)
    ls.add_argument("--min-db", type=float, default=-30); ls.add_argument("--cooldown", type=float, default=8)
    ls.add_argument("--meter", action="store_true"); ls.add_argument("--input", help="microphone name/index (default: built-in)")
    rm = sub.add_parser("rhythm-mode"); rm.add_argument("mode", choices=["microphone", "aux"])

    # camera debugger
    cm = sub.add_parser("camera", help="camera-in-the-loop debugging (needs the 'camera' extra)")
    cm.add_argument("action", choices=["calibrate", "map", "check", "snap"])
    cm.add_argument("--camera", type=int, default=0, help="OpenCV camera index (0 = first camera)")
    cm.add_argument("--brightness", type=int, default=30, help="panel brightness during calibration")
    cm.add_argument("--scene"); cm.add_argument("--effect"); cm.add_argument("--at", type=float, default=0.0)
    cm.add_argument("--param", action="append", metavar="KEY=VALUE"); cm.add_argument("--out", help="image path")

    # streaming & raw
    sub.add_parser("stream-test", help="stream a short colour sweep over UDP, then restore")
    sub.add_parser("stop-stream")
    rw = sub.add_parser("raw"); rw.add_argument("method"); rw.add_argument("path"); rw.add_argument("--body")
    sub.add_parser("serve", help="run the MCP server (stdio)")

    a = p.parse_args(argv)
    nl = Nanoleaf()
    d = a.device
    try:
        if a.cmd == "discover": _print(nl.discover())
        elif a.cmd == "import-tokens": _print(nl.import_desktop_app_tokens())
        elif a.cmd == "pair": _print(nl.pair(None if d == "all" else d))
        elif a.cmd == "devices": _print(nl.list_devices())
        elif a.cmd == "label": _print(nl.set_friendly_name(d, a.label))
        elif a.cmd == "status": _print(nl.each(d, nl.status))
        elif a.cmd == "identify": _print(nl.identify(d))
        elif a.cmd == "on": _print(nl.set_power(d, True))
        elif a.cmd == "off": _print(nl.set_power(d, False))
        elif a.cmd == "brightness": _print(nl.set_brightness(d, a.value, a.fade))
        elif a.cmd == "color": _print(nl.set_color(d, a.color, a.brightness))
        elif a.cmd == "effects": _print(nl.each(d, nl.effects))
        elif a.cmd == "effect": _print(nl.activate(d, a.name))
        elif a.cmd == "show": _print(nl.each(d, lambda dv, c: nl.effect_detail(dv, c, a.name)))
        elif a.cmd == "delete": _print(nl.delete(d, a.name))
        elif a.cmd == "plugins":
            for label, plugins in nl.each(d, lambda dv, c: nl.plugins(dv, c, a.refresh)).items():
                print(f"== {label}")
                if isinstance(plugins, dict):
                    print("  ", plugins); continue
                for q in plugins:
                    opts = ", ".join(f"{o['name']}({o.get('min')}-{o.get('max')})" if o.get('min') is not None else o['name'] for o in q["options"])
                    print(f"  [{q['type']:6}] {q['name']:26} {opts}")
        elif a.cmd == "create":
            _print(nl.create_effect(d, a.name, a.colors, a.plugin, _kv(a.option), a.mode, a.duration, True, a.palette_brightness, a.brightness))
        elif a.cmd == "presets":
            for q in nl.list_presets():
                print(f"  {q['name']:18} {q['title']:18} {q['description']}")
        elif a.cmd == "preset": _print(nl.apply_preset(d, a.name, a.brightness))
        elif a.cmd == "layout": _print(nl.each(d, nl.layout))
        elif a.cmd == "render":
            from .render import want_color
            use_color = want_color(True if a.color else (False if a.plain else None))
            if a.play:
                if not a.effect:
                    raise ValueError("--play needs --effect NAME")
                dev, c = nl.one(d)
                lines = 0
                try:
                    for frame, dt in nl.play(dev, c, a.effect, a.fps, a.loops, a.width, use_color, a.ids):
                        if lines:
                            sys.stdout.write(f"\x1b[{lines}A")
                        sys.stdout.write("\x1b[J" + frame + "\n"); sys.stdout.flush()
                        lines = frame.count("\n") + 1
                        time.sleep(dt)
                except KeyboardInterrupt:
                    pass
            elif a.scene:
                order = a.order or (None if d == "all" else [d])
                for art in nl.preview_scene(order, a.scene, a.at or 0.0, _kv(a.param), a.gap, a.align, use_color, a.width, a.ids, a.svg).values():
                    print(art); print()
            else:
                cols = json.loads(a.colors) if a.colors else None
                for label, art in nl.each(d, lambda dv, c: nl.render(dv, c, cols, a.effect, ansi=use_color, width=a.width, svg_path=a.svg, labels=a.ids, at_s=a.at)).items():
                    print(art if isinstance(art, str) else f"{label}: {art}"); print()
        elif a.cmd == "scenes":
            for q in nl.list_scenes():
                kind = "static" if q["static"] else ("loop" if q["loop"] else "one-shot")
                params = ", ".join(f"{k}={v['default']}" for k, v in q["params"].items())
                print(f"  {q['name']:16} {q['title']:18} [{kind}{', rows>=' + str(q['min_rows']) if q['min_rows'] > 1 else ''}] {q['description']}" + (f"\n{'':37}params: {params}" if params else ""))
        elif a.cmd == "save-scene":
            order = a.order or (None if d == "all" else [d])
            _print(nl.save_scene(order, a.scene, a.name, _params(a), a.gap, a.align, a.step, a.activate, a.max_seconds))
        elif a.cmd == "live":
            order = a.order or (None if d == "all" else [d])
            try:
                _print(nl.live_show(order, a.scene, _params(a), a.gap, a.align, a.fps, a.seconds, a.brightness))
            except KeyboardInterrupt:
                print("\nstopped; previous scenes restored")
        elif a.cmd == "live-stop": _print(nl.stop_live_scene())
        elif a.cmd == "sync-play": _print(nl.sync_play({dev.label: a.effect for dev in nl.targets(d)}))
        elif a.cmd == "play-once": _print(nl.play_once(d, a.effect))
        elif a.cmd == "mock":
            from .mock import build_player
            html = build_player(a.layout or ["4x8-2", "5x6", "3x10"], a.scene, a.fps)
            open(a.out, "w").write(html)
            print(f"wrote {a.out} ({len(html) // 1024} KB); open it in a browser")
        elif a.cmd == "listen":
            from .sound import ClapConfig, ClapDetector
            devs = nl.targets(d)
            bodies = {dev.label: nl.one_shot_body(nl.client(dev), a.effect) for dev in devs}
            for dev in devs:
                nl.show_idle(dev.label, a.effect)
            dur = max(b[1] for b in bodies.values())
            cfg = ClapConfig(sensitivity_db=a.sensitivity, min_db=a.min_db, cooldown_s=max(a.cooldown, dur + 1), input=a.input)
            print(f"listening for a clap -> {a.effect!r} on {', '.join(bodies)} ({dur:.1f}s). Ctrl-C to stop.", flush=True)
            def fire(db):
                print(f"{time.strftime('%H:%M:%S')} clap at {db:.0f} dBFS -> playing", flush=True)
                res = nl.sync_play({label: a.effect for label in bodies}, bodies)
                print(f"  started on {len(res['devices'])} device(s), spread {res['start_spread_ms']} ms", flush=True)
            meter = (lambda db, floor: print(f"\r level {db:6.1f} dB  floor {floor:6.1f} dB   ", end="", flush=True)) if a.meter else None
            try:
                ClapDetector(cfg).run(fire, on_level=meter)
            except KeyboardInterrupt:
                print("\nstopped")
        elif a.cmd == "rhythm-mode": _print(nl.set_rhythm_mode(d, a.mode))
        elif a.cmd == "camera":
            from . import camera as cam
            from pathlib import Path
            if a.action == "snap":
                c_ = cam.Camera(a.camera); img = c_.grab(frames=3); c_.close()
                out = a.out or "camera-snap.jpg"; cam._cv2()[0].imwrite(out, img); print("wrote", out)
            elif a.action == "calibrate":
                _print(cam.calibrate(nl, d, a.camera, a.brightness))
            elif a.action == "map":
                calib = cam.load_calibration(nl, d)
                _print(cam.fit_layout(nl, d, calib))
                print("map image:", cam.draw_map(nl, d, calib, Path(a.out or "camera-map.jpg")))
            elif a.action == "check":
                _print(cam.check(nl, d, a.scene, a.effect, a.at, _kv(a.param), Path(a.out) if a.out else None))
        elif a.cmd == "stream-test":
            import colorsys
            for dev in nl.targets(d):
                ids = [pp["panelId"] for pp in nl.client(dev).layout()["positionData"]]
                seq = []
                for i in range(60):
                    r, g, b = [round(x * 255) for x in colorsys.hsv_to_rgb((i / 60) % 1.0, 1, 1)]
                    seq.append({pid: f"rgb({r},{g},{b})" for pid in ids})
                _print({dev.label: nl.stream_animation(dev.label, seq, fps=10, transition_tenths=1)})
            _print(nl.stop_streaming(d))
        elif a.cmd == "stop-stream": _print(nl.stop_streaming(d))
        elif a.cmd == "raw": _print(nl.raw(d, a.method, a.path, json.loads(a.body) if a.body else None))
        elif a.cmd == "serve":
            from .server import main as serve
            serve()
    except (LookupError, ValueError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
