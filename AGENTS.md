# AGENTS.md

Diese Hinweise ergänzen [CONTRIBUTING.md](CONTRIBUTING.md) und
[SECURITY.md](SECURITY.md). Dort festgelegte Projekt-, Sicherheits- und
Release-Regeln haben Vorrang.

## Zusammenarbeit und Arbeitsweise

- Lies vor Änderungen die einschlägigen Abschnitte in `README.md`, `docs/`,
  den betroffenen Quellcode und vorhandene Tests. Prüfe außerdem den Git-Status
  und arbeite auf einem eigenen Branch, nie direkt auf `main`.
- Halte Änderungen klein und auf das angefragte Ziel begrenzt. Bewahre
  bestehendes Verhalten, Konfigurationen und Kompatibilität, sofern die Aufgabe
  nichts anderes verlangt.
- Wenn Anforderungen oder Geräteangaben fehlen und sie die richtige Umsetzung
  beeinflussen, frage gezielt nach. Erfinde keine Anforderungen, Daten,
  Geofox-IDs, Funktionen oder Prüfergebnisse.
- Berichte direkt und sachlich. Trenne klar zwischen umgesetzt, lokal geprüft,
  in CI geprüft und tatsächlich am Gerät getestet. Ein erfolgreicher Build
  belegt keinen Gerätetest.
- Verändere keine installierte Konfiguration und starte, flashe oder
  konfiguriere keine Geräte oder Dienste ohne entsprechenden Auftrag.

## Geräte- und Installationskompatibilität

- Bestimme vor Änderungen den betroffenen Installationspfad und das konkrete
  Gerät. Raspberry Pi mit ILI-Display, Pi-/Linux-/NAS-Backend, native
  Home-Assistant-Integration, ESPHome-CYD und ESP32-Profile mit separaten
  Displays unterscheiden sich. Behandle sie nicht als austauschbare Varianten.
- Prüfe in der Dokumentation die genaue Platine, Displayrevision und
  Displaysteuerung, Auflösung, Ausrichtung und Anschlussbelegung. Die Namen
  ähnlicher CYD-Boards reichen nicht als Kompatibilitätsnachweis.
- Beurteile Änderungen an gemeinsam genutztem Code und Profilen für alle davon
  betroffenen, dokumentierten Geräte. Erhalte board-spezifische Einstellungen
  und Profile; verschiebe keine Pins, Displayparameter, Speicherpuffer oder
  Build-Optionen pauschal zwischen Boards.
- Behaupte Unterstützung nur für konkret dokumentierte und passende Modelle
  und Revisionen. Nenne bei Firmware- oder Displayänderungen, welche Profile
  validiert, gebaut und falls zutreffend physisch geprüft wurden. Beschreibe
  bekannte Grenzen offen.
- Halte die Integrationswege eindeutig: Die native Home-Assistant-Integration
  spricht mit dem Pi-/Container-Webdienst; ein eigenständiges CYD ruft Geofox
  selbst ab und wird über ESPHome angebunden. Verwechsle diese Wege weder in
  Code noch in Anleitungen.

## Produktangaben, Links und Zugangsdaten

- Prüfe Feature-Aussagen gegen den aktuellen Code und die passende
  Dokumentation. Beschreibe nur Funktionen, die der betreffende Installations-
  und Gerätepfad tatsächlich unterstützt.
- Füge Amazon-Affiliate-Links nur hinzu, wenn der Repository-Eigentümer den
  konkreten Link ausdrücklich bereitgestellt oder freigegeben hat. Derzeit
  bereitgestellter ESP32-Link:
  [https://link.amazon/B05zqAOgp](https://link.amazon/B05zqAOgp).
  Verwende ihn unverändert. Erzeuge keine Affiliate-URLs oder IDs, wandle
  normale Amazon-Links nicht in Affiliate-Links um und ersetze freigegebene
  Links nicht durch fremde Affiliate-Links. Kennzeichne Affiliate-Links
  gegenüber Lesern klar.
- Geofox-Zugangsdaten, WLAN-Passwörter, Tokens, private TLS-Schlüssel,
  personenbezogene Daten und lokale Konfigurationen gehören nicht in Commits,
  Logs, Screenshots oder öffentliche Beispiele. Bewahre HTTPS,
  Zertifikatsprüfung, Authentifizierung und Firmware-Update-Schutz.

## Änderungen und Pull Requests

- Folge dem Prüf- und Releaseablauf aus `CONTRIBUTING.md`. Berücksichtige bei
  Konfigurationsänderungen den dort beschriebenen Backup-Kompatibilitätsvertrag
  und erhalte historische Reader, Defaults und Fixtures.
- Aktualisiere README, Setup-Anleitungen und Beispielkonfigurationen, wenn
  Bedienung, unterstützte Geräte oder Konfiguration sich ändern.
- Fülle das Pull-Request-Template vollständig aus: Motivation, Änderungen,
  Produktwirkung, Risiken, tatsächlich ausgeführte Prüfungen und offene Punkte.
  Markiere nichts als geprüft, wenn es nicht ausgeführt wurde; kennzeichne
  nicht zutreffende Prüfungen kurz.
- Halte PRs fokussiert und beschreibe Kompatibilitätsgrenzen sowie betroffene
  Geräte ausdrücklich. Erforderliche Reviews und Checks bleiben bestehen.
