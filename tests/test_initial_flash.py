from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from pwflash.initial_flash import flash_initial_bootloader, required_commands
from pwflash.profiles import ProfileError, load_profiles, validate_profile
from pwflash.system import Result


ROOT = Path(__file__).resolve().parents[1]


class RecordingRunner:
    dry_run = True

    def __init__(self) -> None:
        self.commands: list[tuple[tuple[str, ...], Path | None]] = []

    def run(self, command, *, cwd=None, **kwargs) -> Result:
        cmd = tuple(str(part) for part in command)
        self.commands.append((cmd, cwd))
        return Result(cmd, 0, "")


class RealFilesystemRunner(RecordingRunner):
    dry_run = False


class InitialFlashTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.profiles = {profile.id: profile for profile in load_profiles(ROOT / "devices")}

    def test_ebb_uses_profile_driven_stm32_dfu_parameters(self) -> None:
        profile = self.profiles["btt-ebb42-v1.2"]
        runner = RecordingRunner()
        firmware = Path("/tmp/katapult.bin")
        flash_initial_bootloader(
            runner,
            profile,
            firmware,
            source_dir=Path("/tmp/katapult"),
            saved_config=Path("/tmp/ebb.config"),
        )
        command = runner.commands[-1][0]
        self.assertIn("0483:df11", command)
        self.assertIn("0x08000000:mass-erase:force:leave", command)
        self.assertIn(str(firmware), command)

    def test_eddy_uses_rp2040_bootsel_and_uf2(self) -> None:
        profile = self.profiles["btt-eddy-duo-can-eddy-ng"]
        initial = profile.workflow["initial_flash"]
        self.assertEqual("rp2040-bootsel", initial["method"])
        self.assertEqual("2e8a:0003", initial["usb_id"])
        self.assertEqual("katapult.uf2", profile.data["firmware"]["katapult"]["output"])
        self.assertEqual(["g++"], required_commands(profile))
        runner = RecordingRunner()
        flash_initial_bootloader(
            runner,
            profile,
            Path("/tmp/katapult.uf2"),
            source_dir=Path("/tmp/katapult"),
            saved_config=Path("/tmp/eddy.config"),
        )
        self.assertEqual(("make", "olddefconfig"), runner.commands[0][0])
        self.assertEqual(("make", "flash"), runner.commands[1][0])

    def test_full_profile_without_explicit_transport_is_rejected(self) -> None:
        data = copy.deepcopy(self.profiles["btt-ebb42-v1.2"].data)
        del data["workflow"]["initial_flash"]
        with self.assertRaises(ProfileError):
            validate_profile(data, Path("broken.json"))

    def test_rp2040_flash_restores_previous_katapult_config(self) -> None:
        profile = self.profiles["btt-eddy-duo-can-standard"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "katapult"
            source.mkdir()
            active = source / ".config"
            active.write_text("CONFIG_MACH_STM32=y\n", encoding="utf-8")
            saved = root / "eddy.config"
            saved.write_text("CONFIG_MACH_RP2040=y\n", encoding="utf-8")
            runner = RealFilesystemRunner()
            flash_initial_bootloader(
                runner,
                profile,
                root / "katapult.uf2",
                source_dir=source,
                saved_config=saved,
            )
            self.assertEqual("CONFIG_MACH_STM32=y\n", active.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
