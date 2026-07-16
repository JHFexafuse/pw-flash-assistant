# PrintWars Flash Assistant

Ein geführter, KIAUH-artiger Terminalassistent für Klipper-Druckerboards. Unterstützt werden derzeit das BIGTREETECH EBB42 V1.0, V1.1 und V1.2 sowie Eddy Duo über CAN.

## Ziel

Der Assistent trennt physische Arbeitsschritte und automatische Prüfungen. Er zeigt immer nur den nächsten sicheren Schritt, wartet auf die Bestätigung und prüft anschließend den erwarteten Hardwarezustand.

Der Assistent trennt zwei Arbeitsaufträge:

- **INSTALL:** Neues Board erstmals einrichten; beim EBB42 Katapult per USB/DFU und anschließend Klipper per CAN installieren.
- **UPDATE:** Vorhandene CAN-Komponente aus der Druckerkonfiguration auswählen, Katapult unverändert lassen und ausschließlich deren Klipper-Firmware aktualisieren.

Erstinstallation:

1. Boardrevision und CAN-Bitrate auswählen.
2. Katapult mit dem passenden MCU-, Pin- und Offsetprofil kompilieren.
3. Am noch nicht angeschlossenen, spannungsfreien Board `USB_5V` setzen und es danach ausschließlich per Daten-USB anschließen.
4. BOOT halten, RESET kurz drücken und BOOT loslassen.
5. DFU-Gerät automatisch erkennen und Katapult schreiben.
6. USB entfernen, `USB_5V` entfernen und Board am CAN-Bus anschließen.
7. CAN-Bitrate prüfen und genau eine Katapult-UUID ermitteln.
8. Klipper mit 8-KiB-Offset kompilieren und über CAN schreiben.
9. UUID mit Backup und aktuellem Zeitstempel direkt im gewählten `[mcu ...]`-Abschnitt aktualisieren; genau eine vorherige UUID samt vorhandenem Zeitstempel bleibt als Kommentar erhalten.

Bei der Klipper-Aktualisierung werden die USB-/DFU-/Katapult-Schritte vollständig übersprungen. Das Flashwerkzeug fordert das laufende Klipper über CAN zum Sprung in das bereits vorhandene Katapult auf.

Der UPDATE-Arbeitsauftrag liest alle `[mcu ...]`-Abschnitte mit `canbus_uuid` aus `printer.cfg` und den weiteren CFG-Dateien. Nach der MCU-Auswahl zeigt er ausschließlich dazu passende Geräteprofile an: bei `[mcu CanHead]` die EBB42-Varianten, bei `[mcu eddy]` die beiden Eddy-Duo-Varianten. Die einmal bestätigte Zuordnung aus MCU-Abschnitt, UUID und Hardware-/Softwareprofil wird unter `~/.local/share/pwflash/inventory.json` gespeichert. Unterstützt werden EBB42 V1.0–V1.2 sowie Eddy Duo CAN mit Klipper Standard oder eddy-ng. Beim eddy-ng-Profil wird die Erweiterung vor dem Firmwarebuild aktualisiert und erneut in Klipper eingebunden.

Bestätigungsfragen verlangen ausdrücklich `j` oder `n`; eine leere Eingabe löst keine Aktion aus.

## Installation

Den folgenden Block vollständig kopieren und auf dem Klipper-Rechner im Terminal einfügen:

```bash
cd ~
git clone https://github.com/JHFexafuse/pw-flash-assistant.git
cd ~/pw-flash-assistant
bash install.sh
~/.local/bin/pwflash
```

Das Tool wird bewusst nicht mit `sudo` gestartet. Nur einzelne administrative Schritte fragen bei Bedarf nach dem Passwort. Falls `pwflash` nach einer neuen Anmeldung direkt gefunden wird, genügt künftig:

```bash
pwflash
```

## Aktualisieren

Eine vorhandene Installation wird mit diesem vollständigen Block aktualisiert und anschließend gestartet:

```bash
cd ~/pw-flash-assistant
git pull --ff-only
bash install.sh
~/.local/bin/pwflash
```

Die gespeicherten Gerätezuordnungen unter `~/.local/share/pwflash/` bleiben dabei erhalten.

## Testlauf ohne Hardwareänderungen

```bash
pwflash install --device btt-ebb42-v1.2 --bitrate 1000000 --dry-run --verbose
pwflash update
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
