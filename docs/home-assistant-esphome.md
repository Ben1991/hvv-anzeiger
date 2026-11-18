# Home Assistant und ESP32: Überblick

Der HVV-Anzeiger kann neben dem Raspberry Pi auch Home Assistant und ESP32-
Displays nutzen. Der Python-Hintergrunddienst übernimmt Geofox-Zugriff,
Haltestellenauflösung und Konfiguration. Home Assistant stellt Zustände und
Abfahrtsdaten bereit; ESPHome übernimmt WLAN, Anzeige, Diagnose und Updates am
ESP32. Der Pi bleibt nur als Diensthost nötig, nicht als physisches Display.

## Funktionsumfang

- Gemeinsame Abfahrtsdaten und Linienfilter für Pi, Home Assistant und ESP32.
- ESPHome-Profile für ILI9341, CYD ESP32-2432S028 sowie ESP32-S3/ILI9488.
- ESP32-Diagnosewerte für Heap-Speicher sowie Verbindungs- und Datenstatus.
- Optionaler direkter HTTPS-Transport vom ESP32 zum Hintergrunddienst.

## Welche Anleitung brauche ich?

- [Home Assistant und Hintergrunddienst einrichten](home-assistant.md):
  API, TLS, REST-Sensor, Paketdatei, Dashboard und HA-Updates.
- [ESP32 einrichten und flashen](esp32-setup.md):
  Hardwareprofile, automatisiertes Windows-Setup, Firmwarebau, USB-Flashen,
  Fehlerbehebung und OTA-Updates.

Für ein reines Raspberry-Pi-Display gelten weiter die
[Pi-Installation und -Dokumentation](../README.md#installieren).