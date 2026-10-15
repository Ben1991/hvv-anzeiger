# Prüfstand vom 15. Oktober 2026

Arbeitsbranch: `codex-feature/esphome-home-assistant`, Basis `987bc7d`.
Initialer lokaler Prüfstand auf Windows mit Python 3.12 und
ESPHome 2026.9.1 / ESP-IDF 5.5.5, vor den zusätzlichen Merge-Prüfungen.

| Prüfung | Ergebnis |
|---|---|
| Python-Regressionen im auf Windows ausführbaren Umfang | 252 Tests: 237 erfolgreich, 15 regulär übersprungen |
| Neue Backend-/HTTP-Vertragstests | alle 7 erfolgreich |
| Home-Assistant-YAML und Jinja-Vorlagen | 12 Szenarien erfolgreich |
| ESPHome-Konfigurationen | alle 4 gültig, C++-Quellen generiert |
| ESP32 DevKit / ILI9341 | Firmware vollständig gebaut, Factory- und OTA-Dateien erzeugt |
| Direkter HTTPS-Transport / ILI9341 | Firmware vollständig gebaut, Factory- und OTA-Dateien erzeugt |
| CYD / ILI9341 | Firmware vollständig gebaut, Factory- und OTA-Dateien erzeugt |
| ESP32-S3 / ILI9488 | Firmware vollständig gebaut, Factory- und OTA-Dateien erzeugt |
| C++-Anzeigelogik auf dem Host | erfolgreich mit ArduinoJson 7.4.3 und tatsächlichem Python-Snapshot |
| Ruff, Python-Kompilierung, Git-Whitespace-Prüfung | erfolgreich |
| Python-Wheel und Quellarchiv | gebaut; ESPHome-/HA-Beispiele im Quellarchiv, Geheimnisse/Buildcache ausgeschlossen |

Der native C++-Test führt den Produktionsheader aus. Nur die ESPHome-
Zeichenschnittstelle wird durch einen Test-Adapter ersetzt. Geprüft werden
Countdownvarianten, Uhrzeit, `sofort`, `AUS`, vollständige Übernahme, ungültige
Snapshots, Ablauf, Wiederholung alter Daten, ESP32-Neustart mit altem HA-Attribut, falsche Zeit,
Nachtmodus, ausgeschaltete Anzeige und Millisekundenzähler-Überlauf.
Die Zeichenaufrufe werden für 240×135, 320×240 und 480×320 geprüft;
das ist kein visueller Test eines echten Displays.

Neun Linux-spezifische Prüfungen sind im lokalen erfolgreichen Teillauf explizit
ausgenommen: sechs Shell-/Zugangsdaten-Installertests, zwei Systemd-Socket-Tests
und die Prüfung ausführbarer Unix-Dateirechte. Ein vollständiger lokaler
Testsuitenaufruf ist deshalb unter Windows nicht grün. Die vorhandenen
Linux-CI-Prüfungen bleiben bestehen. Die neuen CI-Jobs bauen alle vier
Firmwareprofile und den Backend-Container. Zusätzlich prüfen sie den
Compose-Start und das Ersetzen des Containers mit restriktiven Dateirechten,
TLS und Anmeldung sowie den Pi-Updateablauf mit einem lokalen Git-Remote.
Den aktuellen Status dieser Linux-Prüfungen vor dem Merge im Pull Request prüfen.

Lokal nicht live geprüft: Home-Assistant-Instanz und deren REST-/ESPHome-Kopplung,
Docker-Laufzeit, reale Geofox-Zugangsdaten sowie Flashen, Displaydarstellung,
Pinbelegung, Hintergrundbeleuchtung, Stromversorgung und WLAN-Ausfälle am Gerät.
Die erstellten Test-Firmwares enthalten Beispiel-WLAN-Werte und zufällige
Testschlüssel. Für den Einsatz zuerst die eigene Konfiguration anpassen und
neu bauen. Es wurde keine bestehende Installation geändert oder geflasht.
