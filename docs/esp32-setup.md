# ESP32 mit ESPHome einrichten und flashen

Diese Anleitung behandelt die Board-Auswahl, ESPHome-Konfiguration, Firmware,
USB-Flashen und ESPHome-Updates für das CYD. Das Standardprofil fragt den
Python-Hintergrunddienst direkt per HTTPS ab; **Home Assistant ist dafür nicht
erforderlich**. Der Hintergrunddienst muss erreichbar sein. Seine Installation
steht in der Anleitung zum
[Hintergrunddienst](home-assistant.md#1-hintergrunddienst-bereitstellen).
Home Assistant ist eine separate optionale Funktion; dafür gibt es das Profil
`hvv-cyd-ha`.

Vor dem Flashen muss der Python-Hintergrunddienst laufen und ein Webpasswort
haben. Prüfe im Browser, ob sich seine HTTPS-Weboberfläche öffnen und anmelden
lässt. Wenn das noch nicht funktioniert, richte zuerst den
[Hintergrunddienst](home-assistant.md#1-hintergrunddienst-bereitstellen) ein.

## Schnellstart für Windows: CYD einrichten und flashen

Dieser Ablauf ist für das **2,8-Zoll-CYD ESP32-2432S028 mit 240×320 Pixeln**,
einschließlich der abgebildeten Dual-USB-Revision.
Er verwendet das Profil `hvv-cyd` und setzt den Displaycontroller standardmäßig
auf ILI9341. Eine automatische Erkennung des Controllers ist bei diesen Boards
nicht zuverlässig. Für andere Boards siehe [weitere Profile](#weitere-profile).

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

Wenn `esphome/secrets.yaml` noch nicht vorhanden ist, fragt das Skript beim
ersten Lauf nach WLAN-Name und WLAN-Passwort. Für das direkte Profil fragt es
danach zusätzlich nach der HTTPS-Adresse des Hintergrunddienstes und dem dort
eingerichteten Webpasswort. Der Benutzername `hvv-anzeiger` wird automatisch
verwendet; das Passwort bleibt bei der Eingabe verdeckt:

1. Gib den Namen deines WLANs ein und drücke die Eingabetaste.
2. Gib das WLAN-Passwort ein. Während der Eingabe zeigt PowerShell keine Zeichen
   an. Drücke danach die Eingabetaste.
3. Gib beim Profil `hvv-cyd` die HTTPS-Adresse deines Hintergrunddienstes ein.
   Die Adresse muss auf `/api/esphome` enden.
4. Gib das Webpasswort des Hintergrunddienstes ein. Auch hier zeigt PowerShell
   keine Zeichen an.
5. Warte, bis ESPHome die Konfiguration geprüft hat.

Das Skript richtet Python 3.12, eine getrennte Python-Umgebung und ESPHome ein.
Es erstellt `esphome/secrets.yaml` mit einem zufälligen ESPHome-API-Schlüssel
und `esphome/hvv-cyd.local.yaml` als lokale Profilkopie. Vorhandene lokale
Display- und Pin-Einstellungen überschreibt es nicht. Bei einem Upgrade des
bisherigen CYD-Profils ändert es nur den Transport auf direkten HTTPS-Abruf,
entfernt die nicht mehr benötigte `board_entity`-Zeile und legt vorher eine
Sicherung mit der Endung `.pre-direct-backend.bak` an. Alte
`secrets.yaml`-Dateien ergänzt das Skript um fehlende Backend-Felder und fragt
danach nur noch deren Werte ab. Die Dateien enthalten private Zugangsdaten und
bleiben von Git ausgeschlossen.

Die Backend-Adresse muss mit `https://` beginnen und auf `/api/esphome` enden,
zum Beispiel `https://anzeige.example.net:8080/api/esphome`. Der Hostname muss
vom ESP32 erreichbar sein und ein vom Gerät akzeptiertes TLS-Zertifikat
verwenden. Bei einer eigenen Zertifizierungsstelle siehe den Abschnitt
[Direktes HTTPS](#direkt-per-https).

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

**Wenn die Backend-Adresse abgelehnt wird:** Gib eine vollständige HTTPS-Adresse
ein, die mit `/api/esphome` endet. Prüfe außerdem, dass der Hintergrunddienst
läuft und von deinem WLAN aus erreichbar ist.

**Wenn die Anmeldung am Backend fehlschlägt:** Verwende das aktuelle Webpasswort
des Hintergrunddienstes für den Benutzer `hvv-anzeiger`. Öffne bei einem
Tippfehler `esphome/secrets.yaml` und setze die Zeile
`backend_authorization` auf `Basic REPLACE_WITH_BASE64_CREDENTIALS` zurück.
Starte danach Schritt 4 erneut; das Skript fragt das Webpasswort erneut ab.
Zugangsdaten nicht in Issues, Chats oder Screenshots teilen.

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
Querformat stimmen. Das CYD fragt den Hintergrunddienst alle 15 Sekunden ab.

**Wenn keine Abfahrten erscheinen:** Prüfe, ob das WLAN 2,4 GHz nutzt und der
Hintergrunddienst erreichbar ist. Öffne `esphome/secrets.yaml` und prüfe
`wifi_ssid`, `wifi_password`, `backend_url` und `backend_authorization`. Ändere
falsche WLAN-Werte dort. Bei einem falschen Backendpasswort setze die
Authorization-Zeile wie oben zurück. Flash danach mit dem Befehl aus Schritt 5
erneut.

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

### Optionale Funktion: CYD mit Home Assistant verbinden

Die Standardfirmware `hvv-cyd` zeigt Abfahrten ohne Home Assistant an. Wenn du
zusätzlich HA-Entitäten und HA-Steuerung möchtest, richte zuerst Hintergrund-
dienst, HA-Paket und `sensor.hvv_board` nach der
[Home-Assistant-Anleitung](home-assistant.md) ein. Flash danach das getrennte
HA-Profil:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\setup-esphome.ps1 -Profile hvv-cyd-ha -Flash
```

Füge das Gerät in Home Assistant unter **Einstellungen → Geräte & Dienste →
Integration hinzufügen → ESPHome** hinzu. Wenn Home Assistant nach dem
API-Schlüssel fragt, übernimm lokal `api_encryption_key` aus
`esphome/secrets.yaml` in den geschützten Dialog. Das HA-Profil bezieht Daten
über `sensor.hvv_board`; es ersetzt damit den direkten Backendtransport der
Standardfirmware. Zum Wechsel zurück auf den direkten Betrieb erneut `-Profile
hvv-cyd` flashen.

**Wenn das Gerät in HA nicht gefunden wird:** Prüfe, ob ESP32 und Home Assistant
im selben erreichbaren Netzwerk sind und das WLAN 2,4 GHz unterstützt.
Kontrolliere SSID und Passwort in `esphome/secrets.yaml` und flashe erneut.

### Weitere Profile

| Profil | Zielhardware und Display | Transport |
|---|---|---|
| `hvv-cyd` | CYD ESP32-2432S028; 2,8 Zoll, 240×320, ILI9341 als Standard, Querformat | Direkt per HTTPS zum Hintergrunddienst; kein HA nötig |
| `hvv-cyd-ha` | Dasselbe CYD-Board und Display | Home Assistant, optional |
| `hvv-display` | ESP32 DevKit + externes ILI9341, 320×240 quer | Home Assistant |
| `hvv-s3-ili9488` | ESP32-S3 DevKit + externes ILI9488, 480×320 quer | Home Assistant |
| `hvv-direct` | ESP32 DevKit + externes ILI9341 | Direkt per HTTPS zum Hintergrunddienst |

Für ein anderes Board `-Profile` auf den Profilnamen setzen. Eigene Namen,
`board_entity` und Pin-Änderungen gehören nur in die zugehörige `*.local.yaml`.
Gemeinsame Dateien in `boards/` und `packages/` nicht editieren. Die direkten
Profile `hvv-cyd` und `hvv-direct` benötigen `backend_url` und
`backend_authorization`. Das Setup-Skript fragt die HTTPS-Adresse und das
Webpasswort verdeckt ab und erzeugt den Authorization-Wert.

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

Für `hvv-cyd` zusätzlich `backend_url` auf die erreichbare
`https://<Hostname>:8080/api/esphome`-Adresse setzen. `backend_authorization` ist
`Basic` plus Base64 aus `hvv-anzeiger:<Webpasswort>`. Diese Werte sind für den
direkten CYD-Betrieb nötig; das HA-Profil `hvv-cyd-ha` nutzt sie nicht.
Den Authorization-Wert kannst du ohne das Passwort in der Shell-History so
erzeugen:

```sh
python -c 'import base64,getpass; print("Basic " + base64.b64encode(("hvv-anzeiger:" + getpass.getpass("Backend-Webpasswort: ")).encode()).decode())'
```

Die Ausgabe kommt in die Zeile `backend_authorization` der lokalen
`secrets.yaml`. Teile sie nicht in Chats oder Issues.

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

## Direkt per HTTPS

Das Standardprofil `hvv-cyd.yaml` und das generische Profil `hvv-direct.yaml`
benötigen kein laufendes HA für die Abfahrtsanzeige, aber weiterhin den
Python-Hintergrunddienst. In `secrets.yaml` `backend_url` auf
`https://<Hostname>:8080/api/esphome` und `backend_authorization` auf
`Basic <Base64 von hvv-anzeiger:Webpasswort>` setzen. Base64 ist keine
Verschlüsselung; diese Zugangsdaten nur über HTTPS übertragen. Das Windows-
Setup-Skript fragt Adresse und Webpasswort ab und erzeugt den Authorization-Wert.
Manuelle Installationen tragen diese Werte selbst ein.
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
