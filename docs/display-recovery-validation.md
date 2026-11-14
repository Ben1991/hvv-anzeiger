# Automatische Wiederherstellung des Pi-Displays

## Verhalten

Ziel ist ein ILI9341 am Raspberry Pi, dessen Controller nach kurzzeitigem
Kontaktverlust ein weißes oder beschädigtes Bild zeigt, während der Host
erfolgreiche SPI-Schreibzugriffe meldet. Ein Fehlerhandler allein erkennt diesen
Fall nicht. Nach jeweils 60 Sekunden monotoner Laufzeit führt der nächste
Anzeigezyklus deshalb einen RST-Puls am konfigurierten GPIO aus: 100 ms LOW,
danach HIGH und 150 ms Wartezeit. Anschließend führt er zusätzlich einen
Software-Reset (0x01) aus, wartet 150 ms, spielt
die Initialisierung des installierten luma-Treibers erneut ab und wartet nach
Sleep Out (0x11) weitere 120 ms. Danach wird das ganze Bild neu übertragen.

Initialisierungsbefehle **und Registerparameter** werden einmal bei der
Treiberkonstruktion ohne Hardwarezugriff erfasst. luma sendet Parameter über
die Datenleitung mit DC=HIGH; nur Bilddaten nach Memory Write (0x2C) dürfen
bei der Aufzeichnung entfallen. Frühere Zwischenstände auf diesem Branch
erfassten nur Befehlsbytes. Der Resilienzreview hat diese unvollständige
Initialisierung korrigiert und die Tests entsprechend verschärft.

Auch nach Verbindungsfehlern wird dieselbe luma-Instanz mit derselben einmaligen
Initialisierungsaufzeichnung und demselben Exit-Hook weiterverwendet. Nur die
defekte SPI-Verbindung wird geschlossen und neu geöffnet. Ein solcher Neuaufbau
löscht zunächst das Panel, bevor die aktuelle Anzeige vollständig folgt.
Spätere Pixeltransfers und Befehle vergrößern die Aufzeichnung nicht.
Beim Konfigurationswechsel und regulären Dienstende werden alte Verbindungen
explizit geschlossen. Alte Exit-Hooks dürfen keine Befehle an freigegebene Pins
senden. Der dokumentierte LED-Anschluss liegt direkt an 3,3 V; lumas impliziter
Backlight-GPIO 18 wird deshalb nicht konfiguriert oder geschaltet.
Der vollständige Framebuffer verhindert, dass die Differenzoptimierung im
Treiber unveränderte Pixel nach einem Controller-Reset weglässt. Die Anwendung
überspringt identische Bilder zwischen den Resets weiterhin.

Die Prüfung läuft im vorhandenen Anzeigezyklus, auch nachts und bei
API-Fehlern. Deshalb ist das Wiederherstellungsfenster nach Wiederverbindung
60 Sekunden plus bis zu einem Anzeigezyklus und laufenden Netzwerkabfragen.
Die Routine schaltet weder Pi noch Display-Stromversorgung aus. Sie kann kurz
flackern. Ohne zuverlässige Strom-, Masse-, CS-, DC- und SPI-Verbindungen oder
bei einem Controller, der weder auf RST noch auf Befehle reagiert, ist keine Wiederherstellung
garantiert. Ein erfolgreicher SPI-Aufruf ist kein optischer Funktionsnachweis.

| Verbindung | Unterstützung nach stabiler Wiederverbindung | Nicht messbar/behebbar |
|---|---|---|
| SCK, MOSI, CS, DC | RST-Puls, Software-Reset, Initialisierung und vollständiges Bild | dauerhaft offene Leitung, tatsächlicher Signalpegel am Panel |
| RST | gezielter LOW/HIGH-Puls am konfigurierten GPIO; zusätzlich SPI-Reset | dauerhaft getrennte oder kurzgeschlossene Resetleitung |
| VCC, GND | Reset/Initialisierung nach zurückgekehrter Versorgung können helfen | Spannungsabfall und fehlende Versorgung; keine elektrische Schaltmöglichkeit |
| LED | keine Softwaremaßnahme beim dokumentierten 3,3-V-Anschluss | unterbrochene Versorgung der Hintergrundbeleuchtung |
| MISO, optional | für die Schreibausgabe nicht benutzt | kein Register- oder Bild-Readback implementiert |

