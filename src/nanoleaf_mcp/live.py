"""Live rendering: a scene is sampled every frame on the computer and streamed to every controller over external
control (UDP). All panels share one clock, so motion is exactly in sync across controllers and any scene can run,
at the cost of needing the computer on for the whole show. (Compare core.save_scene: keyframes stored on the
controllers, no computer needed after the start, but only what fits in an animation.)
"""
from __future__ import annotations

import threading
import time

import logging

from .client import NanoleafClient, NanoleafError
from .config import Device
from .scenes import Geo, SceneFn, to_rgb
from .stream import Streamer

log = logging.getLogger("nanoleaf")


class LiveShow:
    def __init__(self, devices: list[Device], clients: dict[str, NanoleafClient], geo: Geo, fn: SceneFn,
                 fps: float = 20.0, transition_tenths: int = 1):
        self.devices = devices
        self.clients = clients
        self.geo = geo
        self.fn = fn
        self.fps = max(1.0, min(30.0, fps))
        self.transition = transition_tenths
        self.stop = threading.Event()
        self.stats = {"frames": 0, "late": 0, "avg_frame_ms": 0.0, "max_frame_ms": 0.0}

    def run(self, duration_s: float | None = None) -> dict:
        streams = {d.key: Streamer(self.clients[d.key]) for d in self.devices}
        for d in self.devices:
            # controllers can stall for a few seconds right after a mode change; retry rather than abort the show
            for attempt in range(4):
                try:
                    self.clients[d.key].set_state(on=True)
                    streams[d.key].start()
                    break
                except NanoleafError as e:
                    if attempt == 3:
                        raise
                    log.warning("%s not ready (%s); retrying", d.label, e)
                    time.sleep(1.5 * (attempt + 1))
        period = 1.0 / self.fps
        t0 = time.perf_counter()
        next_tick = t0
        total_ms = 0.0
        try:
            while not self.stop.is_set():
                now = time.perf_counter()
                t = now - t0
                if duration_s is not None and t >= duration_s:
                    break
                frames: dict[str, dict[int, tuple[int, int, int, int]]] = {d.key: {} for d in self.devices}
                for p in self.geo.panels:
                    r, g, b = to_rgb(self.fn(t, p))
                    frames[p.device][p.id] = (r, g, b, self.transition)
                for key, frame in frames.items():
                    if frame:
                        streams[key].send(frame)
                dt_ms = (time.perf_counter() - now) * 1000
                total_ms += dt_ms
                self.stats["frames"] += 1
                self.stats["max_frame_ms"] = max(self.stats["max_frame_ms"], dt_ms)
                next_tick += period
                sleep = next_tick - time.perf_counter()
                if sleep > 0:
                    time.sleep(sleep)
                else:
                    self.stats["late"] += 1
                    next_tick = time.perf_counter()
        finally:
            for s in streams.values():
                s.close()
        if self.stats["frames"]:
            self.stats["avg_frame_ms"] = total_ms / self.stats["frames"]
        self.stats["seconds"] = time.perf_counter() - t0
        self.stats["achieved_fps"] = self.stats["frames"] / max(1e-6, self.stats["seconds"])
        return dict(self.stats)
