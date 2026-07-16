from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pwflash.kconfig import build_firmware, validate_config, write_seed_config
from pwflash.profiles import load_profiles
from pwflash.system import AssistantError, Result, parse_katapult_nodes, parse_klipper_nodes


ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def test_all_profiles_validate(self) -> None:
        profiles = load_profiles(ROOT / "devices")
        self.assertEqual(3, len(profiles))

    def test_v11_has_hotend_warning(self) -> None:
        profiles = {profile.id: profile for profile in load_profiles(ROOT / "devices")}
        warning = " ".join(profiles["btt-ebb42-v1.1"].data["safety_warnings"])
        self.assertIn("Hotend", warning)
        self.assertIn("PA2", warning)

    def test_v12_does_not_request_printer_power_off(self) -> None:
        profiles = {profile.id: profile for profile in load_profiles(ROOT / "devices")}
        instructions = " ".join(profiles["btt-ebb42-v1.2"].workflow["enter_dfu_steps"])
        self.assertNotIn("Drucker ausschalten", instructions)
        self.assertIn("eingeschaltet lassen", instructions)

    def test_bitrate_is_rendered(self) -> None:
        profile = load_profiles(ROOT / "devices")[0]
        lines = profile.config_lines("katapult", 500000)
        self.assertIn("CONFIG_CANBUS_FREQUENCY=500000", lines)

    def test_seed_config_writer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".config"
            write_seed_config(path, ["CONFIG_ONE=y", "", " CONFIG_TWO=42 "])
            self.assertEqual("CONFIG_ONE=y\nCONFIG_TWO=42\n", path.read_text(encoding="utf-8"))


class KatapultOutputTests(unittest.TestCase):
    def test_parse_query(self) -> None:
        output = "Detected UUID: 4220d6e9e9f9, Application: Katapult\n"
        self.assertEqual([("4220d6e9e9f9", "katapult")], parse_katapult_nodes(output))

    def test_parse_klipper_query(self) -> None:
        output = "Found canbus_uuid=4220d6e9e9f9, Application: Klipper\n"
        self.assertEqual([("4220d6e9e9f9", "klipper")], parse_klipper_nodes(output))


class FakeBuildRunner:
    dry_run = False

    def __init__(self, *, remove_setting: str | None = None) -> None:
        self.remove_setting = remove_setting
        self.commands: list[tuple[str, ...]] = []

    def run(self, command, *, cwd=None, **kwargs) -> Result:
        cmd = tuple(str(part) for part in command)
        self.commands.append(cmd)
        active = Path(cwd) / ".config"
        if cmd == ("make", "olddefconfig") and self.remove_setting:
            lines = active.read_text(encoding="utf-8").splitlines()
            active.write_text(
                "\n".join(line for line in lines if line != self.remove_setting) + "\n",
                encoding="utf-8",
            )
        if len(cmd) == 2 and cmd[0] == "make" and cmd[1].startswith("-j"):
            output = Path(cwd) / "out" / "katapult.bin"
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"firmware")
        return Result(cmd, 0, "")


class FirmwareBuildTests(unittest.TestCase):
    def test_build_uses_active_config_and_restores_previous_config(self) -> None:
        profile = {item.id: item for item in load_profiles(ROOT / "devices")}["btt-ebb42-v1.2"]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "katapult"
            source.mkdir()
            active = source / ".config"
            active.write_text("CONFIG_MACH_LPC176X=y\n", encoding="utf-8")
            saved = root / "saved.config"
            runner = FakeBuildRunner()

            output = build_firmware(
                runner,
                source_dir=source,
                config_path=saved,
                profile=profile,
                firmware="katapult",
                bitrate=250000,
            )

            self.assertTrue(output.is_file())
            self.assertEqual("CONFIG_MACH_LPC176X=y\n", active.read_text(encoding="utf-8"))
            validate_config(saved, profile.config_lines("katapult", 250000))

    def test_build_stops_when_board_setting_is_not_applied(self) -> None:
        profile = {item.id: item for item in load_profiles(ROOT / "devices")}["btt-ebb42-v1.2"]
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "katapult"
            source.mkdir()
            runner = FakeBuildRunner(remove_setting="CONFIG_MACH_STM32G0B1=y")
            with self.assertRaises(AssistantError):
                build_firmware(
                    runner,
                    source_dir=source,
                    config_path=Path(tmp) / "saved.config",
                    profile=profile,
                    firmware="katapult",
                    bitrate=250000,
                )


if __name__ == "__main__":
    unittest.main()
