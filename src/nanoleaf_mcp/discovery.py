"""LAN discovery of Nanoleaf controllers.

Nanoleaf devices that expose the OpenAPI advertise `_nanoleafapi._tcp.local.` (port 16021) with TXT
records id=<mac>, md=<model e.g. NL22>, srcvers=<firmware>.

On macOS we prefer Apple's `dns-sd` (talks to mDNSResponder over a local socket) because
third‑party binaries that haven't been granted the *Local Network* privacy permission cannot
send/receive multicast at all. Elsewhere we use python-zeroconf.
"""
from __future__ import annotations

import re
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

SERVICE = "_nanoleafapi._tcp.local."


@dataclass
class Found:
    name: str
    ip: str
    port: int = 16021
    host: str | None = None
    txt: dict[str, str] = field(default_factory=dict)

    @property
    def model(self) -> str | None:
        return self.txt.get("md")

    @property
    def firmware(self) -> str | None:
        return self.txt.get("srcvers")

    def as_dict(self) -> dict:
        return {"name": self.name, "ip": self.ip, "port": self.port, "host": self.host,
                "model": self.model, "firmware": self.firmware, "mac": self.txt.get("id")}


def _run(args: list[str], timeout: float) -> str:
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.stdout
    except subprocess.TimeoutExpired as e:  # dns-sd never exits on its own
        out = e.stdout or ""
        return out.decode() if isinstance(out, bytes) else out
    except FileNotFoundError:
        return ""


def _discover_dns_sd(timeout: float) -> list[Found]:
    out = _run(["dns-sd", "-B", "_nanoleafapi._tcp", "local."], timeout)
    names: list[str] = []
    for line in out.splitlines():
        m = re.search(r"\bAdd\s+\d+\s+\d+\s+\S+\s+_nanoleafapi\._tcp\.\s+(.+?)\s*$", line)
        if m and m.group(1) not in names:
            names.append(m.group(1))
    found: list[Found] = []
    for name in names:
        lk = _run(["dns-sd", "-L", name, "_nanoleafapi._tcp", "local."], 3)
        m = re.search(r"can be reached at (\S+?):(\d+)", lk)
        if not m:
            continue
        host, port = m.group(1), int(m.group(2))
        txt = dict(re.findall(r"(\w+)=(\S+)", lk.split("can be reached at", 1)[1]))
        ip = None
        ga = _run(["dns-sd", "-G", "v4", host], 3)
        ips = re.findall(r"\s(\d+\.\d+\.\d+\.\d+)\s", ga)
        if ips:
            ip = ips[0]
        else:
            try:
                ip = socket.gethostbyname(host.rstrip("."))
            except OSError:
                continue
        found.append(Found(name=name, ip=ip, port=port, host=host.rstrip("."), txt=txt))
    return found


def _discover_zeroconf(timeout: float) -> list[Found]:
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []
    results: dict[str, Found] = {}

    class L(ServiceListener):
        def add_service(self, zc, type_, name):
            info = zc.get_service_info(type_, name, timeout=2000)
            if not info:
                return
            addrs = info.parsed_addresses()
            if not addrs:
                return
            txt = {k.decode() if isinstance(k, bytes) else k: (v.decode() if isinstance(v, bytes) else str(v))
                   for k, v in (info.properties or {}).items()}
            inst = name.replace("." + SERVICE, "")
            results[inst] = Found(name=inst, ip=addrs[0], port=info.port or 16021,
                                  host=(info.server or "").rstrip("."), txt=txt)
        def update_service(self, zc, type_, name): pass
        def remove_service(self, zc, type_, name): pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE, L())
        time.sleep(timeout)
    finally:
        zc.close()
    return list(results.values())


def discover(timeout: float = 4.0) -> list[Found]:
    found: list[Found] = []
    if sys.platform == "darwin":
        found = _discover_dns_sd(timeout)
    if not found:
        found = _discover_zeroconf(timeout)
    if not found and sys.platform != "darwin":
        found = _discover_dns_sd(timeout)
    return found


if __name__ == "__main__":
    import json
    print(json.dumps([f.as_dict() for f in discover()], indent=2))
