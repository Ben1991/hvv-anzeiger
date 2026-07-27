#!/usr/bin/env bash

set -Eeuo pipefail

ENV_FILE="${HVV_ENV_FILE:-/etc/hvv-anzeiger.env}"
FORCE=0
ROOT_TEMP_FILE=""
geofox_user=""
geofox_password=""

cleanup() {
  if [[ -n "$ROOT_TEMP_FILE" ]]; then
    sudo rm -f -- "$ROOT_TEMP_FILE" 2>/dev/null || true
  fi
}
trap cleanup EXIT

fail() {
  echo "Fehler: $*" >&2
  exit 1
}

usage() {
  cat <<'EOF'
Verwendung: ./configure-credentials.sh [--force]

Speichert die Geofox Application-ID und das Passwort geschützt unter
/etc/hvv-anzeiger.env. Vorhandene vollständige Zugangsdaten bleiben ohne
--force unverändert.
EOF
}

credential_present() {
  local key="$1"
  [[ -e "$ENV_FILE" ]] || return 1
  sudo awk -v key="$key" '
    index($0, key "=") == 1 {
      value = substr($0, length(key) + 2)
      if (value != "" && value != "\"\"" && value != "\047\047") {
        found = 1
      }
    }
    END { exit found ? 0 : 1 }
  ' "$ENV_FILE"
}

credentials_complete() {
  credential_present "GEOFOX_USER" &&
    credential_present "GEOFOX_PASSWORD"
}

prompt_nonempty() {
  local variable_name="$1"
  local prompt="$2"
  local hidden="$3"
  local value=""

  while [[ ! "$value" =~ [^[:space:]] ]]; do
    if [[ "$hidden" == "true" ]]; then
      IFS= read -r -s -p "$prompt" value ||
        fail "Eingabe wurde abgebrochen."
      echo
    else
      IFS= read -r -p "$prompt" value ||
        fail "Eingabe wurde abgebrochen."
    fi
    if [[ ! "$value" =~ [^[:space:]] ]]; then
      echo "Der Wert darf nicht leer sein." >&2
    fi
  done

  if [[ "$value" == *$'\r'* || "$value" == *$'\n'* ]]; then
    fail "Zugangsdaten dürfen keinen Zeilenumbruch enthalten."
  fi
  printf -v "$variable_name" "%s" "$value"
}

quote_environment_value() {
  local escaped="$1"
  escaped="${escaped//\\/\\\\}"
  escaped="${escaped//\"/\\\"}"
  escaped="${escaped//\$/\\$}"
  escaped="${escaped//\`/\\\`}"
  printf '"%s"' "$escaped"
}

write_credentials() {
  local user="$1"
  local password="$2"

  ROOT_TEMP_FILE="$(sudo mktemp "${ENV_FILE}.tmp.XXXXXX")"
  {
    printf "GEOFOX_USER="
    quote_environment_value "$user"
    printf "\nGEOFOX_PASSWORD="
    quote_environment_value "$password"
    printf "\n"
  } | sudo tee "$ROOT_TEMP_FILE" >/dev/null
  sudo chown root:root "$ROOT_TEMP_FILE"
  sudo chmod 0600 "$ROOT_TEMP_FILE"
  sudo mv -f -- "$ROOT_TEMP_FILE" "$ENV_FILE"
  ROOT_TEMP_FILE=""
}

case "${1:-}" in
  "")
    ;;
  --force)
    FORCE=1
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

command -v sudo >/dev/null 2>&1 || fail "sudo wurde nicht gefunden."
if [[ "${EUID}" -eq 0 ]]; then
  fail "Bitte als normaler Benutzer starten (nicht mit sudo)."
fi

if ((FORCE == 0)) && credentials_complete; then
  sudo chown root:root "$ENV_FILE"
  sudo chmod 0600 "$ENV_FILE"
  echo "Geofox-Zugangsdaten sind bereits vollständig hinterlegt."
  exit 0
fi

echo "Geofox-Zugangsdaten einrichten"
echo "Das Passwort bleibt bei der Eingabe unsichtbar."
prompt_nonempty geofox_user "Geofox Application-ID: " false
prompt_nonempty geofox_password "Geofox Passwort: " true
write_credentials "$geofox_user" "$geofox_password"
unset geofox_password

echo "Geofox-Zugangsdaten wurden geschützt in ${ENV_FILE} gespeichert."
