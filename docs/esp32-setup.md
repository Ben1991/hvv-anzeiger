# ESP32 mit ESPHome einrichten und flashen

Diese Anleitung richtet das **eigenständige ESP32+CYD-System** ein. Die Firmware
fragt Geofox direkt ab, filtert die lokal konfigurierten Haltestellen und zeigt
Abfahrten an. Dafür sind weder Pi-Backend, Weboberfläche noch Home Assistant
erforderlich. ESPHome-API und mDNS erlauben Home Assistant, dasselbe CYD
optional als Gerät zu erkennen und Status/Abfahrten zu konsumieren.

Das **Pi+ILI-System** ist separat: Python-Backend, Weboberfläche und ILI-Display
laufen auf dem Pi. Dessen HA-Integration steht unter
[Raspberry-Pi-Backend und Home Assistant](home-assistant.md). Die Systeme teilen
ein versioniertes Display-Datenmodell, aber keine Laufzeit, Stationseinstellung
oder Geofox-Zugangsdaten.

## Schnellstart für Windows: CYD einrichten und flashen

Dieser Ablauf ist für das **2,8-Zoll-CYD ESP32-2432S028 mit 320×240 Pixeln im
Querformat**, einschließlich der abgebildeten Dual-USB-Revision.
Es verwendet `hvv-cyd` mit dem ILI9342-Profil und standardmäßiger 90°-Drehung
im Querformat.
Eine automatische Erkennung des Controllers ist bei diesen Boards nicht
zuverlässig. Für andere Displayrevisionen siehe
[Displayrevision und Pinbelegung](#hardware-displayrevision-und-pinbelegung).

### 1. Voraussetzungen und Projektdateien

Du brauchst einen [Geofox-Zugang](../README.md#geofox-zugang-beantragen),
2,4-GHz-WLAN, ein CYD und ein USB-Datenkabel. Installiere Git und Python 3.12.
Unter Windows muss der Python Launcher anschließend auf `py -3.12 --version` antworten.

```sh
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
```

Bei einem vorhandenen Checkout sichere lokale Änderungen und aktualisiere ihn
mit `git pull --ff-only origin main`. Für eine vorhandene CYD-Konfiguration
folge zuerst der [Migration](#vorhandenes-cyd-vom-pi-backend-umstellen).

### 2. Profil, Zugangsdaten und Haltestellen

Unter Windows übernimmt das Skript ESPHome-Installation und erste Konfigurationsprüfung.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
```

Das Skript legt bei Bedarf `esphome/hvv-cyd.local.yaml` und die daneben
liegende, von Git ignorierte `esphome/secrets.yaml` an. Es fragt beim ersten
Lauf WLAN und Geofox ab und erzeugt den API-Schlüssel. Passwörter werden verdeckt
eingegeben. Danach `hvv_stations_json` im lokalen Profil anhand der
[Stationsanleitung](esp32-stations.md) anpassen. Bei Bedarf dort auch das
[Displaymodell](#hardware-displayrevision-und-pinbelegung) wählen.
Linux, macOS und Device Builder folgen der
[manuellen Einrichtung](#manuelle-installation-oder-esphome-device-builder).

Die Felder `geofox_user_cpp` und `geofox_password_cpp` enthalten jeweils ein
C++-Stringliteral mit doppelten Anführungszeichen. YAML hält das Literal in
einfachen Anführungszeichen. Beispiel mit erfundenen Werten:

```yaml
geofox_user_cpp: '"demo-user"'
geofox_password_cpp: '"demo-passwort"'
```

Im Literal werden Backslash und doppeltes Anführungszeichen als `\\` und `\"`
geschrieben. Ein einfaches Anführungszeichen wird für YAML verdoppelt.
Gib dem Windows-Skript die ursprünglichen Werte ohne zusätzliche Anführungszeichen.
Für eine erneute Abfrage setze das betreffende Feld lokal auf `'""'`.
Die Prüfung erkennt fehlende und falsch formatierte Werte vor dem Build.
Ob die Zugangsdaten beim Anbieter gültig sind, zeigt der Funktionscheck am Gerät.

### 3. Validieren, bauen und übertragen

Alle Befehle im Projektordner ausführen. Unter Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Build
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
```

`-Flash` validiert und baut ebenfalls. Für den ersten Flash das Board per
USB-Datenkabel anschließen und den COM-Port wählen. Bei zwei Buchsen jeweils
nur eine verwenden. Für OTA `-Flash -Device hvv-cyd.local` angeben.
Der Name vor `.local` entspricht der Substitution `name`. Wenn mDNS
scheitert, stattdessen die lokale IP aus dem Router verwenden. Bei nicht
erreichbarem OTA oder fehlender OTA-Unterstützung wieder USB verwenden.
Bei fehlendem USB-Port Kabel, Treiber und andere serielle Programme prüfen.

### 4. Funktion am Gerät prüfen

Mit aktivierter ESPHome-Umgebung im Projektordner:

```sh
esphome logs esphome/hvv-cyd.local.yaml --device hvv-cyd.local
```

Unter Windows lässt sich `esphome` durch `..venv-esphomeScriptspython.exe -m esphome`
ersetzen. IP oder einen seriellen Port kannst du ebenfalls als `--device` angeben.
Der Netzwerkbefehl verbindet sich über die verschlüsselte ESPHome-API.
Prüfe nach der Uhrzeitsynchronisierung auf dem Display und in den Logs, dass
`Backendstatus` auf `ok` wechselt und `Abfahrt 1` bei passenden Verbindungen
befüllt ist. Die übrigen Sensoren können bei weniger als fünf Treffern leer sein.
Mit Strg+C beendest du die Loganzeige.

| Symptom | Prüfung |
|---|---|
| Geofox meldet HTTP 401 | Geofox-Benutzername und Passwort lokal prüfen, korrigieren und erneut bauen und übertragen. |
| Geofox meldet HTTP 400 | Stations-IDs und Konfiguration prüfen. Auch falsch übernommene Zugangsdaten oder ein fehlerhafter HMAC-Header können je nach Geofox-Antwort mit 400 auffallen. |
| Uhrzeit fehlt | WLAN, DNS und SNTP prüfen. Die Firmware startet Geofox-Abfragen erst mit gültiger Uhrzeit. |
| Status `ok`, aber keine Abfahrt | Stations-ID, Linien- und Richtungsfilter nach der Stationsanleitung prüfen. |
| Keine API- oder OTA-Verbindung | Gerätenamen, IP und WLAN prüfen. Bei Bedarf USB-Logs verwenden. Für API-Verbindungen muss der lokale Schlüssel zur installierten Firmware passen. |

### Vorhandenes CYD vom Pi-Backend umstellen

1. Lokale Haupt-YAML und `secrets.yaml` privat sichern. Bei Bedarf auch
   das alte Backend-Zertifikat für eine Rückkehr zum alten Profil sichern.
2. Gerätenamen, WLAN, API-Schlüssel und alle Display-/Pin-Overrides übernehmen.
   Das Windows-Skript migriert das mitgelieferte alte lokale Profil und legt
   eine `.pre-esp32-geofox-backend.bak` daneben ab. In einem eigenen Profil
   unter `packages:` den Transport `packages/https.yaml` durch `packages/geofox.yaml`
   ersetzen und eine eventuelle `board_entity`-Substitution des alten Transports
   entfernen. Das Hardwarepaket und eigene Hardware-Einstellungen beibehalten.
3. Die Geofox-Felder ergänzen und die bisherigen Stationen und Filter aus dem
   Pi-Setup nach `hvv_stations_json` übertragen. Übernommene Beispielstationen
   vor dem Flashen ersetzen. Anschließend validieren, per OTA oder USB
   übertragen und den Funktionscheck durchführen.

### CYD in Home Assistant erkennen

Das Profil `hvv-cyd` veröffentlicht die ESPHome-Native-API mit Verschlüsselung
und mDNS. Home Assistant entdeckt das eingeschaltete CYD unter
**Einstellungen → Geräte & Dienste** und bietet die integrierte ESPHome-
Integration an. Beim Einrichten wird `api_encryption_key` aus der lokalen
`esphome/secrets.yaml` benötigt. Es ist kein Pi-Backend, keine zusätzliche
benutzerdefinierte HVV-Integration und kein Wechsel zu `hvv-cyd-ha` nötig.

Wenn automatische Erkennung nicht angeboten wird, zuerst prüfen, ob ESP32 und
HA dasselbe LAN/mDNS erreichen. Alternativ die lokale Geräte-IP im Dialog der
ESPHome-Integration angeben. `hvv-cyd-ha` bleibt ein separates Profil für
Setups, die Daten aus der HA-Entität `sensor.hvv_board` beziehen.

**Wenn das Gerät in HA nicht gefunden wird:** Prüfe, ob ESP32 und Home Assistant
im selben erreichbaren Netzwerk sind und das WLAN 2,4 GHz unterstützt.
Kontrolliere SSID und Passwort in `esphome/secrets.yaml` und flashe erneut.

### Weitere Profile

| Profil | Zielhardware und Display | Transport |
|---|---|---|
| `hvv-cyd` | Dual-USB-CYD ESP32-2432S028; 2,8 Zoll, 320×240 nativ, ILI9342, Querformat | Eigenständiger Geofox-Backenddienst + Display; HA optional über ESPHome |
| `hvv-cyd-ha` | Dasselbe CYD-Board und Display | HA-Entität `sensor.hvv_board` als Datenquelle |
| `hvv-display` | ESP32 DevKit + externes ILI9341, 320×240 quer | HA-Entität als Datenquelle |
| `hvv-s3-ili9488` | ESP32-S3 DevKit + externes ILI9488, 480×320 quer | HA-Entität als Datenquelle |
| `hvv-direct` | ESP32 DevKit + externes ILI9341 | Direkter HTTPS-Zugriff auf Pi-Backend |

Für ein anderes Board `-Profile` auf den Profilnamen setzen. Eigene Namen,
Stationsdaten und Pin-Änderungen gehören nur in die zugehörige `*.local.yaml`.
Gemeinsame Dateien in `boards/` und `packages/` nicht editieren. `hvv-cyd`
verlangt Geofox-Zugangsdaten; `hvv-direct` benötigt Pi-Backend-URL, separaten
CYD-Schlüssel und private CA.

### Wenn der Setup-Befehl nicht startet

Falls Windows meldet, dass das Ausführen von Skripts blockiert ist, den Befehl
genau wie oben mit `powershell -NoProfile -ExecutionPolicy Bypass -File` starten.
Diese Einstellung gilt nur für den gestarteten PowerShell-Prozess und ändert
nicht die Richtlinie für das ganze System.

Der Build verwendet standardmäßig den kurzen ESP-IDF-Pfad `C:\ei`. Wenn dein
Benutzer ihn nicht erstellen darf, lege einen kurzen beschreibbaren lokalen
Ordner an und übergib ihn mit `-EspIdfPrefix 'C:\Users\<Name>\ei'`.

### Manuelle Installation oder ESPHome Device Builder

ESPHome **2026.9.1 oder neuer** verwenden. Unter Linux/macOS lässt sich die
Umgebung so erstellen:

Erstelle bei Bedarf eine Umgebung mit `python3.12 -m venv .venv-esphome`,
aktiviere sie mit `. .venv-esphome/bin/activate` und installiere
`python -m pip install esphome==2026.9.1`. Eine vorhandene kompatible
ESPHome-Umgebung kannst du direkt verwenden.

```sh
test -e esphome/secrets.yaml || cp esphome/secrets.example.yaml esphome/secrets.yaml
test -e esphome/hvv-cyd.local.yaml || cp esphome/hvv-cyd.yaml esphome/hvv-cyd.local.yaml
```

Ergänze WLAN, einen individuellen 32-Byte-Base64-API-Schlüssel aus deinem
Passwortmanager und die beiden Geofox-Literale in `esphome/secrets.yaml`.
Setze die Stationen im lokalen Profil und führe aus:

```sh
python scripts/check_cyd_secrets.py esphome/hvv-cyd.local.yaml --esphome config
python scripts/check_cyd_secrets.py esphome/hvv-cyd.local.yaml --esphome compile
esphome upload esphome/hvv-cyd.local.yaml
```

Für OTA an den letzten Befehl `--device hvv-cyd.local` oder die Geräte-IP
anhängen. Prüfe nach dem Upload die API und die Abfahrten wie oben.

Für `hvv-direct` `backend_url` auf
`https://hvv-anzeiger.local:8080/api/esphome` setzen und den zufälligen
CYD-Schlüssel aus der Backend-Weboberfläche als `Bearer <Schlüssel>` in
`backend_authorization` eintragen. `backend-ca.pem` muss das lokale
Backendzertifikat enthalten. Die Profile `hvv-cyd` und `hvv-cyd-ha` benötigen
diese Werte nicht. Das Profil `hvv-cyd` fragt Geofox direkt ab und hält seine
Geofox-Zugangsdaten lokal.

Im ESPHome Device Builder kopierst du den kompletten Ordner `esphome/` in den
Konfigurationsordner, einschließlich `hvv_board.h`, `hvv_geofox.h`, `boards/`, `packages/` und `fonts/`.
Der Header muss neben den Profil-YAML-Dateien liegen. Geheime Werte aus
`secrets.example.yaml` in eine eigene `secrets.yaml` übernehmen; vorhandene
Geheimnisse zusammenführen statt überschreiben. Das Format der Zugangsdaten vorab mit `python scripts/check_cyd_secrets.py <Pfad-zur-Profil-YAML>` aus einer ESPHome-Umgebung prüfen. Anschließend über den Builder per USB installieren.

## Hardware, Displayrevision und Pinbelegung

Das CYD-Profil verwendet ILI9342 und 320×240 Pixel im Querformat (90° Rotation).
Der resistive Touchscreen wird nicht verwendet; die Abfahrtsanzeige läuft als
reine Anzeige. SPI-Pins und Hintergrundbeleuchtung sind im Hardwareprofil gesetzt.

Eine zuverlässige automatische Erkennung des Displaycontrollers ist nicht
konfiguriert: ESPHome wählt die Controller-Initialisierung beim Firmware-Build,
und Produktname sowie Platinenaufdruck unterscheiden die Displayrevisionen
nicht eindeutig. Das Standardprofil zielt auf die hier getestete Dual-USB-
Revision mit ILI9342 und `display_rotation: '90'`. Für die ILI9341-Revision
oder die Dual-USB-Revision mit ST7789V muss `display_model` in der eigenen
`*.local.yaml` auf `ILI9341` beziehungsweise `ESP32-2432S028-7789` gesetzt
werden; die Ausrichtung ist am konkreten Modul zu prüfen. Bei
abweichenden Farben kann `display_color_order` auf `bgr` geändert werden.
Änderungen nur in der eigenen `*.local.yaml` vornehmen.

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

Die DejaVu-Schriften liegen samt Lizenz im Repository; das Gerät
benötigt dafür im Betrieb keinen Zugriff.

## Darstellung wie auf dem Pi

Bei 320 × 240 Pixeln nutzt die Firmware das Pi-Layout: Kopfzeile mit lokaler Uhr,
fünf feste Abfahrtszeilen, dieselben Linienfarben und Logoformen, Stationskürzel
und rechts Countdown plus absolute Abfahrtszeit. Im Modus `departure_time` wird
rechts nur die absolute Zeit dargestellt. Eine Verspätung steckt bereits in der
prognostizierten Abfahrtszeit; es erscheint wie auf dem Pi keine zusätzliche
`+0 min`-/`+N min`-Zeile. Ausfälle bleiben rot mit `AUS` markiert.

Die Schriften werden aus `fonts/` eingebunden. Diesen Ordner auch bei manuellen
Updates im Device Builder übernehmen. Nachtabschaltung, Display-Schalter und
Warnungen bei veralteten oder abgelaufenen Daten bleiben erhalten.

[Reproduzierbarer visueller Vergleich und Testgrenzen](esp32-display-parity.md).

## Firmware aktualisieren

### ESPHome Device Builder

Im Device Builder `hvv_board.h`, `hvv_geofox.h`, `boards/`, `packages/` und `fonts/` aus dem aktualisierten
Repository übernehmen. Eigene Haupt-YAML, `secrets.yaml`, Gerätename, GPIOs und
API-Schlüssel erhalten. Versionshinweise auf Änderungen am Beispielprofil prüfen.
Das Profil validieren und über **Installieren → Drahtlos** neu bauen und übertragen.
Falls der Builder die benötigte ESPHome-Version noch nicht unterstützt, zuerst
den Builder aktualisieren. Bei nicht erreichbarem Gerät per USB flashen.

### ESPHome über die Kommandozeile

Im Repository zuerst eigene Änderungen prüfen und dann `main` per Fast-Forward
aktualisieren. Lokale `*.local.yaml`-Profile und `secrets.yaml` bleiben erhalten.
Danach erneut [validieren, bauen und übertragen](#3-validieren-bauen-und-übertragen).
Für OTA den bestehenden Gerätenamen oder die lokale IP verwenden.

### Nach jedem Update prüfen

1. ESPHome-API verbunden, `Backendstatus` ist `ok` und bei passenden Verbindungen sind Abfahrtssensoren befüllt.
2. Auf dem Display die eigenen Linien, Ziele und Labels sowie aktuelle Abfahrtszeiten.
3. Helligkeit, Anzeigeschalter und Rückkehr aus dem Nachtmodus.
4. Bei Verbindungsausfall Warnung und Ablauf alter Daten; nach Wiederverbindung
   erneute Aktualisierung. Das ist ein Test am realen Aufbau und wird durch
   einen erfolgreichen Compilerlauf nicht ersetzt.

## Direkter HTTPS-Transport zum Pi-Backend

Nur das generische Profil `hvv-direct.yaml` fragt das separate Pi-Backend per
HTTPS ab. Das Standardprofil `hvv-cyd.yaml` nutzt diesen Transport nicht.
`backend_url` auf
`https://hvv-anzeiger.local:8080/api/esphome` und `backend_authorization` auf
`Bearer <zufälliger CYD-Schlüssel>` setzen. Das lokale Backendzertifikat als
`backend-ca.pem` neben die Haupt-YAML kopieren. Der Schlüssel ist vom
Webpasswort getrennt und nur für den schreibgeschützten Abfahrtsfeed gültig.
`verify_ssl: true` und `follow_redirects: false` bleiben aktiv.
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
