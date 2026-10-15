# Home Assistant und ESP32 mit ESPHome

Der HVV-Anzeiger kann zusätzlich zur Raspberry-Pi-Anzeige in Home Assistant
und auf ESP32-Displays laufen. Die Geofox-Abfragen, Haltestellenauflösung,
Linien-/Richtungsfilter und Einstellungen bleiben im vorhandenen Python-Dienst.
ESPHome übernimmt WLAN, Anzeige, native HA-Verbindung und verschlüsselte
Firmwareupdates. Geofox-Zugangsdaten müssen nicht auf den ESP32.

## Aufbau und Funktionsumfang

```text
Geofox -> hvv-web -> HTTPS -> Home Assistant REST-Sensor
                               -> verschlüsselte ESPHome-API -> ESP32-Display

Optional: hvv-web -> HTTPS -> ESP32 (unabhängig von HA)
```

Ein vorhandener Raspberry Pi kann den Hintergrunddienst weiter bereitstellen.
Alternativ läuft dieser auf einem Linux-Rechner/NAS als Container; ein physisches
Pi-Display ist dafür nicht notwendig. Mehrere ESP32 und HA teilen sich denselben
Web-Cache. Der separate Pi-Anzeigedienst hat weiterhin seinen eigenen Abrufzyklus;
für einen reinen ESP32-Betrieb muss er nicht gestartet werden.

| Funktion | Umsetzung |
|---|---|
| Haltestellen, Linien, Verkehrsmittel, Richtung/Ziel, Labels | bestehende config.json und Webeinstellungen |
| Erwartete Abfahrt inklusive Verspätung, Ausfälle | gemeinsame Geofox-Logik; `AUS` und Verspätung auf ESP32 |
| Countdown / Uhrzeit; `min`, `m`, ohne Einheit; `sofort` | ESP32 zählt sekündlich anhand der erwarteten Abfahrt weiter |
| Gemeinsame Sortierung und bis zu fünf Abfahrten | bestehender Datenabruf, Anzeige begrenzt auf fünf Zeilen |
| Unterschiedliche Displaygrößen | dynamische Zeilenhöhe; kleine Displays zeigen weniger Zeilen |
| Linienfarben und Formen | gleicher Stil-Katalog; ESP32 nutzt einfache geometrische Formen |
| Fehlende Verbindung, alte Daten, API-Backoff, Rate-Limits | Cache/Backoff im Hintergrunddienst, Ablaufkontrolle zusätzlich im ESP32 |
| Nachtabschaltung | Smart-Home-Endpunkte pausieren Geofox-Abrufe; ESP32 schwarz und Backlight aus |
| Webkonfiguration, Backups, Diagnose, Pi-Treiber | bestehende Funktionen bleiben verfügbar |
| Helligkeit, Anzeigeschalter, Neustart, WLAN/Laufzeit | ESPHome-Entitäten in Home Assistant |

Die bestehenden Web-Abfahrtsseiten können weiterhin auf Benutzeranforderung
Daten abrufen, auch während der Nachtpause des Smart-Home-Endpunkts.
CPU-/SD-Diagnose und Systemneustart im Web betreffen den Hintergrundrechner;
der separate ESPHome-Neustartknopf betrifft den ESP32.
Touchbedienung und beliebige RGB-/E-Paper-Panels sind nicht automatisch eingerichtet.
Die ESP32-Layouts sind funktional ähnlich, aber keine pixelidentische Kopie des Pi-Bilds.

## 1. Hintergrunddienst bereitstellen

### Vorhandener Raspberry Pi

