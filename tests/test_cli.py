from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from pwflash.cli import main


ROOT = Path(__file__).resolve().parents[1]


class InteractiveMenuTests(unittest.TestCase):
    def run_menu(self, answers: list[str]) -> tuple[int, str]:
        output = io.StringIO()
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            result = main(["--plain", "--profiles", str(ROOT / "devices")])
        return result, output.getvalue()

    def test_board_list_returns_to_main_menu(self) -> None:
        result, output = self.run_menu(["2", "", "q"])
        self.assertEqual(0, result)
        self.assertIn("btt-ebb42-v1.2", output)
        self.assertEqual(2, output.count("\nHauptmenü\n"))

    def test_back_from_board_selection_returns_to_main_menu(self) -> None:
        result, output = self.run_menu(["1", "b", "q"])
        self.assertEqual(0, result)
        self.assertIn("b) Zurück zum Hauptmenü", output)
        self.assertEqual(2, output.count("\nHauptmenü\n"))


if __name__ == "__main__":
    unittest.main()
