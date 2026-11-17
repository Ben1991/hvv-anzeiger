# Zeitschaltuhr, Stromunterbrechung und Kaltstart

## Ziel und Grenzen

Der Hauptfall ist ein fertig eingerichteter Raspberry Pi, dessen Versorgung
nachts durch eine Zeitschaltuhr abgeschaltet und morgens wieder eingeschaltet
wird. Ein normaler Shutdown darf keine Voraussetzung für den nächsten Start
der Anwendung sein. Es gibt keinen gespeicherten „läuft noch“-Schalter und
keine PID-Datei, die nach einem harten Abbruch manuell gelöscht werden muss.

Die Maßnahmen gelten auch, wenn der Prozess mitten in einem Schreibvorgang
abbricht. Voraussetzung bleibt, dass Kernel, Dateisystem und Speichermedium
nach der Stromrückkehr funktionsfähig sind. SIGKILL-Tests prüfen die
Anwendungsgrenzen, nicht das Verhalten einer physisch stromlosen SD-Karte.

## Normaler Betrieb und Boot

- Anzeige und Webdienst werden weiterhin über `multi-user.target` automatisch
  gestartet. Sie sind nur hinter `network.target` eingeordnet, nicht hinter
  einem möglicherweise auf WLAN/NTP wartenden `network-online.target` oder
  `time-sync.target`. Die Betriebssystem-Zeitsynchronisierung bleibt aktiviert.
- Die Pi-Anwendung selbst bestätigt die Uhr, bevor sie den signierten
  Abfahrtscache lädt oder Geofox-Abfragen startet. Vorher erscheint der
  Wartezustand. Anschließend greifen die vorhandenen Frische-/Backoff-Regeln;
  alte Abfahrten werden nicht durch einen neuen Abrufzeitstempel aufgefrischt.
- Der neue Prozess ersetzt den vorherigen Laufzeitstatus vor SPI-/Netzwerk-I/O.
  Zusätzlich speichert der Publisher die aktuelle Linux-Boot-ID intern in
  `health.json`. Ein Leser mit verfügbarer Boot-ID verwirft Dateien aus einem
  anderen Boot sowie ältere Dateien ohne passende ID. Die ID wird nicht in
  der öffentlichen Diagnose-API ausgegeben.
- Ohne lesbare Linux-Boot-ID bleibt die bisherige Heartbeat-Prüfung erhalten.
  Der strikte Bootvergleich ist auf dem Pi mit verfügbarem `/proc` wirksam.
- Für den Webdienst sind wie für die Anzeige dauerhafte Neustartversuche
  eingerichtet; das Stoppen ist auf zehn Sekunden begrenzt. Ein explizites
  `systemctl stop` bleibt eine absichtliche Deaktivierung bis zum nächsten Start.
- Betriebssystem-Dateisperren werden beim Prozessende und beim Reboot vom
  Kernel freigegeben. Eine verbliebene Sperrdatei ist keine gehaltene Sperre.

## Dauerhafte Daten

Die neue Schreibfunktion erzeugt eine private Datei neben dem Ziel, schreibt
den vollständigen Inhalt und führt vor dem atomaren Umbenennen `flush` und
`fsync` aus. Nach dem Umbenennen wird auf POSIX auch das Zielverzeichnis
synchronisiert. Zugangsdaten werden zusammen in einer Datei veröffentlicht;
das Webpasswort wird ausschließlich als Hash gespeichert. Schreibfehler werden
nicht als erfolgreiche Speicherung bestätigt.

Bei einem Abbruch vor der Veröffentlichung bleibt die alte Datei verwendbar.
Nach dem atomaren Austausch liegt die vollständige neue Datei vor. Ein Fehler
der abschließenden Verzeichnissynchronisierung wird weiterhin gemeldet: Die
neue Datei kann dann bereits sichtbar sein, ihre Dauerhaftigkeit ist aber noch
nicht bestätigt. Bei einem Abbruch einer Änderung kann daher der alte oder
neue Stand gelten; die UI kann einen unbeantworteten Speichervorgang nicht
nachträglich als bestätigt behandeln.

Eindeutige temporäre Dateinamen verhindern, dass ein Überbleibsel den nächsten
Schreibvorgang blockiert. Fremde oder eventuell noch verwendete temporäre
Dateien werden nicht pauschal gelöscht. Die bestehenden Konfigurationsbackups
und der signierte Abfahrtscache behalten ihre eigenen atomaren, bereits
synchronisierten Schreibpfade und Format-/Authentizitätsprüfungen.

