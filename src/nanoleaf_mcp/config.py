"""Persistent device registry: ~/.config/nanoleaf-mcp/devices.json

Schema:
{
  "devices": {
    "<key>": {"name": str, "ip": str, "port": int, "token": str|None,
              "host": str|None, "model": str|None, "serial": str|None,
              "firmware": str|None}
  },
  "default": "<key>" | null
}
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Iterable


def config_path() -> Path:
    env = os.environ.get("NANOLEAF_CONFIG")
    if env:
        return Path(env).expanduser()
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "nanoleaf-mcp" / "devices.json"


@dataclass
class Device:
    name: str
    ip: str
    port: int = 16021
    token: str | None = None
    host: str | None = None
    model: str | None = None
    serial: str | None = None
    firmware: str | None = None
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        """Stable key: serial if known, else the mDNS name, else the ip."""
        return self.serial or self.name or self.ip

    @property
    def label(self) -> str:
        """Human name: the name given in the Nanoleaf app if known, else the mDNS name."""
        return self.extra.get("friendly_name") or self.name

    @property
    def paired(self) -> bool:
        return bool(self.token)

    @property
    def base_url(self) -> str:
        return f"http://{self.ip}:{self.port}/api/v1"

    def public(self) -> dict:
        d = asdict(self)
        d["paired"] = self.paired
        d["key"] = self.key
        d["label"] = self.label
        d["friendly_name"] = self.extra.get("friendly_name")
        d.pop("token", None)
        d.pop("extra", None)
        return d


class Registry:
    def __init__(self, path: Path | None = None):
        self.path = path or config_path()
        self.devices: dict[str, Device] = {}
        self.default: str | None = None
        self.load()

    # -- persistence -------------------------------------------------------
    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text())
        except json.JSONDecodeError:
            return
        self.devices = {}
        for key, d in raw.get("devices", {}).items():
            d = dict(d)
            d.setdefault("extra", {})
            self.devices[key] = Device(**{k: v for k, v in d.items() if k in Device.__dataclass_fields__})
        self.default = raw.get("default")

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = {"devices": {k: asdict(v) for k, v in self.devices.items()}, "default": self.default}
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    # -- mutation ----------------------------------------------------------
    def upsert(self, dev: Device) -> Device:
        """Merge by serial (preferred), then by mDNS name, then by ip. Keeps existing token."""
        existing = None
        for d in self.devices.values():
            if dev.serial and d.serial == dev.serial:
                existing = d; break
        if existing is None:
            for d in self.devices.values():
                if dev.name and d.name == dev.name:
                    existing = d; break
        if existing is None:
            for d in self.devices.values():
                if d.ip == dev.ip:
                    existing = d; break
        if existing is not None:
            old_key = existing.key
            for f in ("name", "ip", "port", "host", "model", "serial", "firmware"):
                v = getattr(dev, f)
                if v is not None:
                    setattr(existing, f, v)
            if dev.token:
                existing.token = dev.token
            existing.extra.update(dev.extra)
            self.devices.pop(old_key, None)
            self.devices[existing.key] = existing
            if self.default == old_key:
                self.default = existing.key
            dev = existing
        else:
            self.devices[dev.key] = dev
        if self.default is None:
            self.default = dev.key
        return dev

    def remove(self, key: str) -> bool:
        if key in self.devices:
            del self.devices[key]
            if self.default == key:
                self.default = next(iter(self.devices), None)
            return True
        return False

    # -- lookup ------------------------------------------------------------
    def resolve(self, query: str | None, *, paired_only: bool = False) -> list[Device]:
        """Resolve a user/agent supplied device reference.

        query: None -> default device (or all devices if no default); "all"/"*" -> every device;
               otherwise case-insensitive match on key, name (substring), ip, host, serial.
        """
        pool: Iterable[Device] = self.devices.values()
        if paired_only:
            pool = [d for d in pool if d.paired]
        pool = list(pool)
        if query is None or query == "":
            if self.default and self.default in self.devices:
                d = self.devices[self.default]
                if not paired_only or d.paired:
                    return [d]
            return pool[:1] if len(pool) == 1 else pool
        q = query.strip().lower()
        if q in ("all", "*", "every", "both"):
            return pool
        exact = [d for d in pool if q in (d.key.lower(), d.ip, (d.host or "").lower(), (d.serial or "").lower(), d.name.lower(), d.label.lower())]
        if exact:
            return exact[:1]
        # tolerate "light panels 55" / "559b93" style partial matches
        norm = re.sub(r"[^a-z0-9]", "", q)
        partial = [d for d in pool if norm and norm in re.sub(r"[^a-z0-9]", "", (d.name + d.label + (d.serial or "") + d.ip).lower())]
        return partial

    def resolve_one(self, query: str | None, *, paired_only: bool = False) -> Device:
        found = self.resolve(query, paired_only=paired_only)
        if len(found) == 1:
            return found[0]
        names = ", ".join(sorted(d.label for d in self.devices.values())) or "(none registered)"
        if not found:
            raise LookupError(f"No {'paired ' if paired_only else ''}device matches {query!r}. Known devices: {names}")
        raise LookupError(f"{query!r} is ambiguous; matches: {', '.join(d.label for d in found)}. Use a full name, ip, or 'all'.")
