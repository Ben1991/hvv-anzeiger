#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${HVV_APP_DIR:-/opt/hvv-anzeiger}"
ENV_FILE="${HVV_ENV_FILE:-/etc/hvv-anzeiger.env}"
SYSTEMD_DIR="${HVV_SYSTEMD_DIR:-/etc/systemd/system}"
SERVICE_NAME="hvv-anzeiger"
LOG_CLEANUP_SERVICE="hvv-anzeiger-log-cleanup.service"
LOG_CLEANUP_TIMER="hvv-anzeiger-log-cleanup.timer"
WEB_SERVICE="hvv-anzeiger-web.service"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
APP_USER="hvv-anzeiger"
APP_GROUP="hvv-anzeiger"
WEB_ENV_FILE="${APP_DIR}/var/web.env"
BACKUP_DIR="${APP_DIR}.previous"
STAGING_DIR=""
UNIT_BACKUP_DIR=""
ENV_BACKUP_DIR=""
SERVICE_WAS_ACTIVE=0
SWITCHED=0
INSTALL_SUCCEEDED=0

fail() {
  echo "Fehler: $*" >&2
  exit 1
}

safe_remove_tree() {
  local target="$1"
  [[ -n "$target" && "$target" = /* && "$target" != "/" ]] ||
    fail "Unsicherer Löschpfad abgelehnt: ${target}"
  sudo rm -rf -- "$target"
}

backup_unit() {
  local unit="$1"
  if [[ -e "${SYSTEMD_DIR}/${unit}" ]]; then
    sudo cp -p "${SYSTEMD_DIR}/${unit}" "${UNIT_BACKUP_DIR}/${unit}"
  else
    sudo touch "${UNIT_BACKUP_DIR}/${unit}.missing"
  fi
}

restore_units() {
  local unit
  for unit in "$SERVICE_NAME.service" "$WEB_SERVICE" "$LOG_CLEANUP_SERVICE" "$LOG_CLEANUP_TIMER"; do
    if [[ -e "${UNIT_BACKUP_DIR}/${unit}.missing" ]]; then
      sudo rm -f -- "${SYSTEMD_DIR}/${unit}"
    elif [[ -e "${UNIT_BACKUP_DIR}/${unit}" ]]; then
      sudo cp -p "${UNIT_BACKUP_DIR}/${unit}" "${SYSTEMD_DIR}/${unit}"
    fi
  done
  sudo systemctl daemon-reload || true
}

restore_credentials() {
  if [[ -e "${ENV_BACKUP_DIR}/credentials.missing" ]]; then
    sudo rm -f -- "$ENV_FILE"
  elif [[ -e "${ENV_BACKUP_DIR}/credentials" ]]; then
    sudo cp -p "${ENV_BACKUP_DIR}/credentials" "$ENV_FILE"
  fi
}

cleanup() {
  local exit_code=$?
  if ((INSTALL_SUCCEEDED == 0)); then
    set +e
    if ((SWITCHED == 1)); then
      sudo systemctl stop "$SERVICE_NAME"
      if [[ -e "$APP_DIR" ]]; then
        safe_remove_tree "$APP_DIR"
      fi
      if [[ -e "$BACKUP_DIR" ]]; then
        sudo mv "$BACKUP_DIR" "$APP_DIR"
      fi
    elif [[ -n "$STAGING_DIR" && -e "$STAGING_DIR" ]]; then
      safe_remove_tree "$STAGING_DIR"
    fi
    if [[ -n "$UNIT_BACKUP_DIR" && -d "$UNIT_BACKUP_DIR" ]]; then
      restore_units
    fi
    if [[ -n "$ENV_BACKUP_DIR" && -d "$ENV_BACKUP_DIR" ]]; then
      restore_credentials
    fi
    if ((SERVICE_WAS_ACTIVE == 1)) && [[ -d "$APP_DIR" ]]; then
      echo "Installation fehlgeschlagen; vorherige Version wird gestartet." >&2
      sudo systemctl start "$SERVICE_NAME" || true
    fi
  fi
  if [[ -n "$UNIT_BACKUP_DIR" && -e "$UNIT_BACKUP_DIR" ]]; then
    safe_remove_tree "$UNIT_BACKUP_DIR"
  fi
  if [[ -n "$ENV_BACKUP_DIR" && -e "$ENV_BACKUP_DIR" ]]; then
    safe_remove_tree "$ENV_BACKUP_DIR"
  fi
  exit "$exit_code"
}
trap cleanup EXIT

for path in "$APP_DIR" "$ENV_FILE" "$SYSTEMD_DIR"; do
  [[ "$path" = /* && "$path" != "/" ]] ||
    fail "Installationspfade müssen sichere absolute Pfade sein: ${path}"
done
if [[ "${EUID}" -eq 0 ]]; then
  fail "Bitte als normaler Benutzer starten: ./install.sh (nicht mit sudo)."
fi

command -v sudo >/dev/null 2>&1 || fail "sudo wurde nicht gefunden."
command -v apt-get >/dev/null 2>&1 ||
  fail "Dieses Skript benötigt Raspberry Pi OS (Lite oder Desktop)."
command -v raspi-config >/dev/null 2>&1 || fail "raspi-config wurde nicht gefunden."
sudo -H python3 -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' ||
  fail "Python 3.10 oder neuer ist erforderlich."

echo "[1/9] Systempakete installieren"
sudo apt-get update
sudo apt-get install -y \
  git \
  python3-dev \
  python3-venv \
  fonts-dejavu-core \
  libjpeg-dev \
  zlib1g-dev \
  libfreetype6-dev

echo "[2/9] SPI aktivieren"
sudo raspi-config nonint do_spi 0

echo "[3/9] Netzwerk-Zeitsynchronisierung aktivieren"
if command -v timedatectl >/dev/null 2>&1; then
  sudo timedatectl set-ntp true
else
  fail "timedatectl wurde nicht gefunden; eine korrekte Systemzeit ist erforderlich."
fi

echo "[4/9] Eingeschränkten Dienstbenutzer vorbereiten"
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

echo "[5/9] Neue Version separat vorbereiten"
if [[ -e "$BACKUP_DIR" ]]; then
  fail "Rollback-Verzeichnis ${BACKUP_DIR} existiert bereits; bitte zuerst prüfen."
fi
sudo install -d -m 0755 "$(dirname "$APP_DIR")" "$SYSTEMD_DIR"
STAGING_DIR="$(sudo mktemp -d "${APP_DIR}.install.XXXXXX")"
sudo cp -R \
  "$SOURCE_DIR/hvv_display" \
  "$SOURCE_DIR/systemd" \
  "$SOURCE_DIR/docs" \
  "$SOURCE_DIR/tests" \
  "$STAGING_DIR/"
sudo install -m 0644 \
  "$SOURCE_DIR/.gitignore" \
  "$SOURCE_DIR/README.md" \
  "$SOURCE_DIR/config.example.json" \
  "$SOURCE_DIR/pyproject.toml" \
  "$SOURCE_DIR/requirements.txt" \
  "$STAGING_DIR/"
sudo install -m 0755 \
  "$SOURCE_DIR/configure-credentials.sh" \
  "$SOURCE_DIR/diagnose.sh" \
  "$SOURCE_DIR/install.sh" \
  "$STAGING_DIR/"
sudo install -d -m 0750 "$STAGING_DIR/var"
if [[ -d "$APP_DIR/var" ]]; then
  sudo cp -a "$APP_DIR/var/." "$STAGING_DIR/var/"
fi
if [[ -f "$APP_DIR/config.json" ]]; then
  sudo cp -p "$APP_DIR/config.json" "$STAGING_DIR/config.json"
else
  sudo install -m 0644 \
    "$STAGING_DIR/config.example.json" "$STAGING_DIR/config.json"
fi
sudo chown -R root:root "$STAGING_DIR"
sudo chown -R "$APP_USER:$APP_GROUP" "$STAGING_DIR/var"
sudo chmod 0755 "$STAGING_DIR"
sudo chmod 0750 "$STAGING_DIR/var"
sudo chown "$APP_USER:$APP_GROUP" "$STAGING_DIR/config.json"
sudo chmod 0640 "$STAGING_DIR/config.json"

echo "[6/9] Python-Umgebung installieren und lokal prüfen"
sudo python3 -m venv "$STAGING_DIR/.venv"
sudo -H "$STAGING_DIR/.venv/bin/pip" install \
  --require-hashes \
  --requirement "$STAGING_DIR/requirements.txt"
sudo -H "$STAGING_DIR/.venv/bin/pip" install \
  --no-build-isolation \
  --no-deps \
  "$STAGING_DIR"
sudo "$STAGING_DIR/.venv/bin/python" -m hvv_display.preview \
  "$STAGING_DIR/var/install-preview.png"
sudo rm -f "$STAGING_DIR/var/install-preview.png"

echo "[7/9] Geofox-Zugangsdaten einrichten"
ENV_BACKUP_DIR="$(sudo mktemp -d "${TMPDIR:-/tmp}/hvv-credentials.XXXXXX")"
if [[ -e "$ENV_FILE" ]]; then
  sudo cp -p "$ENV_FILE" "$ENV_BACKUP_DIR/credentials"
else
  sudo touch "$ENV_BACKUP_DIR/credentials.missing"
fi
HVV_ENV_FILE="$ENV_FILE" "$SOURCE_DIR/configure-credentials.sh"

echo "[8/9] Neue Version transaktional aktivieren"
UNIT_BACKUP_DIR="$(sudo mktemp -d "${TMPDIR:-/tmp}/hvv-units.XXXXXX")"
backup_unit "$SERVICE_NAME.service"
backup_unit "$WEB_SERVICE"
backup_unit "$LOG_CLEANUP_SERVICE"
backup_unit "$LOG_CLEANUP_TIMER"
sudo install -m 0644 \
  "$STAGING_DIR/systemd/hvv-anzeiger.service" \
  "${SYSTEMD_DIR}/${SERVICE_NAME}.service"
sudo install -m 0644 \
  "$STAGING_DIR/systemd/$WEB_SERVICE" \
  "${SYSTEMD_DIR}/${WEB_SERVICE}"
sudo install -m 0644 \
  "$STAGING_DIR/systemd/$LOG_CLEANUP_SERVICE" \
  "$STAGING_DIR/systemd/$LOG_CLEANUP_TIMER" \
  "$SYSTEMD_DIR/"

if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
  SERVICE_WAS_ACTIVE=1
  sudo systemctl stop "$SERVICE_NAME"
fi
if [[ -e "$APP_DIR" ]]; then
  sudo mv "$APP_DIR" "$BACKUP_DIR"
fi
SWITCHED=1
sudo mv "$STAGING_DIR" "$APP_DIR"
STAGING_DIR=""
sudo chmod 0755 "$APP_DIR"
# Console scripts contain the absolute venv path. Reinstalling the local package
# after the move rewrites their shebangs to the final application directory.
sudo -H "$APP_DIR/.venv/bin/python" -m pip install \
  --force-reinstall \
  --no-build-isolation \
  --no-deps \
  "$APP_DIR"
sudo "$APP_DIR/.venv/bin/python" -m hvv_display.preview \
  "$APP_DIR/var/install-preview.png"
sudo rm -f "$APP_DIR/var/install-preview.png"

if [[ ! -s "$WEB_ENV_FILE" ]]; then
  echo "Erzeuge ein zufälliges Web-Token für den LAN-Zugriff"
  WEB_TOKEN="$(sudo python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  printf 'HVV_WEB_TOKEN=%s\n' "$WEB_TOKEN" | sudo tee "$WEB_ENV_FILE" >/dev/null
  sudo chown "$APP_USER:$APP_GROUP" "$WEB_ENV_FILE"
  sudo chmod 0600 "$WEB_ENV_FILE"
fi

echo "[9/9] Autostart aktivieren und Ergebnis prüfen"
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"
sudo systemctl enable --now "$WEB_SERVICE"
sudo systemctl enable --now "$LOG_CLEANUP_TIMER"
sudo systemctl restart "$SERVICE_NAME" ||
  fail "Der neue Dienst konnte nicht gestartet werden."
sleep 2
sudo systemctl is-active --quiet "$SERVICE_NAME" ||
  fail "Der neue Dienst ist nach dem Start nicht aktiv."

INSTALL_SUCCEEDED=1
if [[ -e "$BACKUP_DIR" ]]; then
  safe_remove_tree "$BACKUP_DIR"
fi
if [[ -n "$UNIT_BACKUP_DIR" && -e "$UNIT_BACKUP_DIR" ]]; then
  safe_remove_tree "$UNIT_BACKUP_DIR"
  UNIT_BACKUP_DIR=""
fi
if [[ -n "$ENV_BACKUP_DIR" && -e "$ENV_BACKUP_DIR" ]]; then
  safe_remove_tree "$ENV_BACKUP_DIR"
  ENV_BACKUP_DIR=""
fi

echo
echo "Installation abgeschlossen:"
printf "  %-24s %s\n" "Anwendung" "$APP_DIR"
printf "  %-24s %s\n" "Geofox-Zugangsdaten" "$ENV_FILE (root:root, 0600)"
printf "  %-24s %s\n" "Dienst" "$(systemctl is-active "$SERVICE_NAME")"
printf "  %-24s %s\n" "Autostart" "$(systemctl is-enabled "$SERVICE_NAME")"
printf "  %-24s %s\n" "Log-Bereinigung" "$(systemctl is-active "$LOG_CLEANUP_TIMER")"
if [[ -e /dev/spidev0.0 ]]; then
  printf "  %-24s %s\n" "SPI" "/dev/spidev0.0 verfügbar"
else
  printf "  %-24s %s\n" "SPI" "nach Neustart erneut prüfen"
fi
echo
echo "Vollständige Prüfung nach dem Neustart: cd ${APP_DIR} && ./diagnose.sh"
echo "Ein Neustart des Raspberry Pi wird empfohlen: sudo reboot"
