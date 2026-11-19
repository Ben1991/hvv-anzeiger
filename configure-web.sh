#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${HVV_APP_DIR:-/opt/hvv-anzeiger}"
APP_USER="${HVV_APP_USER:-hvv-anzeiger}"
APP_GROUP="${HVV_APP_GROUP:-hvv-anzeiger}"
WEB_ENV_FILE="${HVV_WEB_ENV_FILE:-${APP_DIR}/var/web.env}"
CERT_DIR="${HVV_WEB_CERT_DIR:-/etc/hvv-anzeiger}"
CERT_FILE="${HVV_WEB_CERTFILE:-${CERT_DIR}/web.crt}"
KEY_FILE="${HVV_WEB_KEYFILE:-${CERT_DIR}/web.key}"
AVAHI_CONFIG="${HVV_AVAHI_CONFIG:-/etc/avahi/avahi-daemon.conf}"
FORCE_CERTIFICATE=0
TEMP_DIR=""
WEB_PASSWORD_INITIALIZED=0

cleanup() {
  if [[ -n "$TEMP_DIR" && -e "$TEMP_DIR" ]]; then
    rm -rf -- "$TEMP_DIR"
  fi
}
trap cleanup EXIT

fail() {
  echo "Fehler: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Verwendung: ./configure-web.sh [--force-certificate]

Ermittelt die aktuelle lokale IPv4-Adresse, richtet den geschützten
LAN-Webzugriff mit einem selbst signierten TLS-Zertifikat ein und gibt die
HTTPS-Adresse der Weboberfläche aus. Das Zertifikat wird nur neu erzeugt,
wenn es fehlt, die IP nicht enthält oder --force-certificate gesetzt ist.
EOF
}

valid_ipv4() {
  local candidate="$1"
  [[ "$candidate" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] || return 1
  awk -F. '
    NF == 4 && $1 <= 255 && $2 <= 255 && $3 <= 255 && $4 <= 255 { found = 1 }
    END { exit found ? 0 : 1 }
  ' <<<"$candidate"
}

detect_local_ipv4() {
  local candidate

  if command -v ip >/dev/null 2>&1; then
    candidate="$(ip -4 route get 1.1.1.1 2>/dev/null | awk '
      { for (field = 1; field <= NF; field++) if ($field == "src") {
          print $(field + 1)
          exit
        }
      }
    ')"
    if valid_ipv4 "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi

    candidate="$(ip -4 -o addr show scope global 2>/dev/null | awk '
      { split($4, address, "/"); print address[1]; exit }
    ')"
    if valid_ipv4 "$candidate"; then
      printf '%s\n' "$candidate"
      return 0
    fi
  fi

  if command -v hostname >/dev/null 2>&1; then
    while read -r candidate; do
      if valid_ipv4 "$candidate"; then
        printf '%s\n' "$candidate"
        return 0
      fi
    done < <(hostname -I 2>/dev/null | tr ' ' '\n')
  fi

  return 1
}

certificate_contains_ip() {
  sudo test -s "$CERT_FILE" || return 1
  sudo openssl x509 -in "$CERT_FILE" -noout -ext subjectAltName 2>/dev/null |
    grep -Fq "IP Address:${LOCAL_IP}" &&
    sudo openssl x509 -in "$CERT_FILE" -noout -ext subjectAltName 2>/dev/null |
    grep -Fq "DNS:hvv-anzeiger.local"
}

ensure_web_password() {
  [[ -x "$APP_DIR/.venv/bin/python" ]] ||
    fail "Die Python-Umgebung fehlt unter $APP_DIR/.venv."

  sudo install -d -o "$APP_USER" -g "$APP_GROUP" -m 0750 "$(dirname -- "$WEB_ENV_FILE")"
  if ! sudo test -f "$WEB_ENV_FILE"; then
    sudo install -o "$APP_USER" -g "$APP_GROUP" -m 0600 /dev/null "$WEB_ENV_FILE"
  fi
  if ! sudo grep -q '^HVV_WEB_PASSWORD_HASH=.*[^"[:space:]]' "$WEB_ENV_FILE"; then
    local password_hash
    password_hash="$(sudo "$APP_DIR/.venv/bin/python" -c \
      'from hvv_display.web import hash_web_password; print(hash_web_password("hvv-anzeiger"))')"
    [[ -n "$password_hash" ]] || fail "Der Erstpasswort-Hash konnte nicht erzeugt werden."
    sudo sed -i '/^HVV_WEB_PASSWORD_HASH=/d;/^HVV_WEB_PASSWORD_MUST_CHANGE=/d' "$WEB_ENV_FILE"
    printf 'HVV_WEB_PASSWORD_HASH="%s"\nHVV_WEB_PASSWORD_MUST_CHANGE="1"\n' "$password_hash" |
      sudo tee -a "$WEB_ENV_FILE" >/dev/null
    WEB_PASSWORD_INITIALIZED=1
  elif sudo "$APP_DIR/.venv/bin/python" -c '
import sys
from pathlib import Path
from hvv_display.web import verify_web_password
values = {}
for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    key, sep, value = line.partition("=")
    if sep: values[key] = value.strip().strip("\"\x27")
raise SystemExit(not verify_web_password("hvv-anzeiger", values.get("HVV_WEB_PASSWORD_HASH", "")) or values.get("HVV_WEB_PASSWORD_MUST_CHANGE") == "1")
' "$WEB_ENV_FILE"; then
    WEB_PASSWORD_INITIALIZED=1
    sudo sed -i '/^HVV_WEB_PASSWORD_MUST_CHANGE=/d' "$WEB_ENV_FILE"
    printf 'HVV_WEB_PASSWORD_MUST_CHANGE="1"\n' | sudo tee -a "$WEB_ENV_FILE" >/dev/null
  fi
  sudo chown "$APP_USER:$APP_GROUP" "$WEB_ENV_FILE"
  sudo chmod 0600 "$WEB_ENV_FILE"
}

ensure_device_token() {
  if ! sudo grep -q '^HVV_ESPHOME_API_TOKEN=.*[^"[:space:]]' "$WEB_ENV_FILE"; then
    local device_token
    device_token="$(sudo "$APP_DIR/.venv/bin/python" -c 'import secrets; print(secrets.token_urlsafe(32))')"
    [[ -n "$device_token" ]] || fail "Der CYD-Schlüssel konnte nicht erzeugt werden."
    sudo sed -i '/^HVV_ESPHOME_API_TOKEN=/d' "$WEB_ENV_FILE"
    printf 'HVV_ESPHOME_API_TOKEN="%s"\n' "$device_token" |
      sudo tee -a "$WEB_ENV_FILE" >/dev/null
    sudo chown "$APP_USER:$APP_GROUP" "$WEB_ENV_FILE"
    sudo chmod 0600 "$WEB_ENV_FILE"
  fi
}

ensure_mdns_name() {
  sudo test -f "$AVAHI_CONFIG" ||
    fail "Avahi-Konfiguration fehlt unter $AVAHI_CONFIG."
  if sudo grep -q '^host-name=' "$AVAHI_CONFIG"; then
    sudo sed -i 's/^host-name=.*/host-name=hvv-anzeiger/' "$AVAHI_CONFIG"
  else
    sudo sed -i '/^\[server\]/a host-name=hvv-anzeiger' "$AVAHI_CONFIG"
  fi
}

ensure_certificate() {
  sudo install -d -o root -g "$APP_GROUP" -m 0750 "$CERT_DIR"
  if ((FORCE_CERTIFICATE == 0)) && certificate_contains_ip; then
    return 0
  fi

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hvv-web-certificate.XXXXXX")"
  if sudo test -s "$KEY_FILE"; then
    # Keep the key during renewal: old and new certificates then both match,
    # including when power fails between individual file publications.
    sudo openssl req -x509 -days 825 -key "$KEY_FILE" \
      -out "$TEMP_DIR/web.crt" -subj "/CN=hvv-anzeiger.local" \
      -addext "basicConstraints=critical,CA:TRUE" \
      -addext "keyUsage=critical,digitalSignature,keyCertSign,keyEncipherment" \
      -addext "subjectAltName=IP:${LOCAL_IP},IP:127.0.0.1,DNS:localhost,DNS:hvv-anzeiger.local"
  else
    openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
      -keyout "$TEMP_DIR/web.key" -out "$TEMP_DIR/web.crt" \
      -subj "/CN=hvv-anzeiger.local" \
      -addext "basicConstraints=critical,CA:TRUE" \
      -addext "keyUsage=critical,digitalSignature,keyCertSign,keyEncipherment" \
      -addext "subjectAltName=IP:${LOCAL_IP},IP:127.0.0.1,DNS:localhost,DNS:hvv-anzeiger.local"
    sudo chown "root:$APP_GROUP" "$TEMP_DIR/web.key"
    sudo chmod 0640 "$TEMP_DIR/web.key"
    sudo python3 "$APP_DIR/hvv_display/install_state.py" --restore-file \
      "$TEMP_DIR/web.key" "$KEY_FILE"
  fi
  sudo chown "root:$APP_GROUP" "$TEMP_DIR/web.crt"
  sudo chmod 0644 "$TEMP_DIR/web.crt"
  sudo python3 "$APP_DIR/hvv_display/install_state.py" --restore-file \
    "$TEMP_DIR/web.crt" "$CERT_FILE"
}

case "${1:-}" in
  "")
    ;;
  --force-certificate)
    FORCE_CERTIFICATE=1
    ;;
  -h | --help)
    usage
    exit 0
    ;;
  *)
    usage >&2
    fail "Unbekannte Option: $1"
    ;;
