#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="/opt/hvv-anzeiger"
ENV_FILE="/etc/hvv-anzeiger.env"
SERVICE_NAME="hvv-anzeiger"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_USER="$(id -un)"
INSTALL_GROUP="$(id -gn)"
TEMP_SERVICE=""
SERVICE_WAS_ACTIVE=0
INSTALL_SUCCEEDED=0
VENV_BACKED_UP=0
VENV_BACKUP="${APP_DIR}/.venv.previous"

cleanup() {
  if [[ -n "$TEMP_SERVICE" && -f "$TEMP_SERVICE" ]]; then
    rm -f "$TEMP_SERVICE"
  fi
  if ((INSTALL_SUCCEEDED == 0 && VENV_BACKED_UP == 1)); then
    rm -rf "${APP_DIR}/.venv"
    mv "$VENV_BACKUP" "${APP_DIR}/.venv"
  fi
  if ((INSTALL_SUCCEEDED == 0 && SERVICE_WAS_ACTIVE == 1)); then
    echo "Installation fehlgeschlagen; vorherigen Dienst wieder starten." >&2
    sudo systemctl start "$SERVICE_NAME" || true
  fi
}
trap cleanup EXIT

fail() {
  echo "Fehler: $*" >&2
  exit 1
}

if [[ "${EUID}" -eq 0 ]]; then
  fail "Bitte als normaler Benutzer starten: ./install.sh (nicht mit sudo)."
fi

command -v sudo >/dev/null 2>&1 || fail "sudo wurde nicht gefunden."
command -v apt-get >/dev/null 2>&1 || fail "Dieses Skript benötigt Raspberry Pi OS/Debian."
command -v raspi-config >/dev/null 2>&1 || fail "raspi-config wurde nicht gefunden."

echo "[1/7] Systempakete installieren"
sudo apt-get update
sudo apt-get install -y \
  git \
  python3-dev \
  python3-venv \
  fonts-dejavu-core \
  libjpeg-dev \
  zlib1g-dev \
  libfreetype6-dev

echo "[2/7] SPI aktivieren"
sudo raspi-config nonint do_spi 0

echo "[3/7] Netzwerk-Zeitsynchronisierung aktivieren"
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true
else
  fail "timedatectl wurde nicht gefunden; eine korrekte Systemzeit ist erforderlich."
fi

echo "[4/7] Anwendung nach ${APP_DIR} kopieren"
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  SERVICE_WAS_ACTIVE=1
  sudo systemctl stop "$SERVICE_NAME"
fi
sudo install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" "$APP_DIR"
sudo install -d -o "$INSTALL_USER" -g "$INSTALL_GROUP" "$APP_DIR/var"
if [[ "$(realpath "$SOURCE_DIR")" != "$(realpath "$APP_DIR")" ]]; then
  sudo cp -R \
    "$SOURCE_DIR/hvv_display" \
    "$SOURCE_DIR/systemd" \
    "$SOURCE_DIR/docs" \
    "$SOURCE_DIR/tests" \
    "$APP_DIR/"
  sudo install -m 0644 \
    "$SOURCE_DIR/.gitignore" \
    "$SOURCE_DIR/README.md" \
    "$SOURCE_DIR/config.example.json" \
    "$SOURCE_DIR/constraints.txt" \
    "$SOURCE_DIR/pyproject.toml" \
    "$APP_DIR/"
  sudo install -m 0755 "$SOURCE_DIR/diagnose.sh" "$APP_DIR/diagnose.sh"
fi
sudo chown -R "$INSTALL_USER:$INSTALL_GROUP" "$APP_DIR"

echo "[5/7] Python-Umgebung installieren"
if [[ -e "$VENV_BACKUP" ]]; then
  fail "Temporäres Backup ${VENV_BACKUP} existiert bereits; bitte zuerst prüfen."
fi
if [[ -d "$APP_DIR/.venv" ]]; then
  mv "$APP_DIR/.venv" "$VENV_BACKUP"
  VENV_BACKED_UP=1
fi
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip
"$APP_DIR/.venv/bin/pip" install \
  --constraint "$APP_DIR/constraints.txt" \
  "$APP_DIR"

if [[ ! -f "$APP_DIR/config.json" ]]; then
  install -m 0644 "$APP_DIR/config.example.json" "$APP_DIR/config.json"
fi

echo "[6/7] Zugangsdaten-Datei vorbereiten"
if [[ ! -e "$ENV_FILE" ]]; then
  sudo install -m 0600 -o root -g root /dev/null "$ENV_FILE"
fi

echo "[7/7] Autostart installieren"
TEMP_SERVICE="$(mktemp)"
sed \
  -e "s/^User=.*/User=${INSTALL_USER}/" \
  -e "s/^Group=.*/Group=${INSTALL_GROUP}/" \
  "$APP_DIR/systemd/hvv-anzeiger.service" >"$TEMP_SERVICE"
sudo install -m 0644 "$TEMP_SERVICE" "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

if sudo grep -Eq '^GEOFOX_USER=.+$' "$ENV_FILE" &&
  sudo grep -Eq '^GEOFOX_PASSWORD=.+$' "$ENV_FILE"; then
  sudo systemctl restart "$SERVICE_NAME"
  echo
  echo "Installation abgeschlossen. Der Dienst läuft."
  echo "Status: systemctl status ${SERVICE_NAME}"
else
  echo
  echo "Installation abgeschlossen. Vor dem Start fehlen noch die Geofox-Zugangsdaten:"
  echo "  sudo nano ${ENV_FILE}"
  echo "  GEOFOX_USER=DEINE_APPLICATION_ID"
  echo "  GEOFOX_PASSWORD=DEIN_PASSWORT"
  echo
  echo "Danach starten:"
  echo "  sudo systemctl start ${SERVICE_NAME}"
fi

if ((VENV_BACKED_UP == 1)); then
  rm -rf "$VENV_BACKUP"
  VENV_BACKED_UP=0
fi
INSTALL_SUCCEEDED=1

echo
echo "Ein Neustart des Raspberry Pi wird empfohlen: sudo reboot"
