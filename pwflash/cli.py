from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
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
    result.add_argument("command", nargs="?", choices=["install", "list", "validate", "doctor"], help="Aktion")
    result.add_argument("--device", help="Geräteprofil-ID")
    result.add_argument("--bitrate", type=int, help="CAN-Bitrate")
    result.add_argument("--can-interface", default="can0")
    result.add_argument("--klipper-dir", type=Path, default=Path("~/klipper"))
    result.add_argument("--katapult-dir", type=Path, default=Path("~/katapult"))
    result.add_argument("--state-dir", type=Path, default=Path("~/.local/share/pwflash"))
    result.add_argument("--printer-config", type=Path, default=Path("~/printer_data/config/printer.cfg"))
    result.add_argument("--mcu-section", default="CanHead", help="MCU-Abschnitt in printer.cfg")
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
    selected = ui.choose("Boardversion auswählen", options)
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return profiles[int(selected) - 1]


def select_bitrate(ui: UI, profile: DeviceProfile, requested: int | None) -> int:
    rates = profile.hardware["supported_bitrates"]
    if requested is not None:
        if requested not in rates:
            raise AssistantError(f"{requested} wird von diesem Profil nicht angeboten.")
        return requested
    options = [(str(index), f"{rate:,} Bit/s") for index, rate in enumerate(rates, start=1)]
    options.extend([("b", "Zurück zum Hauptmenü"), ("q", "Beenden")])
    selected = ui.choose("CAN-Bitrate auswählen", options)
    if selected == "b":
        raise BackToMenu
    if selected == "q":
        raise ExitRequested
    return rates[int(selected) - 1]


def interactive_command(ui: UI) -> str:
    ui.header()
    ui.title("Hauptmenü")
    return ui.choose(
        "Aktion",
        [
            ("1", "Board geführt installieren"),
            ("2", "Unterstützte Boards anzeigen"),
            ("3", "System prüfen"),
            ("q", "Beenden"),
        ],
    )


def list_devices(profiles: list[DeviceProfile]) -> None:
    for profile in profiles:
        rates = ", ".join(str(rate) for rate in profile.hardware["supported_bitrates"])
        print(f"{profile.id:18} {profile.name}  [{rates}]")


def doctor(runner: Runner, interface: str) -> int:
    required = ["git", "make", "dfu-util", "lsusb", "ip", "python3", "arm-none-eabi-gcc"]
    missing = missing_commands(required)
    print("Programme: " + ("OK" if not missing else "FEHLT: " + ", ".join(missing)))
    bitrate = can_link_bitrate(runner, interface)
    print(f"{interface}: " + (f"{bitrate} Bit/s" if bitrate else "nicht aktiv oder nicht vorhanden"))
    return 1 if missing else 0


def run_install(args: argparse.Namespace, ui: UI, runner: Runner, profiles: list[DeviceProfile]) -> None:
    profile = select_profile(ui, profiles, args.device)
    bitrate = select_bitrate(ui, profile, args.bitrate)
    workflow = FlashWorkflow(
        profile,
        bitrate,
        runner=runner,
        ui=ui,
        klipper_dir=args.klipper_dir,
        katapult_dir=args.katapult_dir,
        state_dir=args.state_dir,
        printer_config=args.printer_config,
        mcu_section=args.mcu_section,
        can_interface=args.can_interface,
    )
    workflow.run()


def interactive_loop(args: argparse.Namespace, ui: UI, runner: Runner, profiles: list[DeviceProfile]) -> int:
    while True:
        selected = interactive_command(ui)
        if selected == "q":
            return 0
        if selected == "2":
            ui.header("Unterstützte Boards")
            ui.title("Unterstützte Boards")
            list_devices(profiles)
            ui.pause("ENTER drücken für das Hauptmenü")
            continue
        if selected == "3":
            ui.header("Systemprüfung")
            ui.title("Systemprüfung")
            doctor(runner, args.can_interface)
            ui.pause("ENTER drücken für das Hauptmenü")
            continue
        try:
            run_install(args, ui, runner, profiles)
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
        run_install(args, ui, runner, profiles)
        return 0
    except (AssistantError, ProfileError, BackToMenu, ExitRequested, KeyboardInterrupt) as exc:
        ui.error(str(exc) if str(exc) else "Abgebrochen.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
