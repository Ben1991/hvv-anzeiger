# Raspberry-Pi-Backend und optionale Home-Assistant-Integration

Diese Anleitung beschreibt ausschließlich das eigenständige Raspberry-Pi-
System mit Python-Backend und optionalem ILI-Display sowie dessen optionale
Home-Assistant-Anbindung. Der Pi-Dienst kann auch als Linux-/NAS-Container
ohne Display laufen. Die native Home-Assistant-Integration findet diesen
Pi-Dienst per mDNS und liest seine HTTPS-API nach Anmeldung.

Das ESP32+CYD-System ist davon unabhängig: seine Firmware fragt Geofox selbst
ab und kann direkt am CYD anzeigen. Home Assistant erkennt das CYD über die
integrierte ESPHome-API. Für diesen Betrieb werden weder Pi-Dienst noch diese
benutzerdefinierte HA-Integration benötigt. Setup, Haltestellenänderung und
Flashen stehen unter [ESP32/CYD](esp32-setup.md) und
[CYD-Haltestellen ändern](esp32-stations.md).

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
Verwende das individuelle Webpasswort, das du beim Pi-Setup festgelegt hast.
Der Pi liefert die Abfahrten mit dem bereits eingerichteten Geofox-Zugang.
Home Assistant muss den Zertifikatsnamen auflösen und der ausstellenden CA vertrauen.
Das gilt auch für eine selbst betriebene Zertifizierungsstelle.
Für HA OS ist ein Zertifikat einer bereits vertrauten CA für eine eigene Domain
mit lokaler DNS-Auflösung der unkomplizierteste Weg. Ein vorhandenes selbst
signiertes Pi-Zertifikat wird vom REST-Sensor nicht automatisch akzeptiert.

