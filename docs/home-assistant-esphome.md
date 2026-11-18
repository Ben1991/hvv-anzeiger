# Home Assistant und ESP32: Überblick

Der Python-Hintergrunddienst übernimmt Geofox-Zugriff, Haltestellenauflösung
und Konfiguration. Ein CYD-ESP32 kann seine Abfahrtsdaten direkt per HTTPS vom
Dienst holen und sie ohne Home Assistant anzeigen. Optional kann eine separate
ESPHome-Firmware das CYD über die HA-Integration einbinden. Der Pi bleibt nur
als Diensthost nötig, nicht als physisches Display.

## Funktionsumfang

- Gemeinsame Abfahrtsdaten und Linienfilter für Pi, Home Assistant und ESP32.
- ESPHome-Profile für ILI9341, CYD ESP32-2432S028 sowie ESP32-S3/ILI9488.
- ESP32-Diagnosewerte für Heap-Speicher sowie Verbindungs- und Datenstatus.
- Standard: direkter HTTPS-Transport vom CYD zum Hintergrunddienst, ohne HA.
- Separate optionale CYD-Firmware mit Home-Assistant-Transport.

## Welche Anleitung brauche ich?

- [Hintergrunddienst und optionale Home-Assistant-Integration](home-assistant.md):
  Backend, TLS, REST-Sensor, HA-Paketdatei, Dashboard und HA-Updates.
- [ESP32 einrichten und flashen](esp32-setup.md):
  Hardwareprofile, automatisiertes Windows-Setup, Firmwarebau, USB-Flashen,
  Fehlerbehebung und OTA-Updates.

Für ein reines Raspberry-Pi-Display gelten weiter die
[Pi-Installation und -Dokumentation](../README.md#installieren).