Die Pin-Zuordnung folgt der Konfiguration, nicht einem fest verdrahteten GPIO
25. Der RST-Pin wird auch bei einem unterbrochenen Resetablauf wieder auf HIGH
gesetzt, sofern der GPIO-Treiber das noch zulässt. Bei Fehlern der
Treiberinitialisierung bleibt der Dienst aktiv und versucht es im nächsten
Zyklus erneut. Ein `--once`-Aufruf meldet eine gescheiterte Ausgabe mit Exit 1.

Die Anzeige-/Statusschleife schläft höchstens 15 Sekunden, auch wenn das
Geofox-Intervall größer ist. Geofox bleibt durch seinen eigenen nächsten
Abrufzeitpunkt begrenzt. Das Lebenszeichen erhält dadurch einen Timeout von
90 Sekunden statt eines durch das API-Intervall verlängerten Timeouts.
Ein alter Status aus der Zukunft wird nach einem Uhrzeitrücksprung nicht als
gesund interpretiert. Vor dem ersten SPI-/Netzwerkzugriff wird der alte
Prozessstatus durch einen neuen, zunächst unbekannten Displaystatus ersetzt.

Der systemd-Watchdog bleibt bei 90 Sekunden. `TimeoutStopSec=10` begrenzt das
Stoppen; `RestartSec=10` und `StartLimitIntervalSec=0` erhalten dauerhafte
Neustartversuche. `systemd-analyze verify` prüft eine ansonsten identische
Unit-Kopie mit `ExecStart=/usr/bin/true`, da der Pi-Installationspfad in der
Cloud nicht existiert. Die echten Startargumente werden zusätzlich in den
Repositorytests geprüft. Das ist kein Nachweis eines tatsächlich ausgelösten
Watchdog-Neustarts auf dem Pi.
Laufende Netzwerkaufrufe verzögern weiterhin den Anzeigezyklus. Ein im Kernel
ununterbrechbar blockierter Hardwarezugriff kann sich auch SIGKILL entziehen
und einen physischen Eingriff erfordern.

## Diagnose und Home Assistant

`health.json`, `/api/health` und `/api/diagnostics` enthalten das optionale
Objekt `display_diagnostics` mit `error_count`, `consecutive_failures`,
`recovery_attempts`, `recovery_successes`, `last_error_kind`, `last_error_at`
und `last_recovery_at`. Zeitpunkte sind UTC; Zähler gelten seit Dienststart.
Fehlerarten sind ausschließlich `none`, `initialization`, `reset` und `transfer`.
Rohe Exception-Texte und Pfade werden nicht exportiert. Alte Statusdateien ohne
diese Felder bleiben lesbar; ihr Displaydiagnosestatus bleibt unbekannt.
Ein Image-Backend liefert kein GPIO-Diagnoseobjekt.

Erst die erfolgreiche Bildübertragung nach einem Reset beziehungsweise
Treiber-Neuaufbau zählt als erfolgreiche Wiederherstellung. Eine vorsorgliche
Initialisierung erhöht keinen Fehlerzähler. Die Zähler messen keine
elektrischen Kontaktverluste und keine optischen Defekte.

Das [HA-Paket](../home-assistant/hvv.yaml) liefert `sensor.hvv_display_error`
und `binary_sensor.hvv_display_problem`. Beim Update zusätzlich
`hvv_health_url: https://<Hostname>:8080/api/diagnostics` in HA-Secrets ergänzen.
Der neue Endpunkt braucht dieselbe Anmeldung und TLS-Konfiguration, fragt
keine Geofox-Daten ab und antwortet auch bei einem Gerätefehler mit HTTP 200.
Damit kann HA Fehlerattribute lesen. `/api/health` behält unverändert die
Monitoring-Codes 200/503/500.

Aktive Fehler verschwinden nach erfolgreicher Ausgabe. Die letzte Fehlerart,
deren UTC-Zeit und der Gesamtzähler bleiben bis zum Dienstneustart erhalten.
Ein ausgebliebenes Lebenszeichen ergibt `service_unavailable`. Ein nicht
erreichbarer Webdienst ergibt nicht verfügbare Sensoren; ein alter oder
fehlender GPIO-Status wird nicht als gesund behandelt.

