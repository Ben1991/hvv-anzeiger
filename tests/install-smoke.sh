#!/usr/bin/env bash

set -Eeuo pipefail

ROOT="$(mktemp -d)"
FAKE_BIN="$ROOT/bin"
APP_DIR="$ROOT/opt/hvv-anzeiger"
ENV_FILE="$ROOT/etc/hvv-anzeiger.env"
SYSTEMD_DIR="$ROOT/systemd"
SYSTEMCTL_STATE="$ROOT/systemctl-active"
SOURCE_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"

cleanup() {
  rm -rf -- "$ROOT"
}
trap cleanup EXIT

mkdir -p "$FAKE_BIN" "$(dirname "$ENV_FILE")" "$SYSTEMD_DIR"

for command_name in \
  apt-get raspi-config timedatectl groupadd useradd usermod getent id; do
  printf '#!/usr/bin/env bash\nexit 0\n' >"$FAKE_BIN/$command_name"
  chmod 0755 "$FAKE_BIN/$command_name"
done

cat >"$FAKE_BIN/ip" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == "-4 route get 1.1.1.1" ]]; then
  echo "1.1.1.1 dev wlan0 src 192.0.2.10 uid 1000"
fi
EOF
chmod 0755 "$FAKE_BIN/ip"

cat >"$FAKE_BIN/sudo" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
while [[ "${1:-}" == "-H" ]]; do
  shift
done
if [[ "${1:-}" == "chown" ]]; then
  exit 0
fi
if [[ "${1:-}" == "install" ]]; then
  shift
  args=()
  while (($#)); do
    case "$1" in
      -o | -g)
        shift 2
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done
  exec install "${args[@]}"
fi
exec "$@"
EOF
chmod 0755 "$FAKE_BIN/sudo"

cat >"$FAKE_BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
set -Eeuo pipefail
command_name="${1:-}"
shift || true
case "$command_name" in
  is-active)
    if [[ -e "$HVV_FAKE_SYSTEMCTL_STATE" ]]; then
      [[ "${1:-}" == "--quiet" ]] || echo "active"
      exit 0
    fi
    [[ "${1:-}" == "--quiet" ]] || echo "inactive"
    exit 3
    ;;
  is-enabled)
    echo "enabled"
    ;;
  stop)
    rm -f "$HVV_FAKE_SYSTEMCTL_STATE"
    ;;
  start)
    touch "$HVV_FAKE_SYSTEMCTL_STATE"
    ;;
  restart)
    if [[ "${HVV_FAKE_FAIL_RESTART:-0}" == "1" ]]; then
      exit 1
    fi
    touch "$HVV_FAKE_SYSTEMCTL_STATE"
    ;;
  daemon-reload | enable)
    ;;
  *)
    echo "unexpected systemctl command: $command_name" >&2
    exit 2
    ;;
esac
EOF
chmod 0755 "$FAKE_BIN/systemctl"

export PATH="$FAKE_BIN:$PATH"
export HVV_APP_DIR="$APP_DIR"
export HVV_ENV_FILE="$ENV_FILE"
export HVV_SYSTEMD_DIR="$SYSTEMD_DIR"
export HVV_WEB_CERT_DIR="$ROOT/etc/hvv-anzeiger"
export HVV_FAKE_SYSTEMCTL_STATE="$SYSTEMCTL_STATE"

printf 'smoke-application\nsmoke-password\n' | "$SOURCE_DIR/install.sh"

test -x "$APP_DIR/.venv/bin/hvv-anzeiger"
test -x "$APP_DIR/.venv/bin/hvv-preview"
test -x "$APP_DIR/configure-web.sh"
test "$(stat -c '%a' "$APP_DIR")" = "755"
"$APP_DIR/.venv/bin/hvv-preview" "$ROOT/post-install-preview.png"
test -s "$ROOT/post-install-preview.png"
"$APP_DIR/.venv/bin/hvv-anzeiger" --help >/dev/null
test -x "$APP_DIR/configure-credentials.sh"
test -f "$APP_DIR/config.json"
test -f "$SYSTEMD_DIR/hvv-anzeiger.service"
grep -q -- '--host 0.0.0.0' "$SYSTEMD_DIR/hvv-anzeiger-web.service"
grep -q -- '--tls-certfile /etc/hvv-anzeiger/web.crt' \
  "$SYSTEMD_DIR/hvv-anzeiger-web.service"
grep -q -- '--tls-keyfile /etc/hvv-anzeiger/web.key' \
  "$SYSTEMD_DIR/hvv-anzeiger-web.service"
test -f "$ENV_FILE"
test "$(stat -c '%a' "$ENV_FILE")" = "600"
test -f "$HVV_WEB_CERT_DIR/web.crt"
test -f "$HVV_WEB_CERT_DIR/web.key"
web_certificate_checksum="$(sha256sum "$HVV_WEB_CERT_DIR/web.crt")"
grep -q '^GEOFOX_USER="smoke-application"$' "$ENV_FILE"
grep -q '^GEOFOX_PASSWORD="smoke-password"$' "$ENV_FILE"
test ! -e "${APP_DIR}.previous"
test -e "$SYSTEMCTL_STATE"

touch "$APP_DIR/rollback-marker"
printf '\n# rollback-unit-marker\n' >>"$SYSTEMD_DIR/hvv-anzeiger.service"
printf 'GEOFOX_USER="previous-incomplete-value"\n' >"$ENV_FILE"
chmod 0600 "$ENV_FILE"
credential_checksum="$(sha256sum "$ENV_FILE")"

if printf 'replacement-application\nreplacement-password\n' |
  HVV_FAKE_FAIL_RESTART=1 "$SOURCE_DIR/install.sh"; then
  echo "expected the simulated service failure to abort installation" >&2
  exit 1
fi

test -e "$APP_DIR/rollback-marker"
grep -q '^# rollback-unit-marker$' "$SYSTEMD_DIR/hvv-anzeiger.service"
test "$credential_checksum" = "$(sha256sum "$ENV_FILE")"
test "$web_certificate_checksum" = "$(sha256sum "$HVV_WEB_CERT_DIR/web.crt")"
test ! -e "${APP_DIR}.previous"
test -z "$(find "$(dirname "$APP_DIR")" -maxdepth 1 -name 'hvv-anzeiger.install.*' -print -quit)"
test -e "$SYSTEMCTL_STATE"

echo "Installer smoke test passed"
