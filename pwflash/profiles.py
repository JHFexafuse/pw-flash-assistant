from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class DeviceProfile:
    path: Path
    data: dict[str, Any]

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def name(self) -> str:
        return str(self.data["name"])

    @property
    def hardware(self) -> dict[str, Any]:
        return self.data["hardware"]

    @property
    def workflow(self) -> dict[str, Any]:
        return self.data["workflow"]

    def config_lines(self, firmware: str, bitrate: int) -> list[str]:
        try:
            lines = self.data["firmware"][firmware]["kconfig"]
        except KeyError as exc:
            raise ProfileError(f"Profil {self.id}: Firmwarebereich {firmware!r} fehlt") from exc
        return [str(line).format(bitrate=bitrate) for line in lines]


REQUIRED = {
    "id": str,
    "name": str,
    "schema_version": int,
    "hardware": dict,
    "workflow": dict,
    "firmware": dict,
}


def validate_profile(data: dict[str, Any], source: Path) -> None:
    for key, expected in REQUIRED.items():
        if key not in data:
            raise ProfileError(f"{source}: Pflichtfeld {key!r} fehlt")
        if not isinstance(data[key], expected):
            raise ProfileError(f"{source}: {key!r} hat den falschen Datentyp")
    if data["schema_version"] != 1:
        raise ProfileError(f"{source}: Unbekannte schema_version")
    for firmware in ("katapult", "klipper"):
        section = data["firmware"].get(firmware)
        if not isinstance(section, dict) or not isinstance(section.get("kconfig"), list):
            raise ProfileError(f"{source}: firmware.{firmware}.kconfig fehlt")
    rates = data["hardware"].get("supported_bitrates")
    if not isinstance(rates, list) or not rates or not all(isinstance(rate, int) for rate in rates):
        raise ProfileError(f"{source}: hardware.supported_bitrates ist ungültig")


def load_profiles(directory: Path) -> list[DeviceProfile]:
    profiles: list[DeviceProfile] = []
    for path in sorted(directory.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ProfileError(f"{path}: {exc}") from exc
        validate_profile(data, path)
        profiles.append(DeviceProfile(path=path, data=data))
    if not profiles:
        raise ProfileError(f"Keine Geräteprofile in {directory} gefunden")
    ids = [profile.id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise ProfileError("Geräteprofil-IDs müssen eindeutig sein")
    return profiles
