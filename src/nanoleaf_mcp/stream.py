"""External Control streaming: push per-panel colours over UDP at up to ~10-30 fps.

v1 (original Light Panels): enable -> device replies with streamControlPort (60221). Packet:
    nPanels(1) [panelId(1) nFrames(1)=1 R G B W transTime(1)]...
v2 (Canvas and newer firmware, incl. recent Light Panels firmware): port 60222. Packet:
    nPanels(2 BE) [panelId(2 BE) R G B W transTime(2 BE)]...
transTime is in tenths of a second.

Fallback: if the process is denied LAN access (macOS Local Network permission) sendto() raises
EHOSTUNREACH; we then pipe datagrams through Apple-signed /usr/bin/nc, which is exempt.
"""
from __future__ import annotations

import logging
import socket
import struct
import subprocess
import time
from typing import Iterable

from .client import NanoleafClient, NanoleafError, LOCAL_NETWORK_HINT

log = logging.getLogger("nanoleaf")

Frame = dict[int, tuple[int, int, int, int]]  # panelId -> (r, g, b, transition_tenths)


class Streamer:
    def __init__(self, client: NanoleafClient, version: str = "auto"):
        self.client = client
        self.version = version
        self.target: tuple[str, int] | None = None
        self._sock: socket.socket | None = None
        self._nc: subprocess.Popen | None = None
        self.started_at: float | None = None

    def start(self) -> dict:
        versions = ["v2", "v1"] if self.version == "auto" else [self.version]
        last: Exception | None = None
        for v in versions:
            try:
                info = self.client.enable_ext_control(v)
                self.version = v
                self.target = (info["ip"], info["port"])
                self.started_at = time.time()
                return info
            except NanoleafError as e:
                last = e
                if e.status not in (400, 422, 404):
                    raise
        raise NanoleafError(f"Could not enable external control: {last}")

    def encode(self, frame: Frame) -> bytes:
        if self.version == "v1":
            out = bytearray([len(frame) & 0xFF])
            for pid, (r, g, b, t) in frame.items():
                out += bytes([pid & 0xFF, 1, r & 0xFF, g & 0xFF, b & 0xFF, 0, max(0, min(255, int(t)))])
            return bytes(out)
        out = bytearray(struct.pack(">H", len(frame)))
        for pid, (r, g, b, t) in frame.items():
            out += struct.pack(">HBBBBH", pid & 0xFFFF, r & 0xFF, g & 0xFF, b & 0xFF, 0, max(0, min(65535, int(t))))
        return bytes(out)

    def send(self, frame: Frame) -> None:
        if self.target is None:
            self.start()
        data = self.encode(frame)
        if self._nc is not None:
            self._nc.stdin.write(data)  # type: ignore[union-attr]
            self._nc.stdin.flush()      # type: ignore[union-attr]
            return
        if self._sock is None:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._sock.sendto(data, self.target)
        except OSError as e:
            if e.errno in (65, 113):
                log.warning(LOCAL_NETWORK_HINT.replace("curl for HTTP", "nc for UDP"))
                self._nc = subprocess.Popen(["nc", "-u", self.target[0], str(self.target[1])], stdin=subprocess.PIPE)
                self._nc.stdin.write(data)  # type: ignore[union-attr]
                self._nc.stdin.flush()      # type: ignore[union-attr]
            else:
                raise

    def play(self, frames: Iterable[Frame], fps: float = 10.0) -> int:
        n = 0
        period = 1.0 / max(0.5, fps)
        for f in frames:
            t0 = time.time()
            self.send(f)
            n += 1
            dt = period - (time.time() - t0)
            if dt > 0:
                time.sleep(dt)
        return n

    def close(self) -> None:
        if self._sock:
            self._sock.close(); self._sock = None
        if self._nc:
            try:
                self._nc.stdin.close(); self._nc.terminate()  # type: ignore[union-attr]
            except Exception:
                pass
            self._nc = None
