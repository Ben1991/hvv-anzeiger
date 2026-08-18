#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
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
exec "$SCRIPT_DIR/install.sh"
