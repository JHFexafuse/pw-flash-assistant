from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .system import AssistantError


@dataclass(frozen=True)
class ConfigUpdate:
    old_uuid: str
    new_uuid: str
    backup_path: Path


def _uuid_line_index(lines: list[str], section: str) -> tuple[int, str]:
    section_pattern = re.compile(r"^\s*\[mcu\s+([^\]]+)\]\s*(?:[#;].*)?$")
    uuid_pattern = re.compile(r"^\s*canbus_uuid\s*:\s*([0-9a-fA-F]{12})\b")
    in_target = False
    found_section = False
    for index, line in enumerate(lines):
        stripped = line.rstrip("\r\n")
        section_match = section_pattern.match(stripped)
        if section_match:
            in_target = section_match.group(1).strip().casefold() == section.casefold()
            found_section = found_section or in_target
            continue
        if stripped.lstrip().startswith("["):
            in_target = False
        if in_target:
            uuid_match = uuid_pattern.match(stripped)
            if uuid_match:
                return index, uuid_match.group(1).lower()
    if not found_section:
        raise AssistantError(f"Abschnitt [mcu {section}] wurde nicht gefunden.")
    raise AssistantError(f"Im Abschnitt [mcu {section}] wurde kein canbus_uuid-Eintrag gefunden.")


def find_canbus_uuid(path: Path, section: str) -> str:
    target = path.resolve()
    if not target.is_file():
        raise AssistantError(f"Konfigurationsdatei fehlt: {path}")
    return _uuid_line_index(target.read_text(encoding="utf-8").splitlines(keepends=True), section)[1]


def _uuid_history(line: str) -> tuple[str | None, str | None, str | None]:
    segments = [segment.strip() for segment in line.rstrip("\r\n").split("#")[1:] if segment.strip()]
    current_stamp: str | None = None
    previous_uuid: str | None = None
    previous_stamp: str | None = None
    date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}(?:\s+\d{2}:\d{2}:\d{2}(?:\s+\S+)?)?$")
    previous_pattern = re.compile(
        r"^(?:vorher|alte\s+ID)\s*:\s*([0-9a-fA-F]{12})(?:\s+(.+))?$",
        re.IGNORECASE,
    )
    for segment in segments:
        previous_match = previous_pattern.match(segment)
        if previous_match:
            previous_uuid = previous_match.group(1).lower()
            previous_stamp = previous_match.group(2).strip() if previous_match.group(2) else None
        elif current_stamp is None and date_pattern.match(segment):
            current_stamp = segment
        elif previous_uuid is None and re.fullmatch(r"[0-9a-fA-F]{12}", segment):
            previous_uuid = segment.lower()
    return current_stamp, previous_uuid, previous_stamp


def update_canbus_uuid(
    path: Path,
    section: str,
    new_uuid: str,
    *,
    timestamp: datetime | None = None,
) -> ConfigUpdate:
    if not re.fullmatch(r"[0-9a-fA-F]{12}", new_uuid):
        raise AssistantError(f"Ungültige CAN-UUID: {new_uuid}")
    target = path.resolve()
    lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    index, old_uuid = _uuid_line_index(lines, section)
    current_stamp, previous_uuid, previous_stamp = _uuid_history(lines[index])
    now = timestamp or datetime.now().astimezone()
    display_stamp = now.strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    file_stamp = now.strftime("%Y%m%d-%H%M%S")
    newline = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    indent = re.match(r"^\s*", lines[index]).group(0)
    normalized_uuid = new_uuid.lower()
    if normalized_uuid != old_uuid:
        previous_uuid = old_uuid
        previous_stamp = current_stamp
    history = f" # vorher: {previous_uuid}" if previous_uuid else ""
    if history and previous_stamp:
        history += f" {previous_stamp}"
    lines[index] = f"{indent}canbus_uuid: {normalized_uuid}  # {display_stamp}{history}{newline}"
    backup = target.with_name(f"{target.name}.pwflash-{file_stamp}.bak")
    if backup.exists():
        backup = target.with_name(f"{target.name}.pwflash-{now.strftime('%Y%m%d-%H%M%S-%f')}.bak")
    temporary = target.with_name(f".{target.name}.pwflash.tmp")
    shutil.copy2(target, backup)
    try:
        temporary.write_text("".join(lines), encoding="utf-8")
        shutil.copymode(target, temporary)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return ConfigUpdate(old_uuid=old_uuid, new_uuid=normalized_uuid, backup_path=backup)
