from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pwflash.profiles import load_profiles
from pwflash.workflow import FlashWorkflow


ROOT = Path(__file__).resolve().parents[1]


class CapturingUI:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str]] = []

    def header(self, text: str) -> None:
        self.messages.append(("header", text))

    def title(self, text: str) -> None:
        self.messages.append(("title", text))

    def info(self, text: str) -> None:
        self.messages.append(("info", text))

    def warn(self, text: str) -> None:
        self.messages.append(("warn", text))

    def confirm(self, text: str) -> bool:
        self.messages.append(("confirm", text))
        return True


class WorkflowUiTests(unittest.TestCase):
    def make_workflow(self, printer_config: Path, ui: CapturingUI) -> FlashWorkflow:
        profile = {item.id: item for item in load_profiles(ROOT / "devices")}["btt-ebb42-v1.2"]
        return FlashWorkflow(
            profile,
            250000,
            runner=None,
            ui=ui,
            klipper_dir=Path("~/klipper"),
            katapult_dir=Path("~/katapult"),
            state_dir=Path("~/.local/share/pwflash"),
            printer_config=printer_config,
            mcu_section="CanHead",
            mode="klipper",
        )

    def test_update_summary_is_short_and_neutral(self) -> None:
        ui = CapturingUI()
        workflow = self.make_workflow(Path("printer.cfg"), ui)
        workflow._summary()
        self.assertIn(("info", "Ablauf: Mittels Katapult-Bootloader Klipper aktualisieren"), ui.messages)
        self.assertIn(("confirm", "Stimmt die Auswahl überein?"), ui.messages)
        self.assertFalse(any(kind == "warn" for kind, _ in ui.messages))

    def test_target_display_does_not_repeat_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            printer = Path(tmp) / "printer.cfg"
            printer.write_text("[mcu CanHead]\ncanbus_uuid: 93741c9204fa\n", encoding="utf-8")
            ui = CapturingUI()
            workflow = self.make_workflow(printer, ui)
            self.assertEqual("93741c9204fa", workflow._existing_klipper_uuid())
            self.assertIn(("title", "Zielgerät"), ui.messages)
            self.assertFalse(any(kind == "confirm" for kind, _ in ui.messages))


if __name__ == "__main__":
    unittest.main()
