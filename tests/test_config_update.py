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
                "canbus_uuid: 112233445566  # 2026-07-16 15:30:00 UTC # vorher: aabbccddeeff",
                updated,
            )
            self.assertEqual("112233445566", find_canbus_uuid(path, "canhead"))

    def test_refuses_missing_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printer.cfg"
            path.write_text("[mcu]\nserial: /dev/ttyUSB0\n", encoding="utf-8")
            with self.assertRaises(AssistantError):
                find_canbus_uuid(path, "CanHead")

    def test_same_uuid_refreshes_date_and_keeps_one_legacy_predecessor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printer.cfg"
            path.write_text(
                "[mcu CanHead]\ncanbus_uuid: 93741c9204fa #d954149907ed\n",
                encoding="utf-8",
            )
            update_canbus_uuid(
                path,
                "CanHead",
                "93741c9204fa",
                timestamp=datetime(2026, 7, 16, 16, 0, tzinfo=timezone.utc),
            )
            line = path.read_text(encoding="utf-8").splitlines()[1]
            self.assertEqual(
                "canbus_uuid: 93741c9204fa  # 2026-07-16 16:00:00 UTC # vorher: d954149907ed",
                line,
            )

    def test_new_uuid_keeps_only_direct_predecessor_with_its_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "printer.cfg"
            path.write_text(
                "[mcu CanHead]\n"
                "canbus_uuid: aaaaaaaaaaaa  # 2026-06-01 10:00:00 CEST "
                "# vorher: bbbbbbbbbbbb 2026-05-01 09:00:00 CEST\n",
                encoding="utf-8",
            )
            update_canbus_uuid(
                path,
                "CanHead",
                "cccccccccccc",
                timestamp=datetime(2026, 7, 16, 16, 30, tzinfo=timezone.utc),
            )
            line = path.read_text(encoding="utf-8").splitlines()[1]
            self.assertEqual(
                "canbus_uuid: cccccccccccc  # 2026-07-16 16:30:00 UTC "
                "# vorher: aaaaaaaaaaaa 2026-06-01 10:00:00 CEST",
                line,
            )
            self.assertNotIn("bbbbbbbbbbbb", line)


if __name__ == "__main__":
    unittest.main()
