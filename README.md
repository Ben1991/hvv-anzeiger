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
  und erhält einen roten Hinweis „DATEN VERALTET“. Nach standardmäßig fünf Minuten
  werden alte Buszeilen ausgeblendet, damit abgelaufene Prognosen nicht dauerhaft
  als „sofort“ erscheinen. Die Uhrzeit des letzten Datenstands bleibt sichtbar.
- Bei getrennter WLAN-Verbindung zeigt die Statusleiste ausdrücklich „KEIN WLAN“
  und, falls vorhanden, die Uhrzeit des letzten erfolgreichen Datenstands.
- Bei wiederholten Fehlern verdoppelt sich der Abstand zwischen den Versuchen bis
  maximal fünf Minuten. Der Anzeigezustand wird trotzdem alle 15 Sekunden geprüft.
  Nach einem erfolgreichen Abruf gelten auch für die API wieder 15 Sekunden.
- Schriftarten werden im Arbeitsspeicher wiederverwendet. Ein neues Bild wird nur
  gerendert und über SPI übertragen, wenn sich der sichtbare Inhalt geändert hat.
  Das spart CPU-Zeit und SPI-Übertragungen, ohne die Geofox-Abrufe zu reduzieren.
- Sowohl HTTP-Fehler als auch Geofox-Fehler im JSON-Feld `returnCode` werden geprüft.
- Geofox-Antworten sind auf 1 MiB begrenzt, damit eine fehlerhafte Server- oder
  Proxy-Antwort nicht unkontrolliert Arbeitsspeicher belegt.
- Erfolgreiche Routineabrufe stehen im Debug-Log. Auf Info-Ebene erscheint höchstens
  einmal pro Stunde ein Lebenszeichen; Fehler bleiben sofort sichtbar. Das reduziert
  unnötige Schreibzugriffe auf die SD-Karte.
- Ein systemd-Timer bereinigt das Journal wöchentlich. Archivierte Einträge, die
  älter als sieben Tage sind, werden entfernt; zusätzlich wird der archivierte
  Journalbestand auf 100 MiB begrenzt.
- Der systemd-Dienst startet erst nach Netzwerk- und Zeitsynchronisierungs-Targets.
  Das ist wichtig, weil ein Raspberry Pi üblicherweise keine Echtzeituhr besitzt.
- Der systemd-Dienst darf das Betriebssystem, Benutzerverzeichnisse und den
  Anwendungscode nicht verändern. Schreibzugriff besteht nur auf den lokalen
  Haltestellen-Cache unter `/opt/hvv-anzeiger/var`.
- Der Dienst läuft unter dem nicht interaktiven Systembenutzer `hvv-anzeiger`.
  Programmcode und Konfiguration gehören `root`; nur das Cache-Verzeichnis gehört
  dem Dienstbenutzer.
- Geofox-Anfragen sind ausschließlich über HTTPS an `gti.geofox.de` erlaubt.
  Externe Fehlermeldungen werden vor der Ausgabe auf eine einzelne sichere
  Protokollzeile begrenzt.
- Laufzeit- und Testabhängigkeiten sind vollständig mit Versionen und
  SHA-256-Prüfsummen gesperrt. Der Dependency Audit in CI prüft jede Änderung
  zusätzlich gegen bekannte Sicherheitsmeldungen.

## Sicherheitsmodell

Der Raspberry Pi stellt durch diese Anwendung keinen eingehenden Netzwerkdienst
bereit. Die einzige Netzwerkkommunikation sind ausgehende HTTPS-Anfragen an
Geofox. Die Zugangsdaten liegen als `root:root` mit Dateirechten `0600` unter
`/etc/hvv-anzeiger.env` und werden weder in Git noch als Kommandozeilenparameter
gespeichert.

Die Installation trennt drei Bereiche:

| Bereich | Eigentümer | Rechte des Dienstes |
|---|---|---|
| Programm und virtuelle Umgebung unter `/opt/hvv-anzeiger` | `root:root` | lesen und ausführen |
| Konfiguration `/opt/hvv-anzeiger/config.json` | `root:root` | nur lesen |
| Laufzeitdaten `/opt/hvv-anzeiger/var` | `hvv-anzeiger:hvv-anzeiger` | lesen und schreiben |

