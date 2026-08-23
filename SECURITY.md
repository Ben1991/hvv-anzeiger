# Sicherheitsrichtlinie

## Unterstützte Version

| Version | Unterstützt |
|---|---|
| `V1` (veröffentlicht am 10. August 2026) | Nein |
| `V2` (veröffentlicht am 18. August 2026) | Ja |
| `V2.1` (veröffentlicht am 18. August 2026) | Ja |
| `V2.2` (veröffentlicht am 23. August 2026) | Ja |
| `main` (Entwicklungsstand) | Ja, sofern nicht anders angegeben |

V2.2 ist die aktuelle veröffentlichte Version und entspricht dem unveränderlichen
Git-Tag [`V2.2`](https://github.com/Ben1991/hvv-anzeiger/releases/tag/V2.2).
V1 bleibt als nicht mehr unterstützte Veröffentlichung dokumentiert.
Sicherheitskorrekturen werden für V2.2 und den aktuellen Stand des Branches `main` bereitgestellt,
soweit die Korrektur auf diese Versionen anwendbar ist.
Ältere Commits, Forks und lokal veränderte Installationen werden nicht separat
unterstützt.

## Sicherheitslücke vertraulich melden

Eine vermutete Sicherheitslücke bitte nicht in einem öffentlichen Issue, einer
Diskussion oder einem Pull Request veröffentlichen. Stattdessen auf der
GitHub-Seite dieses Repositorys unter **Security → Advisories → Report a
vulnerability** einen privaten Bericht erstellen:

<https://github.com/Ben1991/hvv-anzeiger/security/advisories/new>

Der Bericht sollte enthalten:

- betroffene Version oder Commit-ID,
- verständliche Beschreibung und mögliche Auswirkungen,
- reproduzierbare Schritte oder einen kleinen Proof of Concept,
- bekannte Voraussetzungen und mögliche Abhilfen,
- eine Kontaktmöglichkeit für Rückfragen.

Keine echten Geofox-Zugangsdaten, WLAN-Passwörter oder andere Geheimnisse
übermitteln. Wurde ein Geheimnis offengelegt, muss es beim zuständigen Anbieter
widerrufen oder geändert werden; das Entfernen aus Git allein macht es nicht
wieder sicher.

Der Eingang soll nach Möglichkeit innerhalb von sieben Tagen bestätigt werden.
Zeitpunkt und Umfang einer Korrektur hängen von Schweregrad, Reproduzierbarkeit
und verfügbarer Wartungskapazität ab. Dies ist keine garantierte Reaktionszeit
und kein Bug-Bounty-Programm.

## Koordinierte Veröffentlichung

Details erst veröffentlichen, nachdem eine Korrektur oder eine abgestimmte
Abhilfe verfügbar ist. Der Melder erhält, soweit praktikabel, Gelegenheit zur
Prüfung und kann auf Wunsch in der Veröffentlichung genannt werden.

Untersuchungen in gutem Glauben sollten ausschließlich eigene Systeme und
Testzugänge verwenden, keine Fahrgast- oder Drittdaten abrufen, den Geofox-Dienst
nicht belasten und keine Verfügbarkeit beeinträchtigen. Maßgeblich bleiben die
Nutzungsbedingungen der betroffenen Dienste.

## Abgrenzung

Fehler in Geofox, HVV-Daten oder fremder Hardware liegen außerhalb der Kontrolle
dieses Projekts. Sicherheitsprobleme dieser Anbieter bitte zusätzlich über deren
offizielle Meldewege melden. Normale Programmfehler ohne Sicherheitsauswirkung
gehören in ein öffentliches
[GitHub-Issue](https://github.com/Ben1991/hvv-anzeiger/issues/new).
