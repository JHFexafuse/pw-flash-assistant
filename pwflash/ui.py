from __future__ import annotations

import os
import sys
import textwrap


class UI:
    WIDTH = 68

    def __init__(self, *, plain: bool = False) -> None:
        self.plain = plain
        self.color = not plain and sys.stdout.isatty() and "NO_COLOR" not in os.environ

    def _c(self, code: str, value: str) -> str:
        return f"\033[{code}m{value}\033[0m" if self.color else value

    def clear(self) -> None:
        if sys.stdout.isatty():
            os.system("clear")

    def header(self, subtitle: str = "Firmware sicher installieren") -> None:
        self.clear()
        if self.plain:
            print("+" + "-" * self.WIDTH + "+")
            print("|" + " PRINTWARS FLASH ASSISTANT ".center(self.WIDTH) + "|")
            print("|" + subtitle.center(self.WIDTH) + "|")
            print("+" + "-" * self.WIDTH + "+")
        else:
            print("╔" + "═" * self.WIDTH + "╗")
            print("║" + self._c("96;1", " PRINTWARS FLASH ASSISTANT ".center(self.WIDTH)) + "║")
            print("║" + subtitle.center(self.WIDTH) + "║")
            print("╚" + "═" * self.WIDTH + "╝")

    def title(self, text: str) -> None:
        print(f"\n{self._c('96;1', text)}")
        print(("-" if self.plain else "─") * min(self.WIDTH, len(text) + 2))

    def info(self, text: str) -> None:
        self._wrapped(text, "  ")

    def ok(self, text: str) -> None:
        marker = "OK" if self.plain else "✓"
        print(self._c("92;1", f"  {marker} {text}"))

    def warn(self, text: str) -> None:
        marker = "ACHTUNG:" if self.plain else "⚠"
        self._wrapped(self._c("93;1", f"{marker} {text}"), "  ")

    def error(self, text: str) -> None:
        marker = "FEHLER:" if self.plain else "✗"
        self._wrapped(self._c("91;1", f"{marker} {text}"), "  ")

    def instruction(self, number: int, text: str) -> None:
        marker = self._c("96;1", f"[{number}]")
        lines = textwrap.wrap(text, self.WIDTH - 7) or [""]
        print(f"  {marker} {lines[0]}")
        for line in lines[1:]:
            print(f"      {line}")

    def _wrapped(self, text: str, prefix: str) -> None:
        for line in textwrap.wrap(text, self.WIDTH - len(prefix)) or [""]:
            print(prefix + line)

    def choose(self, prompt: str, options: list[tuple[str, str]]) -> str:
        print()
        for key, label in options:
            print(f"  {self._c('96;1', key + ')')} {label}")
        while True:
            answer = input(f"\n{prompt}: ").strip().lower()
            for key, _ in options:
                if answer == key.lower():
                    return key
            self.error("Bitte eine der angezeigten Optionen wählen.")

    def confirm(self, prompt: str) -> bool:
        suffix = "[j/n]"
        while True:
            answer = input(f"\n{prompt} {suffix}: ").strip().lower()
            if answer in {"j", "ja", "y", "yes"}:
                return True
            if answer in {"n", "nein", "no"}:
                return False
            self.error("Bitte mit j oder n antworten.")

    def pause(self, prompt: str = "ENTER drücken, sobald dieser Schritt erledigt ist") -> None:
        input(f"\n{self._c('96;1', prompt)} ")
