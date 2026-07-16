from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from extensions.pw_multibed import PrintWarsMultiBed
from pwflash.multibed import MultibedManager, discover_multibed_heaters, render_multibed_config
from pwflash.system import Runner
from pwflash.ui import UI


ROOT = Path(__file__).resolve().parents[1]


class FakeHeater:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeHeaters:
    def __init__(self) -> None:
        self.by_name = {name: FakeHeater(name) for name in ("heater_bed", "_Bed_2", "_Bed_3")}
        self.calls: list[tuple[str, float, bool]] = []

    def lookup_heater(self, name: str) -> FakeHeater:
        return self.by_name[name]

    def set_temperature(self, heater: FakeHeater, target: float, wait: bool = False) -> None:
        self.calls.append((heater.name, target, wait))


class FakeGcode:
    def __init__(self, original) -> None:
        self.mux_commands = {"SET_HEATER_TEMPERATURE": ("HEATER", {"heater_bed": original})}
        self.commands = {"M140": object(), "M190": object()}

    def register_command(self, name, handler, **kwargs):
        if handler is None:
            return self.commands.pop(name, None)
        self.commands[name] = handler


class FakePrinter:
    config_error = RuntimeError

    def __init__(self) -> None:
        self.events = {}
        self.heaters = FakeHeaters()
        self.primary_calls: list[float] = []
        self.gcode = FakeGcode(lambda gcmd: self.primary_calls.append(gcmd.get_float("TARGET", 0.0)))

    def register_event_handler(self, event, handler) -> None:
        self.events[event] = handler

    def lookup_object(self, name):
        return {"heaters": self.heaters, "gcode": self.gcode}[name]


class FakeConfig:
    error = RuntimeError

    def __init__(self, printer: FakePrinter) -> None:
        self.printer = printer

    def get_printer(self) -> FakePrinter:
        return self.printer

    def get(self, name, default=None):
        values = {
            "heaters": "heater_bed, _Bed_2, _Bed_3",
            "primary": "heater_bed",
        }
        return values.get(name, default)

    def getboolean(self, name, default=False):
        return True if name == "wait_all" else default


class FakeCommand:
    def __init__(self, **values: float) -> None:
        self.values = values
        self.messages: list[str] = []

    def get_float(self, name, default=0.0):
        return self.values.get(name, default)

    def respond_info(self, message: str) -> None:
        self.messages.append(message)


class MultibedExtensionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.printer = FakePrinter()
        self.extension = PrintWarsMultiBed(FakeConfig(self.printer))
        self.printer.events["klippy:connect"]()

    def test_m140_sets_all_heaters(self) -> None:
        self.extension.cmd_M140(FakeCommand(S=65.0))
        self.assertEqual(
            [("heater_bed", 65.0, False), ("_Bed_2", 65.0, False), ("_Bed_3", 65.0, False)],
            self.printer.heaters.calls,
        )

    def test_m190_waits_for_every_heater(self) -> None:
        self.extension.cmd_M190(FakeCommand(S=70.0))
        waited = [name for name, _, wait in self.printer.heaters.calls if wait]
        self.assertEqual(["heater_bed", "_Bed_2", "_Bed_3"], waited)

    def test_primary_set_heater_command_syncs_other_zones(self) -> None:
        self.extension.cmd_SET_HEATER_TEMPERATURE(FakeCommand(TARGET=55.0))
        self.assertEqual([55.0], self.printer.primary_calls)
        self.assertEqual(
            [("_Bed_2", 55.0, False), ("_Bed_3", 55.0, False)],
            self.printer.heaters.calls,
        )


class MultibedInstallerTests(unittest.TestCase):
    def test_discovers_only_bed_zones_in_natural_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "printer.cfg").write_text(
                "[heater_generic chamber]\n"
                "[heater_generic _Bed_10]\n"
                "[heater_bed]\n"
                "[heater_generic _Bed_2]\n",
                encoding="utf-8",
            )
            self.assertEqual(
                ["heater_bed", "_Bed_2", "_Bed_10"],
                discover_multibed_heaters(root),
            )

    def test_rendered_config_waits_for_all_zones(self) -> None:
        rendered = render_multibed_config(["heater_bed", "_Bed_2"])
        self.assertIn("wait_all: True", rendered)
        self.assertIn("  _Bed_2", rendered)

    def test_install_dry_run_does_not_write_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            printer = config_dir / "printer.cfg"
            printer.write_text(
                "[heater_bed]\n[heater_generic _Bed_2]\n",
                encoding="utf-8",
            )
            klipper = root / "klipper"
            output = io.StringIO()
            manager = MultibedManager(
                runner=Runner(dry_run=True),
                ui=UI(plain=True),
                root=ROOT,
                klipper_dir=klipper,
                printer_config=printer,
            )
            with patch("builtins.input", return_value="j"), redirect_stdout(output):
                manager.install()
            self.assertFalse((config_dir / "pw_multibed.cfg").exists())
            self.assertNotIn("include pw_multibed", printer.read_text(encoding="utf-8"))
            self.assertIn("Dry Run", output.getvalue())

    def test_legacy_patch_migration_is_only_reported_during_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "config"
            config_dir.mkdir()
            printer = config_dir / "printer.cfg"
            printer.write_text("[heater_bed]\n[heater_generic _Bed_2]\n", encoding="utf-8")
            klipper = root / "klipper"
            extras = klipper / "klippy" / "extras"
            extras.mkdir(parents=True)
            heaters = extras / "heaters.py"
            heaters.write_text("# synchronisiere andere Betten\n", encoding="utf-8")
            manager = MultibedManager(
                runner=Runner(dry_run=True),
                ui=UI(plain=True),
                root=ROOT,
                klipper_dir=klipper,
                printer_config=printer,
            )
            output = io.StringIO()
            with patch("builtins.input", side_effect=["j", "j"]), redirect_stdout(output):
                manager.install()
            self.assertEqual("# synchronisiere andere Betten\n", heaters.read_text(encoding="utf-8"))
            self.assertIn("alte Kernpatch würde gesichert", output.getvalue())


if __name__ == "__main__":
    unittest.main()
