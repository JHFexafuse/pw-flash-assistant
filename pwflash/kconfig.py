from __future__ import annotations

import os
from pathlib import Path

from .profiles import DeviceProfile
from .system import AssistantError, Runner


def write_seed_config(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [line.strip() for line in lines if line.strip()]
    path.write_text("\n".join(normalized) + "\n", encoding="utf-8")


def build_firmware(
    runner: Runner,
    *,
    source_dir: Path,
    config_path: Path,
    profile: DeviceProfile,
    firmware: str,
    bitrate: int,
) -> Path:
    if not source_dir.is_dir() and not runner.dry_run:
        raise AssistantError(f"Quellverzeichnis fehlt: {source_dir}")
    if not runner.dry_run:
        write_seed_config(config_path, profile.config_lines(firmware, bitrate))
    env = os.environ.copy()
    env["KCONFIG_CONFIG"] = str(config_path)
    runner.run(["make", "olddefconfig"], cwd=source_dir, env=env)
    runner.run(["make", "clean"], cwd=source_dir, env=env)
    runner.run(["make", f"-j{max(1, os.cpu_count() or 1)}"], cwd=source_dir, env=env)
    output_name = "katapult.bin" if firmware == "katapult" else "klipper.bin"
    output = source_dir / "out" / output_name
    if not output.is_file() and not runner.dry_run:
        raise AssistantError(f"Erwartete Firmware wurde nicht erzeugt: {output}")
    return output
