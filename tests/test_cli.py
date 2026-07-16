from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pwflash.cli import main
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
    def test_enter_uses_visible_recommended_yes_default(self) -> None:
        with patch("builtins.input", return_value="") as ask:
            answer = UI(plain=True).confirm("Erweiterung installieren?", default=True)
        self.assertTrue(answer)
        ask.assert_called_once_with("\nErweiterung installieren? [j/n, ENTER = ja]: ")

    def test_enter_uses_no_for_safety_default(self) -> None:
        with patch("builtins.input", return_value=""):
            self.assertFalse(UI(plain=True).confirm("Firmware schreiben?", default=False))


if __name__ == "__main__":
    unittest.main()
