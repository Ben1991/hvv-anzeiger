# Home Assistant und der HVV-Anzeiger

Diese Anleitung richtet den Python-Hintergrunddienst und die HA-Paketintegration
ein. Sie deckt keine ESP32-Hardware, Firmware-Builds oder USB-
Flashvorgänge ab. Dafür gibt es die separate
[ESP32-Einrichtungsanleitung](esp32-setup.md).

Der Hintergrunddienst bleibt die Quelle für Geofox-Abfragen, Haltestellen-
auflösung, Linien-/Richtungsfilter und Konfiguration. Er kann auf einem
Raspberry Pi oder einem Linux-/NAS-Containerhost laufen. Home Assistant bindet
seine HTTPS-API ein; ein physisches Pi-Display oder der Pi-Anzeigedienst ist
für Home Assistant und ESP32 nicht erforderlich.

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
Für die Displaydiagnose zusätzlich `hvv_health_url` auf
`https://<Hostname>:8080/api/diagnostics` setzen; auch bei einem Update beide
URL-Secrets und das vorhandene Webpasswort übernehmen.
TLS-Prüfung eingeschaltet lassen; bei eigener CA deren Vertrauenskette auf dem
HA-System einrichten. Konfiguration prüfen und HA neu starten.

Erwartete Entität: `sensor.hvv_board`, Zustand `ok`, `stale`, `expired`,
`unavailable` oder `night`. Bei Namenskollision den tatsächlich vergebenen
Entity-Namen in den Vorlagen, Recorder-Ausschlüssen und ESPHome-Substitutionen
anpassen. Abfahrten und `display_payload` sind Attribute, weil ein HA-Zustand
auf 255 Zeichen begrenzt ist. Der vollständige Datensatz wird nicht im Recorder
gespeichert. `home-assistant/dashboard.yaml` ist eine optionale Dashboardkarte.

Das Paket ergänzt `sensor.hvv_diagnostics`, `sensor.hvv_display_error` und
`binary_sensor.hvv_display_problem`. Der Fehlersensor meldet `initialization`,
`reset` und `transfer` für erkannte Treiberfehler, `service_unavailable` für
einen gestoppten Dienst beziehungsweise ausgebliebene Lebenszeichen und `none`
bei erfolgreicher Bildausgabe. Attribute enthalten Fehler- und
Wiederherstellungszähler sowie letzte Fehlerart und UTC-Zeitpunkte. Nach
erfolgreicher Wiederherstellung geht der Problemsensor aus; historische Fehler
bleiben in den Attributen, bis der Pi-Anzeigedienst neu startet. Vorsorgliche
Resets erhöhen die Wiederherstellungs-, aber keine Fehlerzähler.

Die unabhängige REST-Diagnose benötigt keinen Geofox-Zugang und fragt nur den
lokalen Dienststatus ab. `/api/diagnostics` liefert auch bei Gerätefehlern HTTP
200, damit Home Assistant die Fehlerattribute auswerten kann. Authentifizierung,
TLS-Prüfung und Rate-Limit gelten wie für `/api/health`; dessen HTTP-Codes bleiben
unverändert. Fehlt die Diagnose, ist der Webdienst nicht erreichbar, läuft nur
ein Image-Backend oder stammt der Dienststatus aus einer alten Version ohne
Displaydiagnose, werden die Display-Sensoren nicht als gesund ausgegeben.
Ein stilles Weißbild trotz erfolgreicher SPI-Schreibzugriffe ist nicht direkt
erkennbar. Die Sensoren beweisen weder elektrische Verbindung noch sichtbares
Bild. Siehe [Display-Wiederherstellung und Abnahme](display-recovery-validation.md).

Die REST-Abfrage läuft alle 15 Sekunden. Ihr Timeout ist 30 Sekunden: Ein
erster Abruf kann mehrere Geofox-Aufrufe zur Haltestellenauflösung benötigen.
Bei sehr vielen Haltestellen können ein größerer Timeout und ein passender
Abfrageabstand nötig sein. Der vorhandene Backend-Cache verhindert zusätzliche
Geofox-Abfragen durch mehrere Displays desselben Webdienstes.

## Updates für Hintergrunddienst und Home Assistant

Die Reihenfolge für HA: Hintergrunddienst aktualisieren, Paketdatei übernehmen,
HA-Konfiguration prüfen und Home Assistant neu starten. `secrets.yaml`, die
REST-Entität und eigene Entity-Namen erhalten.

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

### Home-Assistant-Paket aktualisieren

Neue Versionen von `home-assistant/hvv.yaml` mit der eigenen Paketdatei vergleichen,
eigene Entity-Namen und Einstellungen beibehalten und nur die benötigte Paketdatei
übernehmen. HA-Konfiguration prüfen und Home Assistant neu starten. Die
`secrets.yaml` nicht durch die Beispieldatei ersetzen.

Das ESPHome-Gerät selbst wird separat aktualisiert. Vorgehen und Prüfung stehen
unter [ESP32-Firmware aktualisieren](esp32-setup.md#firmware-aktualisieren).
