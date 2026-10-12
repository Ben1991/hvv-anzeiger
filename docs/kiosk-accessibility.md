# Lesender Displaymodus und Kiosk

`/display` zeigt Abfahrten mit absoluten Uhrzeiten. Dashboard und Displaymodus
verwenden dieselbe begrenzte Web-Datenquelle; die Hardwareanzeige verwendet
dieselben Regeln für Backoff und das Ausblenden zu alter Daten. Der
Hardwaredienst hat einen eigenen Abrufzyklus. Ein erfolgreicher Webabruf ist
deshalb kein Nachweis eines funktionierenden Hardwaredisplays.

## Lesbarkeit und Bedienung

- Abfahrten stehen als Liste in einem benannten Bereich. Linien, Stationen,
  Ziel, semantische Uhrzeit und Status können der Reihe nach gelesen werden.
  Verspätungen und Ausfälle haben Text; Farbe ist nur ein Zusatz.
- Tab erreicht Standardansicht, Vollbild und die Aktualisierungspause.
  Enter/Leertaste bedienen die Schaltflächen. Der Fokus ist sichtbar und
  bleibt beim Datenwechsel erhalten. Die Pause ermöglicht ungestörtes Lesen.
- Kleine Ansichten ordnen Linie/Station, Ziel und Uhrzeit untereinander an.
  Lange Texte werden umgebrochen. Textvergrößerung bis 200 % und reduzierte
  Bewegung werden in den Browserprüfungen abgedeckt.
- Nur Änderungen am Fehlerzustand oder an Ausfällen/Verspätungen werden
  höflich angekündigt. Die laufende Altersanzeige und gewöhnliche Aktualisierungen
  sind keine Live-Regionen; sie unterbrechen Screenreader nicht laufend.
- Ohne JavaScript bleibt die initiale Ansicht lesbar, aktualisiert sich aber
  nicht automatisch. Die Seite weist darauf hin.

## Dauerbetrieb und Ausfälle

Die Seite lädt kein vollständiges Dokument im festen Takt neu. Sie fragt einen
geschützten JSON-Endpunkt ab, mit maximal einem aktiven Browserabruf und einem
20-Sekunden-Abbruchlimit. Web-Anfragen teilen sich einen Cache und eine Sperre;
ein weiterer Bildschirm löst innerhalb des Abrufintervalls keinen neuen
Geofox-Aufruf aus. Die Datenmenge ist auf 30 Abfahrten im Speicher begrenzt.

Bei Geofox-Fehlern wächst die Wartezeit wie beim Hardwaredienst auf höchstens
300 Sekunden; ein längeres `Retry-After` bleibt maßgeblich. Browser-Netzfehler
führen zu 30, 60, 120, 240 und anschließend 300 Sekunden Wartezeit. Es werden
keine Offline-Daten oder Geheimnisse in Browser-Storage geschrieben.

Letzter erfolgreicher Abruf, Datenalter und Fehlertext bleiben sichtbar. Nach
`api.max_stale_age_minutes` werden Abfahrten ausgeblendet, auch wenn der Browser
keinen Server mehr erreicht oder die Aktualisierung pausiert ist. Der letzte
Abrufzeitpunkt bleibt zur Einordnung sichtbar. Bei Verbindungserholung erfolgt
die nächste Aktualisierung im geplanten Takt. Ein Konfigurationswechsel verwirft
den vorherigen Stationsstand. 401/403 beendet automatische Wiederholungen und
fordert eine erneute Anmeldung über die Standardansicht an.

Der Gesundheitsstatus aus #58 ergänzt bekannte Nachtabschaltung und unbestätigte
Gerätezeit. Fehlende Gesundheitsdateien werden nicht als erfolgreicher
Hardwarebetrieb ausgegeben.

## Chromium auf Raspberry Pi OS

1. Zuerst `https://<raspberry-pi-ip>:8080/display` in einem normalen Browser
   öffnen und die bestehende Web-Anmeldung abschließen. Zertifikat und
   Vertrauenskette regulär einrichten; keine Zertifikatsprüfung deaktivieren.
2. Für browsergesteuertes Vollbild „Vollbild“ anklicken oder F11 verwenden.
   Der Seitenbutton benötigt eine Benutzeraktion und Browserunterstützung.
   Esc beziehungsweise der Vollbildbutton beendet API-Vollbild, F11 beendet
   das vom Browser aktivierte Vollbild.
3. Optional Chromium im Kioskmodus starten, zum Beispiel in der grafischen
   Sitzung von Raspberry Pi OS:

   ```sh
   chromium --kiosk 'https://<raspberry-pi-ip>:8080/display'
   ```

   Je nach Distribution heißt das Programm `chromium-browser`. Für Autostart
   die Anleitung der eingesetzten Raspberry-Pi-OS-Version verwenden, da sich
   Desktop-/Compositor-Konfigurationen unterscheiden.
4. „Standardansicht“ führt zum geschützten Dashboard zurück. Der Kioskmodus
   selbst bleibt eine Browserentscheidung; zum Beenden beispielsweise Alt+F4
   in der grafischen Sitzung verwenden. Er ist keine Zugriffssperre für das
   Betriebssystem und ersetzt keine Web-Anmeldung.

Zugangsdaten gehören weder in Startparameter/URLs noch in Autostartdateien oder
Browser-Storage. Vollbild und Kiosk verändern keine Authentifizierung,
TLS-Anforderung oder Security-Header. Konfiguration und Neustart sind in der
Displayansicht nicht als Aktionen vorhanden.

Quellen: [Fullscreen API](https://developer.mozilla.org/en-US/docs/Web/API/Element/requestFullscreen),
[Raspberry-Pi-Kioskanleitung](https://www.raspberrypi.com/tutorials/how-to-use-a-raspberry-pi-in-kiosk-mode/),
[Live-Regionen](https://developer.mozilla.org/en-US/docs/Web/Accessibility/ARIA/Guides/Live_regions),
[reduzierte Bewegung](https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion).

## Automatisierte und manuelle Qualitätsprüfung

`npm test --prefix browser` führt in CI sowohl die bestehenden Smoke-Tests als
auch `kiosk.spec.mjs` aus. Der Kiosktest startet eine lokale Datenfixture über
die echten Webrouten, ohne Geofox oder Hardware. Er prüft:

- axe-core mit WCAG-A/AA-Regeln einschließlich Kontrast auf Desktop, Mobil und
  bei 200-%-Textvergrößerung; keine Ausnahmen für die Displayansicht;
- Tastaturbedienung, sichtbaren Fokus, Pause, reduzierte Bewegung;
- lange Texte, benannte Liste, Ausfall-/Verspätungstexte und sparsames Ankündigen;
- Offline-Beibehaltung, Backoff, Altersgrenze und Wiederherstellung;
- tatsächliches Browser-API-Vollbild, abgewiesenes Vollbild und Stop bei 401;
- Desktop-/Mobil-Screenshots als Anhänge im Playwright-Bericht.

Python-Tests decken serverseitigen Cache, Rate-Limits, parallele Leser,
Konfigurationswechsel, Altersgrenze, Escaping und geschützte Endpunkte ab.
axe und DOM-Prüfungen ersetzen keinen echten Screenreader-Durchlauf. Ein
NVDA-/Orca-Test sowie langer Dauerbetrieb und grafischer Chromium-Kiosk auf
einem Raspberry Pi müssen separat am Zielgerät geprüft werden.