Der Benutzer `hvv-anzeiger` besitzt keine Login-Shell und erhält nur über die
Gruppen `spi` und `gpio` Zugriff auf die Display-Hardware. Die systemd-Sandbox
verhindert zusätzlich Änderungen an Betriebssystem, Kernel-Einstellungen,
Benutzerverzeichnissen und Anwendungscode.

Sicherheitsupdates werden in zwei Stufen geprüft:

- `requirements.txt` und `requirements-dev.txt` enthalten festgelegte
  Versionen und die erlaubten Paketprüfsummen. Eine manipulierte Paketdatei wird
  bei der Installation abgelehnt.
- GitHub Actions führt `pip-audit` gegen die Laufzeit-Lockdatei aus. Bekannte
  Abhängigkeitsschwachstellen lassen den Workflow fehlschlagen.

### Einmalige GitHub-Einstellungen für den Repository-Owner

Einige Schutzfunktionen liegen nicht im Repository und können deshalb nicht durch
einen Commit aktiviert werden. Der Owner sollte einmalig in den
Repository-Einstellungen prüfen:

- **Dependabot Alerts** und **Dependabot Security Updates** aktivieren. Die Datei
  `.github/dependabot.yml` übernimmt danach die wöchentlichen, in CI geprüften
  Versionsupdates.
- `main` mit einer Branch-Regel oder einem Ruleset schützen, den Workflow **CI**
  als erforderlichen Check setzen und Force-Push sowie Branch-Löschung
  deaktivieren.
- **Secret Scanning** aktivieren, falls es für den verwendeten GitHub-Tarif
  verfügbar ist.
- Optional **Code Scanning/CodeQL** aktivieren, falls es für das private
  Repository verfügbar ist. Ruff Security und `pip-audit` laufen unabhängig
  davon bereits bei jedem Push und Pull Request.

Nur ein Repository-Owner oder Benutzer mit Admin-Rechten kann diese Einstellungen
ändern. Der aktuelle Zustand lässt sich unter **Settings → Security** und
**Settings → Rules** kontrollieren.

Voraussetzung ist **Python 3.10 oder neuer**. Empfohlen wird Raspberry Pi OS
Bookworm 64 Bit mit Python 3.11. Python 3.9 wird nicht mehr unterstützt, weil die
bereinigte Pillow-Version 12.3.0 mindestens Python 3.10 benötigt.

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

## Erwarteter Ressourcenverbrauch auf dem Pi Zero 2 W

Die folgenden Werte sind realistische Orientierungswerte, aber noch keine Messung
auf dem konkreten Raspberry Pi und Display. Betriebssystem, Python-/Pillow-Version,
WLAN-Qualität und Größe der Geofox-Antwort beeinflussen die tatsächlichen Werte.

| Ressource | Erwartungswert | Auswirkung |
|---|---:|---|
| Arbeitsspeicher | ungefähr 40–70 MiB im Dauerbetrieb | deutlich unter den 512 MiB des Pi Zero 2 W; Raspberry Pi OS Lite und die Anzeige sollten ausreichend Reserve haben |
| CPU | meist niedriger einstelliger Prozentbereich im zeitlichen Mittel, mit kurzen Spitzen beim API-Abruf und Rendern | die vier Kerne werden nicht dauerhaft belastet; andere kleine Dienste können parallel laufen |
| Bildspeicher | 230.400 Byte pro 320 × 240-RGB-Bild, zeitweise wenige Bildpuffer | weniger als einige MiB; für den Pi unkritisch |
| SPI | 230.400 Byte pro vollständig übertragenem Bild | bei unveränderter Anzeige meist nur etwa einmal pro Minute statt viermal; bei jeder sichtbaren Änderung sofort |
| Netzwerk | 240 Geofox-Abrufe pro Stunde; typischerweise wenige MiB pro Stunde | geringes Datenvolumen, aber dauerhaftes WLAN ist erforderlich; die Antwortgröße bestimmt den exakten Wert |
| Installation | grob 50–120 MiB für Anwendung, virtuelle Python-Umgebung und Bibliotheken | die Paket-Caches des Betriebssystems können zusätzlich Speicherplatz belegen |

Der größte dauerhafte Stromverbrauch entsteht voraussichtlich durch Raspberry Pi,
WLAN und Display-Hintergrundbeleuchtung, nicht durch das Python-Programm. Für diese
Anwendung ist normalerweise keine aktive Kühlung nötig. In einem engen,
schlecht belüfteten Gehäuse sollte die Temperatur nach einigen Stunden dennoch
kontrolliert werden.

