from __future__ import annotations

import os
import shutil
from pathlib import Path

from .profiles import DeviceProfile
from .system import AssistantError, Runner


def write_seed_config(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [line.strip() for line in lines if line.strip()]
    path.write_text("\n".join(normalized) + "\n", encoding="utf-8")


def validate_config(path: Path, expected_lines: list[str]) -> None:
    configured = {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    expected = {line.strip() for line in expected_lines if line.strip()}
    missing = sorted(expected - configured)
    if missing:
        raise AssistantError(
            "Die erzeugte Firmware-Konfiguration passt nicht zum gewählten Board. "
            "Nicht übernommen: " + ", ".join(missing)
        )


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
    requested = profile.config_lines(firmware, bitrate)
    active_config = source_dir / ".config"
    previous_config = active_config.read_bytes() if active_config.is_file() and not runner.dry_run else None
    had_config = active_config.is_file()
    try:
        if not runner.dry_run:
            write_seed_config(active_config, requested)
        runner.run(["make", "olddefconfig"], cwd=source_dir)
        if not runner.dry_run:
            validate_config(active_config, requested)
            config_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(active_config, config_path)
        runner.run(["make", "clean"], cwd=source_dir)
        runner.run(["make", f"-j{max(1, os.cpu_count() or 1)}"], cwd=source_dir)
        output_name = "katapult.bin" if firmware == "katapult" else "klipper.bin"
        output = source_dir / "out" / output_name
        if not output.is_file() and not runner.dry_run:
            raise AssistantError(f"Erwartete Firmware wurde nicht erzeugt: {output}")
        return output
    finally:
        if not runner.dry_run:
            if had_config and previous_config is not None:
                active_config.write_bytes(previous_config)
            else:
                active_config.unlink(missing_ok=True)
