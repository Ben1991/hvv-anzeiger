# HVV-Anzeiger für Raspberry Pi

Zeigt die nächsten passenden HVV-Busabfahrten auf einem 2,2-Zoll-ILI9341-SPI-Display
mit 320 × 240 Pixeln im Querformat. Die Daten kommen alle 15 Sekunden aus der
Geofox-GTI-API.

Vorkonfiguriert sind:

- Weistritzstraße: 186 nach S Othmarschen, 184 nach S Halstenbek und 384 nach
  Elbgaustraße
- Recknitzstraße: 21 nach U Niendorf Nord

Die in der Anforderung doppelt erscheinende Bezeichnung „D21“ wird als
Formatierungsfehler behandelt. Es wird nur Linie 21 angezeigt.

## Was das Programm robust macht

- Es nutzt Geofox-Echtzeitdaten, rechnet Verspätungen in die sichtbare Zeit ein und
  sortiert alle Treffer nach der erwarteten Abfahrtszeit.
- Die Zugangsdaten stehen nicht im Code oder in Git.
- Die aktuell bestätigten Haltestellen-IDs sind vorkonfiguriert. Fehlt eine ID,
  wird sie automatisch gesucht und lokal zwischengespeichert.
- Ein gemeinsamer API-Aufruf fragt beide Haltestellen ab. Das respektiert das in der
  Geofox-Dokumentation genannte Limit von durchschnittlich höchstens einer Anfrage
  pro Sekunde.
- Bei einem Netzwerk- oder API-Fehler bleibt der letzte erfolgreiche Stand sichtbar
  und erhält einen roten Hinweis „DATEN VERALTET“.
- Sowohl HTTP-Fehler als auch Geofox-Fehler im JSON-Feld `returnCode` werden geprüft.

## Benötigte Hardware

- Raspberry Pi Zero 2 W mit Raspberry Pi OS Lite (64 Bit empfohlen)
- 2,2-Zoll-TFT mit ILI9341-Controller, 240 × 320 Pixel
- passende Jumper-Kabel

### Beispielverdrahtung

Die Bezeichnungen auf Display-Modulen unterscheiden sich. `SCK` kann auch `CLK`,
`MOSI` auch `SDI` oder `DIN` und `CS` auch `CE` heißen.

| Display | Raspberry Pi | Physischer Pin |
|---|---|---:|
| VCC | 3,3 V | 1 |
| GND | GND | 6 |
| SCK / CLK | GPIO 11 (SPI0 SCLK) | 23 |
| MOSI / SDI | GPIO 10 (SPI0 MOSI) | 19 |
| CS / CE | GPIO 8 (SPI0 CE0) | 24 |
| DC / RS | GPIO 24 | 18 |
| RST / RESET | GPIO 25 | 22 |
| LED | 3,3 V | 17 |

> Das Display nur mit 3,3-V-Logik betreiben. Vor dem Anschluss das Datenblatt des
> konkreten Moduls prüfen. Die Hintergrundbeleuchtung nicht direkt über einen
> GPIO-Pin versorgen, wenn das Modul dafür keinen geeigneten Vorwiderstand oder
> Treiber besitzt.

## Installation

### 1. Raspberry Pi vorbereiten

```bash
sudo apt update
sudo apt install -y git python3-venv python3-dev fonts-dejavu-core \
  libjpeg-dev zlib1g-dev libfreetype6-dev
sudo raspi-config
```

In `raspi-config` **Interface Options → SPI → Yes** wählen und anschließend neu
starten:

```bash
sudo reboot
```

Nach dem Neustart sollte `/dev/spidev0.0` existieren:

```bash
ls -l /dev/spidev0.0
```

### 2. Anwendung installieren

Sobald das GitHub-Repository verfügbar ist:

```bash
sudo git clone https://github.com/Ben1991/hvv-anzeiger.git /opt/hvv-anzeiger
sudo chown -R "$USER":"$USER" /opt/hvv-anzeiger
cd /opt/hvv-anzeiger
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
cp config.example.json config.json
```

`config.json` kann unverändert als Startpunkt dienen. Falls das Bild auf dem Kopf
steht, `display.rotate` von `0` auf `2` ändern. Bei vertauschten Farben
`display.bgr` auf `true` setzen.