Die Anwendung vermeidet unnötige Arbeit:

- Geofox wird weiterhin alle 15 Sekunden abgefragt, damit Echtzeitänderungen schnell
  sichtbar werden.
- Solange Uhrzeit, Abfahrten und Statushinweis gleich bleiben, entfallen Rendering
  und SPI-Transfer vollständig.
- Geladene Schriftarten werden wiederverwendet.
- Zwischen Aktualisierungen wacht der Prozess höchstens einmal pro Sekunde auf.
  Dadurch reagiert der Dienst weiterhin zeitnah auf ein Stoppsignal, ohne viermal
  pro Sekunde unnötig aktiv zu werden.

### Verbrauch auf dem eigenen Pi messen

Nach einigen Minuten Laufzeit liefern diese Befehle aussagekräftigere Werte für
das konkrete Gerät:

```bash
pid="$(systemctl show --property MainPID --value hvv-anzeiger)"
ps -p "$pid" -o pid,%cpu,rss,etime,cmd
systemctl show hvv-anzeiger -p MemoryCurrent -p CPUUsageNSec
du -sh /opt/hvv-anzeiger
awk '{printf "%.1f °C\n", $1 / 1000}' /sys/class/thermal/thermal_zone0/temp
```

`RSS` wird von `ps` in KiB ausgegeben. Für einen belastbaren CPU-Mittelwert den
`ps`-Befehl mehrmals über einige Minuten ausführen. Das Netzwerkvolumen lässt sich
vor und nach einer Stunde anhand der RX-/TX-Zähler von `wlan0` vergleichen:

```bash
grep wlan0 /proc/net/dev
```

### Log-Aufbewahrung

`hvv-anzeiger-log-cleanup.timer` läuft standardmäßig einmal pro Woche. Durch
`Persistent=true` wird eine während eines ausgeschalteten Raspberry Pi verpasste
Ausführung beim nächsten Start nachgeholt. Vor der Bereinigung wird das aktive
Journal rotiert. Danach gelten zwei Grenzen:

- archivierte Journal-Einträge älter als sieben Tage werden gelöscht,
- archivierte Journale belegen zusammen höchstens 100 MiB.

Journald verwaltet die Meldungen aller systemd-Dienste gemeinsam. Die Bereinigung
betrifft deshalb das gesamte Systemjournal, nicht nur `hvv-anzeiger`. Die jeweils
letzte Woche bleibt weiterhin beispielsweise mit `journalctl -u hvv-anzeiger`
abrufbar. Status und aktuellen Speicherverbrauch prüfen:

```bash
systemctl status hvv-anzeiger-log-cleanup.timer
journalctl --disk-usage
```

Für einen sofortigen manuellen Bereinigungslauf:

```bash
sudo systemctl start hvv-anzeiger-log-cleanup.service
```

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
- stoppt bei einer Wiederholungsinstallation zuerst den laufenden Dienst,
- sichert die bisherige Python-Umgebung und stellt sie bei einem Installationsfehler
  automatisch wieder her,
- aktiviert die Netzwerk-Zeitsynchronisierung,
- legt den nicht interaktiven Systembenutzer `hvv-anzeiger` an,
- schützt Programmcode und Konfiguration als `root:root` und gibt dem Dienst nur
  Schreibrecht auf `var`,
- installiert ausschließlich die in `requirements.txt` festgelegten Pakete mit
  geprüften SHA-256-Hashes,
- aktiviert die wöchentliche Journal-Bereinigung,
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

Die manuelle Installation verwendet denselben eingeschränkten Dienstbenutzer und
dieselbe geprüfte Lockdatei wie `install.sh`:

