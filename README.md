# HVV-Anzeiger für Raspberry Pi

[![CI](https://github.com/Ben1991/hvv-anzeiger/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ben1991/hvv-anzeiger/actions/workflows/ci.yml)

Zeigt die nächsten passenden HVV-Busabfahrten auf einem 2,2-Zoll-ILI9341-SPI-Display
mit 320 × 240 Pixeln im Querformat. Die Daten kommen alle 15 Sekunden aus der
Geofox-GTI-API.

Vorkonfiguriert sind:

- Weistritzstraße: 186 nach S Othmarschen, 184 nach S Halstenbek und 384 nach
  Elbgaustraße
- Recknitzstraße: 21 nach U Niendorf Nord

![Beispielansicht der HVV-Abfahrtsanzeige](docs/hvv-anzeiger-preview.png)

Das Kürzel `W` kennzeichnet die Weistritzstraße, `R` die Recknitzstraße. Dadurch
bleibt auch bei einer gemeinsamen, chronologisch sortierten Liste erkennbar, von
welcher Haltestelle der Bus abfährt.

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
- Bei getrennter WLAN-Verbindung zeigt die Statusleiste ausdrücklich „KEIN WLAN“
  und, falls vorhanden, die Uhrzeit des letzten erfolgreichen Datenstands.
- Bei wiederholten Fehlern verdoppelt sich der Abstand zwischen den Versuchen bis
  maximal fünf Minuten. Uhrzeit und sichtbare Restzeiten werden trotzdem alle
  15 Sekunden neu gezeichnet. Nach einem erfolgreichen Abruf gelten auch für die
  API wieder 15 Sekunden.
- Sowohl HTTP-Fehler als auch Geofox-Fehler im JSON-Feld `returnCode` werden geprüft.
- Der systemd-Dienst startet erst nach Netzwerk- und Zeitsynchronisierungs-Targets.
  Das ist wichtig, weil ein Raspberry Pi üblicherweise keine Echtzeituhr besitzt.

## Welche Abfahrtszeit wird angezeigt?

Die Anzeige verwendet nicht einfach die unveränderte Fahrplanzeit, sondern die
aktuelle Geofox-Echtzeitprognose:

```text
angezeigte Abfahrt = Planabfahrt + von Geofox gemeldete Verspätung
```

Geofox liefert die Verspätung in Sekunden. Sowohl die große Restzeit wie
`7 min` als auch die kleine absolute Uhrzeit wie `12:34` werden aus dieser
korrigierten Abfahrtszeit berechnet. Die Prognose wird regulär alle 15 Sekunden
neu abgerufen.

Wichtig: Bei einer zukünftigen Abfahrt ist dies die aktuell bestmögliche
Prognose, nicht eine bereits gemessene tatsächliche Abfahrt. Liefert Geofox keine
Verspätung, wird die planmäßige Abfahrtszeit verwendet. Gemeldete Ausfälle werden
statt einer Restzeit mit `AUS` gekennzeichnet.

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

### Schnellinstallation

Raspberry Pi OS verwendet Linux. Deshalb ist die Installationsdatei ein
Bash-Skript (`install.sh`) und keine Windows-`.bat`-Datei.

```bash
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
chmod +x install.sh
./install.sh
```

Das Skript:

- installiert die benötigten System- und Python-Pakete,
- aktiviert SPI,
- installiert die Anwendung unter `/opt/hvv-anzeiger`,
- übernimmt eine vorhandene `config.json` und Zugangsdaten unverändert,
- aktiviert die Netzwerk-Zeitsynchronisierung,
- passt den systemd-Dienst an den aktuellen Linux-Benutzer an,
- aktiviert den Autostart.

Die Zugangsdaten werden nicht als Kommandozeilenparameter abgefragt oder
gespeichert. Wenn sie noch fehlen, nennt das Skript am Ende die beiden
erforderlichen Befehle. Nach der erstmaligen SPI-Aktivierung sollte der
Raspberry Pi neu gestartet werden.

### Manuelle Installation

### 1. Raspberry Pi vorbereiten

```bash
sudo apt update
sudo apt install -y git python3-venv python3-dev fonts-dejavu-core \
  libjpeg-dev zlib1g-dev libfreetype6-dev
sudo raspi-config
sudo timedatectl set-ntp true
```

In `raspi-config` **Interface Options → SPI → Yes** wählen und anschließend neu
starten:

```bash
sudo reboot
```

Nach dem Neustart sollte `/dev/spidev0.0` existieren:

```bash
ls -l /dev/spidev0.0
timedatectl status
```

Bei `System clock synchronized` muss `yes` stehen, bevor die echten Abfahrtszeiten
geprüft werden.

### 2. Anwendung installieren

Sobald das GitHub-Repository verfügbar ist:

```bash
sudo git clone https://github.com/Ben1991/hvv-anzeiger.git /opt/hvv-anzeiger
sudo chown -R "$USER":"$USER" /opt/hvv-anzeiger
cd /opt/hvv-anzeiger
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install --constraint constraints.txt .
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

Eine vollständige Softwarediagnose auf dem Raspberry Pi ausführen:

```bash
cd /opt/hvv-anzeiger
./diagnose.sh
```

Sie prüft Linux, SPI, Zeitsynchronisierung, Installation, Zugangsdaten,
WLAN-Verbindung, Autostart, Dienststatus und das lokale Rendern eines
Displaybilds. Zugangsdaten werden dabei nicht ausgegeben.

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
| `stations[].label` | eindeutiges Kürzel mit 1 bis 3 Zeichen für die Anzeige |
| `stations[].routes` | erlaubte Kombinationen aus Linie und Ziel |

Die WLAN-Schnittstelle ist standardmäßig `wlan0`. Falls das Betriebssystem einen
anderen Namen verwendet, den systemd-Dienst überschreiben:

```bash
sudo systemctl edit hvv-anzeiger
```

Folgenden Inhalt eintragen:

```ini
[Service]
Environment=HVV_WIFI_INTERFACE=DEINE_WLAN_SCHNITTSTELLE
```

Danach neu laden und starten:

```bash
sudo systemctl daemon-reload
sudo systemctl restart hvv-anzeiger
```

Linien und Ziele werden tolerant gegenüber Groß-/Kleinschreibung, Umlauten und
Schreibweisen wie `Straße`/`Strasse` verglichen. Dadurch passt zum Beispiel das
konfigurierte Ziel „Elbgaustraße“ auch auf „S Elbgaustraße“ aus der API.

## Tests

Auf einem Entwicklungsrechner:

```bash
python3 -m venv .venv
.venv/bin/pip install --constraint constraints.txt --editable ".[test]"
.venv/bin/ruff check .
.venv/bin/coverage run -m unittest discover -s tests -v
.venv/bin/coverage report
.venv/bin/hvv-preview preview.png
bash -n install.sh diagnose.sh
shellcheck install.sh diagnose.sh
```

Die automatisierten Tests prüfen unter anderem:

- Konfigurationsgrenzen und die vorkonfigurierten Haltestellen,
- HMAC-Signatur, HTTP-/Geofox-Fehler und mehrdeutige Haltestellensuchen,
- Linienfilter, Echtzeitverspätungen, Sortierung und Zeitumstellungen,
- Haltestellen-Cache und atomisches Speichern gefundener IDs,
- eine dokumentationsnahe, anonymisierte Geofox-Beispielantwort vom API-Eingang
  bis zum gerenderten Displaybild,
- Herkunftskennzeichnung pro Haltestelle und begrenztes Fehler-Backoff,
- verbundene, getrennte, unbekannte und alternativ benannte WLAN-Schnittstellen,
- normale, leere und veraltete Anzeigezustände,
- Screenshot, Installationsskript, Pi-Diagnose und systemd-Konfiguration.

GitHub Actions führt diese Prüfungen nach jedem Push und für jeden Pull Request mit
Python 3.9, 3.11 und 3.13 aus. Zusätzlich werden Ruff, eine Mindest-Testabdeckung
von 80 Prozent, beide Shell-Skripte mit Bash und ShellCheck, ein Vorschaubild und
das installierbare Python-Paket geprüft.

Die direkten Laufzeitabhängigkeiten sind in `constraints.txt` festgeschrieben.
Dependabot sucht wöchentlich nach kontrollierten Aktualisierungen für Python-Pakete
und GitHub Actions.

Der echte Displayzugriff und der authentifizierte Geofox-Produktivzugang können
weiterhin erst mit Hardware beziehungsweise gültigen Zugangsdaten geprüft werden.

## Abnahme auf dem Raspberry Pi

Nach Installation, Zugangsdaten und Neustart:

1. `./diagnose.sh` muss ohne Fehler enden.
2. Das Display muss fünf Zeilen vollständig und scharf darstellen.
3. Rot und Blau müssen korrekt sein; andernfalls `display.bgr` ändern.
4. `W` und `R` müssen die richtige Ausgangshaltestelle kennzeichnen.
5. WLAN kurz trennen: Der letzte Stand muss mit „KEIN WLAN“ sichtbar bleiben.
6. WLAN wieder verbinden: Die Anzeige muss selbstständig zu 15 Sekunden
   Aktualisierung zurückkehren.
7. Den Raspberry Pi neu starten und mit `systemctl status hvv-anzeiger` prüfen,
   dass die Anzeige ohne manuelles Eingreifen wieder läuft.

## Technischer Hintergrund

Die Anwendung verwendet die Geofox-Methode
`POST /gti/public/departureList` mit API-Version 63 und `useRealtime: true`.
Die Signatur ist Base64-codiertes HMAC-SHA1 über den exakten UTF-8-JSON-Body.
Jede Anfrage bekommt eine eigene `X-TraceId`, die bei Fehlern im Log steht.

Das Display wird über `luma.lcd` angesteuert. Die Oberfläche selbst wird mit Pillow
als 320 × 240 Pixel großes RGB-Bild erzeugt und anschließend vollständig auf das
ILI9341 übertragen.
