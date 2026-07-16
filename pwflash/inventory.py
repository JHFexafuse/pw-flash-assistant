from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from .system import AssistantError


@dataclass(frozen=True)
class CanMcu:
    section: str
    uuid: str
    config_path: Path


@dataclass(frozen=True)
class InventoryEntry:
    section: str
    uuid: str
    profile_id: str
    config_path: str


def discover_can_mcus(printer_config: Path) -> list[CanMcu]:
    root = printer_config.expanduser().parent
    if not root.is_dir():
        raise AssistantError(f"Konfigurationsverzeichnis fehlt: {root}")
    section_pattern = re.compile(r"^\s*\[mcu(?:\s+([^\]]+))?\]\s*(?:[#;].*)?$", re.IGNORECASE)
    uuid_pattern = re.compile(r"^\s*canbus_uuid\s*:\s*([0-9a-fA-F]{12})\b", re.IGNORECASE)
    discovered: dict[tuple[str, str], CanMcu] = {}
    for path in sorted(root.rglob("*.cfg")):
        current_section: str | None = None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            section_match = section_pattern.match(line)
            if section_match:
                current_section = (section_match.group(1) or "mcu").strip()
                continue
            if line.lstrip().startswith("["):
                current_section = None
            if current_section:
                uuid_match = uuid_pattern.match(line)
                if uuid_match:
                    uuid = uuid_match.group(1).lower()
                    key = (current_section.casefold(), uuid)
                    discovered.setdefault(key, CanMcu(current_section, uuid, path))
    return sorted(discovered.values(), key=lambda item: item.section.casefold())


class DeviceInventory:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()
        self.entries: list[InventoryEntry] = []
        if self.path.is_file():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self.entries = [InventoryEntry(**item) for item in data.get("devices", [])]
            except (OSError, ValueError, TypeError) as exc:
                raise AssistantError(f"Gerätekartei ist beschädigt: {self.path}: {exc}") from exc

    def find(self, device: CanMcu) -> InventoryEntry | None:
        for entry in self.entries:
            if entry.section.casefold() == device.section.casefold():
                return entry
        return None

    def bind(self, device: CanMcu, profile_id: str) -> InventoryEntry:
        entry = InventoryEntry(device.section, device.uuid, profile_id, str(device.config_path))
        self.entries = [
            existing for existing in self.entries if existing.section.casefold() != device.section.casefold()
        ]
        self.entries.append(entry)
        self.entries.sort(key=lambda item: item.section.casefold())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps({"schema_version": 1, "devices": [asdict(item) for item in self.entries]}, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return entry