```bash
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger

getent group hvv-anzeiger >/dev/null ||
  sudo groupadd --system hvv-anzeiger
id -u hvv-anzeiger >/dev/null 2>&1 ||
  sudo useradd --system --gid hvv-anzeiger \
    --home-dir /opt/hvv-anzeiger --no-create-home \
    --shell /usr/sbin/nologin hvv-anzeiger
sudo usermod --append --groups spi,gpio hvv-anzeiger

sudo install -d -m 0755 -o root -g root /opt/hvv-anzeiger
sudo cp -R hvv_display systemd /opt/hvv-anzeiger/
sudo install -m 0644 README.md config.example.json pyproject.toml \
  requirements.txt /opt/hvv-anzeiger/
sudo install -m 0755 diagnose.sh /opt/hvv-anzeiger/diagnose.sh
sudo install -d -m 0750 -o hvv-anzeiger -g hvv-anzeiger \
  /opt/hvv-anzeiger/var

sudo python3 -m venv /opt/hvv-anzeiger/.venv
sudo -H /opt/hvv-anzeiger/.venv/bin/pip install \
  --require-hashes --requirement /opt/hvv-anzeiger/requirements.txt
sudo -H /opt/hvv-anzeiger/.venv/bin/pip install \
  --no-build-isolation --no-deps /opt/hvv-anzeiger
sudo install -m 0644 -o root -g root config.example.json \
  /opt/hvv-anzeiger/config.json
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

Der Dienst verwendet immer den eigens angelegten Benutzer `hvv-anzeiger`. `User=`
und `Group=` sollten nicht auf den normalen Login-Benutzer geändert werden.

```bash
sudo cp systemd/hvv-anzeiger.service \
  systemd/hvv-anzeiger-log-cleanup.service \
  systemd/hvv-anzeiger-log-cleanup.timer \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hvv-anzeiger
sudo systemctl enable --now hvv-anzeiger-log-cleanup.timer
```

Status und Protokoll anzeigen:

```bash
systemctl status hvv-anzeiger
journalctl -u hvv-anzeiger -f
systemctl list-timers hvv-anzeiger-log-cleanup.timer
```

Eine vollständige Softwarediagnose auf dem Raspberry Pi ausführen:

```bash
cd /opt/hvv-anzeiger
./diagnose.sh
```

Sie prüft Linux, SPI, Zeitsynchronisierung, Installation, Zugangsdaten,
WLAN-Verbindung, Autostart, Dienststatus, Journal-Bereinigung und das lokale
Rendern eines Displaybilds. Zugangsdaten werden dabei nicht ausgegeben.

Nach Änderungen an `config.json`:

```bash
sudo systemctl restart hvv-anzeiger
```

## Konfiguration

`config.example.json` enthält alle empfohlenen Werte. Optionale Felder dürfen
weggelassen werden; dann gelten die folgenden Defaults aus dem Programmcode.

### API-Defaults

| Feld | Default | Bedeutung und Grenze |
|---|---:|---|
| `api.base_url` | kein Default, Pflichtfeld | ausschließlich HTTPS auf `gti.geofox.de`; im Beispiel `https://gti.geofox.de/gti/public` |
| `api.version` | `63` | verwendete Geofox-GTI-Version |
| `api.refresh_seconds` | `15` | regulärer Abstand der Echtzeitabrufe; mindestens 15 Sekunden |
| `api.request_timeout_seconds` | `8` | Zeitlimit pro HTTP-Anfrage; muss größer als 0 sein |
| `api.max_departures` | `5` | maximal sichtbare Zeilen; erlaubt sind 1 bis 5 |
| `api.max_time_offset_minutes` | `90` | Geofox-Suchzeitraum ab der aktuellen Uhrzeit; muss größer als 0 sein |
| `api.max_stale_age_minutes` | `5` | so lange dürfen alte Buszeilen bei einem Abruffehler sichtbar bleiben; danach bleibt nur der Fehlerstatus mit letztem Datenstand |

### Display-Defaults

| Feld | Default | Bedeutung und Grenze |
|---|---:|---|
| `display.spi_port` | `0` | SPI-Port |
| `display.spi_device` | `0` | SPI-Gerät beziehungsweise Chip-Select; entspricht üblicherweise `/dev/spidev0.0` |
| `display.gpio_dc` | `24` | GPIO-Nummer für Data/Command |
| `display.gpio_reset` | `25` | GPIO-Nummer für Reset |
| `display.rotate` | `0` | Drehung; erlaubt sind 0, 1, 2 oder 3 |
| `display.bus_speed_hz` | `16000000` | SPI-Takt in Hertz; muss größer als 0 sein |
| `display.bgr` | `false` | auf `true` setzen, falls Rot und Blau vertauscht sind |

### Haltestellen-Defaults

