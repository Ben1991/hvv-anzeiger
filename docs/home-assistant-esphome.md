# Zwei getrennte HVV-Anzeiger-Systeme: Pi+ILI und ESP32+CYD

Pi+ILI und ESP32+CYD sind unabhängige Geräte und Backend-Systeme. Jedes bezieht
Geofox-Daten und zeigt Abfahrten ohne Home Assistant an. Ein System ist nicht
Backend des anderen.

## Funktionsumfang

- **Pi+ILI:** Python-Backend, Geofox-Zugang, Weboberfläche, Konfiguration,
  Sicherungen und Displayausgabe auf dem Pi. HA kann das Backend optional über
  die benutzerdefinierte, mDNS-entdeckbare Pi-Integration konsumieren.
- **ESP32+CYD:** schlanke ESPHome-Firmware mit direktem Geofox-Abruf,
  festgelegten Stationen und lokaler Displayausgabe. Keine Pi-Abhängigkeit,
  keine Weboberfläche und kein Home Assistant für den Anzeigebetrieb.
- HA erkennt das CYD über die integrierte ESPHome-Integration und empfängt
  Abfahrten, Status und Steuerungen über die verschlüsselte native API.
- Für beide Systeme getrennte Konfiguration und Geheimnisse; nur das
  versionierte Display-Datenmodell ist gemeinsam.

## Welche Anleitung brauche ich?

- [Raspberry-Pi-Backend und HA-Integration](home-assistant.md):
  Pi-Backend, TLS, REST-Sensor, automatische Erkennung, HA-Paketdatei und
  Dashboard.
- [ESP32 einrichten und flashen](esp32-setup.md):
  Hardwareprofile, automatisiertes Windows-Setup, Firmwarebau, USB-Flashen,
  Fehlerbehebung und OTA-Updates.
- [Haltestellen im ESP32/CYD-Profil ändern](esp32-stations.md):
  lokale Konfiguration prüfen, anpassen und Firmware neu flashen.

Für Installation und Updates des Pi-Systems gelten die
[Pi-Anleitung](../README.md#installieren). CYD-Stationen werden ausschließlich
im lokalen ESPHome-Profil gepflegt.
