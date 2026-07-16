"""Developer check: validate all profile selections against source checkouts."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pwflash.profiles import load_profiles


def validate(source: Path, firmware: str) -> None:
    script = source / "lib" / "kconfiglib" / "olddefconfig.py"
    if not script.is_file():
        raise SystemExit(f"olddefconfig.py fehlt in {source}")
    for profile in load_profiles(ROOT / "devices"):
        for bitrate in profile.hardware["supported_bitrates"]:
            requested = profile.config_lines(firmware, bitrate)
            with tempfile.TemporaryDirectory() as tmp:
                config = Path(tmp) / ".config"
                config.write_text("\n".join(requested) + "\n", encoding="utf-8")
                env = os.environ.copy()
                env["KCONFIG_CONFIG"] = str(config)
                process = subprocess.run(
                    [sys.executable, str(script), "src/Kconfig"],
                    cwd=source,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                if process.returncode:
                    raise SystemExit(process.stdout)
                resolved = config.read_text(encoding="utf-8")
                missing = [line for line in requested if line not in resolved]
                if missing:
                    raise SystemExit(
                        f"{profile.id} / {firmware} / {bitrate}: Auswahl verworfen: {missing}"
                    )
                print(f"OK {profile.id} {firmware} {bitrate}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--katapult", type=Path, required=True)
    parser.add_argument("--klipper", type=Path, required=True)
    args = parser.parse_args()
    validate(args.katapult.resolve(), "katapult")
    validate(args.klipper.resolve(), "klipper")


if __name__ == "__main__":
    main()
