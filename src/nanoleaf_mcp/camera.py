"""Camera-in-the-loop debugging: point a webcam at the panels and let the software *see* what is lit.

    nanoleaf camera calibrate -d wall     # lights each panel in turn, finds it in the image -> pixel map
    nanoleaf camera map -d wall           # draws the map next to the controller's layout, reports rotation / mirror
    nanoleaf camera check -d wall --scene heart          # expected vs seen, per panel, with an annotated photo
    nanoleaf camera check -d wall --effect "Heart"       # same for a stored effect

Needs the 'camera' extra (OpenCV). Calibration is stored per device in ~/.config/nanoleaf-mcp/camera-<key>.json.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from .effects import hsb_to_rgb, parse_color, rgb_to_hsb


def _cv2():
    try:
        import cv2  # noqa
        import numpy  # noqa
        return cv2, numpy
    except ImportError as e:
        raise RuntimeError("camera debugging needs the 'camera' extra: uv sync --extra camera") from e


class Camera:
    def __init__(self, index: int = 0, width: int = 1280, height: int = 720):
        cv2, _ = _cv2()
        self.cv2 = cv2
        self.cap = cv2.VideoCapture(index)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera {index} could not be opened (is the terminal allowed to use the camera?)")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width); self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        for _ in range(6):
            self.cap.read()

    def grab(self, settle: float = 0.0, frames: int = 3):
        """Average a few frames (reduces noise and rolling-shutter banding)."""
        _, np = _cv2()
        if settle:
            time.sleep(settle)
        for _ in range(2):
            self.cap.read()                       # flush stale frames
        acc = None
        for _ in range(frames):
            ok, f = self.cap.read()
            if not ok:
                raise RuntimeError("camera returned no frame")
            acc = f.astype("float32") if acc is None else acc + f
        return (acc / frames).astype("uint8")

    def close(self):
        self.cap.release()


def calib_path(reg_dir: Path, key: str) -> Path:
    return reg_dir / f"camera-{key}.json"


def calibrate(nl, device: str, camera: int = 0, brightness: int = 30, settle: float = 0.45, out_dir: Path | None = None) -> dict:
    """Light each panel alone (white, over UDP) and locate it in the camera image."""
    cv2, np = _cv2()
    dev, c = nl.one(device)
    ids = [p["panelId"] for p in c.layout()["positionData"]]
    snap = nl.snapshot(dev, c)
    cam = Camera(camera)
    try:
        c.set_state(on=True, brightness=brightness)
        nl.stream_frame(dev.label, {}, fill="black")
        dark = cam.grab(settle=1.0, frames=5).astype("int16")
        found: dict[int, dict[str, Any]] = {}
        weak: list[int] = []
        for pid in ids:
            nl.stream_frame(dev.label, {pid: "white"}, fill="black")
            img = cam.grab(settle=settle, frames=3).astype("int16")
            diff = np.clip(img - dark, 0, 255).astype("uint8")
            gray = cv2.cvtColor(diff, cv2.COLOR_BGR2GRAY)
            gray = cv2.GaussianBlur(gray, (9, 9), 0)
            peak = int(gray.max())
            if peak < 25:
                weak.append(pid); continue
            _, mask = cv2.threshold(gray, max(20, int(peak * 0.5)), 255, cv2.THRESH_BINARY)
            n, labels, stats, cents = cv2.connectedComponentsWithStats(mask)
            if n < 2:
                weak.append(pid); continue
            k = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
            cx, cy = cents[k]
            found[pid] = {"x": float(cx), "y": float(cy), "area": int(stats[k, cv2.CC_STAT_AREA]), "peak": peak}
        nl.stop_streaming(dev.label, restore=False)
        nl.restore(dev, c, snap)
    finally:
        cam.close()
    data = {"device": dev.key, "label": dev.label, "camera": camera, "brightness": brightness,
            "image_size": [int(dark.shape[1]), int(dark.shape[0])], "panels": found, "not_found": weak,
            "captured": time.strftime("%Y-%m-%d %H:%M:%S")}
    calib_path(nl.reg.path.parent, dev.key).write_text(json.dumps(data, indent=1))
    return {"calibrated": len(found), "not_found": weak, "file": str(calib_path(nl.reg.path.parent, dev.key))}


def load_calibration(nl, device: str) -> dict:
    dev, _ = nl.one(device)
    p = calib_path(nl.reg.path.parent, dev.key)
    if not p.exists():
        raise LookupError(f"no camera calibration for {dev.label}; run: nanoleaf camera calibrate -d {dev.label!r}")
    data = json.loads(p.read_text())
    data["panels"] = {int(k): v for k, v in data["panels"].items()}
    return data


def fit_layout(nl, device: str, calib: dict) -> dict:
    """Best similarity transform (scale, rotation, optional mirror) from the controller's layout to the camera map.
    Tells you whether the stored globalOrientation matches the wall and whether the layout is mirrored."""
    _, np = _cv2()
    from .render import oriented_triangles
    dev, c = nl.one(device)
    pos = c.layout()["positionData"]; go = c.global_orientation()["value"]
    tris = {t["id"]: t for t in oriented_triangles(pos, go)}
    ids = [i for i in calib["panels"] if i in tris]
    A = np.array([[tris[i]["cx"], tris[i]["cy"]] for i in ids])           # layout (y up)
    B = np.array([[calib["panels"][i]["x"], -calib["panels"][i]["y"]] for i in ids])   # image (flip y so up is up)
    best = None
    for mirror in (False, True):
        A2 = A.copy()
        if mirror:
            A2[:, 0] *= -1
        ca, cb = A2.mean(0), B.mean(0)
        H = (A2 - ca).T @ (B - cb)
        U, S, Vt = np.linalg.svd(H)
        R = Vt.T @ U.T
        if np.linalg.det(R) < 0:
            Vt[-1] *= -1; R = Vt.T @ U.T
        s = S.sum() / ((A2 - ca) ** 2).sum()
        fit = (s * (A2 - ca) @ R.T) + cb
        err = float(np.sqrt(((fit - B) ** 2).sum(1)).mean())
        ang = math.degrees(math.atan2(R[1, 0], R[0, 0]))
        if best is None or err < best["error_px"]:
            best = {"mirror": mirror, "rotation_deg": round(ang, 1), "error_px": round(err, 1), "scale": float(s)}
    spread = float(np.sqrt(((B - B.mean(0)) ** 2).sum(1)).mean())
    best["relative_error"] = round(best["error_px"] / max(1.0, spread), 3)
    best["verdict"] = ("layout matches the wall" if best["relative_error"] < 0.08 and abs(best["rotation_deg"]) < 8 and not best["mirror"]
                       else f"layout is {'MIRRORED and ' if best['mirror'] else ''}rotated {best['rotation_deg']}° relative to the wall"
                       if best["relative_error"] < 0.15 else "poor fit: recalibrate (check the camera sees every panel)")
    return best


def draw_map(nl, device: str, calib: dict, out: Path) -> Path:
    cv2, np = _cv2()
    w, h = calib["image_size"]
    cam = Camera(calib.get("camera", 0))
    try:
        img = cam.grab(frames=3)
    finally:
        cam.close()
    for pid, p in calib["panels"].items():
        cv2.circle(img, (int(p["x"]), int(p["y"])), 14, (0, 255, 255), 2)
        cv2.putText(img, str(pid), (int(p["x"]) - 12, int(p["y"]) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(img, str(pid), (int(p["x"]) - 12, int(p["y"]) + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 1)
    cv2.imwrite(str(out), img)
    return out


def check(nl, device: str, scene: str | None = None, effect: str | None = None, at_s: float = 0.0,
          params: dict | None = None, out: Path | None = None, radius: int = 9) -> dict:
    """Compare what the panels should show with what the camera sees at each calibrated panel position."""
    cv2, np = _cv2()
    calib = load_calibration(nl, device)
    dev, c = nl.one(device)
    if scene:
        from . import scenes as _scenes
        geo, devs, clients, _ = nl.geo_for([dev.label])
        fn, dur, spec = _scenes.build(scene, geo, params)
        expected = {int(k): v for k, v in _scenes.colours_at(geo, fn, at_s)[dev.key].items()}
        what = f"scene {spec.title!r} at {at_s:.1f}s"
    elif effect:
        from .render import anim_data_frames, colors_at, anim_data_colors
        target = effect
        body = c.request_effect(target)
        if body.get("animData"):
            expected = colors_at(anim_data_frames(body["animData"]), at_s * 10) if at_s else anim_data_colors(body["animData"])
        else:
            raise ValueError(f"{effect!r} is a plugin effect; the camera check needs a static/custom effect or a scene")
        what = f"effect {effect!r} at {at_s:.1f}s"
    else:
        expected = {}
        what = "whatever is showing"
    cam = Camera(calib.get("camera", 0))
    try:
        img = cam.grab(settle=0.3, frames=3)
    finally:
        cam.close()
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    rows, mism = [], 0
    for pid, p in calib["panels"].items():
        x, y = int(p["x"]), int(p["y"])
        patch = hsv[max(0, y - radius):y + radius, max(0, x - radius):x + radius]
        hh, ss, vv = patch[..., 0].mean() * 2, patch[..., 1].mean() / 2.55, patch[..., 2].mean() / 2.55
        seen_lit = vv > 30
        row = {"panel": pid, "seen": {"hue": round(float(hh)), "sat": round(float(ss)), "val": round(float(vv))}}
        if expected and pid in expected:
            eh, es, ev = parse_color(expected[pid])
            row["expected"] = {"hue": eh, "sat": es, "val": ev, "hex": expected[pid]}
            exp_lit = ev > 12
            if exp_lit != seen_lit:
                row["mismatch"] = "expected lit, seen dark" if exp_lit else "expected dark, seen lit"
            elif exp_lit and es > 30 and ss > 25:
                dh = min(abs(eh - hh), 360 - abs(eh - hh))
                if dh > 40:
                    row["mismatch"] = f"hue off by {dh:.0f}°"
            if "mismatch" in row:
                mism += 1
        rows.append(row)
        colour = (0, 0, 255) if "mismatch" in row else (0, 255, 0)
        cv2.circle(img, (x, y), radius + 4, colour, 2)
        cv2.putText(img, str(pid), (x - 10, y - radius - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    out = out or (nl.reg.path.parent / f"camera-check-{dev.key}.jpg")
    cv2.imwrite(str(out), img)
    return {"what": what, "panels_checked": len(rows), "mismatches": mism,
            "details": [r for r in rows if "mismatch" in r] if expected else rows, "image": str(out)}
