"""Thin client for the Nanoleaf OpenAPI (v1) that a controller exposes on port 16021.

    http://<ip>:16021/api/v1/<auth_token>/...

Transport: httpx by default. On macOS 15+ a third-party binary that has not been granted the
*Local Network* privacy permission gets EHOSTUNREACH for every LAN socket; Apple-signed tools are
exempt. When that happens (or NANOLEAF_HTTP_BACKEND=curl) we transparently shell out to /usr/bin/curl
so the layer keeps working while the user flips the toggle.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from typing import Any

import httpx

log = logging.getLogger("nanoleaf")

LOCAL_NETWORK_HINT = (
    "macOS blocked LAN access for this process (EHOSTUNREACH). Grant the app that runs it "
    "(your terminal, e.g. Ghostty / Terminal / iTerm / VS Code, or the Claude desktop app) the "
    "'Local Network' permission: System Settings > Privacy & Security > Local Network, then restart it. "
    "Until then nanoleaf-mcp falls back to /usr/bin/curl for HTTP."
)


class NanoleafError(Exception):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _is_ehostunreach(exc: BaseException) -> bool:
    seen = set()
    e: BaseException | None = exc
    while e is not None and id(e) not in seen:
        seen.add(id(e))
        if isinstance(e, OSError) and getattr(e, "errno", None) in (65, 113):
            return True
        if "No route to host" in str(e):
            return True
        e = e.__cause__ or e.__context__
    return False


class NanoleafClient:
    def __init__(self, ip: str, port: int = 16021, token: str | None = None,
                 timeout: float = 6.0, backend: str | None = None):
        self.ip = ip
        self.port = port
        self.token = token
        self.timeout = timeout
        self.backend = backend or os.environ.get("NANOLEAF_HTTP_BACKEND", "auto")
        self._http = httpx.Client(timeout=timeout)
        self._warned = False

    # ------------------------------------------------------------------ transport
    @property
    def base(self) -> str:
        return f"http://{self.ip}:{self.port}/api/v1"

    def _url(self, path: str, auth: bool) -> str:
        path = path if path.startswith("/") else "/" + path
        if not auth:
            return self.base + path
        if not self.token:
            raise NanoleafError("Device is not paired (no auth token). Run pairing first.", 401)
        return f"{self.base}/{self.token}{path}"

    def request(self, method: str, path: str, body: Any = None, *, auth: bool = True, retries: int = 3) -> Any:
        """Controllers stall for a few seconds after mode changes (entering/leaving streaming, adding effects);
        a timed-out request is retried with a short back-off before giving up."""
        url = self._url(path, auth)
        data = json.dumps(body) if body is not None else None
        for attempt in range(retries):
            try:
                if self.backend == "curl":
                    status, text = self._curl(method, url, data)
                else:
                    try:
                        r = self._http.request(method, url, content=data,
                                               headers={"Content-Type": "application/json"} if data else None)
                        status, text = r.status_code, r.text
                    except (httpx.TransportError, OSError) as e:
                        if self.backend == "auto" and _is_ehostunreach(e) and shutil.which("curl"):
                            if not self._warned:
                                log.warning(LOCAL_NETWORK_HINT)
                                self._warned = True
                            self.backend = "curl"
                            status, text = self._curl(method, url, data)
                        elif isinstance(e, httpx.TimeoutException):
                            raise NanoleafError(f"{method} {path} timed out", None, "timeout") from e
                        else:
                            raise NanoleafError(f"{method} {path} failed: {e}") from e
                return self._handle(method, path, status, text)
            except NanoleafError as e:
                timed_out = e.body == "timeout" or "timed out" in str(e)
                if not timed_out or attempt == retries - 1:
                    raise
                log.warning("%s %s timed out (controller busy); retrying in %ds", method, path, 2 * (attempt + 1))
                time.sleep(2 * (attempt + 1))

    def _curl(self, method: str, url: str, data: str | None) -> tuple[int, str]:
        cmd = ["curl", "-sS", "-m", str(self.timeout), "-X", method, "-o", "-", "-w", "\n__STATUS__%{http_code}", url]
        if data is not None:
            cmd += ["-H", "Content-Type: application/json", "--data", data]
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            raise NanoleafError(f"{method} {url} failed via curl: {p.stderr.strip()}")
        text, _, status = p.stdout.rpartition("\n__STATUS__")
        return int(status or 0), text

    @staticmethod
    def _handle(method: str, path: str, status: int, text: str) -> Any:
        if status in (200, 204):
            if not text.strip():
                return None
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return text
        hints = {
            400: "bad request (malformed JSON or invalid value)",
            401: "unauthorized (bad or expired auth token; re-pair the device)",
            403: "forbidden (for /new: the controller is not in pairing mode; hold its power button 5-7 s until the LEDs flash, then retry within 30 s)",
            404: "not found (unknown resource or effect name)",
            422: "unprocessable (a value is out of range, or this firmware lacks the feature)",
            500: "device internal error",
        }
        raise NanoleafError(f"{method} {path} -> HTTP {status}: {hints.get(status, 'error')}"
                            + (f" | {text[:300]}" if text.strip() else ""), status, text)

    # ------------------------------------------------------------------ pairing
    def pair(self) -> str:
        res = self.request("POST", "/new", auth=False)
        token = (res or {}).get("auth_token") if isinstance(res, dict) else None
        if not token:
            raise NanoleafError(f"Pairing returned no auth_token: {res!r}")
        self.token = token
        return token

    def unpair(self) -> None:
        self.request("DELETE", "/")
        self.token = None

    # ------------------------------------------------------------------ info / state
    def info(self) -> dict:
        return self.request("GET", "/")

    def state(self) -> dict:
        return self.request("GET", "/state")

    def set_state(self, **fields: Any) -> None:
        """set_state(on=True, brightness=(50, duration_s), hue=270, sat=100, ct=4000)"""
        body: dict[str, Any] = {}
        for k, v in fields.items():
            if v is None:
                continue
            if isinstance(v, tuple):
                val, dur = v
                body[k] = {"value": val, "duration": int(dur)}
            elif isinstance(v, dict):
                body[k] = v
            else:
                body[k] = {"value": v}
        if body:
            self.request("PUT", "/state", body)

    def identify(self) -> None:
        self.request("PUT", "/identify")

    # ------------------------------------------------------------------ effects
    def effects_list(self) -> list[str]:
        return self.request("GET", "/effects/effectsList") or []

    def selected_effect(self) -> str:
        return self.request("GET", "/effects/select")

    def select_effect(self, name: str) -> None:
        self.request("PUT", "/effects", {"select": name})

    def write(self, command: dict) -> Any:
        return self.request("PUT", "/effects", {"write": command})

    def request_effect(self, name: str) -> dict:
        return self.write({"command": "request", "animName": name})

    def request_all(self) -> dict:
        return self.write({"command": "requestAll"})

    def request_plugins(self) -> dict:
        try:
            return self.write({"command": "requestPlugins", "version": "2.0"})
        except NanoleafError as e:
            if e.status in (400, 422, 404):
                return self.write({"command": "requestPlugins"})
            raise

    def add_effect(self, effect: dict) -> Any:
        return self.write({"command": "add", **effect})

    def display_effect(self, effect: dict, duration_s: int | None = None) -> Any:
        """Show an effect without saving it. With duration_s, reverts afterwards (displayTemp)."""
        if duration_s:
            return self.write({"command": "displayTemp", "duration": int(duration_s), **effect})
        return self.write({"command": "display", **effect})

    def delete_effect(self, name: str) -> None:
        self.write({"command": "delete", "animName": name})

    def rename_effect(self, old: str, new: str) -> None:
        self.write({"command": "rename", "animName": old, "newName": new})

    # ------------------------------------------------------------------ layout / rhythm
    def layout(self) -> dict:
        return self.request("GET", "/panelLayout/layout")

    def global_orientation(self) -> dict:
        return self.request("GET", "/panelLayout/globalOrientation")

    def set_global_orientation(self, degrees: int) -> None:
        self.request("PUT", "/panelLayout", {"globalOrientation": {"value": int(degrees)}})

    def rhythm(self) -> dict | None:
        try:
            return self.request("GET", "/rhythm")
        except NanoleafError as e:
            if e.status == 404:
                return None
            raise

    def set_rhythm_mode(self, mode: int) -> None:
        """0 = built-in/attached microphone, 1 = aux-in."""
        self.request("PUT", "/rhythm/rhythmMode", {"rhythmMode": int(mode)})

    # ------------------------------------------------------------------ streaming
    def enable_ext_control(self, version: str = "v2") -> dict:
        """Put the controller in external-control mode. Returns {'version', 'ip', 'port'}."""
        body = {"command": "display", "animType": "extControl", "extControlVersion": version}
        res = self.write(body)
        if version == "v1":
            res = res or {}
            return {"version": "v1", "ip": res.get("streamControlIpAddr", self.ip),
                    "port": int(res.get("streamControlPort", 60221)), "protocol": res.get("streamControlProtocol", "udp")}
        return {"version": "v2", "ip": self.ip, "port": 60222, "protocol": "udp"}

    def close(self) -> None:
        self._http.close()
