"""Clap / loud-transient detector on the Mac's microphone (used to fire one-shot animations on the panels).

Levels are RMS in dBFS per short block. A slow-moving noise floor is tracked from quiet blocks; a trigger
fires when a block jumps well above that floor (sensitivity_db), above an absolute minimum (min_db), and rises
sharply from the previous block (a transient, not a fade-in). A cooldown suppresses re-triggers while the
animation plays.
"""
from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable


@dataclass
class ClapConfig:
    samplerate: int = 16000
    block_ms: int = 25
    sensitivity_db: float = 18.0   # how far above the quiet floor a block must jump
    min_db: float = -30.0          # absolute loudness required (dBFS); protects against noisy rooms
    rise_db: float = 10.0          # must rise this much versus the previous block (transient)
    cooldown_s: float = 8.0
    floor_alpha: float = 0.03      # EMA rate for the noise floor
    input: str | int | None = None # sounddevice input name/index; None = built-in mic if present, else default


def resolve_input(pref: str | int | None) -> tuple[int | None, str]:
    """Pick the capture device: explicit name/index, else the built-in microphone (not Bluetooth headsets), else default."""
    import sounddevice as sd
    devs = sd.query_devices()
    inputs = [(i, d) for i, d in enumerate(devs) if d["max_input_channels"] > 0]
    if isinstance(pref, int):
        return pref, devs[pref]["name"]
    if isinstance(pref, str) and pref.strip():
        for i, d in inputs:
            if pref.lower() in d["name"].lower():
                return i, d["name"]
        raise ValueError(f"No input device matching {pref!r}; available: {[d['name'] for _, d in inputs]}")
    for i, d in inputs:
        if any(k in d["name"].lower() for k in ("built-in", "macbook", "imac", "mac mini", "mac studio")):
            return i, d["name"]
    i = sd.default.device[0]
    return i, devs[i]["name"] if i is not None and i >= 0 else "default"


class ClapDetector:
    def __init__(self, cfg: ClapConfig | None = None):
        self.cfg = cfg or ClapConfig()
        self.floor_db: float | None = None
        self.last_trigger = 0.0
        self.last_db = -120.0
        self.silent_blocks = 0

    def process(self, db: float, now: float) -> bool:
        cfg = self.cfg
        if self.floor_db is None:
            self.floor_db = db
        spike = db > self.floor_db + cfg.sensitivity_db and db > cfg.min_db and db - self.last_db > cfg.rise_db
        if not spike:                                # only quiet blocks feed the floor
            self.floor_db += cfg.floor_alpha * (db - self.floor_db)
        self.last_db = db
        if spike and now - self.last_trigger > cfg.cooldown_s:
            self.last_trigger = now
            return True
        return False

    def run(self, on_clap: Callable[[float], None], stop: threading.Event | None = None,
            verbose: bool = False, on_level: Callable[[float, float], None] | None = None) -> None:
        try:
            import numpy as np
            import sounddevice as sd
        except ImportError as e:
            raise RuntimeError("the clap listener needs the 'sound' extra: uv sync --extra sound") from e
        cfg = self.cfg
        block = int(cfg.samplerate * cfg.block_ms / 1000)
        events: list[tuple[float, float]] = []
        lock = threading.Lock()

        def cb(indata, frames, t, status):
            rms = float(np.sqrt(np.mean(np.square(indata[:, 0]))))
            db = 20 * math.log10(max(rms, 1e-9))
            with lock:
                events.append((time.time(), db))

        dev_index, dev_name = resolve_input(cfg.input)
        print(f"microphone: {dev_name}", file=sys.stderr, flush=True)
        with sd.InputStream(device=dev_index, samplerate=cfg.samplerate, channels=1, blocksize=block, callback=cb):
            silent_since = time.time()
            while not (stop and stop.is_set()):
                time.sleep(cfg.block_ms / 1000)
                with lock:
                    batch, events[:] = events[:], []
                for now, db in batch:
                    if db > -85:
                        silent_since = now
                    elif now - silent_since > 3 and self.silent_blocks == 0:
                        self.silent_blocks = 1
                        print("microphone is returning silence: grant your terminal app the macOS Microphone "
                              "permission (System Settings > Privacy & Security > Microphone) and restart it.",
                              file=sys.stderr, flush=True)
                    fired = self.process(db, now)
                    if on_level:
                        on_level(db, self.floor_db or db)
                    if fired:
                        try:
                            on_clap(db)
                        except Exception as e:  # a failed launch must not stop the listener
                            print(f"trigger handler failed: {e}", file=sys.stderr, flush=True)
