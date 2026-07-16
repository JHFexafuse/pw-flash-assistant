# PrintWars Flash Assistant

Ein geführter, KIAUH-artiger Terminalassistent für Klipper-Druckerboards. Die erste Gerätefamilie ist das BIGTREETECH EBB42 V1.0, V1.1 und V1.2 über CAN.

## Ziel

Der Assistent trennt physische Arbeitsschritte und automatische Prüfungen. Er zeigt immer nur den nächsten sicheren Schritt, wartet auf die Bestätigung und prüft anschließend den erwarteten Hardwarezustand.

Der aktuelle EBB42-Ablauf:

1. Boardrevision und CAN-Bitrate auswählen.
2. Katapult mit dem passenden MCU-, Pin- und Offsetprofil kompilieren.
3. Stromversorgung trennen und `USB_5V` setzen.
4. BOOT halten, RESET kurz drücken und BOOT loslassen.
5. DFU-Gerät automatisch erkennen und Katapult schreiben.
6. USB entfernen, `USB_5V` entfernen und Board am CAN-Bus anschließen.
7. CAN-Bitrate prüfen und genau eine Katapult-UUID ermitteln.
8. Klipper mit 8-KiB-Offset kompilieren und über CAN schreiben.
9. Fertigen `[mcu EBBCan]`-Abschnitt erzeugen.

## Installation

Das Projekt auf den Klipper-Rechner kopieren oder aus seinem späteren GitHub-Repository klonen. Danach:

```bash
cd ~/printwars-flash-assistant
bash install.sh
pwflash
```

Es wird bewusst nicht als `root` gestartet. Benötigte administrative Schritte fragen einzeln nach `sudo`.

## Testlauf ohne Hardwareänderungen

```bash
pwflash install --device btt-ebb42-v1.2 --bitrate 1000000 --dry-run --verbose
```

## Weitere Boards hinzufügen

Ein Board ist eine JSON-Datei in `devices/`. Das Profil enthält:

- lesbaren Namen und Hardwarekennung;
- unterstützte Bitraten;
- Sicherheitswarnungen;
- die physischen DFU- und CAN-Schritte;
- Kconfig-Auswahl für Katapult und Klipper.

Neue Profile werden beim Start automatisch gefunden und validiert. Für Boards mit einem anderen Transportweg, etwa SD-Karte oder RP2040-BOOTSEL, wird ein zusätzlicher Workflow-Treiber ergänzt; die Menüführung und Systemprüfung bleiben gleich.

## Hilfreiche Befehle

```bash
pwflash list
pwflash validate
pwflash doctor
```

## Sicherheitsprinzipien

- Keine Flashaktion ohne separate Bestätigung.
- DFU wird anhand `0483:df11` geprüft.
- CAN-Bitrate des Linux-Interfaces muss zum Firmwareprofil passen.
- Eine ungezielte Katapult-Abfrage wird abgebrochen, sobald nicht genau ein passendes Gerät erkannt wird.
- Der Klipper-Dienst wird nur für das eigentliche CAN-Flashen gestoppt und anschließend auch im Fehlerfall wieder gestartet.
- EBB42 V1.1 zeigt wegen des Hotend-MOSFETs eine eigene, nicht überspringbare Warnung.