esac

[[ "${EUID}" -ne 0 ]] || fail "Bitte als normaler Benutzer starten (nicht mit sudo)."
command -v sudo >/dev/null 2>&1 || fail "sudo wurde nicht gefunden."
command -v openssl >/dev/null 2>&1 || fail "openssl wurde nicht gefunden."
getent group "$APP_GROUP" >/dev/null ||
  fail "Die Dienstgruppe ${APP_GROUP} wurde nicht gefunden."

LOCAL_IP="$(detect_local_ipv4)" ||
  fail "Keine lokale IPv4-Adresse gefunden. WLAN verbinden und erneut versuchen."

ensure_web_password
ensure_device_token
ensure_mdns_name
sudo systemctl enable --now avahi-daemon
sudo systemctl restart avahi-daemon
ensure_certificate

echo "Weboberfläche ist für den LAN-Zugriff eingerichtet."
printf '  Adresse: https://%s:8080/\n' "$LOCAL_IP"
echo "  CYD-Adresse: https://hvv-anzeiger.local:8080/"
printf '  Zertifikat: %s\n' "$CERT_FILE"
if ((WEB_PASSWORD_INITIALIZED == 1)); then
  echo "  Benutzername: hvv-anzeiger"
  echo "  Erstpasswort: hvv-anzeiger (beim ersten Login zwingend ändern)."
fi
echo "  CYD-Schlüssel findest du nach dem Login unter Einstellungen."
printf '  Zertifikat-Fingerabdruck (SHA-256): '
sudo openssl x509 -in "$CERT_FILE" -noout -fingerprint -sha256 | cut -d= -f2
echo "  Bei der ersten Browserverbindung die Warnung für das lokale Zertifikat bestätigen."
