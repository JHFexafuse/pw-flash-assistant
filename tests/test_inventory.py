from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pwflash.inventory import DeviceInventory, discover_can_mcus


class InventoryTests(unittest.TestCase):
    def test_discovers_only_can_mcus_across_config_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            printer = root / "printer.cfg"
            printer.write_text(
                "[mcu]\nserial: /dev/ttyACM0\n[mcu CanHead]\ncanbus_uuid: 93741c9204fa # old\n",
                encoding="utf-8",
            )
            (root / "eddy.cfg").write_text("[mcu eddy]\ncanbus_uuid: 0aeb59fc9c23\n", encoding="utf-8")
            devices = discover_can_mcus(printer)
            self.assertEqual(["CanHead", "eddy"], [item.section for item in devices])
            self.assertEqual(["93741c9204fa", "0aeb59fc9c23"], [item.uuid for item in devices])

    def test_inventory_persists_profile_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            printer = root / "printer.cfg"
            printer.write_text("[mcu eddy]\ncanbus_uuid: 0aeb59fc9c23\n", encoding="utf-8")
            device = discover_can_mcus(printer)[0]
            path = root / "inventory.json"
            DeviceInventory(path).bind(device, "btt-eddy-duo-can-eddy-ng")
            loaded = DeviceInventory(path).find(device)
            self.assertIsNotNone(loaded)
            self.assertEqual("btt-eddy-duo-can-eddy-ng", loaded.profile_id)


if __name__ == "__main__":
    unittest.main()
