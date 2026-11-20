# Haltestellen für ESP32/CYD ändern

Das Profil `hvv-cyd` ist ein eigenständiges System: Das CYD fragt Geofox direkt
ab, filtert die fest eingetragenen Haltestellen und zeigt die Abfahrten an.
Es braucht dafür weder einen Raspberry Pi noch Python-Backend, Weboberfläche
oder Home Assistant. Änderungen an den Haltestellen werden in der lokalen
ESPHome-Profilkopie gespeichert und mit einer neuen Firmware übernommen.

## Eine Haltestelle eintragen

Für die erste Einrichtung kannst du die mitgelieferten Haltestellen zum Testen
verwenden. Für eine eigene Haltestelle brauchst du ihre Geofox-Kennung. Das ist
eine Nummer mit Präfix wie `Master:82015` für Recknitzstraße in Hamburg.
Übernimm die bestätigte Kennung aus einer vorhandenen HVV-Anzeiger-Konfiguration
oder aus den Geofox-Haltestellendaten.

1. Öffne im Explorer den Projektordner und darin den Ordner **esphome**.
   Kopiere `hvv-cyd.local.yaml` als Sicherung in einen privaten Ordner.
2. Öffne das Original per Rechtsklick mit **Editor**. Drücke **Strg+F**
   und suche nach `hvv_stations_json:`.
3. Ersetze die ganze Zeile durch das folgende Beispiel. Behalte die beiden
   Leerzeichen am Zeilenanfang bei. Die einfachen Anführungszeichen um die
   eckigen Klammern gehören mit in die Datei.

```yaml
  hvv_stations_json: '[{"name":"Recknitzstraße","city":"Hamburg","id":"Master:82015","label":"R","routes":[]}]'
```

4. Ersetze den Namen, den Ort, die bestätigte Kennung und das Kürzel zwischen
   den doppelten Anführungszeichen. Mit `"routes":[]` werden alle Linien der
   Haltestelle berücksichtigt. Speichere mit **Strg+S**.
5. Übertrage die Änderung per USB mit dem
   [Befehl aus der Einrichtung](esp32-setup.md#3-validieren-bauen-und-übertragen).
   Nach dem Neustart sollte das neue Kürzel neben den Abfahrten erscheinen.
   Bei einem Fehler kannst du die gesicherte Datei zurückkopieren.

## Mehrere Haltestellen oder bestimmte Linien

Das Setup erzeugt `esphome/hvv-cyd.local.yaml`. Diese Datei wird von Git
ignoriert und bleibt bei Updates erhalten. Darin liegt `hvv_stations_json` als
JSON-Array. Die Firmware kann höchstens vier Haltestellen und fünf Abfahrten
anzeigen. Eine Haltestelle benötigt einen verifizierten Geofox-Schlüssel wie
`Master:82015`; die Firmware kann keine Haltestellensuche über Namen ausführen.
Linien- und Zielfilter stehen unter `routes`. Eine leere `routes`-Liste zeigt
alle Geofox-Abfahrten dieser Haltestelle. Das `label` ist das ein- bis
dreibuchstabige Kürzel auf dem Display.

Beispiel für eine temporäre Datei `$env:TEMP\hvv-stations.json`:

```json
[
  {
    "name": "Recknitzstraße",
    "city": "Hamburg",
    "id": "Master:82015",
    "label": "R",
    "routes": [
      {"line": "21", "destination": "U Niendorf Nord"}
    ]
  }
]
```

Haltestellen-ID, Linienbezeichnung und Ziel müssen zu Geofox passen. Bei einer
mehrdeutigen Haltestelle erst die genaue Stadt/Adresse oder eine bestätigte
Geofox-ID ermitteln. IDs nicht aus ähnlich klingenden Haltestellennamen raten.

## Vorschau und Änderung

Im Repository-Ordner die Haltestellen prüfen. Die Vorschau verändert weder das
Profil noch Zugangsdaten und gibt den aktuellen SHA-256-Wert des Profils aus:

```powershell
py -3 .\scripts\update_esphome_stations.py `
  --profile .\esphome\hvv-cyd.local.yaml `
  --stations-file "$env:TEMP\hvv-stations.json"
```

Die Vorschau anhand des gewünschten JSON-Arrays prüfen. Danach dieselbe
Änderung mit dem SHA-256-Wert aus der Vorschau schreiben lassen. Das Skript
lehnt die Änderung ab, falls sich das lokale Profil inzwischen geändert hat;
vor dem Schreiben legt es eine zeitgestempelte Sicherung an:

```powershell
py -3 .\scripts\update_esphome_stations.py `
  --profile .\esphome\hvv-cyd.local.yaml `
  --stations-file "$env:TEMP\hvv-stations.json" `
  --expected-sha256 <SHA256_AUS_DER_VORSCHAU> `
  --write
```

## Firmware prüfen und übertragen

Zuerst nur konfigurieren und bauen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Build
```

Wenn das CYD im selben LAN erreichbar ist, ESPHome-OTA verwenden:

```powershell
& .\.venv-esphome\Scripts\python.exe -m esphome upload `
  .\esphome\hvv-cyd.local.yaml --device hvv-cyd.local
```

Den Gerätenamen durch den `name`-Wert aus dem lokalen Profil oder dessen
IP-Adresse ersetzen. Meldet ESPHome das Gerät als nicht erreichbar, das CYD
per USB verbinden und stattdessen aus dem Repository-Ordner ausführen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
```

`-Flash` baut die geprüfte Firmware und startet den USB-Upload. Danach prüfen,
ob die eigenen Haltestellen, Linien, Ziele und Abfahrtszeiten sichtbar sind.

## Home Assistant

Das CYD meldet sich mit ESPHome-API-Verschlüsselung selbst im LAN. Home
Assistant erkennt es über seine integrierte ESPHome-Integration; ein Pi und die
benutzerdefinierte Pi-Backend-Integration sind dafür nicht erforderlich. Beim
Hinzufügen wird der Wert `api_encryption_key` aus `esphome/secrets.yaml`
benötigt. ESPHome stellt Status und Abfahrten als Entitäten bereit.

Die Geofox-Zugangsdaten sind Bestandteil der lokal gebauten Firmware. Sie
werden nicht über ESPHome an Home Assistant übertragen; wer Zugriff auf das
Firmwareabbild oder physischen Flash-Speicher hat, kann eingebettete Werte
grundsätzlich auslesen. Schlüssel nicht in Commits, Issues oder Screenshots
teilen. Die Datei `esphome/secrets.yaml` und das lokale Profil nicht teilen.