### 3. Geofox-Zugangsdaten hinterlegen

Die von Geofox erhaltene Application-ID und das Passwort werden in einer
geschützten Systemdatei gespeichert:

```bash
sudo install -m 600 /dev/null /etc/hvv-anzeiger.env
sudo nano /etc/hvv-anzeiger.env
```

Folgenden Inhalt eintragen:

```text
GEOFOX_USER=DEINE_APPLICATION_ID
GEOFOX_PASSWORD=DEIN_PASSWORT
```

Keine Anführungszeichen um die Werte schreiben.

### 4. Einmaliger Funktionstest

```bash
cd /opt/hvv-anzeiger
set -a
. /etc/hvv-anzeiger.env
set +a
.venv/bin/hvv-anzeiger --config config.json --once
```

Die Beispielkonfiguration enthält die geprüften IDs `Master:82039` für
Weistritzstraße und `Master:82015` für Recknitzstraße. Falls eine ID entfernt oder
eine neue Haltestelle ergänzt wird, sucht das Programm sie über Geofox. Die
ermittelte ID landet in `var/stations.json`. Bei mehreren gleichnamigen Treffern
nennt das Programm die Kandidaten; dann die gewünschte ID als `"id": "Master:..."`
beim entsprechenden Eintrag in `config.json` ergänzen.

Für einen Test ohne angeschlossenes Display kann eine PNG-Datei geschrieben werden:

```bash
.venv/bin/hvv-preview preview.png
```

Oder mit echten API-Daten:

```bash
.venv/bin/hvv-anzeiger --config config.json --once --output preview.png
```

### 5. Automatischen Start einrichten

Der Dienst verwendet im Beispiel den Benutzer `pi`. Falls dein Benutzer anders
heißt, `User=` und `Group=` in `systemd/hvv-anzeiger.service` anpassen.

```bash
sudo cp systemd/hvv-anzeiger.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hvv-anzeiger
```

Status und Protokoll anzeigen:

```bash
systemctl status hvv-anzeiger
journalctl -u hvv-anzeiger -f
```

Nach Änderungen an `config.json`:

```bash
sudo systemctl restart hvv-anzeiger
```

## Konfiguration

Die wichtigsten Werte in `config.json`:

| Feld | Bedeutung |
|---|---|
| `api.refresh_seconds` | Aktualisierung; mindestens 15 Sekunden |
| `api.max_departures` | Sichtbare Zeilen; 1 bis 5 |
| `api.max_time_offset_minutes` | Suchzeitraum ab jetzt |
| `display.gpio_dc` / `gpio_reset` | verwendete GPIO-Nummern |
| `display.rotate` | Drehung: 0, 1, 2 oder 3 |
| `display.bgr` | auf `true`, falls Rot und Blau vertauscht sind |
| `stations[].routes` | erlaubte Kombinationen aus Linie und Ziel |

Linien und Ziele werden tolerant gegenüber Groß-/Kleinschreibung, Umlauten und
Schreibweisen wie `Straße`/`Strasse` verglichen. Dadurch passt zum Beispiel das
konfigurierte Ziel „Elbgaustraße“ auch auf „S Elbgaustraße“ aus der API.

## Tests

Auf einem Entwicklungsrechner:

```bash
python3 -m venv .venv
.venv/bin/pip install .
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/hvv-preview preview.png
```

Die automatisierten Tests prüfen Konfiguration, HMAC-Signatur, Linienfilter,
Sortierung und Bildgröße. Der echte Displayzugriff und echte Geofox-Daten können
erst mit Hardware beziehungsweise gültigen Zugangsdaten geprüft werden.

## Technischer Hintergrund

Die Anwendung verwendet die Geofox-Methode
`POST /gti/public/departureList` mit API-Version 63 und `useRealtime: true`.
Die Signatur ist Base64-codiertes HMAC-SHA1 über den exakten UTF-8-JSON-Body.
Jede Anfrage bekommt eine eigene `X-TraceId`, die bei Fehlern im Log steht.

Das Display wird über `luma.lcd` angesteuert. Die Oberfläche selbst wird mit Pillow
als 320 × 240 Pixel großes RGB-Bild erzeugt und anschließend vollständig auf das
ILI9341 übertragen.
