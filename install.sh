#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="/opt/hvv-anzeiger"
ENV_FILE="/etc/hvv-anzeiger.env"
SERVICE_NAME="hvv-anzeiger"
LOG_CLEANUP_TIMER="hvv-anzeiger-log-cleanup.timer"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="hvv-anzeiger"
APP_GROUP="hvv-anzeiger"
SERVICE_WAS_ACTIVE=0
INSTALL_SUCCEEDED=0
VENV_BACKED_UP=0
VENV_BACKUP="${APP_DIR}/.venv.previous"

cleanup() {
  if ((INSTALL_SUCCEEDED == 0 && VENV_BACKED_UP == 1)); then
    sudo rm -rf "${APP_DIR}/.venv"
    sudo mv "$VENV_BACKUP" "${APP_DIR}/.venv"
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

echo "[1/8] Systempakete installieren"
sudo apt-get update
sudo apt-get install -y \
  git \
  python3-dev \
  python3-venv \
  fonts-dejavu-core \
  libjpeg-dev \
  zlib1g-dev \
  libfreetype6-dev

echo "[2/8] SPI aktivieren"
sudo raspi-config nonint do_spi 0

echo "[3/8] Netzwerk-Zeitsynchronisierung aktivieren"
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true
else
  fail "timedatectl wurde nicht gefunden; eine korrekte Systemzeit ist erforderlich."
fi

echo "[4/8] Eingeschränkten Dienstbenutzer vorbereiten"
if ! getent group "$APP_GROUP" >/dev/null; then
  sudo groupadd --system "$APP_GROUP"
fi
if ! id -u "$APP_USER" >/dev/null 2>&1; then
  sudo useradd \
    --system \
    --gid "$APP_GROUP" \
    --home-dir "$APP_DIR" \
    --no-create-home \
    --shell /usr/sbin/nologin \
    "$APP_USER"
else
  sudo usermod \
    --gid "$APP_GROUP" \
    --home "$APP_DIR" \
    --shell /usr/sbin/nologin \
    "$APP_USER"
fi
for hardware_group in spi gpio; do
  getent group "$hardware_group" >/dev/null ||
    fail "Benötigte Hardware-Gruppe ${hardware_group} fehlt."
done
sudo usermod --append --groups spi,gpio "$APP_USER"

echo "[5/8] Anwendung nach ${APP_DIR} kopieren"
if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  SERVICE_WAS_ACTIVE=1
  sudo systemctl stop "$SERVICE_NAME"
fi
# Install the restricted unit before changing ownership so rollback also uses it.
sudo install -m 0644 \
  "$SOURCE_DIR/systemd/hvv-anzeiger.service" \
  "/etc/systemd/system/${SERVICE_NAME}.service"
sudo systemctl daemon-reload
sudo install -d -m 0755 -o root -g root "$APP_DIR"
sudo install -d -m 0750 -o "$APP_USER" -g "$APP_GROUP" "$APP_DIR/var"
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
    "$SOURCE_DIR/pyproject.toml" \
    "$SOURCE_DIR/requirements.txt" \
    "$APP_DIR/"
  sudo install -m 0755 \
    "$SOURCE_DIR/diagnose.sh" \
    "$SOURCE_DIR/install.sh" \
    "$APP_DIR/"
fi
sudo chown -R root:root "$APP_DIR"
sudo chown -R "$APP_USER:$APP_GROUP" "$APP_DIR/var"
sudo chmod 0750 "$APP_DIR/var"

echo "[6/8] Python-Umgebung installieren"
if [[ -e "$VENV_BACKUP" ]]; then
  fail "Temporäres Backup ${VENV_BACKUP} existiert bereits; bitte zuerst prüfen."
fi
if [[ -d "$APP_DIR/.venv" ]]; then
  sudo mv "$APP_DIR/.venv" "$VENV_BACKUP"
  VENV_BACKED_UP=1
fi
sudo python3 -m venv "$APP_DIR/.venv"
sudo -H "$APP_DIR/.venv/bin/pip" install \
  --require-hashes \
  --requirement "$APP_DIR/requirements.txt"
sudo -H "$APP_DIR/.venv/bin/pip" install \
  --no-build-isolation \
  --no-deps \
  "$APP_DIR"

if [[ ! -f "$APP_DIR/config.json" ]]; then
  sudo install -m 0644 -o root -g root \
    "$APP_DIR/config.example.json" "$APP_DIR/config.json"
fi
sudo chown root:root "$APP_DIR/config.json"
sudo chmod 0644 "$APP_DIR/config.json"

echo "[7/8] Zugangsdaten-Datei vorbereiten"
if [[ ! -e "$ENV_FILE" ]]; then
  sudo install -m 0600 -o root -g root /dev/null "$ENV_FILE"
fi

echo "[8/8] Autostart installieren"
sudo install -m 0644 \
  "$APP_DIR/systemd/hvv-anzeiger-log-cleanup.service" \
  "$APP_DIR/systemd/hvv-anzeiger-log-cleanup.timer" \
  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl enable --now "$LOG_CLEANUP_TIMER"

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
  sudo rm -rf "$VENV_BACKUP"
  VENV_BACKED_UP=0
fi
INSTALL_SUCCEEDED=1

echo
echo "Ein Neustart des Raspberry Pi wird empfohlen: sudo reboot"
