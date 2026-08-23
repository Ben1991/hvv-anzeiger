#!/usr/bin/env bash

set -Eeuo pipefail

APP_DIR="${HVV_APP_DIR:-/opt/hvv-anzeiger}"
APP_USER="${HVV_APP_USER:-hvv-anzeiger}"
APP_GROUP="${HVV_APP_GROUP:-hvv-anzeiger}"
WEB_ENV_FILE="${HVV_WEB_ENV_FILE:-${APP_DIR}/var/web.env}"
CERT_DIR="${HVV_WEB_CERT_DIR:-/etc/hvv-anzeiger}"
CERT_FILE="${HVV_WEB_CERTFILE:-${CERT_DIR}/web.crt}"
KEY_FILE="${HVV_WEB_KEYFILE:-${CERT_DIR}/web.key}"
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
  [[ -s "$CERT_FILE" ]] || return 1
  openssl x509 -in "$CERT_FILE" -noout -ext subjectAltName 2>/dev/null |
    grep -Fq "IP Address:${LOCAL_IP}"
}

ensure_web_password() {
  if sudo test -s "$WEB_ENV_FILE" &&
    sudo awk -F= '
      $1 == "HVV_WEB_PASSWORD_HASH" && $2 != "" { found = 1 }
      END { exit found ? 0 : 1 }
    ' "$WEB_ENV_FILE"; then
    return 0
  fi

  [[ -x "$APP_DIR/.venv/bin/python" ]] ||
    fail "Die Python-Umgebung fehlt unter $APP_DIR/.venv."

  local password_hash
  password_hash="$(sudo "$APP_DIR/.venv/bin/python" -c \
    'from hvv_display.web import hash_web_password; print(hash_web_password("hvv-anzeiger"))')"
  [[ -n "$password_hash" ]] || fail "Der Webpasswort-Hash konnte nicht erzeugt werden."

  local temp_env
  temp_env="$(sudo mktemp "${WEB_ENV_FILE}.tmp.XXXXXX")"
  printf 'HVV_WEB_PASSWORD_HASH="%s"\n' "$password_hash" |
    sudo tee "$temp_env" >/dev/null
  sudo chown "$APP_USER:$APP_GROUP" "$temp_env"
  sudo chmod 0600 "$temp_env"
  sudo mv -f -- "$temp_env" "$WEB_ENV_FILE"
  WEB_PASSWORD_INITIALIZED=1
}

ensure_certificate() {
  sudo install -d -o root -g "$APP_GROUP" -m 0750 "$CERT_DIR"
  if ((FORCE_CERTIFICATE == 0)) && certificate_contains_ip; then
    return 0
  fi

  TEMP_DIR="$(mktemp -d "${TMPDIR:-/tmp}/hvv-web-certificate.XXXXXX")"
  openssl req -x509 -nodes -newkey rsa:2048 -days 825 \
    -keyout "$TEMP_DIR/web.key" \
    -out "$TEMP_DIR/web.crt" \
    -subj "/CN=${LOCAL_IP}" \
    -addext "subjectAltName=IP:${LOCAL_IP},IP:127.0.0.1,DNS:localhost"
  chmod 0600 "$TEMP_DIR/web.key"
  sudo install -o root -g "$APP_GROUP" -m 0640 \
    "$TEMP_DIR/web.key" "$KEY_FILE"
  sudo install -o root -g "$APP_GROUP" -m 0644 \
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
ensure_certificate

echo "Weboberfläche ist für den LAN-Zugriff eingerichtet."
printf '  Adresse: https://%s:8080/\n' "$LOCAL_IP"
printf '  Zertifikat: %s\n' "$CERT_FILE"
if ((WEB_PASSWORD_INITIALIZED == 1)); then
  echo "  Erstanmeldung: hvv-anzeiger / hvv-anzeiger"
  echo "  Das Webpasswort nach der ersten Anmeldung ändern."
fi
echo "  Bei der ersten HTTPS-Verbindung die Warnung für das selbst signierte Zertifikat bestätigen."