Bei einer neuen Pi-Installation zuerst die
[Pi-Installationsanleitung](../README.md#installieren) ausführen.
Eine vorhandene Installation im ursprünglichen Repository aktualisieren:

```sh
cd ~/hvv-anzeiger
./update.sh
```

Danach den vorhandenen HTTPS-Webdienst nutzen. Die Details zu Prüfung,
Datenerhalt und Rollback stehen unter [Pi-Updates](../README.md#anwendung-aktualisieren).
Die Anleitung im README zu `configure-web.sh`, individuellem Webpasswort und
TLS gilt weiter. Keine zusätzliche Geofox-Anmeldung oder Datenkopie erforderlich.
Home Assistant muss den Zertifikatsnamen auflösen und der ausstellenden CA vertrauen.
Das gilt auch für eine selbst betriebene Zertifizierungsstelle.
Für HA OS ist ein Zertifikat einer bereits vertrauten CA für eine eigene Domain
mit lokaler DNS-Auflösung der unkomplizierteste Weg. Ein vorhandenes selbst
signiertes Pi-Zertifikat wird vom REST-Sensor nicht automatisch akzeptiert.

Wenn ausschließlich ESP32-Displays verwendet werden, kann der Pi-Anzeigedienst
nach erfolgreicher Webeinrichtung deaktiviert werden:

```sh
sudo systemctl disable --now hvv-anzeiger
```

`hvv-anzeiger-web` muss weiterlaufen. Die Pi-Diagnose meldet den abgeschalteten
Hardware-Anzeigedienst dann als nicht verfügbar; für den ESP32-Betrieb stattdessen
den Zustand von `sensor.hvv_board` beziehungsweise `/api/smart-home` prüfen.
Ein späteres Pi-Update aktiviert den Anzeigedienst wieder; bei reinem ESP32-Betrieb
anschließend erneut deaktivieren.

### Container auf Linux/NAS

Docker Engine und Docker Compose v2 verwenden. Das Webpasswort wird direkt im
Container aus `/data/web.env` gelesen. Compose benötigt keinen Lesezugriff auf
die privaten Dateien und wertet die `$`-Zeichen im Passwort-Hash nicht aus.

Repository auf dem Containerhost klonen und die Daten vorbereiten:

```sh
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
mkdir -p data
chmod 0700 data
cp config.example.json data/config.json
docker compose build
```

Im Repository `data/` anlegen und dort ablegen:

- `config.json`: Kopie von `config.example.json`, eigene Haltestellen eintragen.
- `credentials.env`: `GEOFOX_USER=...` und `GEOFOX_PASSWORD=...`, jeweils eigene Zeile.
- `web.env`: `HVV_WEB_PASSWORD_HASH=...` (kein Klartext-Webpasswort).
- `tls.crt` und `tls.key`: Zertifikatskette und privater Schlüssel für den Hostnamen.

Zertifikat, Schlüssel und `credentials.env` vor dem Start ablegen und die
Haltestellen in `data/config.json` anpassen. Der folgende Befehl erzeugt den
Passwort-Hash im gebauten Image, fragt das individuelle Passwort zweimal ab und
speichert es geschützt in `data/web.env`. Python-Abhängigkeiten auf dem Host
sind dafür nicht nötig. Den Befehl bei der Ersteinrichtung vor dem unten
beschriebenen Eigentümerwechsel ausführen:

```sh
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" hvv python -c '
from getpass import getpass
from pathlib import Path
from hvv_display.web import WebApplication
password = getpass("Webpasswort (mindestens 12 Zeichen): ")
if len(password) < 12:
    raise SystemExit("Mindestens 12 Zeichen erforderlich")
if password != getpass("Webpasswort wiederholen: "):
    raise SystemExit("Passwörter stimmen nicht überein")
app = WebApplication(Path("/data/config.json"), Path("/data/credentials.env"),
                     Path("/data/stations.json"))
app.save_web_password(password)
'
```

Das Webpasswort separat für Home Assistants `secrets.yaml` aufbewahren.
Der Container läuft als UID/GID 10001;
auf Linux müssen `data/` und die Dateien für diese UID les-/schreibbar sein,
weil Konfiguration, Zugangsdaten und Webpasswort über die Weboberfläche geändert
werden können. Verzeichnisrechte 0700, Dateirechte 0600 und passender Eigentümer
sind geeignet. Den privaten Schlüssel nicht öffentlich lesbar machen.

Für einen normalen Linux-Dockerhost ohne Benutzer-Namespace-Umschreibung:

```sh
sudo chown -R 10001:10001 data
sudo chmod 0700 data
sudo chmod 0600 data/config.json data/credentials.env data/web.env data/tls.crt data/tls.key
```

Bei Rootless Docker oder User-Namespace-Remapping den auf dem Host zugeordneten
Benutzer verwenden; die numerische Host-UID kann dort abweichen.

```sh
docker compose up -d --build
docker compose logs --tail=50
```

Der Dienst verweigert einen LAN-Start ohne individuellen Passwort-Hash und TLS.
Kein privilegierter Container, GPIO oder SPI erforderlich. HTTPS-Weboberfläche
unter `https://<Zertifikats-Hostname>:8080/` prüfen.
Dies ist ein eigenständiger Backend-Container, kein Supervisor-Add-on.
Auf Home Assistant OS den bestehenden Pi oder einen separaten Containerhost nutzen.
Der Systemneustart-Knopf der Pi-Weboberfläche startet keinen Containerhost neu;
Container werden mit Docker Compose verwaltet.

## 2. Home Assistant einrichten

In `configuration.yaml` Pakete aktivieren, bestehende `homeassistant:`-Einträge
dabei zusammenführen:

```yaml
homeassistant:
  packages: !include_dir_named packages
```

`home-assistant/hvv.yaml` nach `/config/packages/hvv.yaml` kopieren.
Die Werte aus `home-assistant/secrets.example.yaml` in `/config/secrets.yaml`
übernehmen und ersetzen. `hvv_smart_home_url` muss auf
`https://<Hostname>:8080/api/smart-home` zeigen. Benutzername ist `hvv-anzeiger`.
TLS-Prüfung eingeschaltet lassen; bei eigener CA deren Vertrauenskette auf dem
HA-System einrichten. Konfiguration prüfen und HA neu starten.

Erwartete Entität: `sensor.hvv_board`, Zustand `ok`, `stale`, `expired`,
`unavailable` oder `night`. Bei Namenskollision den tatsächlich vergebenen
Entity-Namen in den Vorlagen, Recorder-Ausschlüssen und ESPHome-Substitutionen
anpassen. Abfahrten und `display_payload` sind Attribute, weil ein HA-Zustand
auf 255 Zeichen begrenzt ist. Der vollständige Datensatz wird nicht im Recorder
gespeichert. `home-assistant/dashboard.yaml` ist eine optionale Dashboardkarte.

Die REST-Abfrage läuft alle 15 Sekunden. Ihr Timeout ist 30 Sekunden: Ein
erster Abruf kann mehrere Geofox-Aufrufe zur Haltestellenauflösung benötigen.
Bei sehr vielen Haltestellen können ein größerer Timeout und ein passender
Abfrageabstand nötig sein. Der vorhandene Backend-Cache verhindert zusätzliche
Geofox-Abfragen durch mehrere Displays desselben Webdienstes.

## 3. ESPHome flashen

Amazon-Suchlinks für ESP32 DevKit, CYD, ESP32-S3, passende SPI-Displays und
Zubehör stehen im [Hardware-Einkauf des README](../README.md#esp32-displays-und-zubehör).
Alle dortigen Amazon-Links sind als Affiliate-Links gekennzeichnet.

ESPHome **2026.9.1 oder neuer** verwenden. Zwei Einrichtungswege sind möglich:

- **ESPHome Device Builder in Home Assistant:** Den Inhalt des Repository-Ordners
  `esphome/` in den ESPHome-Konfigurationsordner kopieren, einschließlich
  `hvv_board.h`, `boards/` und `packages/`. Der Header muss neben den Haupt-YAMLs
  liegen. Das passende Profil in der Oberfläche wählen, prüfen und per USB
  installieren. `secrets.example.yaml` als eigene `secrets.yaml` übernehmen;
  vorhandene Geheimnisse zusammenführen und keine bestehende Datei überschreiben.
- **Kommandozeile:** Python 3.12 und eine eigene virtuelle Umgebung verwenden.
  Die folgenden Befehle im geklonten Repository ausführen:

```sh
python3.12 -m venv .venv-esphome
. .venv-esphome/bin/activate
python -m pip install esphome==2026.9.1
cp esphome/secrets.example.yaml esphome/secrets.yaml
cp esphome/hvv-display.yaml esphome/hvv-display.local.yaml
```

Unter Windows die virtuelle Umgebung mit `py -3.12 -m venv .venv-esphome`
erstellen und mit `.venv-esphome\Scripts\Activate.ps1` in PowerShell aktivieren;
Dateien mit `Copy-Item` statt `cp` kopieren. Wer CYD, S3 oder direkten HTTPS-Abruf
nutzt, kopiert das jeweilige Profil statt `hvv-display.yaml` in eine eigene
`*.local.yaml`. Diese lokalen Profile und `secrets.yaml` bleiben außerhalb von Git.
WLAN, Gerätename, API-Schlüssel und nötige Pin-Anpassungen in diesen eigenen
Dateien eintragen, gemeinsame `boards/`- und `packages/`-Dateien unverändert lassen.
Für jeden ESP32 einen eigenen API-Schlüssel erzeugen:

```sh
python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

| Datei | Referenzhardware / Anpassung |
|---|---|
| `hvv-display.yaml` | ESP32 DevKit + externes ILI9341, 320×240 quer |
| `hvv-cyd.yaml` | CYD ESP32-2432S028, Original mit Micro-USB / ILI9341 |
| `hvv-s3-ili9488.yaml` | ESP32-S3 DevKit + externes ILI9488, 480×320 quer |
| `hvv-direct.yaml` | ESP32 DevKit + ILI9341 mit direktem HTTPS-Abruf |

Die CYD-Varianten mit zwei USB-Anschlüssen brauchen je nach Controller
`display_model: ESP32-2432S028-7789` oder `ESP32-2432S028-9342`.
Beim ILI9342 gegebenenfalls `display_rotation: '0'` unter `substitutions`
in der eigenen Haupt-YAML setzen.
Ein ähnlicher Produktname garantiert keine identische Pinbelegung.

Für den generischen ESP32 gelten folgende GPIOs; die Pins stehen als
Substitutionen im Hardwareprofil und können in der Hauptdatei überschrieben werden:

| Signal | ESP32 DevKit | ESP32-S3-Referenz |
|---|---:|---:|
| SCK | 18 | 12 |
| MOSI | 23 | 11 |
| CS | 21 | 10 |
| DC | 27 | 9 |
| RESET | 33 | 8 |
| Backlight PWM | 32 | 7 |

Gemeinsame Masse und 3,3-V-Logik verwenden. Die Versorgungsspannung richtet sich
nach dem Displaymodul; dessen Datenblatt prüfen. Eine nackte LED-Hinterleuchtung
nicht direkt mit einem GPIO versorgen: nur einen geeigneten BL-Steuereingang
oder eine passende Transistorstufe verwenden. Ein Pi-HAT mit Spezialadapter
ist nicht automatisch direkt mit diesen Pins kompatibel. MISO ist für diese
Anzeige nicht erforderlich.

Andere SPI-Controller wie ST7789V/ST7796 sind über `display_model`, Rotation,
Pins und gegebenenfalls `dimensions` im Hardwareprofil anpassbar. Andere
ESP32-Familien benötigen das passende `esp32.board` und gültige GPIOs.
Der Renderer verwendet ESPHomes allgemeine Display-Schnittstelle; für RGB,
QSPI oder andere Treiber ein eigenes `boards/`-Profil mit denselben IDs
`hvv_screen` und `hvv_backlight` erstellen. Mindestens 240×135 rechteckige Pixel
sind für das vorhandene Layout sinnvoll; für kleinere/runde Displays ist ein
eigenes Layout nötig.

```sh
esphome config esphome/hvv-display.local.yaml
esphome compile esphome/hvv-display.local.yaml
esphome run esphome/hvv-display.local.yaml
```

Unter Windows einen kurzen **physischen** Werkzeugpfad vor dem ersten Build
setzen, etwa `$env:ESPHOME_ESP_IDF_PREFIX = 'C:\ei'` in PowerShell.
Lange Cachepfade können beim ESP-IDF-Compiler zu fehlenden Headern führen;
eine Verknüpfung auf einen langen Pfad hilft nicht, da ESPHome sie auflöst.

Das erste Flashen per USB durchführen, danach sind verschlüsselte OTA-Updates
möglich. Den ESP32 in HA unter Einstellungen → Geräte & Dienste → ESPHome
hinzufügen und den individuellen API-Schlüssel angeben. `board_entity` muss
der REST-Entität entsprechen. Die HA-Textsensor-Komponente braucht diese
Registrierung, damit HA das Attribut übermittelt.
Roboto wird beim Firmwarebau von Google Fonts heruntergeladen; das Gerät
benötigt dafür im Betrieb keinen Zugriff.

## Updates für ESPHome, Home Assistant und Container

### Reihenfolge und Datenerhalt

Zuerst den Python-Hintergrunddienst aktualisieren, danach gegebenenfalls das
HA-Paket und zuletzt die ESP32-Firmware. Vorher Konfiguration über die
Weboberfläche exportieren und eigene ESPHome-Profile, `secrets.yaml` sowie
CA-Zertifikate separat sichern. Ein redigierter Konfigurationsexport enthält
keine Zugangsdaten. API-Schlüssel, Gerätenamen und HA-Entity-IDs bei einem normalen
Update beibehalten; ein neuer Schlüssel erfordert eine Anpassung der HA-Kopplung.

### Python-Hintergrunddienst auf dem Pi

Im ursprünglichen Repository `./update.sh` ausführen, nicht im installierten
Verzeichnis `/opt/hvv-anzeiger` und nicht mit `sudo`. Das Skript verlangt einen
sauberen `main`-Checkout, aktualisiert ausschließlich per Fast-Forward und
installiert die neue Version mit Erhalt von Konfiguration und Zugangsdaten.
Der Installer prüft die neue Installation und stellt bei Fehlern den vorherigen
Stand wieder her. Danach `./diagnose.sh` unter `/opt/hvv-anzeiger` und die
HTTPS-Weboberfläche prüfen. Alle Befehle stehen in der
[Pi-Updateanleitung](../README.md#anwendung-aktualisieren).

### Python-Hintergrunddienst im Container

Im ursprünglichen Repository auf dem Containerhost:

```sh
git status --short
git pull --ff-only origin main
docker compose build
docker compose up -d
docker compose logs --tail=50
```

Eigene Änderungen vor `git pull` sichern oder committen; keine erzwungene
Rücksetzung verwenden. `data/` bleibt als eingebundenes Verzeichnis erhalten,
einschließlich Konfiguration, Geofox-Zugangsdaten, Passwort-Hash und TLS-Dateien.
`docker compose up -d` ersetzt den Dienst durch das neu gebaute Image.
Die Ersteinrichtung des Passworts nicht erneut ausführen. Anschließend
HTTPS-Weboberfläche und `sensor.hvv_board` beziehungsweise `/api/smart-home` prüfen.
Ein Image-Buildfehler lässt den bisherigen Container weiterlaufen; ein
automatischer Rollback nach einem fehlgeschlagenen Containerstart ist nicht eingerichtet.

### Home-Assistant-Paket und ESPHome Device Builder

Neue Versionen von `home-assistant/hvv.yaml` mit der eigenen Paketdatei vergleichen,
eigene Entity-Namen und Einstellungen beibehalten und die geänderte Paketdatei
übernehmen. HA-Konfiguration prüfen und HA neu starten; `secrets.yaml` erhalten.

Im Device Builder `hvv_board.h`, `boards/` und `packages/` aus dem aktualisierten
Repository übernehmen. Eigene Haupt-YAML, `secrets.yaml`, Gerätename, GPIOs und
API-Schlüssel erhalten. Versionshinweise auf Änderungen am Beispielprofil prüfen.
Das Profil validieren und über **Installieren → Drahtlos** neu bauen und übertragen.
Falls der Builder die benötigte ESPHome-Version noch nicht unterstützt, zuerst
den Builder aktualisieren. Bei nicht erreichbarem Gerät per USB flashen.

### ESPHome über die Kommandozeile

Im Repository mit dem eigenen `*.local.yaml` und den separat gesicherten Geheimnissen:

```sh
git status --short
git pull --ff-only origin main
. .venv-esphome/bin/activate
python -m pip install esphome==2026.9.1
esphome config esphome/hvv-display.local.yaml
esphome compile esphome/hvv-display.local.yaml
esphome upload esphome/hvv-display.local.yaml --device hvv-display.local
esphome logs esphome/hvv-display.local.yaml --device hvv-display.local
```

Dateiname und `--device` an das gewählte Profil sowie den eigenen Gerätenamen
anpassen; eine IP-Adresse ist ebenfalls möglich. Unter Windows wie bei der
Ersteinrichtung per PowerShell aktivieren. Die ESPHome-Version hier ist die
für diesen Stand geprüfte Version; bei späteren Projektversionen deren
Versionsvorgabe beachten. `secrets.yaml` niemals aus der Beispieldatei neu kopieren.
Für einen USB-Upload stattdessen den angebotenen seriellen Anschluss wählen.
Logausgabe mit Strg+C beenden; der ESP32 läuft weiter.

### Nach jedem Update prüfen

1. HA-Status `ok` oder bei aktivem Nachtfenster `night`, keine Authentifizierungsfehler.
2. Auf dem Display die eigenen Linien, Ziele und Labels sowie aktuelle Abfahrtszeiten.
3. Helligkeit, Anzeigeschalter und Rückkehr aus dem Nachtmodus.
4. Bei Verbindungsausfall Warnung und Ablauf alter Daten; nach Wiederverbindung
   erneute Aktualisierung. Das ist ein Test am realen Aufbau und wird durch
   einen erfolgreichen Compilerlauf nicht ersetzt.

## Optional: direkt per HTTPS

`hvv-direct.yaml` benötigt kein laufendes HA für die Abfahrtsanzeige, aber
weiterhin den Python-Hintergrunddienst. In `secrets.yaml` `backend_url` auf
`https://<Hostname>:8080/api/esphome` und `backend_authorization` auf
`Basic <Base64 von hvv-anzeiger:Webpasswort>` setzen. Base64 ist keine
Verschlüsselung; diese Zugangsdaten nur über HTTPS übertragen.
Bei eigener CA `ca_certificate_path: backend-ca.pem` in der `http_request:`-
Konfiguration ergänzen und das CA-Zertifikat neben die Haupt-YAML kopieren.
Weiterhin `verify_ssl: true` und `follow_redirects: false` verwenden.
SNTP synchronisiert hier die Gerätezeit. Die ESPHome-API bleibt für
Diagnose, Helligkeit und Updates verfügbar. Genau einen Transport einbinden.

## Fehlerverhalten und Prüfung

Der ESP32 nimmt nur Schema 1, höchstens fünf Zeilen und maximal 8 KiB JSON an.
Zeilen werden gemeinsam übernommen; unvollständige oder wiederholte Snapshots
verlängern die Gültigkeit nicht. Bei älteren API-Daten sinkt die verbleibende
Gültigkeitsfrist trotz erfolgreicher HTTPS-Abfrage weiter. Nach deren Ablauf
verschwinden die Zeilen. Eine einzelne Freigabe ist auf 24 Stunden begrenzt;
normal ist `api.max_stale_age_minutes` (standardmäßig fünf Minuten).
Nach 45 Sekunden ohne neuen Snapshot erscheint ein Verbindungswarnhinweis.
Systemzeit und Daten werden nach einem Neustart neu bezogen; ohne gültige
Systemzeit erscheinen keine Abfahrten. Bei einem Neustart werden keine alten
Snapshots aus dem Flash geladen.

Nacht-Snapshots gelten 60 Sekunden. Bei Verbindungsausfall während der Nacht
wechselt das Gerät danach zu einer sichtbaren Fehlermeldung. Damit bleibt ein
ausgefallener Datenweg nicht unbemerkt hinter einer dauerhaft schwarzen Anzeige.
Ein ausgeschalteter Anzeigeschalter bleibt davon unabhängig ausgeschaltet.

Vor dem produktiven Einsatz am konkreten Gerät prüfen:

1. Farben, Rotation, Text, alle fünf Zeilen und Helligkeitssteuerung.
2. HA/Backend/WLAN getrennt unterbrechen: Warnung, Ablauf, Wiederverbindung.
3. Neustart von ESP32 und HA: keine Wiederverwendung abgelaufener Daten.
4. Zeitdarstellung, Stationslabels, reale Verspätung und `AUS`.
5. Nachtbeginn/-ende und Rückkehr nach einer Nacht ohne Verbindung.

Automatische Prüfungen: Python-Regressionen, HTTP-Authentifizierung und
Protokolltests sowie ESPHome-Konfigurationsprüfung und Firmwarebau in CI.
Diese ersetzen keinen Flash- und Sichttest des tatsächlich verwendeten Displays.
Die tatsächlich ausgeführten Checks und ihre Grenzen stehen im
[Prüfprotokoll](home-assistant-esphome-validation.md).

Offizielle Referenzen: [Compose env_file](https://docs.docker.com/reference/compose-file/services/#env_file),
[HA REST-Sensor](https://www.home-assistant.io/integrations/sensor.rest/),
[ESPHome HA-Textsensor](https://esphome.io/components/text_sensor/homeassistant/),
[MIPI-SPI-Displaytreiber](https://esphome.io/components/display/mipi_spi/),
[HTTP Request](https://esphome.io/components/http_request/).
