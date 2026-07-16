from __future__ import annotations

from pathlib import Path

from .kconfig import build_firmware
from .profiles import DeviceProfile
from .system import (
    AssistantError,
    Runner,
    can_link_bitrate,
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
        can_interface: str = "can0",
    ) -> None:
        self.profile = profile
        self.bitrate = bitrate
        self.runner = runner
        self.ui = ui
        self.klipper_dir = klipper_dir.expanduser()
        self.katapult_dir = katapult_dir.expanduser()
        self.state_dir = state_dir.expanduser()
        self.can_interface = can_interface

    def run(self) -> None:
        if not self.runner.dry_run:
            require_linux()
        self._summary()
        self._preflight()
        katapult_bin = self._build_katapult()
        self._enter_dfu()
        self._flash_katapult(katapult_bin)
        self._move_to_can()
        uuid = self._find_katapult_uuid()
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
        for warning in self.profile.data.get("safety_warnings", []):
            self.ui.warn(str(warning))
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
        current = can_link_bitrate(self.runner, self.can_interface)
        if not self.runner.dry_run and current != self.bitrate:
            actual = "nicht aktiv" if current is None else f"{current:,} Bit/s"
            raise AssistantError(
                f"{self.can_interface} läuft mit {actual}, erwartet werden {self.bitrate:,} Bit/s. "
                "Die CAN-Konfiguration muss vor dem Flashen übereinstimmen."
            )
        self.ui.ok(f"{self.can_interface} verwendet die erwartete Bitrate.")

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
            self.runner.run(
                ["python3", str(tool), "-i", self.can_interface, "-f", str(firmware), "-u", uuid]
            )
            if not self.runner.dry_run:
                query = self.klipper_dir / "scripts" / "canbus_query.py"
                result = self.runner.run(
                    ["python3", str(query), self.can_interface],
                    check=False,
                    capture=True,
                )
                nodes = parse_klipper_nodes(result.stdout)
                if (uuid, "klipper") not in nodes:
                    raise AssistantError(
                        "Das Flashwerkzeug meldete Erfolg, aber das Board antwortet anschließend nicht als Klipper-Gerät."
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
                "[mcu EBBCan]\n"
                f"canbus_uuid: {uuid}\n",
                encoding="utf-8",
            )
        self.ui.title("Fertig")
        self.ui.ok(f"Board-UUID: {uuid}")
        self.ui.info(f"MCU-Konfiguration: {config_path}")
        self.ui.info("Diese Datei kann nun in die Druckerkonfiguration übernommen und um die EBB-Pinbelegung ergänzt werden.")