Ein beschädigter, nicht lesbarer oder nicht schreibbarer Haltestellen-Cache ist
optional: Haltestellen werden bei Bedarf neu aufgelöst, und eine erfolgreiche
Live-Auflösung bleibt trotz fehlgeschlagener Cache-Speicherung verwendbar.
Ungültige Zugangsdaten und beschädigte aktive Einstellungen werden dagegen
nicht durch Defaults oder unsichere Anmeldung ersetzt.

Die CLI-Konfiguration synchronisiert ihre privaten temporären Dateien vor dem
Umbenennen und danach das Zielverzeichnis. Vorhandene gültige Zugangsdaten und
Webpasswörter werden bei einem gewöhnlichen Neustart nicht neu erzeugt.

## Installation und Updates

Die Paketinstallation und Vorschauprüfung geschehen im separaten Stagingbaum.
Generierte Skripte der virtuellen Umgebung erhalten dort schon ihre endgültigen
Pfade. Nach der Veröffentlichung entfällt die bisherige Neuinstallation der
Python-Pakete in den aktiven Anwendungsbaum.

Vor dem letzten Snapshot der Laufzeitdaten werden beide Dienste gestoppt.
Die Laufzeitdaten werden erneut aus den über Dateideskriptoren abgesicherten
Quellen übernommen; anschließend werden alle vorbereiteten Dateien auf das
Dateisystem synchronisiert. Die Zugriffsrechte des künftigen Anwendungspfads
werden ebenfalls vor dem Wechsel gesetzt.

Bei einem Update tauscht Linux die beiden Verzeichnisse mit
`renameat2(RENAME_EXCHANGE)` in einem atomaren Schritt. Der aktive Pfad fehlt
dadurch nicht zwischen zwei Umbenennungen. Die alte Version wird danach als
`.previous` aufbewahrt. Ein regulärer Rollback benutzt ebenfalls den atomaren
Tausch. Bei fehlender Kernel-/Dateisystemunterstützung gibt es keinen Rückfall
auf einen unsicheren Zwei-Schritt-Wechsel.

Units werden erst nach Aktivierung des vollständigen Anwendungsbaums und
einzeln über synchronisierte temporäre Dateien ersetzt. Die aktuelle Anwendung
unterstützt sowohl die vorherigen als auch die neuen Startargumente. Ein
Update darf diese Rückwärtskompatibilität künftig nicht unbemerkt aufgeben.
Zertifikatserneuerungen behalten einen vorhandenen privaten Schlüssel bei:
Altes und neues Zertifikat passen zu demselben Schlüssel. Zertifikate und
Rollbackdateien werden atomar unter Erhalt der vorgesehenen Rechte veröffentlicht.

Ein harter Abbruch kann einen vollständigen alten Baum im Stagingpfad oder
als `.previous` hinterlassen. Dieser verhindert nicht den Boot der aktiven
Anwendung. Vor einem weiteren Update muss ein vorhandenes `.previous`
weiterhin geprüft werden; es wird nicht blind gelöscht. Noch nicht beendete
Erstinstallationen haben keine vorherige funktionsfähige Version und müssen
gegebenenfalls erneut aus dem Checkout ausgeführt werden. Ein Abbruch von
APT, Firmware- oder Betriebssystemupdates wird durch den App-Installer nicht
zu einer atomaren Betriebssystemtransaktion.

## Betriebssystem

Ein intaktes Raspberry Pi OS kann sein Dateisystem beim Boot wie vorgesehen
prüfen beziehungsweise sein Journal wiederherstellen. Dieser PR schaltet
solche Prüfungen nicht ab, aktiviert aber auch keine unbeaufsichtigte
aggressive Dateisystemreparatur. Er verändert keine Partitionstabellen,
Bootdateien, Mountoptionen oder Overlay-Konfigurationen.

