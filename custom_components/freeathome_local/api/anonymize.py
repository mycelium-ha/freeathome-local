"""Anonymise free@home Local API configuration data.

Used by diagnostics and by `scripts/anonymize_dump.py`, which turns a user's
`dump_config` output into a test fixture. The result keeps everything needed to
reproduce behaviour (function, pairing and parameter IDs, datapoint values,
channel and floor/room structure) and replaces what identifies a home: SysAP
UUIDs, device serials (keeping their type prefix), the SysAP name, optionally
display names, user accounts, keys naming credentials, network or location
data, and e-mail, IPv4 and MAC addresses inside strings.

This module uses the standard library only, so the script can load it without
installing the integration's dependencies.
"""

from __future__ import annotations

import re
from typing import Any

# A key is sensitive when one of its words (camelCase, snake_case or kebab-case) is here.
SENSITIVE_WORDS = frozenset(
    {
        "account", "address", "city", "cloud", "email", "host", "hostname", "ip", "jid",
        "lat", "latitude", "lng", "location", "login", "lon", "longitude", "mac", "mail",
        "passwd", "password", "postal", "secret", "ssid", "street", "token", "user",
        "username", "users", "wifi", "zip",
    }
)  # fmt: skip
KEY_WORD = re.compile(r"[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
MAC = re.compile(r"\b(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


class Anonymizer:
    """Stateful anonymiser: the same input value always maps to the same output."""

    def __init__(
        self, *, keep_names: bool = False, keep_serial_prefixes: tuple[str, ...] = ()
    ) -> None:
        """Create an anonymiser.

        `keep_names` leaves device, channel, floor and room names untouched;
        serials starting with one of `keep_serial_prefixes` are kept as they are.
        """
        self.keep_names = keep_names
        self.keep_serial_prefixes = tuple(p.upper() for p in keep_serial_prefixes)
        self.uuids: dict[str, str] = {}
        self.serials: dict[str, str] = {}
        self.removed_keys: set[str] = set()
        self.scrubbed_values = 0

    def uuid(self, value: str) -> str:
        """Return the replacement for a SysAP UUID."""
        return self.uuids.setdefault(value, f"00000000-0000-0000-0000-{len(self.uuids) + 1:012d}")

    def serial(self, value: str) -> str:
        """Return the replacement for a device serial, keeping its type prefix."""
        if value.upper().startswith(self.keep_serial_prefixes) and self.keep_serial_prefixes:
            return value
        if value not in self.serials:
            prefix = value[:8] if value.upper().startswith("FFFF") else value[:4]
            width = max(len(value) - len(prefix), 4)
            self.serials[value] = f"{prefix}{len(self.serials) + 1:0{width}X}"
        return self.serials[value]

    def run(self, dump: dict[str, Any]) -> dict[str, Any]:
        """Return the anonymised copy of a configuration dump."""
        result: dict[str, Any] = {}
        for sysap_uuid, sysap in dump.items():
            key = self.uuid(sysap_uuid) if UUID.match(sysap_uuid) else sysap_uuid
            result[key] = self._sysap(sysap) if isinstance(sysap, dict) else sysap
        scrubbed: dict[str, Any] = self._scrub_strings(result)
        return scrubbed

    def _sysap(self, sysap: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key, value in sysap.items():
            if key == "devices" and isinstance(value, dict):
                out[key] = {
                    self.serial(serial): self._device(device, index)
                    for index, (serial, device) in enumerate(value.items(), start=1)
                }
            elif key == "floorplan" and isinstance(value, dict):
                out[key] = self._floorplan(value)
            elif key == "sysapName":
                out[key] = "SysAP"
            else:
                cleaned = self._clean(key, value)
                if cleaned is not _DROP:
                    out[key] = cleaned
        return out

    def _device(self, device: Any, index: int) -> Any:
        if not isinstance(device, dict):
            return device
        out = {k: v for k, v in device.items() if self._clean(k, v) is not _DROP}
        if not self.keep_names and "displayName" in out:
            out["displayName"] = f"Device {index}"
        channels = out.get("channels")
        if isinstance(channels, dict):
            out["channels"] = {
                channel_id: self._channel(channel, index, number)
                for number, (channel_id, channel) in enumerate(channels.items(), start=1)
            }
        return out

    def _channel(self, channel: Any, device: int, number: int) -> Any:
        if not isinstance(channel, dict):
            return channel
        out = {k: v for k, v in channel.items() if self._clean(k, v) is not _DROP}
        if not self.keep_names and "displayName" in out:
            out["displayName"] = f"Channel {device}.{number}"
        return out

    def _floorplan(self, floorplan: dict[str, Any]) -> dict[str, Any]:
        out = dict(floorplan)
        floors = out.get("floors")
        if isinstance(floors, dict) and not self.keep_names:
            out["floors"] = {}
            for floor_id, floor in floors.items():
                if not isinstance(floor, dict):
                    out["floors"][floor_id] = floor
                    continue
                new_floor = {**floor, "name": f"Floor {floor_id}"}
                rooms = floor.get("rooms")
                if isinstance(rooms, dict):
                    new_floor["rooms"] = {
                        room_id: {**room, "name": f"Room {floor_id}.{room_id}"}
                        if isinstance(room, dict)
                        else room
                        for room_id, room in rooms.items()
                    }
                out["floors"][floor_id] = new_floor
        return out

    def _clean(self, key: str, value: Any) -> Any:
        """Drop sensitive keys recursively; keep everything else."""
        if _is_sensitive(key):
            self.removed_keys.add(key)
            return _DROP
        if isinstance(value, dict):
            return {
                k: cleaned for k, v in value.items() if (cleaned := self._clean(k, v)) is not _DROP
            }
        if isinstance(value, list):
            return [self._clean("", v) for v in value]
        return value

    def _scrub_strings(self, value: Any) -> Any:
        """Replace mapped serials/UUIDs and personal patterns inside every string."""
        if isinstance(value, dict):
            return {self._scrub_text(k): self._scrub_strings(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._scrub_strings(v) for v in value]
        if isinstance(value, str):
            return self._scrub_text(value)
        return value

    def _scrub_text(self, text: str) -> str:
        original = text
        for old, new in (*self.uuids.items(), *self.serials.items()):
            text = text.replace(old, new)
        text = EMAIL.sub("user@example.com", text)
        text = MAC.sub("00:00:00:00:00:00", text)
        text = IPV4.sub("192.0.2.1", text)
        if text != original and original not in self.uuids and original not in self.serials:
            self.scrubbed_values += 1
        return text


def _is_sensitive(key: str) -> bool:
    """Return True if a word of `key` names credentials, accounts, network or location."""
    return any(word.lower() in SENSITIVE_WORDS for word in KEY_WORD.findall(key))


class _Drop:
    """Marker for a removed value."""


_DROP: Any = _Drop()