## Automatisierter Nachweis

Aus dem Repository-Verzeichnis:

```bash
.venv/bin/python -m unittest discover -s tests -p test_hardware.py -v
.venv/bin/python -m unittest discover -s tests -p test_main.py -v
.venv/bin/coverage run -m unittest discover -s tests -v
.venv/bin/coverage report
.venv/bin/ruff check .
```

- `test_real_driver_replays_initialization_and_full_frame_after_silent_loss`
  verwendet den echten luma-ILI9341-Treiber mit simulierten SPI-/GPIO-Endpunkten.
  Es prüft die 60-Sekunden-Grenze, den Reset vor den ursprünglichen
  Initialisierungsbefehlen, die nötigen Wartezeiten und die vollständige erneute
  Übertragung desselben RGB-Bildes (230.400 Byte). Auch ein zweiter Ausfall und
  das schwarze Bild werden geprüft. Treiber, SPI und Exit-Hook bleiben einmalig.
  Das simulierte Panel bleibt trotz erfolgreicher Schreibaufrufe weiß, bis es
  den Hardware-Reset und die Initialisierung empfängt; vorher ignoriert es
  sogar den SPI-Software-Reset. Danach übernimmt es wieder Pixel. Ohne korrekt
  übertragenen Pixelformatparameter (Register 0x3A, Wert 0x46) akzeptiert es
  weiterhin kein Bild. Der Test prüft die gesamte Befehls-/Datenreihenfolge.
- `test_hardware_reset_uses_real_luma_spi_backend_and_configured_gpio` führt
  auch die tatsächliche luma-SPI-Implementierung aus und prüft den RST-Puls auf
  einem abweichend konfigurierten GPIO vor dem ersten SPI-Resetbefehl.
- `test_interrupted_reset_releases_reset_pin_and_can_be_retried` prüft die
  Rückkehr auf HIGH nach einem abgebrochenen Reset.
- `test_reset_failure_propagates_and_does_not_postpone_next_attempt` injiziert
  einen SPI-Fehler beim Reset. Der Fehler wird weitergereicht und der
  Wiederherstellungszeitpunkt bei Misserfolg nicht verschoben.
- `test_silent_display_loss_recovers_even_when_visible_frame_is_unchanged`
  führt die echte Anwendungsschleife und den echten luma-Treiber mit
  simulierter Zeit und Hardware aus. Sechs Zyklen mit gleichem Bild erzeugen
  genau zwei vollständige Bildausgaben: anfangs und nach 60 Sekunden.
  Der Ablauf wird tagsüber und nachts geprüft; nachts bleibt das Bild schwarz
  und es erfolgen keine Geofox-Abfragen.
- Weitere Schleifentests injizieren Initialisierungs- und Resetfehler, prüfen
  die veröffentlichten Fehlerkategorien/Zähler und die anschließende Erholung.
  Ein gescheiterter PNG-Export wird nicht als GPIO-Fehler gezählt.
- `test_thousand_failed_connections_keep_one_driver_and_no_open_handles`
  öffnet echte Betriebssystem-Dateideskriptoren an simulierten SPI-Endpunkten:
  Nach jedem von 1.000 fehlgeschlagenen Verbindungsversuchen bleibt kein Handle
  offen. Anschließend gelingen die Initialisierung, eine vollständige Ausgabe,
  die Erholung nach einem Übertragungsfehler und 1.000 periodische Resets.
  Es bleibt bei einem luma-Gerät/Exit-Hook; höchstens eine Verbindung ist offen,
  Registeraufzeichnung und RGB-Bild bleiben korrekt. Schließen ist idempotent;
  der alte Exit-Hook darf keine Pins erneut beschreiben.
- Der echte luma-Code wird mit einem Backlight-GPIO-Backend geprüft, das nicht
  aufgerufen werden darf. Ein API-Intervall von einer Stunde wird mit sechs
  Anzeigezyklen simuliert: Reset und Statusprüfung bleiben aktiv, während
  Geofox genau einmal abgefragt wird. Startup-Status, Konfigurationswechsel
  während eines Ausfalls und ein Uhrzeitrücksprung sind ebenfalls abgedeckt.
