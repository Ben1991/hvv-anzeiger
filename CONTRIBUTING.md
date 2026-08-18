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

Eine virtuelle Umgebung mit Python 3.10 oder neuer verwenden und die
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