Bei einem eigenständigen CYD folge dem [ESP32-Weg in der README](../README.md#home-assistant-mit-esp32).

### Container auf Linux/NAS

Docker Engine und Docker Compose v2 verwenden. Das Webpasswort wird direkt im
Container aus `/data/web.env` gelesen. Compose benötigt keinen Lesezugriff auf
die privaten Dateien und wertet die `$`-Zeichen im Passwort-Hash nicht aus.
Für die automatische HA-Erkennung muss der Linux-Containerhost mDNS-Multicast
im selben LAN zulassen. Das CYD nutzt diesen Pi-Dienst nicht.

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
- `web.env`: initial gehashter Webzugang, Passwortwechsel-Flag und zufälliger
  CYD-Schlüssel (keine Klartext-Webpasswörter).
- `tls.crt` und `tls.key`: Zertifikatskette und privater Schlüssel für den Hostnamen.

Zertifikat, Schlüssel und `credentials.env` vor dem Start ablegen und die
Haltestellen in `data/config.json` anpassen. Der folgende Befehl erzeugt im
gebauten Image den Hash für das Erstpasswort `hvv-anzeiger`, markiert die
erzwungene Änderung beim ersten Login und generiert einen separaten zufälligen
CYD-Schlüssel. Python-Abhängigkeiten auf dem Host sind dafür nicht nötig. Den
Befehl bei der Ersteinrichtung vor dem unten beschriebenen Eigentümerwechsel
ausführen:

```sh
docker compose run --rm --no-deps --user "$(id -u):$(id -g)" hvv python -c '
from pathlib import Path
from secrets import token_urlsafe
from hvv_display.web import hash_web_password
path = Path("/data/web.env")
if path.exists():
    raise SystemExit("web.env existiert bereits; bestehende Zugangsdaten bleiben erhalten")
content = (
    "HVV_WEB_PASSWORD_HASH=\"" + hash_web_password("hvv-anzeiger") + "\"\n"
    + "HVV_WEB_PASSWORD_MUST_CHANGE=\"1\"\n"
    + "HVV_ESPHOME_API_TOKEN=\"" + token_urlsafe(32) + "\"\n"
)
path.write_text(content, encoding="utf-8")
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

Der Dienst verweigert einen LAN-Start ohne Passwort-Hash, TLS und separaten
CYD-Schlüssel.
Kein privilegierter Container, GPIO oder SPI erforderlich. HTTPS-Weboberfläche
unter `https://<Zertifikats-Hostname>:8080/` prüfen.
Dies ist ein eigenständiger Backend-Container, kein Supervisor-Add-on.
Auf Home Assistant OS den bestehenden Pi oder einen separaten Containerhost nutzen.
Der Systemneustart-Knopf der Pi-Weboberfläche startet keinen Containerhost neu;
Container werden mit Docker Compose verwaltet.

Für die automatische Home-Assistant-Erkennung muss der Container auf einem
Linux-Host im Host-Netzwerk laufen. Compose bindet HTTPS dann direkt an Port
8080 des Hosts; die bisherige Portfreigabe entfällt. Der Container teilt damit
den Netzwerk-Namensraum des Hosts. Firewall und Portbelegung auf dem Host
beachten. Home Assistant und Anzeiger müssen mDNS-Multicast (UDP 5353) im selben
LAN erreichen können.

Wenn das TLS-Zertifikat einen DNS-Namen statt eines `.local`-Namens enthält,
in einer `.env` neben `compose.yaml` den Zertifikatsnamen eintragen:

```dotenv
HVV_WEB_DISCOVERY_HOSTNAME=hvv.example.net
```

Home Assistant muss diesen Namen im lokalen DNS zur Adresse des Containerhosts
auflösen können. Das Passwort wird nicht über mDNS übertragen.

## 2. Home Assistant einrichten

### Als Gerät automatisch erkennen

Die native Integration für das Raspberry-Pi-/Python-Backend liegt im Verzeichnis `custom_components/hvv_anzeiger`.
Sie muss einmal in Home Assistant installiert werden, bevor die Oberfläche das
Gerät erkennt. Das Verzeichnis `hvv_anzeiger` nach
`/config/custom_components/hvv_anzeiger` kopieren und Home Assistant neu
starten. Anschließend erscheint der Anzeiger unter **Einstellungen → Geräte &
Dienste** als entdecktes Gerät. Auswählen, die HTTPS-URL prüfen oder an den
Zertifikatsnamen anpassen und das individuelle Webpasswort eingeben. Der
Benutzername ist `hvv-anzeiger`.

Die Integration prüft beim Einrichten die API und das Zertifikat. TLS-Prüfung
bleibt eingeschaltet. Ein `.local`-mDNS-Name passt meist nicht zu einem
öffentlich ausgestellten Zertifikat; dafür den Zertifikats-DNS-Namen und eine
lokale DNS-Auflösung verwenden. Alternativ kann die bisherige manuelle
YAML-REST-Variante weiter verwendet werden. Nicht beide Varianten gleichzeitig
einrichten, da sonst Abfahrtsentitäten doppelt erscheinen.

Die Integration legt ein Pi-Backend-Gerät mit `sensor.hvv_anzeiger_abfahrtsanzeige` an.
Der Zustand ist `ok`, `stale`, `expired`, `unavailable` oder `night`; Abfahrten
und das begrenzte `display_payload` liegen als Attribute vor. Die Abfrage läuft
alle 15 Sekunden.

### ESP32/CYD erkennen

Das CYD meldet sich separat über die ESPHome-Native-API und deren mDNS-Dienst.
Home Assistant entdeckt das eingeschaltete Gerät über die integrierte
**ESPHome**-Integration; dafür keine Pi-URL oder Webpasswort eingeben. Beim
Einrichten wird der lokale Wert `api_encryption_key` aus
`esphome/secrets.yaml` benötigt. Status und Abfahrten kommen direkt aus der
ESP32-Firmware. Die Stationen dafür stehen in der
[CYD-Haltestellenanleitung](esp32-stations.md).

### Alternative: YAML-Paket und REST-Sensor

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
