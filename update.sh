#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
WEB_SERVICE="hvv-anzeiger-web.service"
cd "$SCRIPT_DIR"

if [[ "$(id -u)" -eq 0 ]]; then
  echo "Bitte als normaler Benutzer starten: ./update.sh (nicht mit sudo)." >&2
  exit 1
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "update.sh muss im main-Branch ausgeführt werden." >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Das Checkout enthält lokale Änderungen. Bitte zuerst sichern oder committen." >&2
  exit 1
fi

echo "Aktualisiere den Checkout ..."
git fetch origin --tags
git pull --ff-only origin main

echo "Installiere die neue Version ..."
"$SCRIPT_DIR/install.sh"

# A changed systemd unit is not necessarily restarted by enable --now when an
# older instance is already active. Reload and restart explicitly so the web
# service uses the just-installed bind address and configuration.
echo "Aktualisiere und prüfe den Webdienst ..."
sudo systemctl daemon-reload
sudo systemctl enable "$WEB_SERVICE"
sudo systemctl restart "$WEB_SERVICE" || {
  echo "Fehler: Die Weboberfläche konnte nach dem Update nicht gestartet werden." >&2
  exit 1
}
sudo systemctl is-active --quiet "$WEB_SERVICE" || {
  echo "Fehler: Die Weboberfläche ist nach dem Update nicht aktiv." >&2
  exit 1
}
echo "Weboberfläche ist aktiv und für den Autostart eingerichtet."
