from __future__ import annotations

from pathlib import Path
from typing import Any

from .kconfig import run_make_target_with_config
from .profiles import DeviceProfile
from .system import AssistantError, Result, Runner


SUPPORTED_METHODS = {"stm32-dfu", "rp2040-bootsel"}


def initial_flash_config(profile: DeviceProfile) -> dict[str, Any]:
    config = profile.workflow.get("initial_flash")
    if not isinstance(config, dict):
        raise AssistantError(f"Profil {profile.id}: workflow.initial_flash fehlt")
    method = config.get("method")
    if method not in SUPPORTED_METHODS:
        raise AssistantError(f"Profil {profile.id}: unbekannte Erstflash-Methode {method!r}")
    return config


def required_commands(profile: DeviceProfile) -> list[str]:
    method = initial_flash_config(profile)["method"]
    return ["dfu-util"] if method == "stm32-dfu" else ["g++"]


def flash_initial_bootloader(
    runner: Runner,
    profile: DeviceProfile,
    firmware: Path,
    *,
    source_dir: Path,
    saved_config: Path,
) -> Result:
    config = initial_flash_config(profile)
    method = config["method"]
    if method == "stm32-dfu":
        address = str(config["address"])
        options = [str(item) for item in config.get("options", [])]
        dfuse_target = ":".join([address, *options])
        command = ["sudo", "dfu-util"]
        if config.get("reset", False):
            command.append("-R")
        command.extend(
            [
                "-a",
                str(config.get("alternate", 0)),
                "-s",
                dfuse_target,
                "-D",
                str(firmware),
                "-d",
                str(config["usb_id"]),
            ]
        )
        return runner.run(command, check=False, capture=True)
    if method == "rp2040-bootsel":
        return run_make_target_with_config(
            runner,
            source_dir=source_dir,
            config_path=saved_config,
            target=str(config.get("make_target", "flash")),
        )
    raise AssistantError(f"Nicht unterstützte Erstflash-Methode: {method}")
