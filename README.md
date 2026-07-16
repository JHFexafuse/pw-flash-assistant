# PrintWars Flash Assistant

Ein geführter, KIAUH-artiger Terminalassistent für Wartung und Erweiterung von Klipper-Druckern. Unterstützt werden derzeit das BIGTREETECH EBB42 V1.0, V1.1 und V1.2, Eddy Duo über CAN sowie PrintWars-Multibed.

## Ziel

Der Assistent trennt physische Arbeitsschritte und automatische Prüfungen. Er zeigt immer nur den nächsten sicheren Schritt, wartet auf die Bestätigung und prüft anschließend den erwarteten Hardwarezustand.

Der Assistent trennt zwei Arbeitsaufträge:

- **INSTALL:** Neues Board erstmals einrichten; Katapult über den zum Profil passenden USB-Bootweg und anschließend Klipper per CAN installieren.
- **UPDATE:** Vorhandene CAN-Komponente aus der Druckerkonfiguration auswählen, Katapult unverändert lassen und ausschließlich deren Klipper-Firmware aktualisieren.

EBB42-Erstinstallation:

1. Boardrevision und CAN-Bitrate auswählen.
2. Katapult mit dem passenden MCU-, Pin- und Offsetprofil kompilieren.
3. Am noch nicht angeschlossenen, spannungsfreien Board `USB_5V` setzen und es danach ausschließlich per Daten-USB anschließen.
4. BOOT halten, RESET kurz drücken und BOOT loslassen.
5. STM32-DFU-Gerät automatisch erkennen und Katapult schreiben.
6. USB entfernen, `USB_5V` entfernen und Board am CAN-Bus anschließen.
7. CAN-Bitrate prüfen und genau eine Katapult-UUID ermitteln.
8. Klipper mit 8-KiB-Offset kompilieren und über CAN schreiben.
9. UUID mit Backup und aktuellem Zeitstempel direkt im gewählten `[mcu ...]`-Abschnitt aktualisieren; genau eine vorherige UUID samt vorhandenem Zeitstempel bleibt als Kommentar erhalten.

Bei der Klipper-Aktualisierung werden die USB-Boot- und Katapult-Installationsschritte vollständig übersprungen. Das Flashwerkzeug fordert das laufende Klipper über CAN zum Sprung in das bereits vorhandene Katapult auf.

Bei einer Eddy-Duo-Erstinstallation verwendet der Assistent dagegen den RP2040-System-Bootmodus: BOOT beim Anschließen über USB halten, das Bootgerät `2e8a:0003` eindeutig erkennen und Katapult als UF2 über den Katapult-eigenen `make flash`-Weg installieren. Die STM32-DFU-Adresse des EBB wird dabei nicht verwendet.

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

## Multibed-Unterstützung

Der Menüpunkt **Multibed-Unterstützung verwalten** erkennt ein vorhandenes `[heater_bed]` und weitere Zonen wie `[heater_generic _Bed_2]` automatisch in den Druckerkonfigurationen. Anschließend kann er eine kleine Klipper-Erweiterung installieren, ihren Status anzeigen oder sie wieder entfernen.

Die Erweiterung synchronisiert:

- `M140` auf alle erkannten Bettzonen;
- `M190` auf alle Bettzonen und wartet auf jede einzelne Zone;
- `SET_HEATER_TEMPERATURE HEATER=heater_bed` auf alle weiteren Bettzonen, damit auch die Hauptbett-Steuerung in Mainsail funktioniert.

Die Pin-, Sensor- und PID-Konfigurationen der Heizflächen werden bewusst nicht automatisch erzeugt. Sie sind hardwarespezifisch und müssen bereits als Klipper-Heizzonen vorhanden sein. Erkennt der Assistent den alten `Klipper-Multibed-Support`-Kernpatch, bietet er eine geführte Migration an: Die veränderten Klipper-Dateien werden gesichert und aus dem aktuell ausgecheckten Klipper-Stand wiederhergestellt, bevor die neue Erweiterung installiert wird.

Direkter Aufruf und gefahrloser Test:

```bash
pwflash multibed
pwflash multibed --multibed-action install --dry-run --plain
pwflash multibed --multibed-action status
```

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
- die physischen USB-Boot- und CAN-Schritte;
- die Erstflash-Methode, USB-ID, das erwartete Firmwareformat und gegebenenfalls die Flashadresse;
- Kconfig-Auswahl für Katapult und Klipper.

Neue Profile werden beim Start automatisch gefunden und validiert. STM32-DFU und RP2040-BOOTSEL sind getrennte Erstflash-Treiber. Ein Profil für eine Erstinstallation wird abgewiesen, wenn Methode, USB-ID oder Firmwareformat fehlen; es gibt keinen stillen EBB-Standardwert. Für weitere Transportwege, etwa SD-Karte, kann ein zusätzlicher Treiber ergänzt werden, während Menüführung und Systemprüfung gleich bleiben.

## Hilfreiche Befehle

```bash
pwflash list
pwflash validate
pwflash doctor
pwflash multibed
```

## Sicherheitsprinzipien

- Keine Flashaktion ohne separate Bestätigung.
- Das erwartete USB-Bootgerät wird anhand der ID des gewählten Boardprofils geprüft; bei mehr als einem Treffer wird abgebrochen.
- CAN-Bitrate des Linux-Interfaces muss zum Firmwareprofil passen.
- Eine ungezielte Katapult-Abfrage wird abgebrochen, sobald nicht genau ein passendes Gerät erkannt wird.
- Der Klipper-Dienst wird nur für das eigentliche CAN-Flashen gestoppt und anschließend auch im Fehlerfall wieder gestartet.
- EBB42 V1.1 zeigt wegen des Hotend-MOSFETs eine eigene, nicht überspringbare Warnung.
