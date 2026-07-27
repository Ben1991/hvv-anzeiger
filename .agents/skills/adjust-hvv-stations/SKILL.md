---
name: adjust-hvv-stations
description: Safely update the HVV-Anzeiger station, line, destination, station ID, and display-label configuration. Use when a user wants to add, remove, replace, or correct stops or route filters in config.example.json or an installed /opt/hvv-anzeiger/config.json.
---

# HVV-Haltestellen anpassen

Ändere ausschließlich die gewünschten Haltestellen und Verbindungen. Bewahre
API-, Display- und Nachtmodus-Einstellungen sowie Geofox-Zugangsdaten.

## Ablauf

1. Repository-Anweisungen und Git-Status prüfen. Bei Codeänderungen nie direkt
   auf `main` arbeiten.
2. Vom Nutzer je Verbindung Haltestelle, Stadt, Linie und Ziel erfassen.
   Fehlende Stadt als `Hamburg` annehmen. Für jede Haltestelle ein eindeutiges
   sichtbares Kürzel mit 1 bis 3 Zeichen wählen.
3. Ziel bestimmen:
   - Repository-Default: `config.example.json`
   - installierter Raspberry Pi: `/opt/hvv-anzeiger/config.json`
4. Geofox-ID nur übernehmen, wenn sie verlässlich bekannt oder bereits
   konfiguriert ist. Andernfalls das Feld `id` weglassen; die Anwendung löst die
   Haltestelle beim nächsten Start über Geofox auf. Niemals eine ID erraten.
5. Eine temporäre JSON-Datei mit einem Array der gewünschten
   Haltestellenobjekte erstellen. Keine Zugangsdaten darin speichern.
6. Änderung zuerst ohne `--write` prüfen:

   ```bash
   python3 .agents/skills/adjust-hvv-stations/scripts/update_stations.py \
     --config config.example.json \
     --stations-file /tmp/hvv-stations.json
   ```

7. Die geprüfte Änderung anwenden:

   ```bash
   python3 .agents/skills/adjust-hvv-stations/scripts/update_stations.py \
     --config config.example.json \
     --stations-file /tmp/hvv-stations.json \
     --write
   ```

   Bei einer installierten Konfiguration `sudo` verwenden. Das Skript legt vor
   dem Überschreiben eine datierte Sicherung neben der Konfiguration an.
8. `python3 -m json.tool <config>` und die Projekt-Tests ausführen. Bei einer
   installierten Konfiguration zusätzlich eine Vorschau rendern.
9. Nur auf ausdrücklichen Nutzerwunsch den laufenden Dienst neu starten:

   ```bash
   sudo systemctl restart hvv-anzeiger
   ```

10. Bei Repository-Defaults die Tabelle „Vorkonfigurierte Verbindungen“ in
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

`id` ist optional. Mindestens eine Haltestelle und je Haltestelle mindestens eine
Linie-Ziel-Kombination angeben. Die Kürzel müssen eindeutig sein.

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
