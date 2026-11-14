# Automatische Wiederherstellung des Pi-Displays

## Verhalten

Ziel ist ein ILI9341 am Raspberry Pi, dessen Controller nach kurzzeitigem
Kontaktverlust ein weißes oder beschädigtes Bild zeigt, während der Host
erfolgreiche SPI-Schreibzugriffe meldet. Ein Fehlerhandler allein erkennt diesen
Fall nicht. Nach jeweils 60 Sekunden monotoner Laufzeit führt der nächste
Anzeigezyklus deshalb einen Software-Reset (0x01) aus, wartet 150 ms, spielt
die Initialisierung des installierten luma-Treibers erneut ab und wartet nach
Sleep Out (0x11) weitere 120 ms. Danach wird das ganze Bild neu übertragen.

Die Initialisierungsbefehle werden einmal bei der Treiberkonstruktion erfasst;
normale Pixeltransfers und spätere Befehle vergrößern die Aufzeichnung nicht.
Es werden keine regelmäßigen neuen luma-Instanzen oder Exit-Hooks angelegt.
Der vollständige Framebuffer verhindert, dass die Differenzoptimierung im
Treiber unveränderte Pixel nach einem Controller-Reset weglässt. Die Anwendung
überspringt identische Bilder zwischen den Resets weiterhin.

Die Prüfung läuft im vorhandenen Anzeigezyklus, auch nachts und bei
API-Fehlern. Deshalb ist das Wiederherstellungsfenster nach Wiederverbindung
60 Sekunden plus bis zu einem Anzeigezyklus und laufenden Netzwerkabfragen.
Die Routine schaltet weder Pi noch Display-Stromversorgung aus. Sie kann kurz
flackern. Ohne zuverlässige Strom-, Masse-, CS-, DC- und SPI-Verbindungen oder
bei einem Controller, der keine Befehle mehr annimmt, ist keine Wiederherstellung
garantiert. Ein erfolgreicher SPI-Aufruf ist kein optischer Funktionsnachweis.

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
  den Reset und die Initialisierung empfängt; danach übernimmt es wieder Pixel.
- `test_reset_failure_propagates_and_does_not_postpone_next_attempt` injiziert
  einen SPI-Fehler beim Reset. Der Fehler wird weitergereicht und der
  Wiederherstellungszeitpunkt bei Misserfolg nicht verschoben.
- `test_silent_display_loss_recovers_even_when_visible_frame_is_unchanged`
  führt die echte Anwendungsschleife und den echten luma-Treiber mit
  simulierter Zeit und Hardware aus. Sechs Zyklen mit gleichem Bild erzeugen
  genau zwei vollständige Bildausgaben: anfangs und nach 60 Sekunden.
  Der Ablauf wird tagsüber und nachts geprüft; nachts bleibt das Bild schwarz
  und es erfolgen keine Geofox-Abfragen.

Diese Tests beweisen den Softwareablauf und die gesendeten Befehle/Bilddaten.
Sie beweisen keine sichtbare Wiederherstellung eines physischen Panels.

Ergebnis in der Cloud auf Basis von `main`-Commit `2959820`: **306 Tests
bestanden**, **100 % Statement- und Branch-Abdeckung**, **Ruff bestanden**.

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
7. Ergebnis mit PASS/FAIL/BLOCKED, Zeiten und Belegen festhalten. Ein
   dauerhaft unterbrochener Kontakt ist ein Hardwarefehler; die Software kann
   fehlende Versorgung oder Leitungen nicht ersetzen.

Hardwareergebnis: **NOT RUN** – in der Cloud ist kein Pi-Display angeschlossen.
