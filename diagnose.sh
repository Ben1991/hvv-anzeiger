#!/usr/bin/env bash

set -u

APP_DIR="/opt/hvv-anzeiger"
ENV_FILE="/etc/hvv-anzeiger.env"
SERVICE_NAME="hvv-anzeiger"
LOG_CLEANUP_TIMER="hvv-anzeiger-log-cleanup.timer"
EXPECTED_SERVICE_USER="hvv-anzeiger"
WIFI_INTERFACE="${HVV_WIFI_INTERFACE:-wlan0}"
FAILURES=0
WARNINGS=0
PREVIEW_FILE="/tmp/hvv-anzeiger-diagnose-preview.png"

pass() {
  echo "OK: $*"
}

warn() {
  echo "WARNUNG: $*" >&2
  WARNINGS=$((WARNINGS + 1))
}

fail() {
  echo "FEHLER: $*" >&2
  FAILURES=$((FAILURES + 1))
}

if [[ "$(uname -s)" == "Linux" ]]; then
  pass "Linux erkannt ($(uname -m))"
else
  fail "Die Diagnose muss auf dem Raspberry Pi unter Linux laufen."
fi

if [[ -e /dev/spidev0.0 ]]; then
  pass "SPI-Gerät /dev/spidev0.0 ist verfügbar."
else
  fail "SPI-Gerät /dev/spidev0.0 fehlt. SPI aktivieren und neu starten."
fi

if [[ -r "/sys/class/net/${WIFI_INTERFACE}/carrier" ]] &&
  [[ "$(<"/sys/class/net/${WIFI_INTERFACE}/carrier")" == "1" ]]; then
  pass "WLAN-Schnittstelle ${WIFI_INTERFACE} ist verbunden."
else
  fail "WLAN-Schnittstelle ${WIFI_INTERFACE} ist nicht verbunden."
fi

if command -v timedatectl >/dev/null 2>&1; then
  NTP_ENABLED="$(timedatectl show --property=NTP --value 2>/dev/null || true)"
  NTP_SYNCED="$(
    timedatectl show --property=NTPSynchronized --value 2>/dev/null || true
  )"
  if [[ "$NTP_ENABLED" == "yes" ]]; then
    pass "Netzwerk-Zeitsynchronisierung ist aktiviert."
  else
    fail "Netzwerk-Zeitsynchronisierung ist nicht aktiviert."
  fi
  if [[ "$NTP_SYNCED" == "yes" ]]; then
    pass "Systemzeit ist synchronisiert."
  else
    fail "Systemzeit ist noch nicht synchronisiert."
  fi
else
  fail "timedatectl wurde nicht gefunden."
fi

if [[ -x "$APP_DIR/.venv/bin/hvv-preview" ]]; then
  if "$APP_DIR/.venv/bin/hvv-preview" "$PREVIEW_FILE"; then
    pass "Die lokale Display-Vorschau wurde erfolgreich gerendert."
    rm -f "$PREVIEW_FILE"
  else
    fail "Die Display-Vorschau konnte nicht gerendert werden."
  fi
else
  fail "Die installierte Anwendung wurde unter $APP_DIR nicht gefunden."
fi

if sudo grep -Eq '^GEOFOX_USER=.+$' "$ENV_FILE" 2>/dev/null &&
  sudo grep -Eq '^GEOFOX_PASSWORD=.+$' "$ENV_FILE" 2>/dev/null; then
  pass "Geofox-Zugangsdaten sind hinterlegt."
else
  fail "Geofox-Zugangsdaten fehlen oder sind unvollständig."
fi

if systemctl is-enabled --quiet "$SERVICE_NAME"; then
  pass "Der Dienst ist für den Autostart aktiviert."
else
  fail "Der Dienst ist nicht für den Autostart aktiviert."
fi

if systemctl is-active --quiet "$SERVICE_NAME"; then
  pass "Der Dienst läuft."
else
  fail "Der Dienst läuft nicht."
fi

if systemctl is-enabled --quiet "$LOG_CLEANUP_TIMER" &&
  systemctl is-active --quiet "$LOG_CLEANUP_TIMER"; then
  pass "Die wöchentliche Journal-Bereinigung ist aktiviert."
else
  fail "Die wöchentliche Journal-Bereinigung ist nicht aktiv."
fi

SERVICE_USER="$(systemctl show "$SERVICE_NAME" --property=User --value 2>/dev/null)"
if [[ "$SERVICE_USER" == "$EXPECTED_SERVICE_USER" ]]; then
  pass "Der Dienst läuft unter dem eingeschränkten Benutzer ${SERVICE_USER}."
  USER_GROUPS="$(id -nG "$SERVICE_USER" 2>/dev/null || true)"
  if [[ " $USER_GROUPS " == *" spi "* && " $USER_GROUPS " == *" gpio "* ]]; then
    pass "Dienstbenutzer hat Zugriff auf die Gruppen spi und gpio."
  else
    warn "Dienstbenutzer ist nicht Mitglied in spi und gpio; SupplementaryGroups wird verwendet."
  fi
else
  fail "Dienst läuft nicht unter dem erwarteten Benutzer ${EXPECTED_SERVICE_USER}."
fi

if [[ "$(stat -c '%U:%G' "$APP_DIR" 2>/dev/null)" == "root:root" ]]; then
  pass "Der Anwendungscode gehört root und ist für den Dienst schreibgeschützt."
else
  fail "Der Anwendungscode unter ${APP_DIR} muss root:root gehören."
fi

if [[ "$(stat -c '%U:%G' "$APP_DIR/var" 2>/dev/null)" ==
  "${EXPECTED_SERVICE_USER}:${EXPECTED_SERVICE_USER}" ]]; then
  pass "Nur das Laufzeitverzeichnis gehört dem Dienstbenutzer."
else
  fail "Das Laufzeitverzeichnis ${APP_DIR}/var hat einen falschen Eigentümer."
fi

echo
echo "Ergebnis: ${FAILURES} Fehler, ${WARNINGS} Warnungen"
if ((FAILURES > 0)); then
  echo "Details zum Dienst: journalctl -u ${SERVICE_NAME} -n 100 --no-pager"
  exit 1
fi

echo "Die Software-Voraussetzungen sind erfüllt."
echo "Displaybild, Orientierung und Farben bitte zusätzlich visuell prüfen."
