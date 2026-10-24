# Zum HVV-Anzeiger beitragen

Beiträge sind über Pull Requests willkommen. Direkte Änderungen an `main` sind
nicht vorgesehen.

## Vor dem Start

1. Für normale Fehler oder Verbesserungsvorschläge zuerst nach bestehenden
   Issues und Pull Requests suchen.
2. Sicherheitsprobleme ausschließlich nach
   [SECURITY.md](SECURITY.md) vertraulich melden.
3. Änderungen klein und thematisch fokussiert halten.
4. Keine Geofox-Zugangsdaten, personenbezogenen Daten, privaten Schlüssel oder
   lokale Konfigurationsdateien einreichen.

## Arbeitsablauf

Externe Beitragende erstellen einen Fork. Freigeschaltete Mitwirkende verwenden
für jede Änderung einen neuen Branch. Niemals direkt auf `main` arbeiten.

```bash
git clone https://github.com/DEIN-BENUTZERNAME/hvv-anzeiger.git
cd hvv-anzeiger
git checkout -b fix/kurze-beschreibung
```

Danach:

1. Änderung und zugehörige Tests gemeinsam umsetzen.
2. README oder Beispielkonfiguration aktualisieren, wenn sich Bedienung oder
   Konfiguration ändern.
3. Die Qualitätsprüfungen lokal ausführen.
4. Den Branch in den eigenen Fork oder das berechtigte Repository pushen.
5. Einen Pull Request gegen `Ben1991/hvv-anzeiger:main` öffnen.

Ein Pull Request muss die Motivation, die sichtbare Auswirkung, Risiken und die
ausgeführten Prüfungen beschreiben. Er darf keine sachfremden Änderungen
enthalten. Das beim Öffnen automatisch eingeblendete Pull-Request-Template
vollständig ausfüllen und nicht zutreffende Punkte kurz kennzeichnen.

## Lizenz der Beiträge

Das Projekt steht unter der GNU General Public License Version 3
(`GPL-3.0-only`). Mit dem Einreichen eines Beitrags bestätigt der Beitragende,
dass er die erforderlichen Rechte daran besitzt und ihn unter denselben
GPL-3.0-Bedingungen bereitstellt. Beitragende behalten das Urheberrecht an ihren
eigenen Beiträgen.

## Lokale Prüfung

Eine virtuelle Umgebung mit Python 3.11 oder neuer verwenden und die
festgeschriebenen Entwicklungsabhängigkeiten installieren:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes \
  --requirement requirements-dev.txt
.venv/bin/python -m pip install --no-build-isolation --no-deps --editable .
```

Vor dem Pull Request mindestens ausführen:

```bash
.venv/bin/ruff check .
.venv/bin/coverage run -m unittest discover -s tests -v
.venv/bin/coverage report
bash -n install.sh update.sh configure-credentials.sh diagnose.sh tests/install-smoke.sh
.venv/bin/python -m build --no-isolation
```

Die Coverage muss 100 Prozent bleiben. Der Pull Request wird außerdem unter den
von GitHub Actions unterstützten Python-Versionen sowie mit dem
Installer-Smoke-Test geprüft.

## Review und Merge

### Verbindlicher Backup-Kompatibilitätsvertrag

Neue HVV-Anzeiger-Versionen müssen alle bislang veröffentlichten Backup-Schemata
weiterhin lesen und in das aktuelle Schema migrieren können. Die App-Version
ist kein Grund, eine ältere Sicherung abzulehnen. Bestehende Schema-Reader,
historische Standardwerte und die Fixtures unter
`tests/fixtures/config-backups` dürfen weder entfernt noch nachträglich auf
neue Defaults umgestellt werden. Der Schema-Zähler darf nicht zurückgesetzt
werden.

Bei einem neuen Schema `CURRENT_SCHEMA_VERSION` erhöhen, einen Reader und eine
unveränderliche Fixture und Felddefinition in `SCHEMA_FIELDS` ergänzen und jede
notwendige Migration zum nächsten
Schema in `SCHEMA_UPGRADERS` registrieren. Ältere Reader bleiben erhalten.
Migrationen müssen gültige Einstellungen und deren Bedeutung bewahren,
offline arbeiten und vor der Vorschau stattfinden. Sie dürfen nichts in die
aktive Datei schreiben und keine Geheimnisse hinzufügen. Eine umbenannte oder
entfernte Einstellung benötigt eine explizite Übersetzung statt stiller
Verwerfung. Für neue optionale Einstellungen sind sichere Defaults nötig.

`tests/test_backup_compatibility.py` prüft alle veröffentlichten Reader und
Upgrade-Schritte, eingefrorene historische Defaults, Legacy-Dateien und den
Restore einer V1-Sicherung unter einer simulierten neuen App-/Schemaversion mit
veränderten Defaults. Diese Tests gehören verpflichtend zu jeder Release-CI.
Unbekannte neuere Formate und beschädigte Inhalte dürfen weiterhin sicher
abgelehnt werden; gültige ältere Formate dürfen nicht verloren gehen.

- Alle Änderungen an `main` müssen über einen Pull Request erfolgen.
- Die vorgeschriebenen GitHub-Actions-Prüfungen müssen erfolgreich sein.
- Der Code Owner `@Ben1991` muss die Änderung freigeben.
- Neue Commits nach einer Freigabe machen eine erneute Prüfung erforderlich.
- Nur der Repository-Administrator führt den Merge aus.
- Force-Pushes und das Löschen von `main` sind nicht erlaubt.

Eine Freigabe oder ein Merge ist nicht garantiert. Änderungen können zur
Überarbeitung zurückgegeben oder abgelehnt werden, wenn sie nicht zum
Projektumfang, zur Wartbarkeit, zu den Geofox-Bedingungen oder zum unterstützten
Raspberry-Pi-Setup passen.
