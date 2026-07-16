from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Iterable


class AssistantError(RuntimeError):
    pass


@dataclass(frozen=True)
class Result:
    command: tuple[str, ...]
    returncode: int
    stdout: str


class Runner:
    def __init__(self, *, dry_run: bool = False, verbose: bool = False) -> None:
        self.dry_run = dry_run
        self.verbose = verbose

    def run(
        self,
        command: Iterable[str],
        *,
        cwd: Path | None = None,
        check: bool = True,
        capture: bool = False,
        env: dict[str, str] | None = None,
        readonly: bool = False,
    ) -> Result:
        cmd = tuple(str(part) for part in command)
        if self.verbose or self.dry_run:
            print("  $ " + " ".join(cmd))
        if self.dry_run and not readonly:
            return Result(cmd, 0, "")
        try:
            process = subprocess.run(
                cmd,
                cwd=cwd,
                env=env,
                text=True,
                stdout=subprocess.PIPE if capture else None,
                stderr=subprocess.STDOUT if capture else None,
                check=False,
            )
        except OSError as exc:
            if readonly:
                return Result(cmd, 127, str(exc))
            raise
        output = process.stdout or ""
        if capture and self.verbose and output:
            print(output, end="")
        if check and process.returncode:
            detail = f"\n{output.strip()}" if output.strip() else ""
            raise AssistantError(f"Befehl fehlgeschlagen ({process.returncode}): {' '.join(cmd)}{detail}")
        return Result(cmd, process.returncode, output)


def require_linux() -> None:
    if os.name != "posix":
        raise AssistantError("Das echte Flashen muss auf dem Linux-Rechner des Druckers ausgeführt werden.")


def missing_commands(names: Iterable[str]) -> list[str]:
    return [name for name in names if shutil.which(name) is None]


def usb_device_count(runner: Runner, usb_id: str) -> int:
    result = runner.run(["lsusb"], check=False, capture=True)
    expected = usb_id.lower()
    return sum(1 for line in result.stdout.lower().splitlines() if expected in line)


def wait_for_single_usb(runner: Runner, usb_id: str, timeout: int = 180) -> int:
    if runner.dry_run:
        return 1
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        count = usb_device_count(runner, usb_id)
        if count:
            return count
        time.sleep(1)
    return 0


def can_link_bitrate(runner: Runner, interface: str) -> int | None:
    result = runner.run(
        ["ip", "-details", "link", "show", interface],
        check=False,
        capture=True,
        readonly=True,
    )
    match = re.search(r"\bbitrate\s+(\d+)", result.stdout)
    return int(match.group(1)) if match else None


def parse_katapult_nodes(output: str) -> list[tuple[str, str]]:
    matches = re.findall(
        r"(?:Detected UUID|UUID)\s*:\s*([0-9a-fA-F]{12}).*?Application\s*:\s*([A-Za-z]+)",
        output,
        flags=re.IGNORECASE,
    )
    return [(uuid.lower(), app.lower()) for uuid, app in matches]


def parse_klipper_nodes(output: str) -> list[tuple[str, str]]:
    matches = re.findall(
        r"Found\s+canbus_uuid=([0-9a-fA-F]{12}).*?Application\s*:\s*([A-Za-z]+)",
        output,
        flags=re.IGNORECASE,
    )
    return [(uuid.lower(), app.lower()) for uuid, app in matches]


def klipper_flash_verified(output: str) -> bool:
    return "Verification Complete" in output and "Programming Complete" in output
