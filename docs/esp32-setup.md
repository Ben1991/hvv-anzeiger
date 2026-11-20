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

### Schritt 1: Git und Python installieren

1. Installiere [Git für Windows](https://git-scm.com/download/win) mit den
   vorgeschlagenen Standardoptionen.
2. Installiere [Python 3.12](https://www.python.org/downloads/windows/). Wähle
   dort eine Version **3.12.x** und achte darauf, dass der **Python Launcher
   (`py`)** mitinstalliert wird. Eine neuere Hauptversion reicht für dieses
   Setup nicht aus.
3. Verbinde das ESP32-Board noch nicht mit dem Computer.

### Schritt 2: PowerShell öffnen und Installation prüfen

1. Öffne das Windows-Startmenü.
2. Tippe `PowerShell` und öffne **Windows PowerShell**. Administratorrechte
   sind für diese Anleitung nicht nötig.
3. Kopiere die folgenden zwei Befehle einzeln in das Fenster und drücke nach
   jedem Befehl die Eingabetaste:

   ```powershell
   git --version
   py -3.12 --version
   ```

   **Erfolg:** Der erste Befehl zeigt eine Git-Version, der zweite `Python 3.12.x`.

   **Wenn ein Befehl als unbekannt gemeldet wird:** Installiere das betreffende
   Programm erneut, achte bei Python auf den Python Launcher und öffne danach
   ein neues PowerShell-Fenster. Prüfe dort dieselben Befehle nochmals.

### Schritt 3: Repository herunterladen

Kopiere jede Zeile einzeln in PowerShell und drücke jeweils die Eingabetaste:

```powershell
git clone https://github.com/Ben1991/hvv-anzeiger.git
cd hvv-anzeiger
```

**Erfolg:** Die Eingabeaufforderung endet jetzt mit `hvv-anzeiger>`.

**Wenn `destination path ... already exists` erscheint:** Das Repository liegt
bereits auf dem Computer. Öffne im Explorer den Ordner `hvv-anzeiger`, klicke
oben in die Adressleiste, tippe `powershell` und drücke die Eingabetaste. Führe
im geöffneten Fenster zuerst `git status --short` aus. Eigene Änderungen
sichern, bevor du Updates mit `git pull --ff-only origin main` übernimmst.

### Schritt 4: ESPHome und das CYD-Profil einrichten

Kopiere den Befehl in dasselbe PowerShell-Fenster und drücke die Eingabetaste:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd
```

Für `hvv-cyd` brauchst du einen gültigen Geofox-Zugang. Das Setup-Skript fragt
den Geofox-Benutzernamen und das Passwort ab und legt sie lokal in der ignorierten
`esphome/secrets.yaml` ab. Es baut keine Pi-URL ein und verlangt weder ein
Pi-Zertifikat noch einen CYD-Geräteschlüssel.

Wenn `esphome/secrets.yaml` noch nicht vorhanden ist, fragt das Skript beim
ersten Lauf nach WLAN-Name und WLAN-Passwort:

1. Gib den Namen deines WLANs ein und drücke die Eingabetaste.
2. Gib das WLAN-Passwort ein. Während der Eingabe zeigt PowerShell keine Zeichen
   an. Drücke danach die Eingabetaste.
3. Gib deinen Geofox-Benutzernamen ein.
4. Gib dein Geofox-Passwort ein. Währenddessen zeigt PowerShell keine Zeichen.
5. Warte, bis ESPHome die Konfiguration geprüft hat.

Das Skript richtet Python 3.12, eine getrennte Python-Umgebung und ESPHome ein.
Es erstellt `esphome/secrets.yaml` mit einem zufälligen ESPHome-API-Schlüssel
und `esphome/hvv-cyd.local.yaml` als lokale Profilkopie. Vorhandene lokale
Display- und Pin-Einstellungen überschreibt es nicht. Ältere Pi-Backend-Secrets
werden nicht gelöscht, aber vom Profil `hvv-cyd` nicht verwendet. Alle lokalen
Zugangsdaten bleiben von Git ausgeschlossen.

**Erfolg:** Am Ende erscheint die Meldung „Konfiguration geprüft.“ ohne Fehlermeldung.

**Wenn `Python 3.12 wurde nicht gefunden` erscheint:** Prüfe in einem neuen
PowerShell-Fenster `py -3.12 --version`. Installiere Python 3.12 samt Python
Launcher, falls der Befehl fehlschlägt.

**Wenn eine vorhandene Umgebung nicht Python 3.12 verwendet:** Wiederhole den
Befehl aus dem Repository-Ordner mit einem neuen Umgebungsnamen:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -VenvPath .venv-esphome-312
```

**Wenn pip/ESPHome nicht heruntergeladen werden kann:** Prüfe die
Internetverbindung und einen möglichen Proxy. Starte danach denselben
Setup-Befehl erneut; vorhandene lokale Profile und Geheimnisse bleiben erhalten.

**Wenn Geofox-Zugangsdaten abgelehnt werden:** Prüfe Benutzername und Passwort
lokal in `esphome/secrets.yaml` und starte das Setup-Skript erneut. Zugangsdaten
nicht in Issues, Chats oder Screenshots kopieren.

**Wenn die Konfiguration wegen Platzhaltern fehlschlägt:** Öffne die Datei mit
`notepad .\esphome\secrets.yaml`. Ersetze nur die noch vorhandenen Werte
`REPLACE_WITH_...` durch deine Daten, speichere die Datei und führe den
Setup-Befehl erneut aus. Für einen noch fehlenden `api_encryption_key` erzeuge
einen neuen Schlüssel mit diesem Befehl:

```powershell
py -3.12 -c "import base64,secrets; print(base64.b64encode(secrets.token_bytes(32)).decode())"
```

Kopiere die ausgegebene Zeile in `secrets.yaml`. Poste WLAN-Passwort und
API-Schlüssel niemals in Issues, Chats oder Screenshots.

### Schritt 5: Board verbinden und Firmware flashen

1. Nimm ein USB-Datenkabel. Ein Ladekabel ohne Datenleitungen funktioniert nicht.
2. Verbinde das CYD mit dem Computer. Hat dein Board zwei USB-Anschlüsse,
   verwende nur einen davon gleichzeitig.
3. Kopiere den Flash-Befehl in PowerShell und drücke die Eingabetaste:

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
   ```

4. Warte auf den Firmwarebau. Wähle anschließend in ESPHome den COM-Port aus,
   der zum angeschlossenen Board gehört.

**Erfolg:** ESPHome meldet den abgeschlossenen Upload. Das Board startet danach
mit der neuen Firmware.

**Wenn kein COM-Port angeboten wird:** Prüfe, ob das Board eingeschaltet ist,
verwende ein anderes Datenkabel und kontrolliere im Windows-Geräte-Manager, ob
bei der seriellen USB-Schnittstelle des Boards ein Treiberfehler angezeigt wird.
Schließe serielle Monitore
oder andere Programme, die den COM-Port verwenden, und wiederhole den Flash.

**Wenn der Upload am Board nicht startet:** Halte `BOOT` gedrückt, drücke kurz
`RESET`, lasse `RESET` los und danach `BOOT`. Starte anschließend den Flash-Befehl
erneut. Die genaue Tastenfolge kann je nach Platinenrevision abweichen.

### Schritt 6: Anzeige prüfen

Prüfe am eingeschalteten Board, ob Abfahrten, Textausrichtung, Farben und
Querformat stimmen. Das CYD fragt Geofox ungefähr alle 15 Sekunden direkt ab.

**Wenn keine Abfahrten erscheinen:** Prüfe 2,4-GHz-WLAN, Zeit-Synchronisierung,
Geofox-Zugangsdaten und das Feld `hvv_stations_json` in
`esphome/hvv-cyd.local.yaml`. Jede Haltestelle muss eine gültige Geofox-ID
enthalten. Für Stationsänderungen den Ablauf unter
[Haltestellen ändern](esp32-stations.md) verwenden. Danach neu bauen und flashen.

**Wenn der Bildschirm leer bleibt oder Farben falsch sind:** Trenne das Board
vom USB, prüfe die tatsächliche Displayrevision und passe `display_model`,
`display_color_order` oder `display_rotation` in
`esphome/hvv-cyd.local.yaml` an. Produktname und Aufdruck allein identifizieren
den Displaycontroller nicht immer eindeutig. Verwende nur den Controller, der
für deine konkrete Platinenrevision angegeben ist: `ESP32-2432S028-7789`
(ST7789V) oder `ESP32-2432S028-9342` (ILI9342). Hinweise stehen unter
[Displayrevision und Pinbelegung](#hardware-displayrevision-und-pinbelegung).

**Nur bauen, noch nicht flashen:** In Schritt 5 `-Flash` durch `-Build` ersetzen.
Das Setup und die Konfigurationsprüfung aus Schritt 4 flashen keine Firmware.

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
Geheimnisse zusammenführen statt überschreiben. Anschließend Profil prüfen und
über den Builder per USB installieren.

## Hardware, Displayrevision und Pinbelegung

Das CYD-Profil verwendet ILI9342 und 320×240 Pixel im Querformat (0° Rotation).
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

```sh
esphome config esphome/hvv-cyd.local.yaml
esphome compile esphome/hvv-cyd.local.yaml
esphome run esphome/hvv-cyd.local.yaml
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
Unter Windows übernimmt das Setup-Skript Prüfung, Build und USB-Flash:

```powershell
git status --short
git pull --ff-only origin main
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd -Flash
```

Unter Linux/macOS mit dem eigenen `*.local.yaml` und den separat gesicherten Geheimnissen:

```sh
git status --short
git pull --ff-only origin main
. .venv-esphome/bin/activate
python -m pip install esphome==2026.9.1
esphome config esphome/hvv-cyd.local.yaml
esphome compile esphome/hvv-cyd.local.yaml
esphome upload esphome/hvv-cyd.local.yaml --device hvv-cyd.local
esphome logs esphome/hvv-cyd.local.yaml --device hvv-cyd.local
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
