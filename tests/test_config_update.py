from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from pwflash.config_update import find_canbus_uuid, update_canbus_uuid
from pwflash.system import AssistantError


class PrinterConfigUpdateTests(unittest.TestCase):
    def test_updates_canhead_with_timestamp_and_backup(self) -> None:
        original = "[printer]\nkinematics: corexy\n\n[mcu CanHead]\ncanbus_uuid: aabbccddeeff\n"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printer.cfg"
            path.write_text(original, encoding="utf-8")
            result = update_canbus_uuid(
                path,
                "CanHead",
                "112233445566",
                timestamp=datetime(2026, 7, 16, 15, 30, tzinfo=timezone.utc),
            )
            self.assertEqual("aabbccddeeff", result.old_uuid)
            self.assertEqual(original, result.backup_path.read_text(encoding="utf-8"))
            updated = path.read_text(encoding="utf-8")
            self.assertIn(
                "canbus_uuid: 112233445566  # 2026-07-16 15:30:00 UTC # alte ID: aabbccddeeff",
                updated,
            )
            self.assertEqual("112233445566", find_canbus_uuid(path, "canhead"))

    def test_refuses_missing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printer.cfg"
            path.write_text("[mcu]\nserial: /dev/ttyUSB0\n", encoding="utf-8")
            with self.assertRaises(AssistantError):
                find_canbus_uuid(path, "CanHead")


if __name__ == "__main__":
    unittest.main()