Ein schreibgeschütztes Root-/Boot-System kann die Risiken täglicher harter
Abschaltungen weiter reduzieren. Es benötigt hier eine getrennte, geplante
persistente Ablage für Konfiguration, Zugangsdaten und Cache sowie einen
Updateweg. Ein pauschales Aktivieren des Raspberry-Pi-Overlay-Modus würde
sonst Einstellungen oder installierte Updates beim Neustart verlieren lassen.
Alternativ erlaubt eine geeignete USV mit Shutdown-Signal ein reguläres
Herunterfahren, bevor die Zeitschaltuhr die Versorgung endgültig trennt.

Keine dieser Softwaremaßnahmen garantiert einen Boot bei defekter SD-Karte,
inkonsistentem Root-Dateisystem oder unvollständigem OS-Update. Die physische
Abnahme sollte auf einer gesicherten Testkarte erfolgen.

## Nachweise

`tests/test_power_loss.py` beendet echte Kindprozesse ohne Aufräumhandler:

- vor der Dateisynchronisierung, vor dem Rename und nach dem Rename einer
  Zugangsdatenänderung; danach werden vollständige Werte gelesen und durch
  einen weiteren Prozesslauf erneut gespeichert;
- während gehaltener Abfahrtscache- und Konfigurationssperren; ein neuer Prozess
  kann anschließend schreiben, eigene verwaiste Konfigurations-Stagingdateien
  werden unter der bestehenden Sperre bereinigt;
- vor und nach dem atomaren Versionsaustausch sowie vor und nach der Ablage
  der vorherigen Version; der aktive Pfad enthält immer einen vollständigen
  alten oder neuen Testbaum.

Weitere Tests prüfen Sync-Reihenfolge, volle beziehungsweise nicht schreibbare
Datenträger, private Dateirechte, Webpasswort nach Neuinstanziierung, Boot-ID,
Haltestellen-Cachefehler und den Übergang von fehlender zu bestätigter Uhrzeit.
Der Installer-Smoke-Test führt Erstinstallation, fertige Konsolenskripte,
Zertifikatserneuerung mit unverändertem Schlüssel und Rollback bei fehlgeschlagenem
Dienststart mit echten Dateien und virtueller Umgebung aus. Betriebssystem- und
systemd-Aufrufe sind darin simuliert; kein Pi wird konfiguriert.

### Lokales Ergebnis

364 Tests bestanden, 100 % Statement- und Branch-Abdeckung. Ruff, Paket-Build,
PNG-Vorschau und Bash-Syntaxprüfung bestanden. Der Installer-Smoke-Test bestand
einschließlich erzwungener Zertifikatserneuerung bei unverändertem Schlüssel
und dem absichtlich fehlgeschlagenen Dienststart mit anschließendem Rollback.

Beide Service-Units wurden zusätzlich mit `systemd-analyze verify` geprüft.
Dafür war ausschließlich `ExecStart` in temporären Kopien auf `/usr/bin/true`
gesetzt, da die Pi-Installationspfade in der Cloud fehlen. Das ist keine echte
Boot- oder systemd-Neustartprüfung. ShellCheck war lokal nicht installiert.

### Noch am Gerät auszuführen

1. SD-Karte sichern; Version, Pi-Modell, Betriebssystem und Stromversorgung
   dokumentieren. Neue Version über den regulären Installer übernehmen.
2. Ohne manuelle Anmeldung starten und `systemctl is-enabled` sowie
   `systemctl is-active` für beide HVV-Dienste prüfen.
3. Auf der Testkarte Versorgung im normalen Betrieb unterbrechen; auch während
   einer beobachteten Aktualisierung wiederholen. Nach dem Einschalten das
   automatische Booten und die unveränderte Anmeldung/Einstellungen prüfen.
4. Mit zunächst fehlendem WLAN/NTP booten, dann das Netzwerk bereitstellen.
   Wartezustand, anschließende Zeitbestätigung und automatische Aktualisierung
   sowie das Ausblenden zu alter Daten prüfen.
5. In HA darf der Status des vorherigen Boots nicht als aktueller gesunder
   Prozess erscheinen. Neue Lebenszeichen und Anzeigeprüfung separat prüfen.
6. Ergebnis mit PASS/FAIL/BLOCKED, Bootdauer und Logs festhalten. Ein Fehler auf
   Betriebssystem-/SD-Ebene muss getrennt von einem Anwendungsfehler behandelt
   werden; keine Tests auf der einzigen ungesicherten produktiven Karte.

Physischer Stromausfall, tatsächlicher OS-Boot und HA-Livekopplung: **NOT RUN**.
