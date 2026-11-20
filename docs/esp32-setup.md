# ESP32 mit ESPHome einrichten und flashen

Mit dieser Anleitung bringst du ein CYD mit eingebautem Bildschirm per USB
zum Laufen. Es holt die Abfahrten direkt von Geofox. Ein Raspberry Pi ist
dafür nicht erforderlich. Codex und Home Assistant sind optional.

Wenn du stattdessen einen Raspberry Pi mit einem separaten ILI9341-Display
hast, folge der [Pi-Anleitung](../README.md#hier-anfangen).

## Schnellstart für Windows: CYD einrichten und flashen

Dieser Ablauf ist für das **2,8-Zoll-CYD ESP32-2432S028 mit 320×240 Pixeln im
Querformat**, einschließlich der abgebildeten Dual-USB-Revision.
Es verwendet `hvv-cyd` mit dem ILI9342-Profil und standardmäßiger 90°-Drehung
im Querformat.
Eine automatische Erkennung des Controllers ist bei diesen Boards nicht
zuverlässig. Für andere Displayrevisionen siehe
[Displayrevision und Pinbelegung](#hardware-displayrevision-und-pinbelegung).

### 1. Voraussetzungen und Projektdateien

1. Lege dein CYD, ein USB-Datenkabel, den Namen und das Passwort deines
   2,4-GHz-WLANs und deinen Geofox-Zugang bereit. Das USB-Kabel muss Daten
   übertragen können. Bei einem reinen Ladekabel taucht später kein Anschluss
   zur Auswahl auf. [Geofox-Zugang beantragen](../README.md#geofox-zugang-beantragen)
2. Installiere [Git für Windows](https://git-scm.com/download/win) und
   [Python 3.12](https://www.python.org/downloads/windows/). Lass den
   Python Launcher bei der Installation ausgewählt.
3. Öffne das Windows-Startmenü, tippe **PowerShell** und öffne
   **Windows PowerShell**. Kopiere die nächsten vier Zeilen nacheinander hinein
   und drücke nach jeder Zeile die Eingabetaste.

```powershell
py -3.12 --version
git --version
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
```

Die erste Zeile sollte eine Versionsnummer wie **Python 3.12.10** anzeigen.
Wenn `py` oder `git` unbekannt ist, schließe PowerShell nach der Installation
und öffne sie erneut. Fehlt Python 3.12 weiterhin, ergänze die Version samt
Launcher. Schlägt das Klonen fehl, prüfe die Internetverbindung und warte
mit `cd hvv-anzeiger`, bis der Download abgeschlossen ist.
Nach der letzten Zeile endet die Eingabeaufforderung auf `hvv-anzeiger>`.
Ist der Projektordner bereits vorhanden, öffne ihn im Explorer, tippe
`powershell` in die Adressleiste und drücke die Eingabetaste. Wenn du schon
ein eingerichtetes CYD hast, sichere zuerst seine Einstellungen und folge der
[Migration](#vorhandenes-cyd-vom-pi-backend-umstellen).

### 2. Profil, Zugangsdaten und Haltestellen

Kopiere diese Zeile in dasselbe PowerShell-Fenster und drücke die Eingabetaste:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
```

Gib bei der Abfrage den WLAN-Namen, das WLAN-Passwort sowie deine Geofox
Application-ID und dein Geofox-Passwort ein. Drücke nach jeder Eingabe die
Eingabetaste. Bei der Passworteingabe bleiben auch die Platzhalterzeichen
unsichtbar. Gib beide Passwörter ohne zusätzliche Anführungszeichen ein.

Warte auf **Konfiguration geprüft.** Das Skript speichert die Einstellungen im
Projektordner unter `esphome`. Lass für den ersten Test die mitgelieferten
Haltestellen stehen. Damit kannst du zuerst WLAN, Geofox-Zugang und Display
prüfen. Nach dem Test kannst du [eigene Haltestellen eintragen](esp32-stations.md).

Wenn der Setup-Befehl nicht startet, prüfe zuerst den
[Projektpfad und die PowerShell-Fehlermeldung](#wenn-der-setup-befehl-nicht-startet).
Bei ungültigen Geofox-Werten setze das betroffene Feld in `esphome/secrets.yaml`
auf `'""'` und starte das Setup erneut. WLAN-Daten kannst du in derselben Datei
ändern. Die Änderung gilt nach dem nächsten Flash.

Linux, macOS und bereits installierte ESPHome-Geräteverwaltungen folgen der
[manuellen Einrichtung](#manuelle-installation-oder-esphome-device-builder).

### 3. Validieren, bauen und übertragen

1. Verbinde das CYD mit einem USB-Datenkabel mit deinem Computer. Hat das
   Gerät zwei USB-Buchsen, verwende eine davon.
2. Kopiere den Befehl in dasselbe PowerShell-Fenster und drücke die Eingabetaste.
   Beim ersten Mal kann der Bau einige Minuten dauern.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
```

3. Wähle bei der Abfrage den USB-Anschluss des CYD. Windows zeigt ihn als
   **COM** mit einer Nummer an, zum Beispiel **COM3**. Wenn du mehrere siehst,
   ziehe das CYD ab und prüfe, welcher Anschluss im Geräte-Manager
   verschwindet. Stecke das Gerät wieder ein und wähle diesen Anschluss.
4. Warte auf die Meldung zum erfolgreichen Upload. Anschließend startet das
   CYD mit der neuen Gerätesoftware. Dieser Vorgang heißt **Flashen**.

Wenn kein COM-Port angeboten wird, versuche ein anderes USB-Datenkabel und
prüfe im Geräte-Manager, ob ein USB-Seriell-Treiber für den Chip deiner
Board-Revision fehlt. Bei einem belegten COM-Port schließe serielle Monitore.
Wenn der Anschluss erkannt wird, der Verbindungsaufbau aber scheitert, nutze
den Flash-Modus nach Anleitung deiner Board-Revision. Bei einem Buildfehler
führe das Setup zunächst ohne `-Flash` aus. Prüfe danach freien Speicher,
Internetzugang für die Downloads und den [ESP-IDF-Pfad](#wenn-der-setup-befehl-nicht-startet).
Du kannst dieselbe Befehlszeile später für Updates per USB benutzen. Für
drahtlose Updates füge `-Device hvv-cyd.local` am Ende an. Wenn der Name
nicht funktioniert, verwende die IP-Adresse, die dein Router beim CYD anzeigt.

### 4. Funktion am Gerät prüfen

Warte, bis das Display die aktuelle Uhrzeit und die ersten Abfahrten zeigt.
Dann ist die Grundinstallation fertig. Wenn etwas fehlt oder du die Verbindung
prüfen möchtest, kopiere diesen Befehl in dasselbe PowerShell-Fenster:

```powershell
.\.venv-esphome\Scripts\python.exe -m esphome logs .\esphome\hvv-cyd.local.yaml --device hvv-cyd.local
```

Wenn die Verbindung steht, zeigt ESPHome laufende Meldungen vom Gerät an.
Suche nach **Backendstatus** und **ok** sowie nach **Abfahrt 1** mit einer
Verbindung. Sind zur Testzeit keine passenden Abfahrten vorhanden, kann der
Status trotzdem **ok** sein. Drücke **Strg+C**, um die Meldungen zu schließen.
Auf Linux oder macOS lautet der Befehl in der aktivierten Umgebung
`esphome logs esphome/hvv-cyd.local.yaml --device hvv-cyd.local`.

| Symptom | Prüfung |
|---|---|
| Geofox meldet HTTP 401 | Geofox-Benutzername und Passwort lokal prüfen, korrigieren und erneut bauen und übertragen. |
| Geofox meldet HTTP 400 | Stations-IDs und Konfiguration prüfen. Auch falsch übernommene Zugangsdaten oder ein fehlerhafter HMAC-Header können je nach Geofox-Antwort mit 400 auffallen. |
| Bildschirm bleibt leer oder Farben sind falsch | USB-Stromversorgung und Anzeigeschalter prüfen. Bei funktionierender API die [Displayrevision und Rotation](#hardware-displayrevision-und-pinbelegung) prüfen. |
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

Fehlt die automatische Erkennung, prüfe im Router, ob das CYD verbunden ist,
und gib seine IP-Adresse in der ESPHome-Integration ein. Prüfe bei einem
Timeout, ob Home Assistant das WLAN des Geräts erreichen kann. Wird der
Schlüssel abgelehnt, verwende den Schlüssel der tatsächlich geflashten Firmware.
`hvv-cyd-ha` bleibt ein separates Profil für Setups mit `sensor.hvv_board`.

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

Prüfe mit `Test-Path .\scripts\setup-esphome.ps1`, ob PowerShell im
Projektordner steht. Bei `False` wechsle in den geklonten Ordner.

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

## Laufendes CYD konfigurieren

1. Sichere `esphome/hvv-cyd.local.yaml` und `esphome/secrets.yaml` privat.
2. Ändere [Haltestellen, Linien und Richtungen](esp32-stations.md) in
   `esphome/hvv-cyd.local.yaml` unter `hvv_stations_json`. Dort kannst du auch
   [Displaymodell und Rotation](#hardware-displayrevision-und-pinbelegung)
   anpassen. WLAN- und Geofox-Zugangsdaten stehen in `esphome/secrets.yaml`.
3. Validiere das lokale Profil, baue die Firmware und übertrage sie wie beim
   [Flashen unter Windows](#3-validieren-bauen-und-übertragen) oder bei der
   [manuellen Einrichtung](#manuelle-installation-oder-esphome-device-builder).
   Nutze USB, wenn das CYD für ein WLAN-Update nicht erreichbar ist.
4. Prüfe am Display und über die [ESPHome-API](#4-funktion-am-gerät-prüfen),
   ob die gewünschten Abfahrten erscheinen.

## Firmware aktualisieren

### ESPHome Device Builder

Im Device Builder `hvv_board.h`, `hvv_geofox.h`, `boards/`, `packages/` und `fonts/` aus dem aktualisierten
Repository übernehmen. Eigene Haupt-YAML, `secrets.yaml`, Gerätename, GPIOs und
API-Schlüssel erhalten. Versionshinweise auf Änderungen am Beispielprofil prüfen.
Das Profil validieren und über **Installieren → Drahtlos** neu bauen und übertragen.
Falls der Builder die benötigte ESPHome-Version noch nicht unterstützt, zuerst
den Builder aktualisieren. Bei nicht erreichbarem Gerät per USB flashen.

### ESPHome über die Kommandozeile

Sichere `esphome/hvv-cyd.local.yaml` und `esphome/secrets.yaml` privat
und führe im Repository aus:

```sh
git status --short
git switch main
git pull --ff-only origin main
```

Wenn Git lokale Änderungen oder abweichende Commits meldet, sichere und kläre
diese vor dem Update. Die ignorierten lokalen Profile und Secrets bleiben
erhalten. Vergleiche bei neuen Profiloptionen deine lokale YAML mit dem
aktualisierten Beispiel. Prüfe unter Linux/macOS auch die ESPHome-Version
und wiederhole den [Validierungs- und Buildablauf](#manuelle-installation-oder-esphome-device-builder).

Unter Windows aktualisierst du die Firmware über das Setup-Skript:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash -Device hvv-cyd.local
```

Verwende bei einem eigenen Gerätenamen dessen `.local`-Adresse oder die IP
aus dem Router. Scheitert OTA, verbinde das Gerät per USB und führe denselben
Befehl ohne `-Device` aus. Bei einer Regression kannst du den vorherigen
Repository-Stand zusammen mit dem gesicherten lokalen Profil neu bauen
und per USB übertragen.

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