- `test_home_assistant.py` liest das ausgelieferte YAML und rendert die echten
  Jinja-Vorlagen für Fehler, Wiederherstellung, Historie, fehlenden/alten Status,
  Dienststillstand und Netzwerkfehler. HTTP-Tests prüfen Anmeldung, Fehlerdaten
  trotz HTTP 200 und Diagnose ohne Geofox-Aufruf. Das ist kein Live-HA-Test.

Diese Tests beweisen den Softwareablauf und die gesendeten Befehle/Bilddaten.
Sie beweisen keine sichtbare Wiederherstellung eines physischen Panels.

Zusätzlicher Negativnachweis: Im Testprozess wurde ausschließlich die
Replay-Methode vorübergehend durch eine Variante ersetzt, die Registerparameter
auslässt. Der verschärfte Paneltest scheitert dann mit genau einem erwarteten
Assertion-Fehler. Diese Mutation wurde nicht in Repositorydateien geschrieben;
der normale vollständige Lauf verwendet den korrigierten Produktionscode.

Aktueller Cloud-Prüfstand: **321 Tests bestanden**, **100 % Statement- und
Branch-Abdeckung**, **Ruff, Paket-Build, Vorschau und Shell-Syntax bestanden**.
Der erste Stand (Commit `6114523`, nur Software-Reset) bestand 306 Tests.
Ein bestehender HTTP-413-Test traf wiederholt auf einen Broken Pipe, weil der
Server die übergroße Anfrage ablehnte, während der Client noch schrieb. Der
Test sendet jetzt eine übergroße Content-Length ohne Body und prüft unverändert
HTTP 413. Damit wird zusätzlich die Ablehnung allein anhand der Header geprüft.
Die physische Abnahme bleibt getrennt.

## Abnahme am Raspberry Pi – noch nicht ausgeführt

1. Commit, Pi-Modell, OS, Panel, Anschlussbelegung und `api.refresh_seconds`
   dokumentieren. Mit spannungsfreiem Aufbau alle Kontakte fest verbinden.
2. Aktualisierten Anzeigedienst starten. Sichtbares Bild und Dienstlaufzeit
   erfassen (`systemctl show hvv-anzeiger -p MainPID -p NRestarts`).
3. Mit stabiler Verkabelung mindestens zehn Minuten beobachten: regelmäßig
   lesbares Bild, akzeptables kurzes Flackern, kein Dienst- oder Pi-Neustart.
4. Falls das bekannte Weißbild im Betrieb erneut auftritt: zuerst nur
   beobachten und den Zeitpunkt dokumentieren. Keine Kontakte unter Spannung
   absichtlich lösen oder umstecken. Sobald die Verbindung wieder stabil ist,
   Wiederherstellung innerhalb des oben beschriebenen Zeitfensters filmen.
   Bei anhaltendem Fehler stromlos schalten und die Verkabelung reparieren.
5. Nach Wiederherstellung prüfen: vollständige Zeilen, richtige Farben und
   Rotation, fortlaufende Aktualisierung; PID und Neustartzähler unverändert.
6. Im konfigurierten Nachtfenster wiederholen: nach einer Initialisierung
   wieder schwarzes Bild, keine neuen Geofox-Abfragen durch den Reset.
7. HA-Paket und URL-Secret aktualisieren, HA-Konfiguration prüfen und neu
   starten. `sensor.hvv_display_error` und `binary_sensor.hvv_display_problem`
   prüfen; vorsorgliche Resets dürfen den Fehlerzähler nicht erhöhen. Einen
   erkannten Treiberfehler samt Fehlerart und Zähler beobachten und nach
   Wiederherstellung `none`/aus sowie erhaltene Historie verifizieren.
8. Ergebnis mit PASS/FAIL/BLOCKED, Zeiten und Belegen festhalten. Ein
   dauerhaft unterbrochener Kontakt ist ein Hardwarefehler; die Software kann
   fehlende Versorgung oder Leitungen nicht ersetzen.

Hardwareergebnis: **NOT RUN** – in der Cloud ist kein Pi-Display angeschlossen.
Live-Home-Assistant-Ergebnis: **NOT RUN** – keine HA-Instanz verbunden.
