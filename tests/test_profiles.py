from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pwflash.kconfig import write_seed_config
from pwflash.profiles import load_profiles
from pwflash.system import parse_katapult_nodes, parse_klipper_nodes


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


if __name__ == "__main__":
    unittest.main()
