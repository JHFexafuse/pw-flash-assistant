from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pwflash.cli import main, matching_update_profiles, select_bitrate
from pwflash.profiles import load_profiles
from pwflash.ui import UI


ROOT = Path(__file__).resolve().parents[1]


class InteractiveMenuTests(unittest.TestCase):
    def run_menu(self, answers: list[str], extra_args: list[str] | None = None) -> tuple[int, str]:
        output = io.StringIO()
        argv = ["--plain", "--profiles", str(ROOT / "devices")]
        argv.extend(extra_args or [])
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            result = main(argv)
        return result, output.getvalue()

    def test_board_list_returns_to_main_menu(self) -> None:
        result, output = self.run_menu(["3", "", "q"])
        self.assertEqual(0, result)
        self.assertIn("btt-ebb42-v1.2", output)
        self.assertEqual(2, output.count("\nHauptmenü\n"))

    def test_back_from_board_selection_returns_to_main_menu(self) -> None:
        result, output = self.run_menu(["1", "b", "q"])
        self.assertEqual(0, result)
        self.assertIn("b) Zurück zum Hauptmenü", output)
        self.assertEqual(2, output.count("\nHauptmenü\n"))

    def test_update_can_return_to_main_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            printer = Path(tmp) / "printer.cfg"
            printer.write_text("[mcu CanHead]\ncanbus_uuid: 93741c9204fa\n", encoding="utf-8")
            result, output = self.run_menu(["2", "b", "q"], ["--printer-config", str(printer)])
        self.assertEqual(0, result)
        self.assertIn("Vorhandenes CAN-Bauteil aktualisieren", output)
        self.assertEqual(2, output.count("\nHauptmenü\n"))


class ConfirmationTests(unittest.TestCase):
    def test_enter_is_not_a_confirmation(self) -> None:
        with patch("builtins.input", side_effect=["", "j"]) as ask:
            answer = UI(plain=True).confirm("Erweiterung installieren?")
        self.assertTrue(answer)
        self.assertEqual(2, ask.call_count)
        ask.assert_called_with("\nErweiterung installieren? [j/n]: ")

    def test_explicit_no_is_required_for_rejection(self) -> None:
        with patch("builtins.input", side_effect=["", "n"]):
            self.assertFalse(UI(plain=True).confirm("Firmware schreiben?"))


class ProfileFilteringTests(unittest.TestCase):
    def test_canhead_lists_only_ebb_profiles(self) -> None:
        names = [profile.name for profile in matching_update_profiles(load_profiles(ROOT / "devices"), "CanHead")]
        self.assertEqual(3, len(names))
        self.assertTrue(all("EBB42" in name for name in names))

    def test_eddy_lists_only_eddy_profiles(self) -> None:
        names = [profile.name for profile in matching_update_profiles(load_profiles(ROOT / "devices"), "eddy")]
        self.assertEqual(2, len(names))
        self.assertTrue(all("Eddy Duo" in name for name in names))


class BitrateSelectionTests(unittest.TestCase):
    def test_current_can_bitrate_is_marked_in_selection(self) -> None:
        profile = {item.id: item for item in load_profiles(ROOT / "devices")}["btt-ebb42-v1.2"]
        output = io.StringIO()
        with patch("builtins.input", return_value="3"), redirect_stdout(output):
            selected = select_bitrate(
                UI(plain=True),
                profile,
                None,
                current=250000,
                interface="can0",
            )
        self.assertEqual(250000, selected)
        self.assertIn("250,000 Bit/s  ← aktuell auf can0", output.getvalue())


class DryRunTests(unittest.TestCase):
    def test_update_dry_run_does_not_write_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            printer = root / "printer.cfg"
            state = root / "state"
            printer.write_text("[mcu CanHead]\ncanbus_uuid: 93741c9204fa\n", encoding="utf-8")
            argv = [
                "update",
                "--plain",
                "--dry-run",
                "--profiles",
                str(ROOT / "devices"),
                "--printer-config",
                str(printer),
                "--state-dir",
                str(state),
                "--device",
                "btt-ebb42-v1.2",
                "--bitrate",
                "250000",
            ]
            output = io.StringIO()
            with (
                patch("builtins.input", side_effect=["1", "j"]),
                patch("pwflash.cli.FlashWorkflow.run"),
                redirect_stdout(output),
            ):
                result = main(argv)
            self.assertEqual(0, result)
            self.assertFalse((state / "inventory.json").exists())
            self.assertIn("Gerätezuordnung wird nicht gespeichert", output.getvalue())


if __name__ == "__main__":
    unittest.main()
