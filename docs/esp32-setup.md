# ESP32 mit ESPHome einrichten und flashen

Diese Anleitung behandelt die Board-Auswahl, ESPHome-Konfiguration, Firmware,
USB-Flashen und ESPHome-Updates. Die Python-API und Home-Assistant-Pakete müssen
zuerst eingerichtet sein, wenn das Gerät den HA-Transport nutzt: siehe
[Home Assistant und Hintergrunddienst](home-assistant.md). Beim optionalen
direkten HTTPS-Profil ist HA für die Abfahrtsdaten nicht erforderlich.

## 1. Voraussetzungen und Profil wählen

Richte zuerst den HTTPS-Hintergrunddienst ein. Für die normale Anbindung muss
Home Assistant den REST-Sensor `sensor.hvv_board` bereitstellen; der ESP32
verbindet sich zusätzlich mit der verschlüsselten ESPHome-API. Siehe
[Home Assistant und Hintergrunddienst](home-assistant.md).

| Profil | Zielhardware und Display | Transport |
|---|---|---|
| `hvv-cyd` | CYD ESP32-2432S028, Dual-USB-Variante wie auf den Produktfotos; 2,8 Zoll, 240×320, ILI9341 als Standard, Querformat | Home Assistant |
| `hvv-display` | ESP32 DevKit + externes ILI9341, 320×240 quer | Home Assistant |
| `hvv-s3-ili9488` | ESP32-S3 DevKit + externes ILI9488, 480×320 quer | Home Assistant |
| `hvv-direct` | ESP32 DevKit + externes ILI9341 | HTTPS direkt zum Hintergrunddienst |

## 2. Windows-Setup automatisieren

Im Repository liegt `scripts/setup-esphome.ps1`. Das Skript richtet Python 3.12
und eine getrennte virtuelle Umgebung ein, installiert die im Projekt geprüfte
ESPHome-Version, legt ein lokales Profil an, erzeugt einen zufälligen
API-Schlüssel und fragt SSID sowie WLAN-Passwort verdeckt ab. Es verändert keine
vorhandene `esphome/secrets.yaml` oder `*.local.yaml`.

1. Installiere Git und Python 3.12 mit dem Python Launcher. Verbinde das Board
   zunächst nicht.
2. Lade das Repository:

   ```powershell
   git clone https://github.com/Ben1991/hvv-anzeiger.git
   cd hvv-anzeiger
   ```

   Bei einem vorhandenen Checkout zuerst `git status --short` prüfen und lokal
   angepasste Dateien sichern. Updates nur mit `git pull --ff-only origin main`
   übernehmen.
