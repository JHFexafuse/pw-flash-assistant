from __future__ import annotations

import time
from pathlib import Path

from .config_update import find_canbus_uuid, update_canbus_uuid
from .kconfig import build_firmware
from .profiles import DeviceProfile
from .system import (
    AssistantError,
    Runner,
    can_link_bitrate,
    klipper_flash_verified,
    missing_commands,
    parse_katapult_nodes,
    parse_klipper_nodes,
    require_linux,
    wait_for_usb,
)
from .ui import UI


class FlashWorkflow:
    def __init__(
        self,
        profile: DeviceProfile,
        bitrate: int,
        *,
        runner: Runner,
        ui: UI,
        klipper_dir: Path,
        katapult_dir: Path,
        state_dir: Path,
        printer_config: Path,
        mcu_section: str,
        mode: str,
        can_interface: str = "can0",
    ) -> None:
        self.profile = profile
        self.bitrate = bitrate
        self.runner = runner
        self.ui = ui
        self.klipper_dir = klipper_dir.expanduser()
        self.katapult_dir = katapult_dir.expanduser()
        self.state_dir = state_dir.expanduser()
        self.printer_config = printer_config.expanduser()
        self.mcu_section = mcu_section
        self.mode = mode
        self.can_interface = can_interface

    def run(self) -> None:
        if not self.runner.dry_run:
            require_linux()
        self._summary()
        self._preflight()
        if self.mode == "full":
            katapult_bin = self._build_katapult()
            self._enter_dfu()
            self._flash_katapult(katapult_bin)
            self._move_to_can()
            uuid = self._find_katapult_uuid()
        else:
            self._verify_can_bitrate()
            uuid = self._existing_klipper_uuid()
        klipper_bin = self._build_klipper()
        self._flash_klipper(uuid, klipper_bin)
        self._finish(uuid)

    def _summary(self) -> None:
        hw = self.profile.hardware
        self.ui.header("Geführte Board-Installation")
        self.ui.title("Auswahl prüfen")
        self.ui.info(f"Board: {self.profile.name}")
        self.ui.info(f"MCU: {hw['mcu']}")
        self.ui.info(f"Ziel: CAN über {self.can_interface} mit {self.bitrate:,} Bit/s")
        if self.mode == "full":
            self.ui.info("Ablauf: Katapult per USB/DFU installieren, danach Klipper per CAN flashen")
            for warning in self.profile.data.get("safety_warnings", []):
                self.ui.warn(str(warning))
        else:
            self.ui.info("Ablauf: Vorhandenes Katapult verwenden und ausschließlich Klipper per CAN aktualisieren")
            self.ui.warn("Katapult wird in diesem Modus nicht neu installiert oder überschrieben.")
        if not self.ui.confirm("Sind Boardversion und Sicherheitsangaben korrekt?", default=False):
            raise AssistantError("Vom Benutzer abgebrochen.")

    def _preflight(self) -> None:
        self.ui.title("System prüfen")
        required = ["git", "make", "dfu-util", "lsusb", "ip", "python3", "arm-none-eabi-gcc"]
        missing = missing_commands(required)
        if missing and not self.runner.dry_run:
            self.ui.error("Es fehlen: " + ", ".join(missing))
            if self.ui.confirm("Fehlende Debian-Pakete jetzt installieren?", default=True):
                self.runner.run(["sudo", "apt-get", "update"])
                self.runner.run(
                    ["sudo", "apt-get", "install", "-y", "git", "make", "dfu-util", "usbutils", "iproute2", "python3", "gcc-arm-none-eabi"]
                )
            remaining = missing_commands(required)
            if remaining:
                raise AssistantError("Benötigte Programme fehlen weiterhin: " + ", ".join(remaining))
        if not self.katapult_dir.exists():
            if self.runner.dry_run or self.ui.confirm("Katapult ist noch nicht vorhanden. Jetzt laden?", default=True):
                self.runner.run(["git", "clone", "https://github.com/Arksine/katapult.git", str(self.katapult_dir)])
        if not self.runner.dry_run and not (self.katapult_dir / ".git").is_dir():
            raise AssistantError(
                f"{self.katapult_dir} ist kein Git-Checkout. Eine aktuelle Katapult-Version kann nicht sichergestellt werden."
            )
        self.runner.run(["git", "-C", str(self.katapult_dir), "pull", "--ff-only"])
        revision = self.runner.run(
            ["git", "-C", str(self.katapult_dir), "rev-parse", "--short", "HEAD"],
            capture=True,
        ).stdout.strip()
        if revision:
            self.ui.ok(f"Katapult ist aktuell (Revision {revision}).")
        if not self.klipper_dir.exists() and not self.runner.dry_run:
            raise AssistantError(f"Klipper wurde nicht unter {self.klipper_dir} gefunden. Bitte zuerst Klipper installieren.")
        self.ui.ok("Grundvoraussetzungen sind erfüllt.")

    def _build_katapult(self) -> Path:
        self.ui.title("Katapult vorbereiten")
        config = self.state_dir / "configs" / f"{self.profile.id}-katapult-{self.bitrate}.config"
        output = build_firmware(
            self.runner,
            source_dir=self.katapult_dir,
            config_path=config,
            profile=self.profile,
            firmware="katapult",
            bitrate=self.bitrate,
        )
        self.ui.ok("Katapult-Konfiguration wurde geprüft und frisch kompiliert.")
        return output

    def _enter_dfu(self) -> None:
        self.ui.title("EBB in den DFU-Modus bringen")
        steps = self.profile.workflow["enter_dfu_steps"]
        for index, step in enumerate(steps, start=1):
            self.ui.instruction(index, str(step))
        self.ui.pause("ENTER drücken; danach wartet das Tool auf das DFU-Gerät")
        usb_id = self.profile.workflow.get("dfu_usb_id", "0483:df11")
        if not wait_for_usb(self.runner, usb_id):
            raise AssistantError(
                f"Kein DFU-Gerät {usb_id} erkannt. USB-Kabel, Jumper und BOOT/RESET-Abfolge prüfen."
            )
        self.ui.ok(f"DFU-Gerät {usb_id} wurde erkannt.")

    def _flash_katapult(self, firmware: Path) -> None:
        self.ui.title("Katapult installieren")
        self.ui.warn("Der nächste Schritt löscht den bisherigen Firmwarebereich des Boards.")
        if not self.ui.confirm("Katapult jetzt auf dieses EBB schreiben?", default=False):
            raise AssistantError("Vor dem Flashen abgebrochen.")
        result = self.runner.run(
            [
                "sudo",
                "dfu-util",
                "-R",
                "-a",
                "0",
                "-s",
                "0x08000000:mass-erase:force:leave",
                "-D",
                str(firmware),
                "-d",
                self.profile.workflow.get("dfu_usb_id", "0483:df11"),
            ],
            check=False,
            capture=True,
        )
        if result.stdout:
            print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
        if result.returncode:
            transferred = "File downloaded successfully" in result.stdout
            if result.returncode == 74 and transferred:
                self.ui.warn(
                    "dfu-util meldet beim automatischen Neustart einen Statusfehler, obwohl das Image vollständig "
                    "übertragen wurde. Als installiert gilt Katapult erst nach der folgenden CAN-Prüfung."
                )
            else:
                raise AssistantError(
                    f"Katapult-Übertragung fehlgeschlagen (dfu-util-Code {result.returncode})."
                )
        else:
            self.ui.ok("Katapult-Image wurde vollständig übertragen; die Funktionsprüfung folgt am CAN-Bus.")

    def _move_to_can(self) -> None:
        self.ui.title("Von USB auf CAN wechseln")
        for index, step in enumerate(self.profile.workflow["connect_can_steps"], start=1):
            self.ui.instruction(index, str(step))
        self.ui.pause()
        self._verify_can_bitrate()

    def _verify_can_bitrate(self) -> None:
        if self.mode != "full":
            self.ui.title("CAN-Verbindung prüfen")
        current = can_link_bitrate(self.runner, self.can_interface)
        if not self.runner.dry_run and current != self.bitrate:
            actual = "nicht aktiv" if current is None else f"{current:,} Bit/s"
            raise AssistantError(
                f"{self.can_interface} läuft mit {actual}, erwartet werden {self.bitrate:,} Bit/s. "
                "Die CAN-Konfiguration muss vor dem Flashen übereinstimmen."
            )
        self.ui.ok(f"{self.can_interface} verwendet die erwartete Bitrate.")

    def _existing_klipper_uuid(self) -> str:
        self.ui.title("Vorhandenes Katapult verwenden")
        try:
            uuid = find_canbus_uuid(self.printer_config, self.mcu_section)
        except AssistantError as exc:
            raise AssistantError(
                f"Die Ziel-UUID konnte nicht aus {self.printer_config} gelesen werden: {exc} "
                "Für ein neues oder noch nicht konfiguriertes Board bitte die Erstinstallation wählen."
            ) from exc
        self.ui.info(f"Zielabschnitt: [mcu {self.mcu_section}]")
        self.ui.info(f"CAN-UUID: {uuid}")
        if not self.ui.confirm(
            "Ist dies das Board mit bereits installiertem Katapult, dessen Klipper-Firmware aktualisiert werden soll?",
            default=False,
        ):
            raise AssistantError("Klipper-Aktualisierung vom Benutzer abgebrochen.")
        self.ui.ok("Katapult bleibt unverändert; das Flashwerkzeug fordert den Bootloader automatisch über CAN an.")
        return uuid

    def _query_nodes(self) -> list[tuple[str, str]]:
        tool = self.katapult_dir / "scripts" / "flashtool.py"
        result = self.runner.run(
            ["python3", str(tool), "-i", self.can_interface, "-q"],
            check=False,
            capture=True,
        )
        return parse_katapult_nodes(result.stdout)

    def _find_katapult_uuid(self) -> str:
        self.ui.title("Katapult am CAN-Bus suchen")
        self.ui.warn("Für diese Suche darf nur das neu installierte, noch nicht konfigurierte Katapult-Gerät antworten.")
        if not self.ui.confirm("Ist das neue EBB das einzige unkonfigurierte Katapult-Gerät am Bus?", default=False):
            raise AssistantError("CAN-Abfrage aus Sicherheitsgründen abgebrochen.")
        if self.runner.dry_run:
            return "000000000000"
        nodes = [uuid for uuid, app in self._query_nodes() if app == "katapult"]
        if len(nodes) != 1:
            raise AssistantError(f"Erwartet wurde genau ein Katapult-Gerät, gefunden: {len(nodes)}.")
        self.ui.ok(f"Katapult-Installation verifiziert. UUID: {nodes[0]}")
        return nodes[0]

    def _build_klipper(self) -> Path:
        self.ui.title("Klipper-Firmware vorbereiten")
        config = self.state_dir / "configs" / f"{self.profile.id}-klipper-{self.bitrate}.config"
        output = build_firmware(
            self.runner,
            source_dir=self.klipper_dir,
            config_path=config,
            profile=self.profile,
            firmware="klipper",
            bitrate=self.bitrate,
        )
        self.ui.ok("Klipper wurde mit passendem 8-KiB-Offset kompiliert.")
        return output

    def _flash_klipper(self, uuid: str, firmware: Path) -> None:
        self.ui.title("Klipper über CAN installieren")
        if not self.ui.confirm(f"Klipper jetzt auf {uuid} schreiben?", default=False):
            raise AssistantError("Vor dem Klipper-Flashen abgebrochen.")
        service = self.profile.workflow.get("klipper_service", "klipper")
        tool = self.katapult_dir / "scripts" / "flashtool.py"
        self.runner.run(["sudo", "systemctl", "stop", service], check=False)
        try:
            flash_result = self.runner.run(
                ["python3", str(tool), "-i", self.can_interface, "-f", str(firmware), "-u", uuid],
                check=False,
                capture=True,
            )
            if flash_result.stdout:
                print(flash_result.stdout, end="" if flash_result.stdout.endswith("\n") else "\n")
            if flash_result.returncode:
                raise AssistantError(f"Klipper-Flash fehlgeschlagen (Code {flash_result.returncode}).")
            if not self.runner.dry_run:
                query = self.klipper_dir / "scripts" / "canbus_query.py"
                detected = False
                for _ in range(15):
                    result = self.runner.run(
                        ["python3", str(query), self.can_interface],
                        check=False,
                        capture=True,
                    )
                    if (uuid, "klipper") in parse_klipper_nodes(result.stdout):
                        detected = True
                        break
                    time.sleep(1)
                if detected:
                    self.ui.ok(f"Klipper-Gerät {uuid} antwortet am CAN-Bus.")
                elif klipper_flash_verified(flash_result.stdout):
                    self.ui.warn(
                        "Das Klipper-Image wurde geschrieben und per SHA verifiziert. Die zusätzliche CAN-Suche "
                        "erhielt während des Neustarts keine Antwort; Klipper oder Mainsail kann das Gerät dennoch bereits erkennen."
                    )
                else:
                    raise AssistantError(
                        "Das Flashwerkzeug meldete keinen verifizierbaren Abschluss und das Board antwortet nicht auf die CAN-Suche."
                    )
        finally:
            self.runner.run(["sudo", "systemctl", "start", service], check=False)
        self.ui.ok("Klipper wurde geschrieben und der Dienst wieder gestartet.")

    def _finish(self, uuid: str) -> None:
        output_dir = self.state_dir / "generated"
        config_path = output_dir / f"{self.profile.id}-{uuid}.cfg"
        if not self.runner.dry_run:
            output_dir.mkdir(parents=True, exist_ok=True)
            config_path.write_text(
                "# Vom PrintWars Flash Assistant erzeugt\n"
                f"[mcu {self.mcu_section}]\n"
                f"canbus_uuid: {uuid}\n",
                encoding="utf-8",
            )
        self.ui.title("Fertig")
        self.ui.ok(f"Board-UUID: {uuid}")
        if not self.runner.dry_run and self.printer_config.is_file():
            try:
                old_uuid = find_canbus_uuid(self.printer_config, self.mcu_section)
                if old_uuid == uuid:
                    self.ui.ok(f"[mcu {self.mcu_section}] enthält bereits diese UUID.")
                else:
                    self.ui.info(f"Aktuelle UUID in [mcu {self.mcu_section}]: {old_uuid}")
                    self.ui.info(f"Neue UUID: {uuid}")
                    if self.ui.confirm(
                        f"UUID direkt in {self.printer_config} aktualisieren und vorher ein Backup anlegen?",
                        default=True,
                    ):
                        update = update_canbus_uuid(self.printer_config, self.mcu_section, uuid)
                        self.ui.ok(f"printer.cfg aktualisiert. Backup: {update.backup_path}")
                        if self.ui.confirm("Klipper-Dienst jetzt neu starten, damit die neue UUID aktiv wird?", default=True):
                            self.runner.run(["sudo", "systemctl", "restart", self.profile.workflow.get("klipper_service", "klipper")])
                            self.ui.ok("Klipper-Dienst wurde neu gestartet.")
            except AssistantError as exc:
                self.ui.warn(f"printer.cfg wurde nicht automatisch geändert: {exc}")
        self.ui.info(f"MCU-Konfiguration: {config_path}")
        self.ui.info("Diese Datei kann nun in die Druckerkonfiguration übernommen und um die EBB-Pinbelegung ergänzt werden.")
