---
name: adjust-hvv-stations
description: Safely update HVV-Anzeiger stations, lines, destinations, verified Geofox IDs, and display labels for either the Raspberry Pi backend or standalone ESP32/CYD, then validate and reflash ESPHome firmware when requested.
---

# HVV-Haltestellen anpassen

Ändere ausschließlich die gewünschten Haltestellen und Verbindungen. Bewahre
API-, Display- und Nachtmodus-Einstellungen sowie Zugangsdaten. Es gibt zwei
unabhängige Installationspfade: Pi+ILI nutzt die Python-Konfiguration und
Weboberfläche; ESP32+CYD nutzt sein lokales ESPHome-Profil und hat keine
Weboberfläche.

## Ablauf

1. Repository-Anweisungen und Git-Status prüfen. Bei Codeänderungen nie direkt
   auf `main` arbeiten.
2. Zielsystem feststellen: Pi+ILI oder ESP32+CYD. Sie sind getrennte Backends
   und dürfen nicht als CYD-Client des Pi beschrieben oder konfiguriert werden.
3. Vom Nutzer je Verbindung Haltestelle, Stadt, Linie und Ziel erfassen.
   Fehlende Stadt als `Hamburg` annehmen. Für jede Haltestelle ein eindeutiges
   sichtbares Kürzel mit 1 bis 3 Zeichen wählen.
4. Geofox-ID muss verifiziert sein. Auf dem Pi kann das Backend eine fehlende
   ID selbst auflösen; beim ESP32 ist die ID im Firmwareprofil erforderlich.
   Bei Mehrdeutigkeit nach Adresse/Stadt oder bestätigter ID fragen, niemals
   eine ID erraten.
5. Eine temporäre JSON-Datei mit dem Array der gewünschten Haltestellenobjekte
   erstellen. Keine Zugangsdaten darin speichern.
6. Den passenden Konfigurationsweg verwenden:

   **Pi+ILI, Repository-Default `config.example.json`:**

   ```bash
   python3 .agents/skills/adjust-hvv-stations/scripts/update_stations.py \
     --config config.example.json --stations-file /tmp/hvv-stations.json
   ```

   **Pi+ILI, installiertes Backend:** `--config /opt/hvv-anzeiger/config.json`
   verwenden.

   **ESP32+CYD:** Mit dem lokalen Profil `esphome/hvv-cyd.local.yaml` arbeiten.
   Zuerst die Vorschau ausführen; sie gibt den erwarteten SHA-256-Wert aus:

   ```bash
   python3 scripts/update_esphome_stations.py \
     --profile esphome/hvv-cyd.local.yaml \
     --stations-file /tmp/hvv-stations.json
   ```

   Vor dem Schreiben sicherstellen, dass Haltestellen, IDs, Linien, Ziele und
   Labels stimmen. Danach die Änderung atomar schreiben und die vorherige
   Profilversion sichern:

   ```bash
   python3 scripts/update_esphome_stations.py \
     --profile esphome/hvv-cyd.local.yaml \
     --stations-file /tmp/hvv-stations.json \
     --expected-sha256 <SHA256_FROM_PREVIEW> --write
   ```

7. Pi-Änderungen wie unten ohne `--write` prüfen:

   ```bash
   python3 .agents/skills/adjust-hvv-stations/scripts/update_stations.py \
     --config config.example.json \
     --stations-file /tmp/hvv-stations.json
   ```

8. Die geprüfte Pi-Änderung anwenden:

   ```bash
   python3 .agents/skills/adjust-hvv-stations/scripts/update_stations.py \
     --config config.example.json \
     --stations-file /tmp/hvv-stations.json \
     --write
   ```

   Bei einer installierten Konfiguration `sudo` verwenden. Das Skript legt vor
   dem Überschreiben eine datierte Sicherung im gemeinsamen Verzeichnis
   `var/config-backups` an und behält die zehn neuesten Sicherungen. Hat sich
   die Ausgangsdatei während der Prüfung verändert, wird nicht geschrieben.
9. Für Pi: `python3 -m json.tool <config>` und die Projekt-Tests ausführen. Bei
   einer installierten Konfiguration zusätzlich eine Vorschau rendern. Den
   Webdienst nicht starten oder neu konfigurieren, um einen ESP32 zu versorgen;
   dieser ist ein unabhängiges Backend.
10. Für ESP32: Profil validieren und bauen:

   ```bash
   esphome config esphome/hvv-cyd.local.yaml
   esphome compile esphome/hvv-cyd.local.yaml
   ```

   Wenn der Nutzer das Reflashen angefordert hat, OTA versuchen, wenn das Board
   im LAN erreichbar ist:

   ```bash
   esphome upload esphome/hvv-cyd.local.yaml --device hvv-cyd.local
   ```

   Den tatsächlichen lokalen Gerätenamen oder die IP verwenden. Bei nicht
   erreichbarem Gerät den Nutzer fragen, bevor auf USB-Flash gewechselt wird.
   Nach dem Flashen Display und HA-Entitäten prüfen. Einen erfolgreichen Build
   nicht als Hardwaretest ausgeben.

11. Nur auf ausdrücklichen Nutzerwunsch den Pi-Dienst neu starten:

   ```bash
   sudo systemctl restart hvv-anzeiger
   ```

12. Bei Repository-Defaults die Tabelle „Vorkonfigurierte Verbindungen“ in
    `README.md` und betroffene Tests synchronisieren.

## Format der Haltestellendatei

```json
[
  {
    "name": "Recknitzstraße",
    "city": "Hamburg",
    "id": "Master:82015",
    "label": "R",
    "routes": [
      {
        "line": "21",
        "destination": "U Niendorf Nord"
      }
    ]
  }
]
```

Für Pi ist `id` optional und kann durch das Backend aufgelöst werden. Für
ESP32 muss `id` gesetzt sein und von Geofox bestätigt sein. Das CYD-Profil
unterstützt ein bis vier Haltestellen und je Haltestelle null oder mehr
Linie-Ziel-Kombinationen; leere `routes` zeigen alle Verbindungen. Die Kürzel
müssen eindeutig und ein bis drei Zeichen lang sein.

## Sicherheitsregeln

- `/etc/hvv-anzeiger.env` weder lesen noch verändern; sie enthält Geheimnisse.
- Keine Geofox-Zugangsdaten in Prompts, Ausgaben, Konfigurationen oder Commits
  übernehmen.
- Nicht anhand ähnlich klingender Namen oder Ziele raten. Mehrdeutige
  Haltestellen dem Nutzer zur Auswahl vorlegen oder eine bestätigte Geofox-ID
  verlangen.
- Vor dem Schreiben immer die Vorschau prüfen.
- Eine Sicherung erst entfernen, wenn die Anzeige mit der neuen Konfiguration
  erfolgreich läuft.
- Für das ESP32-CYD immer `esphome/hvv-cyd.local.yaml` statt der gemeinsamen
  Vorlage editieren. Zugangsdaten sind in `secrets.yaml`; die Haltestellen-
  Vorschau darf keine Secrets ausgeben.
- Das CYD hat keine Weboberfläche. Stationsänderungen werden erst nach einem
  neuen Firmware-Build und OTA- oder USB-Flashen aktiv.