3. Führe das Setup für das CYD aus:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
   ```

   Beim ersten Lauf fragt es nach WLAN-Name und Passwort; die Eingabe des
   Passworts bleibt verdeckt. Das Skript legt `esphome/secrets.yaml` mit
   zufälligem API-Schlüssel sowie `esphome/hvv-cyd.local.yaml` an und prüft die
   ESPHome-Konfiguration. Diese Dateien sind lokal und von Git ausgeschlossen.
   Eine vorhandene Python-Umgebung mit anderer Version überschreibt es ebenfalls
   nicht; nutze in dem Fall `-VenvPath .venv-esphome-312`.
4. Kontrolliere bei Bedarf `esphome/hvv-cyd.local.yaml`. Für andere Boards
   ersetze `hvv-cyd` in `-Profile` durch `hvv-display`, `hvv-s3-ili9488` oder
   `hvv-direct`. Eigene Namen, `board_entity` und Pin-Änderungen gehören nur in
   die lokale YAML. Gemeinsame Dateien in `boards/` und `packages/` nicht
   editieren. Das direkte Profil verlangt zusätzlich gültige `backend_url`- und
   `backend_authorization`-Werte; diese vertraulichen Werte musst du selbst in
   `secrets.yaml` setzen.
5. Verbinde das Board per USB-Datenkabel. Beim CYD nur einen der beiden
   USB-Anschlüsse gleichzeitig verwenden. Flashen und Bauen startest du mit:

   ```powershell
   .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
   ```

   Das Skript prüft die Konfiguration, baut die Firmware und lässt ESPHome den
   COM-Port wählen. Bei `-Build` wird nur gebaut, noch nicht geflasht. Ohne
   Parameter `-Build` oder `-Flash` läuft nur Setup und Konfigurationsprüfung.
   Wenn kein COM-Port erscheint, prüfe im Geräte-Manager, ob für den auf deiner
   Revision verbauten USB-UART-Chip ein passender Treiber fehlt.
6. Füge das Gerät bei HA-Transport über **Einstellungen → Geräte & Dienste →
   Integration hinzufügen → ESPHome** hinzu. Den individuellen API-Schlüssel
   kannst du lokal in `esphome/secrets.yaml` nachsehen und im geschützten Dialog
   eingeben. Niemals in Chat, Logs oder öffentliche Issues kopieren.
7. Prüfe WLAN, angezeigte Abfahrten, Rotation und Farben. Die ESPHome-
   Diagnosewerte **Freier Heap**, **Größter freier Heap-Block** und
   **Minimaler freier Heap** werden alle 30 Sekunden an Home Assistant gemeldet.

Der Build verwendet standardmäßig den kurzen ESP-IDF-Pfad `C:\ei`. Wenn dein
Benutzer ihn nicht erstellen darf, lege einen kurzen beschreibbaren lokalen
Ordner an und übergib ihn mit `-EspIdfPrefix 'C:\Users\<Name>\ei'`.

### Manuelle Installation oder ESPHome Device Builder

ESPHome **2026.9.1 oder neuer** verwenden. Unter Linux/macOS lässt sich die
Umgebung so erstellen:

```sh
python3.12 -m venv .venv-esphome
. .venv-esphome/bin/activate
python -m pip install esphome==2026.9.1
cp esphome/secrets.example.yaml esphome/secrets.yaml
cp esphome/hvv-cyd.yaml esphome/hvv-cyd.local.yaml
```

Unter Windows ohne Setup-Skript kannst du `py -3.12 -m venv .venv-esphome`,
`.venv-esphome\Scripts\Activate.ps1` und `python -m pip install esphome==2026.9.1`
verwenden. Kopiere die Beispielgeheimnisse nur, wenn `secrets.yaml` noch nicht
existiert. Erzeuge für `api_encryption_key` einen individuellen 32-Byte-
Base64-Schlüssel und trage ihn in `secrets.yaml` ein. Mit Python kannst du ihn
erzeugen:

```sh
python -c 'import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())'
```

Die Ausgabe ist vertraulich; nicht in öffentliche Logs oder Issues kopieren.

Im ESPHome Device Builder kopierst du den kompletten Ordner `esphome/` in den
Konfigurationsordner, einschließlich `hvv_board.h`, `boards/` und `packages/`.
Der Header muss neben den Profil-YAML-Dateien liegen. Geheime Werte aus
`secrets.example.yaml` in eine eigene `secrets.yaml` übernehmen; vorhandene
Geheimnisse zusammenführen statt überschreiben. Anschließend Profil prüfen und
über den Builder per USB installieren.

## Hardware, Displayrevision und Pinbelegung

Das CYD-Profil verwendet ILI9341 und 240×320 Pixel. Der resistive Touchscreen
wird nicht verwendet; die Abfahrtsanzeige läuft als reine Anzeige. SPI-Pins und
Hintergrundbeleuchtung sind im Hardwareprofil gesetzt.

Eine zuverlässige automatische Erkennung des Displaycontrollers ist nicht
konfiguriert: ESPHome wählt die Controller-Initialisierung beim Firmware-Build,
und Produktname sowie Platinenaufdruck unterscheiden die Displayrevisionen
nicht eindeutig. Die Firmware ist auf die ILI9341-Angabe der Produktseite
eingestellt. Falls das Display nach dem Flashen leer bleibt, zuerst anhand
der Displayrevision den Controller prüfen und `display_model` in der eigenen
Haupt-YAML passend auf `ESP32-2432S028-7789` (ST7789V) oder
`ESP32-2432S028-9342` (ILI9342) setzen. Bei abweichenden Farben kann
`display_color_order` auf `bgr` geändert werden. Änderungen nur in der eigenen
`*.local.yaml` vornehmen. Für ILI9342 `display_rotation: '0'` setzen; für
ILI9341 und ST7789V bleibt die Rotation `90`.

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

## Firmware aktualisieren

### ESPHome Device Builder

Im Device Builder `hvv_board.h`, `boards/` und `packages/` aus dem aktualisierten
Repository übernehmen. Eigene Haupt-YAML, `secrets.yaml`, Gerätename, GPIOs und
API-Schlüssel erhalten. Versionshinweise auf Änderungen am Beispielprofil prüfen.
Das Profil validieren und über **Installieren → Drahtlos** neu bauen und übertragen.
Falls der Builder die benötigte ESPHome-Version noch nicht unterstützt, zuerst
den Builder aktualisieren. Bei nicht erreichbarem Gerät per USB flashen.

### ESPHome über die Kommandozeile

Im Repository zuerst eigene Änderungen prüfen und dann `main` per Fast-Forward
aktualisieren. Lokale `*.local.yaml`-Profile und `secrets.yaml` bleiben erhalten.
Unter Windows übernimmt das Setup-Skript Prüfung, Build und USB-Flash:

```powershell
git status --short
git pull --ff-only origin main
.\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
```

Unter Linux/macOS mit dem eigenen `*.local.yaml` und den separat gesicherten Geheimnissen:

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
