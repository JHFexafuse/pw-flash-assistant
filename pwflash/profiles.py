from __future__ import annotations

import json
import re
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
    modes = data.get("supported_modes", ["full", "klipper"])
    if "full" in modes:
        for steps_key in ("enter_bootloader_steps", "connect_can_steps"):
            steps = data["workflow"].get(steps_key)
            if not isinstance(steps, list) or not steps:
                raise ProfileError(f"{source}: workflow.{steps_key} fehlt für die Erstinstallation")
        initial = data["workflow"].get("initial_flash")
        if not isinstance(initial, dict):
            raise ProfileError(f"{source}: workflow.initial_flash fehlt für die Erstinstallation")
        method = initial.get("method")
        if method not in {"stm32-dfu", "rp2040-bootsel"}:
            raise ProfileError(f"{source}: unbekannte Erstflash-Methode {method!r}")
        usb_id = initial.get("usb_id")
        if not isinstance(usb_id, str) or not re.fullmatch(r"[0-9a-fA-F]{4}:[0-9a-fA-F]{4}", usb_id):
            raise ProfileError(f"{source}: ungültige USB-ID für die Erstinstallation")
        output = data["firmware"]["katapult"].get("output")
        if not isinstance(output, str) or not output:
            raise ProfileError(f"{source}: firmware.katapult.output fehlt für die Erstinstallation")
        if method == "stm32-dfu":
            if not isinstance(initial.get("address"), str):
                raise ProfileError(f"{source}: STM32-DFU benötigt eine Flashadresse")
            if not output.endswith(".bin"):
                raise ProfileError(f"{source}: STM32-DFU erwartet ein BIN-Artefakt")
        if method == "rp2040-bootsel" and not output.endswith(".uf2"):
            raise ProfileError(f"{source}: RP2040-BOOTSEL erwartet ein UF2-Artefakt")


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