| Feld | Default | Bedeutung und Grenze |
|---|---|---|
| `stations` | kein Default, Pflichtfeld | mindestens eine Haltestelle |
| `stations[].name` | kein Default, Pflichtfeld | Haltestellenname |
| `stations[].city` | `"Hamburg"` | Stadt für die Haltestellensuche |
| `stations[].id` | keine | optionale Geofox-ID; ohne ID wird sie gesucht und unter `var/stations.json` gespeichert |
| `stations[].label` | erster Buchstabe des Namens | eindeutiges Kürzel mit 1 bis 3 Zeichen; wird in Großbuchstaben angezeigt |
| `stations[].routes` | kein Default, Pflichtfeld | mindestens eine erlaubte Kombination aus Linie und Ziel |
| `stations[].routes[].line` | kein Default, Pflichtfeld | Linienbezeichnung, beispielsweise `"21"` |
| `stations[].routes[].destination` | kein Default, Pflichtfeld | erwartetes Fahrtziel |

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
python3.11 -m venv .venv
.venv/bin/pip install --require-hashes --requirement requirements-dev.txt
.venv/bin/pip install --no-build-isolation --no-deps --editable .
.venv/bin/ruff check .
.venv/bin/coverage run -m unittest discover -s tests -v
.venv/bin/coverage report
.venv/bin/pip-audit --requirement requirements.txt --disable-pip
.venv/bin/hvv-preview preview.png
bash -n install.sh diagnose.sh
shellcheck install.sh diagnose.sh
```

Die automatisierten Tests prüfen unter anderem:

- Konfigurationsgrenzen und die vorkonfigurierten Haltestellen,
- HMAC-Signatur, HTTP-/Geofox-Fehler und mehrdeutige Haltestellensuchen,
- Größenbegrenzung von Geofox-Antworten und Ablauf veralteter Abfahrten,
- Linienfilter, Echtzeitverspätungen, Sortierung und Zeitumstellungen,
- Haltestellen-Cache und atomisches Speichern gefundener IDs,
- eine dokumentationsnahe, anonymisierte Geofox-Beispielantwort vom API-Eingang
  bis zum gerenderten Displaybild,
- Herkunftskennzeichnung pro Haltestelle und begrenztes Fehler-Backoff,
- stündlich begrenztes Erfolgs-Logging, gehärteten systemd-Dienst und
  wiederherstellbare Python-Installation,
- HTTPS-/Host-Prüfung, einzeilige externe Fehlertexte, den dedizierten
  Dienstbenutzer und root-eigenen Anwendungscode,
- Prüfsummen der installierten Pakete und bekannte
  Abhängigkeitsschwachstellen,
- wöchentliche Journal-Bereinigung mit Alters- und Größenlimit,
- verbundene, getrennte, unbekannte und alternativ benannte WLAN-Schnittstellen,
- normale, leere und veraltete Anzeigezustände,
- Screenshot, Installationsskript, Pi-Diagnose und systemd-Konfiguration.

GitHub Actions führt diese Prüfungen nach jedem Push und für jeden Pull Request mit
Python 3.10, 3.11 und 3.13 aus. Zusätzlich werden Ruff einschließlich seiner
Security-Regeln, eine Mindest-Testabdeckung von 100 Prozent, `pip-audit`, beide
Shell-Skripte mit Bash und ShellCheck, ein Vorschaubild und das installierbare
Python-Paket geprüft.

Alle direkten und transitiven Laufzeitabhängigkeiten sind mit Prüfsummen in
`requirements.txt` festgeschrieben. `requirements-dev.txt` ergänzt die ebenfalls
gesperrten Test- und Build-Werkzeuge. Dependabot sucht wöchentlich nach
kontrollierten Aktualisierungen für Python-Pakete und GitHub Actions.

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
ILI9341 übertragen. Bereits geladene Schriftarten werden zwischengespeichert.
Ein Bild wird nur neu erzeugt und übertragen, wenn sich sein sichtbarer Inhalt
gegenüber dem vorherigen Bild geändert hat.

Der Dienst läuft als nicht interaktiver Benutzer `hvv-anzeiger` mit
systemd-Schutzmechanismen wie `NoNewPrivileges` und einem schreibgeschützten
Betriebssystem- und Anwendungsbereich. Programm, virtuelle Umgebung und
Konfiguration gehören `root`; `/opt/hvv-anzeiger/var` ist die einzige explizite
Schreibausnahme für den Haltestellen-Cache. Ein bewusstes RAM-Limit ist nicht
gesetzt: Die dokumentierten Messbefehle sollten zuerst auf dem konkreten Pi
ausgeführt werden, damit ein zu knapp angesetztes Limit nicht unnötig zu
Neustarts führt.
