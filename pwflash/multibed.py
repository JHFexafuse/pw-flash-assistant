from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from .system import AssistantError, Runner
from .ui import UI


INCLUDE_LINE = "[include pw_multibed.cfg]"
LEGACY_MARKERS = {
    "klippy/extras/heaters.py": "synchronisiere andere Betten",
    "klippy/extras/heater_bed.py": 'for name in ["heater_bed", "_Bed_2"',
}


def discover_multibed_heaters(config_dir: Path) -> list[str]:
    section_pattern = re.compile(r"^\s*\[(heater_bed|heater_generic\s+([^\]]+))\]", re.IGNORECASE)
    discovered: set[str] = set()
    for path in sorted(config_dir.rglob("*.cfg")):
        if path.name == "pw_multibed.cfg":
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeError):
            continue
        for line in lines:
            match = section_pattern.match(line)
            if not match:
                continue
            if match.group(1).casefold() == "heater_bed":
                discovered.add("heater_bed")
                continue
            name = match.group(2).strip()
            if re.fullmatch(r"_?bed[_ -]?\d+", name, re.IGNORECASE):
                discovered.add(name)

    def sort_key(name: str) -> tuple[int, int, str]:
        if name.casefold() == "heater_bed":
            return (0, 0, name)
        number = re.search(r"\d+", name)
        return (1, int(number.group()) if number else 999, name.casefold())

    return sorted(discovered, key=sort_key)


def render_multibed_config(heaters: list[str]) -> str:
    lines = [
        "# Vom PrintWars Flash Assistant verwaltet",
        "[pw_multibed]",
        "primary: heater_bed",
        "wait_all: True",
        "heaters:",
    ]
    lines.extend(f"  {name}" for name in heaters)
    return "\n".join(lines) + "\n"


def has_include(printer_config: Path) -> bool:
    if not printer_config.is_file():
        return False
    pattern = re.compile(r"^\s*\[include\s+pw_multibed\.cfg\]\s*$", re.IGNORECASE)
    return any(pattern.match(line) for line in printer_config.read_text(encoding="utf-8").splitlines())


