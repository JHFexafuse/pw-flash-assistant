from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .inventory import CanMcu, DeviceInventory, discover_can_mcus
from .profiles import DeviceProfile, ProfileError, load_profiles
from .system import AssistantError, Runner, can_link_bitrate, missing_commands
from .ui import UI
from .workflow import FlashWorkflow


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROFILE_DIR = ROOT / "devices"


class BackToMenu(Exception):
    pass


class ExitRequested(Exception):
    pass


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Geführter Firmware-Assistent für Klipper-Druckerboards")
    result.add_argument("command", nargs="?", choices=["install", "update", "list", "validate", "doctor"], help="Aktion")
    result.add_argument("--device", help="Geräteprofil-ID")
    result.add_argument("--bitrate", type=int, help="CAN-Bitrate")
    result.add_argument("--mode", choices=["full", "klipper"], help="Erstinstallation oder nur Klipper aktualisieren")
    result.add_argument("--can-interface", default="can0")
    result.add_argument("--klipper-dir", type=Path, default=Path("~/klipper"))
    result.add_argument("--katapult-dir", type=Path, default=Path("~/katapult"))
    result.add_argument("--state-dir", type=Path, default=Path("~/.local/share/pwflash"))
    result.add_argument("--printer-config", type=Path, default=Path("~/printer_data/config/printer.cfg"))
    result.add_argument("--mcu-section", help="MCU-Abschnitt in printer.cfg; ohne Angabe wird das Geräteprofil verwendet")
    result.add_argument("--profiles", type=Path, default=DEFAULT_PROFILE_DIR)
    result.add_argument("--dry-run", action="store_true", help="Ablauf zeigen, nichts ausführen")
    result.add_argument("--verbose", action="store_true")
    result.add_argument("--plain", action="store_true", help="Keine Farben und kein Bildschirmleeren")
    result.add_argument("--version", action="version", version=__version__)
    return result


def select_profile(ui: UI, profiles: list[DeviceProfile], requested: str | None) -> DeviceProfile:
    if requested:
        for profile in profiles:
            if profile.id == requested:
                return profile
        raise AssistantError(f"Unbekanntes Geräteprofil: {requested}")
    options = [(str(index), profile.name) for index, profile in enumerate(profiles, start=1)]
    options.extend([("b", "Zurück zum Hauptmenü"), ("q", "Beenden")])
    selected = ui.choose("Geräteprofil auswählen", options)
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return profiles[int(selected) - 1]


def select_bitrate(
    ui: UI,
    profile: DeviceProfile,
    requested: int | None,
    *,
    current: int | None = None,
    interface: str = "can0",
) -> int:
    rates = profile.hardware["supported_bitrates"]
    if requested is not None:
        if requested not in rates:
            raise AssistantError(f"{requested} wird von diesem Profil nicht angeboten.")
        return requested
    options = []
    for index, rate in enumerate(rates, start=1):
        label = f"{rate:,} Bit/s"
        if rate == current:
            label = ui.highlight(f"{label}  ← aktuell auf {interface}")
        options.append((str(index), label))
    options.extend([("b", "Zurück zum Hauptmenü"), ("q", "Beenden")])
    selected = ui.choose("CAN-Bitrate auswählen", options)
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return rates[int(selected) - 1]


def select_mode(ui: UI, requested: str | None) -> str:
    if requested:
        return requested
    selected = ui.choose(
        "Installationsart auswählen",
        [
            ("1", "Neues Board: Katapult per USB und danach Klipper per CAN installieren"),
            ("2", "Katapult ist bereits installiert: nur Klipper per CAN aktualisieren"),
            ("b", "Zurück zum Hauptmenü"),
            ("q", "Beenden"),
        ],
    )
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return {"1": "full", "2": "klipper"}[selected]


def interactive_command(ui: UI) -> str:
    ui.header()
    ui.title("Hauptmenü")
    return ui.choose(
        "Aktion",
        [
            ("1", "Board geführt installieren"),
            ("2", "Vorhandenes CAN-Bauteil aktualisieren"),
            ("3", "Unterstützte Boards anzeigen"),
            ("4", "System prüfen"),
            ("q", "Beenden"),
        ],
    )


def list_devices(profiles: list[DeviceProfile]) -> None:
    for profile in profiles:
        rates = ", ".join(str(rate) for rate in profile.hardware["supported_bitrates"])
        print(f"{profile.id:18} {profile.name}  [{rates}]")


def doctor(runner: Runner, interface: str) -> int:
    required = ["git", "make", "g++", "dfu-util", "lsusb", "ip", "python3", "arm-none-eabi-gcc"]
    missing = missing_commands(required)
    print("Programme: " + ("OK" if not missing else "FEHLT: " + ", ".join(missing)))
    bitrate = can_link_bitrate(runner, interface)
    print(f"{interface}: " + (f"{bitrate} Bit/s" if bitrate else "nicht aktiv oder nicht vorhanden"))
    return 1 if missing else 0


def run_install(args: argparse.Namespace, ui: UI, runner: Runner, profiles: list[DeviceProfile]) -> None:
    install_profiles = [profile for profile in profiles if "full" in profile.data.get("supported_modes", ["full", "klipper"])]
    profile = select_profile(ui, install_profiles, args.device)
    current_bitrate = can_link_bitrate(runner, args.can_interface)
    bitrate = select_bitrate(
        ui,
        profile,
        args.bitrate,
        current=current_bitrate,
        interface=args.can_interface,
    )
    mode = args.mode or "full"
    profile_sections = profile.data.get("mcu_sections", [])
    mcu_section = args.mcu_section or (str(profile_sections[0]) if profile_sections else "mcu")
    workflow = FlashWorkflow(
        profile,
        bitrate,
        runner=runner,
        ui=ui,
        klipper_dir=args.klipper_dir,
        katapult_dir=args.katapult_dir,
        state_dir=args.state_dir,
        printer_config=args.printer_config,
        mcu_section=mcu_section,
        mode=mode,
        can_interface=args.can_interface,
    )
    workflow.run()


