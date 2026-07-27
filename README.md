# HVV-Anzeiger für Raspberry Pi

[![CI](https://github.com/Ben1991/hvv-anzeiger/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/Ben1991/hvv-anzeiger/actions/workflows/ci.yml)

Der HVV-Anzeiger zeigt die nächsten passenden Busabfahrten auf einem
2,2-Zoll-ILI9341-SPI-Display. Die Abfahrten mehrerer Haltestellen werden gemeinsam
nach der erwarteten Abfahrtszeit sortiert und alle 15 Sekunden über die
Geofox-GTI-API aktualisiert.

![Beispielansicht der HVV-Abfahrtsanzeige](docs/hvv-anzeiger-preview.png)

## Funktionsumfang

- Anzeige von bis zu fünf Abfahrten auf 320 × 240 Pixeln im Querformat
- Linie, Fahrtziel, absolute Uhrzeit und verbleibende Minuten
- gemeinsame chronologische Sortierung über mehrere Haltestellen
- frei konfigurierbare Linien, Ziele und Haltestellen
- Geofox-Echtzeitprognosen einschließlich Verspätungen und Ausfällen
- Aktualisierung im Normalbetrieb alle 15 Sekunden
- sichtbare Hinweise bei fehlendem WLAN, veralteten Daten oder noch nicht
  synchronisierter Systemzeit
- Weiteranzeige des letzten erfolgreichen Datenstands bei vorübergehenden Fehlern
- optionaler Nachtmodus mit schwarzem Bild und pausierten Geofox-Abfragen
- automatischer Start, Neustart bei Fehlern und Überwachung durch systemd
- wöchentliche Begrenzung der Systemprotokolle
- Diagnosewerkzeug für die installierte Umgebung

### Vorkonfigurierte Verbindungen

| Kürzel | Haltestelle | Linie | Ziel |
|---|---|---:|---|
| W | Weistritzstraße | 186 | S Othmarschen |
| W | Weistritzstraße | 184 | S Halstenbek |
| W | Weistritzstraße | 384 | Elbgaustraße |
| R | Recknitzstraße | 21 | U Niendorf Nord |

Das Kürzel zeigt bei einer gemeinsam sortierten Liste, von welcher Haltestelle
die jeweilige Abfahrt stammt.

## Welche Abfahrtszeit wird angezeigt?

Die Anzeige verwendet die aktuelle Geofox-Prognose:

```text
erwartete Abfahrtszeit = Planabfahrt + gemeldete Verspätung
```

Die große Restzeit und die kleine absolute Uhrzeit basieren beide auf dieser
erwarteten Abfahrtszeit. Liefert Geofox keine Verspätung, wird die Planzeit
verwendet. Gemeldete Ausfälle erscheinen als `AUS`.

Eine zukünftige Abfahrt ist immer eine Prognose. Sie ist nicht mit einer bereits
gemessenen tatsächlichen Abfahrt gleichzusetzen.

## Datenquelle und Geofox-Zugang

### Was ist Geofox GTI?

Das
[Geofox Thin Interface (GTI)](https://gti.geofox.de/)
ist die REST-ähnliche Web-Service-Schnittstelle der Geofox-Fahrplanauskunft. Sie
stellt unter anderem Haltestellen, Linien, Abfahrten, Fahrtverläufe sowie Plan- und
Echtzeitinformationen bereit. Dieses Projekt verwendet die Abfahrtsliste mit
aktivierten Echtzeitdaten, um Verspätungen und gemeldete Ausfälle zu
berücksichtigen.

Geofox beziehungsweise die Schnittstelle wird von der HBT Hamburger Berater Team
GmbH betrieben. Der Schnittstellenzugang und die Datenbereitstellung für
HVV-Fahrplandaten werden auf der
[offiziellen HVV-Seite für individuelle Entwicklerprojekte](https://www.hvv.de/de/fahrplaene/abruf-fahrplaninfos/datenabruf)
beschrieben. Dieses Repository ist ein unabhängiges Projekt und kein offizielles
Produkt von HVV, HOCHBAHN oder HBT.

### Zugang beantragen

Der Zugriff ist beschränkt und wird nicht automatisch freigeschaltet. Laut HVV
besteht kein grundsätzlicher Anspruch auf einen Zugang. Für die Beantragung:

1. Die
   [HVV-Zugangsseite und Nutzungsbedingungen](https://www.hvv.de/de/fahrplaene/abruf-fahrplaninfos/datenabruf)
   lesen.
2. Den Zugang über die dort angebotene E-Mail-Adresse beantragen.
3. Im Antrag einen Ansprechpartner und eine kurze Beschreibung des Vorhabens
   nennen. Für dieses Projekt passt beispielsweise: private, kostenfreie
   Abfahrtsanzeige auf einem Raspberry Pi, verwendete Haltestellen und ein Abruf
   alle 15 Sekunden.
4. Nach Freigabe werden eine Geofox Application-ID und ein Passwort benötigt.
5. Repository installieren und beide Werte bei der interaktiven Abfrage von
   `./install.sh` eingeben.

Die Zugangsdaten niemals in `config.json`, im Repository, in einem GitHub-Issue
oder in einem Screenshot speichern. Der Installer legt sie geschützt unter
`/etc/hvv-anzeiger.env` ab.

### Nutzungs- und Betriebsgrenzen

- Maßgeblich sind immer die aktuellen Bedingungen von HVV, HOCHBAHN und HBT.
- Die Fahrplanauskunft muss für Endnutzer kostenfrei bleiben. Eine freiwillige
  Unterstützung dieses Open-Source-Projekts schaltet keine Funktionen oder
  Fahrplandaten frei.
- Herkunft und Anbieter der Fahrplandaten müssen erkennbar sein. Datenquelle für
  dieses Projekt ist Geofox/HVV.
- Bei einer öffentlichen Bereitstellung die aktuellen Darstellungs- und
  Hinweispflichten vollständig prüfen. Die HVV-Bedingungen nennen unter anderem
  einen sichtbaren Link zu `www.hvv.de` und einen Hinweis `ohne Gewähr`. Das
  kleine Display dieses privaten Zielsetups stellt diese Hinweise nicht
  automatisch dar.
- Für Vollständigkeit, Richtigkeit, Aktualität oder Verfügbarkeit der Daten gibt
  es keine Garantie.
- Geofox kann Zugriffe begrenzen. Laut
  [GTI-Anwenderhandbuch](https://gti.geofox.de/html/GTIHandbuch_p.html)
  kann ein Durchschnitt von mehr als einem API-Aufruf pro Sekunde zu einer
  temporären Sperre führen. Der Standard dieses Projekts liegt mit einem
  gemeinsamen Abruf alle 15 Sekunden deutlich darunter.
- Das Anwenderhandbuch weist darauf hin, dass inaktive Konten nach einem Jahr
  gelöscht werden können.

## Unterstütztes Setup

### Hardware

- Raspberry Pi Zero 2 W
- microSD-Karte
- zuverlässiges 5-V-Netzteil mit mindestens 2 A
- 2,2-Zoll-TFT mit ILI9341-Controller und 240 × 320 Pixeln
- passende Jumper-Kabel

### Software

- Raspberry Pi OS Lite Bookworm
- 64-Bit-Ausgabe empfohlen
- Python 3.10 oder neuer
- WLAN mit Internetzugang
- gültige Geofox-GTI-Zugangsdaten

Andere Raspberry-Pi-Modelle oder ILI9341-Module können funktionieren, sind aber
nicht das dokumentierte Zielsetup. Pinbelegung, Spannungsversorgung,
Hintergrundbeleuchtung und Farbreihenfolge müssen zum konkreten Display-Modul
passen.

## Verdrahtung

Die Bezeichnungen unterscheiden sich je nach Modul. `SCK` kann auch `CLK`,
`MOSI` auch `SDI` oder `DIN` und `CS` auch `CE` heißen.

| Display | Raspberry Pi | Physischer Pin |
|---|---|---:|
| VCC | 3,3 V | 1 |
| GND | GND | 6 |
| SCK / CLK | GPIO 11, SPI0 SCLK | 23 |
| MOSI / SDI | GPIO 10, SPI0 MOSI | 19 |
| CS / CE | GPIO 8, SPI0 CE0 | 24 |
| DC / RS | GPIO 24 | 18 |
| RST / RESET | GPIO 25 | 22 |
| LED | 3,3 V | 17 |

Vor dem Verdrahten das Datenblatt des konkreten Moduls prüfen. Das Display mit
3,3-V-Logik betreiben. Die Hintergrundbeleuchtung darf nur dann direkt an 3,3 V
angeschlossen werden, wenn das Modul den benötigten Vorwiderstand oder Treiber
enthält. Sie nicht ungeprüft direkt aus einem GPIO-Pin versorgen.

## Strom- und Ressourcenverbrauch

### Durchschnittlicher Stromverbrauch

Für das dokumentierte Setup ist im Dauerbetrieb folgender Planungswert realistisch:

| Messpunkt | Erwarteter Verbrauch |
|---|---:|
| Raspberry Pi Zero 2 W, aktiv | ungefähr 1,8 W |
| vergleichbares 2,2-Zoll-ILI9341-Modul | ungefähr 0,4 W |
| komplettes Setup am USB-Eingang | ungefähr 2,2–2,6 W |
| komplettes Setup an der Steckdose einschließlich Netzteilverlusten | ungefähr 2,5–3,0 W |
| sinnvoller Planungswert | **ungefähr 2,7 W im Durchschnitt** |

Bei 2,7 W und durchgehendem Betrieb entspricht das ungefähr:

- 0,065 kWh pro Tag
- 2,0 kWh pro Monat
- 24 kWh pro Jahr

Die Schätzung basiert auf dem von Raspberry Pi dokumentierten typischen aktiven
Strom von 350 mA für den Zero 2 W und 0,42 W für ein vergleichbares
2,2-Zoll-ILI9341-Modul. Das konkrete Display-Board, WLAN-Empfang, Netzteil und
CPU-Auslastung verändern den tatsächlichen Wert. Quellen:
[Raspberry Pi power supply documentation](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html#power-supply)
und
[LCDWiki MSP2202 manual](https://www.lcdwiki.com/res/MSP2202/2.2inch_SPI_Module_MSP2202_User_Manual_EN.pdf).

Ein USB-Leistungsmessgerät zwischen Netzteil und Raspberry Pi liefert den
verlässlichen Wert für das eigene Gerät. Ein Steckdosenmessgerät erfasst
zusätzlich die Verluste des Netzteils.

### Wirkung des Nachtmodus

Der Nachtmodus zeigt ein schwarzes Bild und pausiert die Geofox-Abfragen. Bei der
oben dokumentierten Verdrahtung bleibt `LED` jedoch dauerhaft an 3,3 V. Ein
schwarzes TFT-Bild spart deshalb praktisch keinen Displaystrom. Die geringere
CPU-, SPI- und WLAN-Aktivität reduziert den Gesamtverbrauch nur wenig.

Für eine relevante Einsparung muss die Hintergrundbeleuchtung elektrisch
abgeschaltet werden. Dafür ist ein zum Modul passender Transistor oder
Treiberbaustein erforderlich. Diese Hardwaresteuerung ist nicht Bestandteil des
Projekts.

### Weitere Ressourcen

| Ressource | Erwartungswert |
|---|---:|
| Arbeitsspeicher | ungefähr 40–70 MiB |
| CPU | im Mittel meist niedriger einstelliger Prozentbereich |
| Netzwerk | maximal 240 Geofox-Abfragen pro aktiver Stunde |
| Anwendungsinstallation | ungefähr 50–120 MiB |
| Displaybild | 230.400 Byte pro RGB-Bild |

Die Werte sind Richtwerte und keine Messung des konkreten Geräts. Für dieses
Setup ist normalerweise keine aktive Kühlung erforderlich. In einem engen,
schlecht belüfteten Gehäuse sollte die Temperatur nach einigen Stunden geprüft
werden.

## Installation

### Voraussetzungen

Vor der Installation werden benötigt:

1. Raspberry Pi OS Lite mit funktionierendem WLAN
2. Zugang per Terminal oder SSH
3. Geofox Application-ID und Geofox-Passwort
4. korrekt angeschlossenes Display

### Automatische Installation

```bash
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
chmod +x install.sh
./install.sh
```

`install.sh` richtet das vollständige System ein:

- benötigte Betriebssystem- und Python-Pakete
- SPI und Netzwerk-Zeitsynchronisierung
- Anwendung unter `/opt/hvv-anzeiger`
- geschützter Dienstbenutzer `hvv-anzeiger`
- Geofox-Zugangsdaten unter `/etc/hvv-anzeiger.env`
- Autostart, Prozessüberwachung und Log-Bereinigung

Bei der ersten Installation fragt das Skript die Geofox Application-ID und das
Passwort ab. Das Passwort bleibt bei der Eingabe unsichtbar. Eine vollständige
vorhandene Zugangsdaten-Datei und eine vorhandene `config.json` werden bei
späteren Installationen beibehalten.

Die neue Version wird vor der Umschaltung vollständig vorbereitet und geprüft.
Falls ihr Dienst anschließend nicht startet, werden Anwendung, Zugangsdaten und
systemd-Konfiguration auf den vorherigen Stand zurückgesetzt.

Nach der ersten Installation den Raspberry Pi neu starten:

```bash
sudo reboot
```

### Installation prüfen

Nach dem Neustart:

```bash
cd /opt/hvv-anzeiger
./diagnose.sh
```

Die Diagnose prüft:

- Linux und SPI-Gerät
- WLAN und Systemzeit
- Anwendung und Konfiguration
- Geofox-Zugangsdaten
- Dienst, Autostart und Watchdog
- Dienstbenutzer und Dateirechte
- Log-Bereinigung
- lokales Rendern eines Displaybilds

Zugangsdaten werden dabei nicht ausgegeben.

### Automatischer Start nach Reboot oder Stromausfall

Der Installer aktiviert `hvv-anzeiger` dauerhaft als systemd-Dienst. Nach einem
normalen Neustart oder nachdem die Stromversorgung wiederhergestellt wurde,
startet die Anzeige ohne Anmeldung und ohne manuellen Befehl.

Beim Hochfahren gilt:

1. systemd startet den Anzeigedienst automatisch.
2. Solange die Systemzeit noch nicht synchronisiert ist, zeigt das Display
   `ZEIT NICHT SYNCHRON` und es werden keine Geofox-Daten abgefragt.
3. Fehlt WLAN, zeigt das Display `KEIN WLAN`.
4. Sobald Systemzeit und Netzwerk verfügbar sind, lädt die Anwendung selbstständig
   aktuelle Geofox-Daten und setzt den normalen 15-Sekunden-Zyklus fort.
5. Endet oder blockiert der Prozess später unerwartet, startet systemd ihn erneut.

Autostart und aktuellen Zustand prüfen:

```bash
systemctl is-enabled hvv-anzeiger
systemctl status hvv-anzeiger --no-pager
```

Der erste Befehl muss `enabled` ausgeben. Falls nicht:

```bash
sudo systemctl enable --now hvv-anzeiger
```

`install.sh` wird bewusst nicht bei jedem Boot ausgeführt. Es dient nur zur
Installation und für Updates; automatisch gestartet wird die bereits installierte
Anzeige.

Ein harter Stromausfall kann unabhängig von dieser Anwendung eine beschriebene
microSD-Karte beschädigen. Für häufige oder kritische Stromunterbrechungen sind
ein zuverlässiges Netzteil und gegebenenfalls eine kleine USV sinnvoll.

## Konfiguration

Die aktive Konfiguration liegt unter:

```text
/opt/hvv-anzeiger/config.json
```

Bearbeiten und anschließend den Dienst neu starten:

```bash
sudo nano /opt/hvv-anzeiger/config.json
sudo systemctl restart hvv-anzeiger
```

`config.example.json` enthält eine vollständige Beispielkonfiguration. Wird ein
optionales Feld weggelassen, gilt der nachfolgend dokumentierte Code-Default.

### API

| Feld | Default | Bedeutung und Grenze |
|---|---:|---|
| `api.base_url` | Pflichtfeld | muss `https://gti.geofox.de/gti/public` verwenden |
| `api.version` | `63` | Geofox-GTI-API-Version |
| `api.refresh_seconds` | `15` | Aktualisierungsabstand; mindestens 15 Sekunden |
| `api.request_timeout_seconds` | `8` | HTTP-Zeitlimit in Sekunden; größer als 0 |
| `api.max_departures` | `5` | sichtbare Abfahrten; 1 bis 5 |
| `api.max_time_offset_minutes` | `90` | betrachteter Zeitraum ab jetzt; größer als 0 |
| `api.max_stale_age_minutes` | `5` | maximale Anzeigezeit alter Abfahrtszeilen bei einem Fehler |

Die Anwendung akzeptiert für `api.base_url` ausschließlich HTTPS und den
offiziellen Host `gti.geofox.de`.

### Display

| Feld | Default | Bedeutung und Grenze |
|---|---:|---|
| `display.spi_port` | `0` | SPI-Port |
| `display.spi_device` | `0` | SPI-Gerät beziehungsweise Chip-Select |
| `display.gpio_dc` | `24` | GPIO-Nummer für Data/Command |
| `display.gpio_reset` | `25` | GPIO-Nummer für Reset |
| `display.rotate` | `0` | Drehung; erlaubt sind 0, 1, 2 oder 3 |
| `display.bus_speed_hz` | `16000000` | SPI-Takt; größer als 0 |
| `display.bgr` | `false` | auf `true` setzen, wenn Rot und Blau vertauscht sind |

Für ein um 180 Grad gedrehtes Display üblicherweise `display.rotate` auf `2`
setzen.

### Nachtmodus

| Feld | Default | Bedeutung und Grenze |
|---|---:|---|
| `night_shutdown.enabled` | `false` | aktiviert den Nachtmodus |
| `night_shutdown.start` | `"21:00"` | Beginn als lokale Hamburger Zeit im Format `HH:MM` |
| `night_shutdown.end` | `"06:30"` | Ende im Format `HH:MM`; muss vom Beginn abweichen |

Der Beginn ist eingeschlossen, das Ende ausgeschlossen. Zeiträume über
Mitternacht und Zeiträume innerhalb desselben Tages werden unterstützt.

Beispiel für die Aktivierung von 21:00 bis 06:30 Uhr:

```json
"night_shutdown": {
  "enabled": true,
  "start": "21:00",
  "end": "06:30"
}
```

Im Nachtfenster wird einmal ein schwarzes Bild geschrieben. Geofox-Abfragen
pausieren bis zum Ende des Fensters.

### Haltestellen und Verbindungen

| Feld | Default | Bedeutung und Grenze |
|---|---|---|
| `stations` | Pflichtfeld | mindestens eine Haltestelle |
| `stations[].name` | Pflichtfeld | Geofox-Haltestellenname |
| `stations[].city` | `"Hamburg"` | Stadt für die Haltestellensuche |
| `stations[].id` | kein Default | optionale eindeutige Geofox-ID |
| `stations[].label` | erster Buchstabe des Namens | eindeutiges sichtbares Kürzel mit 1 bis 3 Zeichen |
| `stations[].routes` | Pflichtfeld | mindestens eine erlaubte Linie-Ziel-Kombination |
| `stations[].routes[].line` | Pflichtfeld | Linienbezeichnung, zum Beispiel `"21"` |
| `stations[].routes[].destination` | Pflichtfeld | erwartetes Fahrtziel |

Beispiel:

```json
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
```

Fehlt `stations[].id`, sucht die Anwendung die Haltestelle bei Geofox und speichert
die gefundene ID unter `/opt/hvv-anzeiger/var/stations.json`. Bei mehreren
gleichnamigen Treffern muss die gewünschte ID ausdrücklich in `config.json`
eingetragen werden.

Linien und Ziele werden tolerant gegenüber Groß-/Kleinschreibung, Umlauten und
Schreibweisen wie `Straße` und `Strasse` verglichen. Ein zusätzliches
Verkehrsmittel-Präfix im Geofox-Ziel, beispielsweise `S Elbgaustraße`, wird
ebenfalls berücksichtigt.

### WLAN-Schnittstelle

Der Dienst überwacht standardmäßig `wlan0`. Falls die WLAN-Schnittstelle anders
heißt:

```bash
sudo systemctl edit hvv-anzeiger
```

Folgenden Inhalt eintragen:

```ini
[Service]
Environment=HVV_WIFI_INTERFACE=DEINE_WLAN_SCHNITTSTELLE
```

Danach:

```bash
sudo systemctl daemon-reload
sudo systemctl restart hvv-anzeiger
```

## Verhalten bei Störungen

| Situation | Verhalten auf dem Display | Automatische Reaktion |
|---|---|---|
| WLAN getrennt | `KEIN WLAN`; letzter Datenstand bleibt sichtbar | neue Abfrage nach Wiederverbindung |
| Geofox vorübergehend nicht erreichbar | `DATEN VERALTET`; letzter Datenstand bleibt sichtbar | wachsender Abstand bis maximal fünf Minuten |
| alte Daten älter als `api.max_stale_age_minutes` | alte Buszeilen verschwinden; Fehlerstatus bleibt | weitere Abrufversuche |
| Geofox-Anfragelimit erreicht | Fehlerstatus | `Retry-After` wird bis maximal eine Stunde respektiert |
| Systemzeit noch nicht synchron | `ZEIT NICHT SYNCHRON` | keine Geofox-Abfrage bis zur Synchronisierung |
| Prozess abgestürzt oder länger als 90 Sekunden blockiert | Anzeige bleibt kurz auf letztem Bild | systemd startet den Dienst neu |
| Nachtmodus aktiv | schwarzes Bild | keine Geofox-Abfrage bis zum Ende des Nachtfensters |

## Betrieb und Wartung

### Dienst steuern

```bash
systemctl status hvv-anzeiger
sudo systemctl restart hvv-anzeiger
sudo systemctl stop hvv-anzeiger
sudo systemctl start hvv-anzeiger
```

### Protokoll ansehen

```bash
journalctl -u hvv-anzeiger -n 100 --no-pager
journalctl -u hvv-anzeiger -f
```

Das Systemjournal wird wöchentlich rotiert. Archivierte Einträge über sieben Tage
werden entfernt und archivierte Journale auf insgesamt 100 MiB begrenzt. Diese
Bereinigung betrifft das gesamte systemd-Journal des Raspberry Pi, nicht nur den
HVV-Anzeiger.

Status der Bereinigung:

```bash
systemctl status hvv-anzeiger-log-cleanup.timer
journalctl --disk-usage
```

### Zugangsdaten ändern

```bash
cd /opt/hvv-anzeiger
./configure-credentials.sh --force
sudo systemctl restart hvv-anzeiger
```

Die Zugangsdaten liegen unter `/etc/hvv-anzeiger.env`, gehören `root:root` und
haben die Dateirechte `0600`.

### Anwendung aktualisieren

Wenn auf GitHub eine neue Version verfügbar ist, per SSH am Raspberry Pi
anmelden und in das ursprünglich geklonte Repository wechseln. Der Ordner heißt
normalerweise `hvv-anzeiger`:

```bash
cd ~/hvv-anzeiger
git pull --ff-only origin main
./install.sh
```

Der Installer aktualisiert die Anwendung unter `/opt/hvv-anzeiger` und startet
den Dienst neu. Danach den Status und die Installation prüfen:

```bash
systemctl status hvv-anzeiger --no-pager
cd /opt/hvv-anzeiger
./diagnose.sh
```

Ein Neustart des Raspberry Pi ist bei einem normalen Anwendungsupdate nicht
erforderlich. Er ist nur nötig, wenn der Installer darauf hinweist oder zugleich
Betriebssystem-, Kernel- oder SPI-Einstellungen geändert wurden.

Vorhandene `config.json` und vollständige Geofox-Zugangsdaten bleiben erhalten.
Neue Defaults aus dem Repository verändern deshalb keine vorhandene
Konfiguration. Kann `git pull` wegen eigener lokaler Änderungen nicht ausgeführt
werden, diese Änderungen nicht ungeprüft überschreiben, sondern zuerst sichern
oder in Git committen.

Falls das ursprünglich geklonte Repository nicht mehr existiert, kann es erneut
heruntergeladen werden. Die bestehende Installation und Konfiguration werden
trotzdem übernommen:

```bash
cd ~
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
./install.sh
```

Schlägt die Prüfung oder der Start der neuen Version fehl, stellt der Installer
automatisch die vorherige funktionsfähige Installation wieder her.

### Vorschau ohne Display erzeugen

```bash
cd /opt/hvv-anzeiger
.venv/bin/python -m hvv_display.preview preview.png
```

Mit Geofox-Daten, aber weiterhin als PNG:

```bash
cd /opt/hvv-anzeiger
set -a
. /etc/hvv-anzeiger.env
set +a
.venv/bin/python -m hvv_display \
  --config config.json --once --output preview.png
```

## Sicherheit und Datenschutz

- Die Anwendung stellt keinen eingehenden Netzwerkdienst bereit.
- Ausgehende API-Kommunikation ist auf HTTPS zu `gti.geofox.de` beschränkt.
- Geofox-Zugangsdaten stehen weder im Repository noch in Prozessargumenten.
- Der Dienst läuft als nicht interaktiver Benutzer `hvv-anzeiger`.
- Programm, virtuelle Python-Umgebung und Konfiguration sind für den Dienst
  schreibgeschützt.
- Nur `/opt/hvv-anzeiger/var` ist für Laufzeitdaten beschreibbar.
- Geofox-Antworten sind auf 1 MiB begrenzt.
- Python-Abhängigkeiten sind mit Versionen und SHA-256-Prüfsummen festgelegt.
- GitHub Actions prüft Abhängigkeiten auf bekannte Schwachstellen.

## Grenzen

- Ein Geofox-Zugang ist erforderlich; es gibt keinen öffentlichen
  Zugangsdaten-freien Fallback.
- Ohne synchronisierte Systemzeit werden keine Abfahrten abgerufen.
- Die maximale Zahl sichtbarer Abfahrten ist wegen der Displaygröße auf fünf
  begrenzt.
- Das Zielsetup ist ein ILI9341 mit 320 × 240 Pixeln im Querformat.
- Der Nachtmodus schaltet die Hintergrundbeleuchtung nicht elektrisch aus.
- Die erwartete Abfahrtszeit bleibt eine Prognose und kann sich bis zur Abfahrt
  ändern.
- Verbindliche Strom-, RAM- und CPU-Werte erfordern eine Messung am konkreten
  Raspberry Pi, Display und Netzteil.
- Display-Hardware und authentifizierte Geofox-Produktivantworten können in
  GitHub Actions nicht geprüft werden.

## Qualitätsprüfung

Bei jedem Push und Pull Request prüft GitHub Actions:

- Python 3.10, 3.11 und 3.13
- Unit- und Integrationstests mit 100 Prozent Coverage
- Code- und Security-Linting
- bekannte Schwachstellen in Laufzeitabhängigkeiten
- Shell-Skripte und systemd-Units
- vollständige Installation und Rollback in einer isolierten Ubuntu-Umgebung
- Paket-Build und Display-Vorschau

## Projekt unterstützen

Der HVV-Anzeiger bleibt frei verfügbar. Wer Entwicklung, Tests und Dokumentation
freiwillig unterstützen möchte, kann das hier tun:

[HVV-Anzeiger auf Ko-fi unterstützen](https://ko-fi.com/bema1991)

Eine Unterstützung ist vollständig freiwillig und hat keinen Einfluss auf
Geofox-Zugang, Funktionen oder Updates. Für jede Nutzung der Geofox-Daten haben
die erteilten Zugangs- und Nutzungsbedingungen Vorrang; ob eine öffentliche
Finanzierung oder Spendeneinbindung damit vereinbar ist, muss der Betreiber im
Zweifel vorab mit dem Schnittstellenanbieter klären.