class MultibedManager:
    def __init__(
        self,
        *,
        runner: Runner,
        ui: UI,
        root: Path,
        klipper_dir: Path,
        printer_config: Path,
    ) -> None:
        self.runner = runner
        self.ui = ui
        self.root = root.resolve()
        self.klipper_dir = klipper_dir.expanduser()
        self.printer_config = printer_config.expanduser()
        self.config_dir = self.printer_config.parent
        self.source_extension = self.root / "extensions" / "pw_multibed.py"
        self.target_extension = self.klipper_dir / "klippy" / "extras" / "pw_multibed.py"
        self.extension_config = self.config_dir / "pw_multibed.cfg"

    def _check_paths(self) -> None:
        if not self.runner.dry_run and not (self.klipper_dir / ".git").is_dir():
            raise AssistantError(f"Klipper-Checkout nicht gefunden: {self.klipper_dir}")
        if not self.printer_config.is_file():
            raise AssistantError(f"printer.cfg nicht gefunden: {self.printer_config}")
        if not self.source_extension.is_file():
            raise AssistantError(f"Multibed-Erweiterung fehlt: {self.source_extension}")

    def _backup(self, path: Path) -> Path:
        stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S-%f")
        backup = path.with_name(f"{path.name}.pwflash-{stamp}.bak")
        shutil.copy2(path, backup)
        return backup

    def _atomic_write(self, path: Path, content: str) -> None:
        temporary = path.with_suffix(path.suffix + ".pwflash.tmp")
        temporary.write_text(content, encoding="utf-8")
        os.replace(temporary, path)

    def _legacy_files(self) -> list[Path]:
        found: list[Path] = []
        for relative, marker in LEGACY_MARKERS.items():
            path = self.klipper_dir / relative
            if path.is_file() and marker in path.read_text(encoding="utf-8", errors="ignore"):
                found.append(path)
        return found

    def _migrate_legacy_patch(self) -> None:
        legacy = self._legacy_files()
        if not legacy:
            return
        self.ui.warn(
            "Alter Klipper-Multibed-Kernpatch erkannt. Die vollständigen Klipper-Dateien müssen durch "
            "die Originaldateien des aktuell ausgecheckten Klipper-Stands ersetzt werden."
        )
        if not self.ui.confirm("Alten Kernpatch sichern und automatisch migrieren?"):
            raise AssistantError("Multibed-Installation wegen des alten Kernpatches abgebrochen.")
        if self.runner.dry_run:
            self.ui.info("Dry Run: Der alte Kernpatch würde gesichert und aus dem aktuellen Klipper-Stand wiederhergestellt.")
            return
        for path in legacy:
            relative = path.relative_to(self.klipper_dir).as_posix()
            result = self.runner.run(
                ["git", "-C", str(self.klipper_dir), "show", f"HEAD:{relative}"],
                check=False,
                capture=True,
            )
            if result.returncode or not result.stdout:
                raise AssistantError(f"Originaldatei konnte nicht aus Klipper gelesen werden: {relative}")
            if not self.runner.dry_run:
                backup = self._backup(path)
                self._atomic_write(path, result.stdout)
                self.ui.ok(f"{relative} wiederhergestellt. Backup: {backup}")

    def install(self) -> None:
        self.ui.header("Multibed-Unterstützung")
        self.ui.title("Heizzonen erkennen")
        self._check_paths()
        heaters = discover_multibed_heaters(self.config_dir)
        if "heater_bed" not in heaters or len(heaters) < 2:
            raise AssistantError(
                "Es wurden nicht mindestens heater_bed und eine weitere Zone wie [heater_generic _Bed_2] "
                "gefunden. Pin- und Sensorbelegungen werden aus Sicherheitsgründen nicht automatisch erzeugt."
            )
        for name in heaters:
            self.ui.info(f"Heizzone: {name}")
        self.ui.info("M140, M190 und die Hauptbett-Steuerung werden auf diese Zonen synchronisiert.")
        self.ui.info("M190 wartet, bis alle aufgeführten Zonen ihre Zieltemperatur erreicht haben.")
        if not self.ui.confirm("Diese Multibed-Zuordnung installieren?"):
            raise AssistantError("Multibed-Installation abgebrochen.")
        self._migrate_legacy_patch()
        if self.runner.dry_run:
            self.ui.info(f"Dry Run: Erweiterung würde nach {self.target_extension} verknüpft.")
            self.ui.info(f"Dry Run: Konfiguration würde nach {self.extension_config} geschrieben.")
            self.ui.info(f"Dry Run: {INCLUDE_LINE} würde in printer.cfg ergänzt.")
            return
        self.target_extension.parent.mkdir(parents=True, exist_ok=True)
        if self.target_extension.exists() or self.target_extension.is_symlink():
            if self.target_extension.exists() and (
                not self.target_extension.is_symlink()
                or self.target_extension.resolve() != self.source_extension
            ):
                backup = self._backup(self.target_extension)
                self.ui.warn(f"Bestehende Erweiterungsdatei gesichert: {backup}")
            self.target_extension.unlink()
        self.target_extension.symlink_to(self.source_extension)
        if self.extension_config.exists():
            self.ui.info(f"Vorhandene Multibed-Konfiguration wird gesichert: {self._backup(self.extension_config)}")
        self._atomic_write(self.extension_config, render_multibed_config(heaters))
        if not has_include(self.printer_config):
            backup = self._backup(self.printer_config)
            content = self.printer_config.read_text(encoding="utf-8")
            separator = "" if not content or content.endswith("\n") else "\n"
            self._atomic_write(self.printer_config, content + separator + "\n" + INCLUDE_LINE + "\n")
            self.ui.ok(f"printer.cfg ergänzt. Backup: {backup}")
        self.ui.ok("Multibed-Erweiterung wurde installiert.")
        if self.ui.confirm("Klipper-Dienst jetzt neu starten?"):
            self.runner.run(["sudo", "systemctl", "restart", "klipper"])
            self.ui.ok("Klipper-Dienst wurde neu gestartet.")

    def status(self) -> None:
        self.ui.header("Multibed-Status")
        self.ui.title("Installationsstatus")
        linked = self.target_extension.is_symlink() and self.target_extension.resolve() == self.source_extension
        self.ui.info(f"Erweiterung: {'installiert' if linked else 'nicht installiert'}")
        self.ui.info(f"Konfiguration: {'vorhanden' if self.extension_config.is_file() else 'fehlt'}")
        self.ui.info(f"printer.cfg-Include: {'vorhanden' if has_include(self.printer_config) else 'fehlt'}")
        heaters = discover_multibed_heaters(self.config_dir) if self.config_dir.is_dir() else []
        self.ui.info("Erkannte Zonen: " + (", ".join(heaters) if heaters else "keine"))
        if self._legacy_files():
            self.ui.warn("Alter Klipper-Kernpatch ist noch vorhanden.")

    def remove(self) -> None:
        self.ui.header("Multibed entfernen")
        self.ui.warn("Die Heizzonen-Konfiguration selbst bleibt erhalten; entfernt wird nur die Synchronisierung.")
        if not self.ui.confirm("Multibed-Synchronisierung entfernen?"):
            raise AssistantError("Entfernen abgebrochen.")
        if self.runner.dry_run:
            self.ui.info("Dry Run: Erweiterung, Verwaltungsdatei und printer.cfg-Include würden entfernt.")
            return
        if has_include(self.printer_config):
            backup = self._backup(self.printer_config)
            pattern = re.compile(r"^\s*\[include\s+pw_multibed\.cfg\]\s*\n?", re.IGNORECASE | re.MULTILINE)
            content = pattern.sub("", self.printer_config.read_text(encoding="utf-8"))
            self._atomic_write(self.printer_config, content)
            self.ui.ok(f"Include entfernt. Backup: {backup}")
        if self.extension_config.is_file():
            self.ui.info(f"Multibed-Konfiguration gesichert: {self._backup(self.extension_config)}")
            self.extension_config.unlink()
        if self.target_extension.is_symlink():
            self.target_extension.unlink()
        self.ui.ok("Multibed-Synchronisierung wurde entfernt.")
        if self.ui.confirm("Klipper-Dienst jetzt neu starten?"):
            self.runner.run(["sudo", "systemctl", "restart", "klipper"])


def run_multibed_menu(manager: MultibedManager) -> str:
    manager.ui.header("Multibed verwalten")
    manager.ui.title("Multibed")
    return manager.ui.choose(
        "Aktion",
        [
            ("1", "Installieren oder aktualisieren"),
            ("2", "Status anzeigen"),
            ("3", "Synchronisierung entfernen"),
            ("b", "Zurück zum Hauptmenü"),
            ("q", "Beenden"),
        ],
    )