def select_can_mcu(ui: UI, devices: list[CanMcu]) -> CanMcu:
    options = [
        (str(index), f"{device.section} – UUID {device.uuid} – {device.config_path.name}")
        for index, device in enumerate(devices, start=1)
    ]
    options.extend([("b", "Zurück zum Hauptmenü"), ("q", "Beenden")])
    selected = ui.choose("CAN-Bauteil auswählen", options)
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return devices[int(selected) - 1]


def matching_update_profiles(profiles: list[DeviceProfile], section: str) -> list[DeviceProfile]:
    return [
        item
        for item in profiles
        if "klipper" in item.data.get("supported_modes", ["full", "klipper"])
        and section.casefold() in {
            str(configured_section).casefold()
            for configured_section in item.data.get("mcu_sections", [])
        }
    ]


def run_update(args: argparse.Namespace, ui: UI, runner: Runner, profiles: list[DeviceProfile]) -> None:
    ui.header("Vorhandenes CAN-Bauteil aktualisieren")
    ui.title("CAN-Geräte aus der Druckerkonfiguration")
    devices = discover_can_mcus(args.printer_config)
    if not devices:
        raise AssistantError("Keine MCU mit canbus_uuid in den Druckerkonfigurationen gefunden.")
    device = select_can_mcu(ui, devices)
    inventory = DeviceInventory(args.state_dir.expanduser() / "inventory.json")
    entry = inventory.find(device)
    by_id = {profile.id: profile for profile in profiles}
    profile = by_id.get(entry.profile_id) if entry and entry.uuid == device.uuid else None
    if profile is None:
        if entry and entry.uuid != device.uuid:
            ui.warn(
                f"Die UUID von [mcu {device.section}] hat sich von {entry.uuid} auf {device.uuid} geändert. "
                "Die Hardwarezuordnung muss erneut bestätigt werden."
            )
        update_profiles = matching_update_profiles(profiles, device.section)
        if not update_profiles:
            raise AssistantError(
                f"Für den MCU-Abschnitt [mcu {device.section}] ist noch kein passendes Geräteprofil hinterlegt."
            )
        profile = select_profile(ui, update_profiles, args.device)
        ui.info(f"Zuordnung: [mcu {device.section}] / {device.uuid} → {profile.name}")
        mapping_prompt = (
            "Diese Gerätezuordnung für den Dry Run verwenden?"
            if runner.dry_run
            else "Diese Gerätezuordnung dauerhaft speichern?"
        )
        if not ui.confirm(mapping_prompt):
            raise AssistantError("Ohne bestätigte Gerätezuordnung wird kein Update ausgeführt.")
        if runner.dry_run:
            ui.info("Dry Run: Die Gerätezuordnung wird nicht gespeichert.")
        else:
            inventory.bind(device, profile.id)
            ui.ok("Gerätezuordnung wurde gespeichert.")
    else:
        ui.ok(f"Gespeicherte Zuordnung: [mcu {device.section}] → {profile.name}")
    current_bitrate = can_link_bitrate(runner, args.can_interface)
    if args.bitrate is not None:
        bitrate = select_bitrate(ui, profile, args.bitrate)
    else:
        bitrate = select_bitrate(
            ui,
            profile,
            None,
            current=current_bitrate,
            interface=args.can_interface,
        )
    workflow = FlashWorkflow(
        profile,
        bitrate,
        runner=runner,
        ui=ui,
        klipper_dir=args.klipper_dir,
        katapult_dir=args.katapult_dir,
        state_dir=args.state_dir,
        printer_config=device.config_path,
        mcu_section=device.section,
        mode="klipper",
        can_interface=args.can_interface,
    )
    workflow.run()


def interactive_loop(args: argparse.Namespace, ui: UI, runner: Runner, profiles: list[DeviceProfile]) -> int:
    while True:
        selected = interactive_command(ui)
        if selected == "q":
            return 0
        if selected == "3":
            ui.header("Unterstützte Boards")
            ui.title("Unterstützte Boards")
            list_devices(profiles)
            ui.pause("ENTER drücken für das Hauptmenü")
            continue
        if selected == "4":
            ui.header("Systemprüfung")
            ui.title("Systemprüfung")
            doctor(runner, args.can_interface)
            ui.pause("ENTER drücken für das Hauptmenü")
            continue
        try:
            if selected == "1":
                run_install(args, ui, runner, profiles)
            else:
                run_update(args, ui, runner, profiles)
            ui.pause("ENTER drücken für das Hauptmenü")
        except BackToMenu:
            continue
        except ExitRequested:
            return 0


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    ui = UI(plain=args.plain)
    runner = Runner(dry_run=args.dry_run, verbose=args.verbose)
    try:
        profiles = load_profiles(args.profiles)
        command = args.command
        if command is None:
            return interactive_loop(args, ui, runner, profiles)
        if command == "list":
            list_devices(profiles)
            return 0
        if command == "validate":
            print(f"{len(profiles)} Geräteprofile sind gültig.")
            return 0
        if command == "doctor":
            return doctor(runner, args.can_interface)
        if command == "update":
            run_update(args, ui, runner, profiles)
        else:
            run_install(args, ui, runner, profiles)
        return 0
    except (AssistantError, ProfileError, BackToMenu, ExitRequested, KeyboardInterrupt) as exc:
        ui.error(str(exc) if str(exc) else "Abgebrochen.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
