# Sicherheitsreview: Pi+ILI und ESP32+CYD

Stand: 19.11.2026. Dies ist ein manueller Review der Änderungen auf dem
Feature-Branch gegenüber dem gemergten PR #120. Der automatisierte Codex
Security-Diff-Scan konnte den Windows-Worktree nicht öffnen und meldete
„Review changes requires a non-bare Git worktree with a resolvable HEAD“.
Der Worktree selbst meldet lokal `is-bare-repository=false` und hat einen
auflösbaren `HEAD`; der Scan wurde daher nicht als erfolgreich ausgeführt
gewertet. Es gab keinen Live-Pi-, Live-Home-Assistant-, Geofox- oder
Hardwaretest.

## Pi+ILI: Python-Backend und optionale HA-Integration

### Behobener Befund — unbegrenzte HA-API-Antwort

- **Risiko:** Eine gefälschte mDNS-Ankündigung im LAN kann Home Assistant beim
  manuellen Einrichten zu einem fremden Endpunkt führen. Ohne Größenlimit
  konnte dessen JSON-Antwort unnötig viel Speicher belegen.
- **Änderung:** Config-Flow und Polling lesen höchstens 1 MiB plus ein Prüfbyte
  und lehnen größere Antworten vor dem JSON-Parsing ab.
- **Fundstellen:** `custom_components/hvv_anzeiger/config_flow.py` und
  `custom_components/hvv_anzeiger/__init__.py`.
- **Status:** Im Änderungssatz behoben; die Laufzeitprüfung mit einer
  installierten Home-Assistant-Instanz steht aus.

### Kein weiterer bestätigter Befund im geprüften Pi-Pfad

Die mDNS-Ankündigung enthält nur API-Pfad, Schema-Version und Transportart,
keine Anmeldedaten. Der entfernte Pi-Dienst verlangt TLS; die HA-Integration
prüft Zertifikate normal und sendet Zugangsdaten nicht bei HTTP-Redirects.
Home Assistant verlangt das Webpasswort erst im Einrichtungsdialog.

## ESP32+CYD: eigenständiger ESPHome-Backenddienst

### Verbleibendes Risiko — Geofox-Zugangsdaten im Firmwareabbild

- **Auswirkung:** Benutzername und HMAC-Geheimnis werden beim Build in die
  Firmware eingebettet. Wer ein Firmwareabbild erhält oder den Flash-Speicher
  physisch ausliest, kann die Geheimnisse möglicherweise extrahieren und den
  Geofox-Zugang missbrauchen.
- **Begrenzung:** Geheimnisse bleiben in lokalen, nicht versionierten
  ESPHome-Secrets-Dateien und werden weder über mDNS noch als HA-Entität
  veröffentlicht. Der Abruf nutzt HTTPS mit Zertifikatsprüfung und
  HMAC-SHA1 gemäß Geofox-Protokoll.
- **Empfehlung:** Geofox-Zugangsdaten mit minimal nötigen Rechten verwenden,
  Firmwaredateien privat halten und Zugangsdaten bei vermutetem Geräte- oder
  Artefaktzugriff rotieren. Flash-Verschlüsselung und Secure Boot wären eine
  zusätzliche physische Schutzmaßnahme, sind in diesem Änderungssatz aber
  nicht eingerichtet oder verifiziert.
- **Status:** Architekturbedingtes Restrisiko, keine unbeabsichtigte
  Geheimnisveröffentlichung im geprüften Änderungssatz festgestellt.

### Kein weiterer bestätigter Befund im geprüften ESP32-Pfad

Der ESP32 nutzt Geofox-HTTPS mit aktivierter Zertifikatsprüfung, begrenzt die
Geofox-Antwort auf 32 KiB, verwendet die verschlüsselte ESPHome-Native-API und
veröffentlicht nur den mDNS-Dienst des Geräts. Die CYD-Konfiguration hat kein
Webinterface und keine Pi-Backend-Abhängigkeit.

## Prüfumfang und offene Verifikation

- Manueller Diff-Review von Pi mDNS/Config-Flow/Coordinator, ESPHome Geofox-
  Transport und Secrets, Stationen-Updatehelfer, Abhängigkeiten und
  Installationsdokumentation.
- Der ESP32-CYD-Build und die Profilvalidierung liefen mit Wegwerf-Secrets;
  daraus folgt keine Prüfung realer Geofox-Anmeldedaten oder des Zielgeräts.
- Keine Prüfung des realen mDNS-Verhaltens auf Pi/NAS, der HA-Integration in
  einer laufenden Instanz oder des physischen Flash-Ausleseschutzes.
- Den Feature-PR nach Erstellung auf neue Code-Review-Kommentare prüfen und
  Befunde vor dem Merge beheben.
