from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PIL import Image

from .clock import in_night_shutdown
from .clock import time_is_synchronized as clock_is_synchronized
from .config import ConfigError, load_config
from .credentials import load_credentials
from .geofox import HAMBURG_TZ, GeofoxClient, GeofoxError
from .hardware import Ili9341Display
from .models import Departure
from .network import wifi_connected
from .render import HEIGHT, WIDTH, board_state_key, render_board
from .service import SystemdNotifier
from .stations import resolve_stations

LOG = logging.getLogger(__name__)
MAX_REFRESH_BACKOFF_SECONDS = 300
SUCCESS_HEARTBEAT_SECONDS = 3600


def refresh_delay(
    refresh_seconds: int,
    consecutive_failures: int,
    retry_after_seconds: int | None = None,
) -> int:
    """Return a bounded retry delay; the first failure doubles the normal interval."""
    if consecutive_failures <= 0:
        return refresh_seconds
    backoff = min(
        MAX_REFRESH_BACKOFF_SECONDS,
        refresh_seconds * (2 ** min(consecutive_failures, 5)),
    )
    return max(backoff, retry_after_seconds or 0)


def log_success(
    departure_count: int,
    *,
    now_monotonic: float,
    previous_heartbeat_at: float | None,
) -> float:
    """Log routine success at most hourly while retaining details at debug level."""
    if (
        previous_heartbeat_at is None
        or now_monotonic - previous_heartbeat_at >= SUCCESS_HEARTBEAT_SECONDS
    ):
        LOG.info("%d passende Abfahrten geladen", departure_count)
        return now_monotonic
    LOG.debug("%d passende Abfahrten geladen", departure_count)
    return previous_heartbeat_at


def departures_for_display(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None,
    stale: bool,
    max_stale_age_minutes: int,
) -> list[Departure]:
    """Hide departures once their last successful data snapshot is too old."""
    if not stale:
        return departures
    if last_updated is None:
        return []
    age = now.astimezone(timezone.utc) - last_updated.astimezone(timezone.utc)
    if age >= timedelta(minutes=max_stale_age_minutes):
        return []
    return departures


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="HVV-Abfahrten auf einem ILI9341")
    parser.add_argument(
        "--config",
        default=os.environ.get("HVV_CONFIG", "config.json"),
        help="Pfad zur JSON-Konfiguration",
    )
    parser.add_argument(
        "--cache",
        default=os.environ.get("HVV_STATION_CACHE", "var/stations.json"),
        help="Pfad für automatisch gefundene Haltestellen-IDs",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env"),
        help="Pfad zur Geofox-EnvironmentFile",
    )
    parser.add_argument("--once", action="store_true", help="Nur einmal aktualisieren")
    parser.add_argument(
        "--output",
        help="PNG schreiben statt Hardware anzusteuern (hilfreich zur Diagnose)",
    )
    return parser.parse_args()


def update_board(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None,
    stale: bool,
    error_message: str | None,
    wifi_is_connected: bool | None,
    max_rows: int,
    previous_state: tuple[object, ...] | None,
    output: str | None,
    display: Ili9341Display | None,
    time_is_synchronized: bool | None = True,
    night_shutdown: bool = False,
) -> tuple[object, ...]:
    """Render and transfer a frame only when its visible content changed."""
    if night_shutdown:
        current_state: tuple[object, ...] = ("night-shutdown",)
    else:
        current_state = board_state_key(
            departures,
            now=now,
            last_updated=last_updated,
            stale=stale,
            error_message=error_message,
            wifi_is_connected=wifi_is_connected,
            max_rows=max_rows,
            time_is_synchronized=time_is_synchronized,
        )
    if current_state == previous_state:
        LOG.debug("Displayinhalt unverändert; Aktualisierung übersprungen")
        return current_state

    if night_shutdown:
        image = Image.new("RGB", (WIDTH, HEIGHT), "black")
    else:
        image = render_board(
            departures,
            now=now,
            last_updated=last_updated,
            stale=stale,
            error_message=error_message,
            wifi_is_connected=wifi_is_connected,
            max_rows=max_rows,
            time_is_synchronized=time_is_synchronized,
        )
    if output:
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
    elif display is not None:
        display.show(image)
    else:
        raise RuntimeError("Kein Display oder Ausgabepfad konfiguriert")
    return current_state


def run() -> int:
    args = _arguments()
    notifier = SystemdNotifier()
    try:
        config_path = Path(args.config)
        credentials_path = Path(
            getattr(
                args,
                "credentials",
                os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env"),
            )
        )
        config = load_config(config_path)
        credentials = load_credentials(credentials_path)
        client = GeofoxClient(
            config.api.base_url,
            credentials.get("GEOFOX_USER", ""),
            credentials.get("GEOFOX_PASSWORD", ""),
            version=config.api.version,
            timeout=config.api.request_timeout_seconds,
        )
        display = None if args.output else Ili9341Display(config.display)
        config_mtime_ns = config_path.stat().st_mtime_ns
        credentials_mtime_ns = (
            credentials_path.stat().st_mtime_ns if credentials_path.exists() else None
        )
    except (ConfigError, GeofoxError, RuntimeError) as exc:
        LOG.error("%s", exc)
        return 2

    stopped = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    latest: list[Departure] = []
    stations = None
    last_updated: datetime | None = None
    consecutive_failures = 0
    last_error: str | None = None
    next_api_attempt_at = 0.0
    wifi_interface = os.environ.get("HVV_WIFI_INTERFACE", "wlan0")
    last_board_state: tuple[object, ...] | None = None
    last_success_heartbeat_at: float | None = None
    clock_confirmed = False
    notifier.ready()
    while not stopped:
        now = datetime.now(HAMBURG_TZ)
        current_monotonic = time.monotonic()
        notifier.ping_if_due(current_monotonic)
        try:
            current_config_mtime_ns = config_path.stat().st_mtime_ns
            current_credentials_mtime_ns = (
                credentials_path.stat().st_mtime_ns
                if credentials_path.exists()
                else None
            )
        except OSError:
            current_config_mtime_ns = config_mtime_ns
            current_credentials_mtime_ns = credentials_mtime_ns
        if (
            current_config_mtime_ns != config_mtime_ns
            or current_credentials_mtime_ns != credentials_mtime_ns
        ):
            try:
                new_config = load_config(config_path)
                new_credentials = load_credentials(credentials_path)
                display_changed = new_config.display != config.display
                config = new_config
                client = GeofoxClient(
                    config.api.base_url,
                    new_credentials.get("GEOFOX_USER", ""),
                    new_credentials.get("GEOFOX_PASSWORD", ""),
                    version=config.api.version,
                    timeout=config.api.request_timeout_seconds,
                )
                credentials_mtime_ns = current_credentials_mtime_ns
                config_mtime_ns = current_config_mtime_ns
                stations = None
                latest = []
                last_updated = None
                last_error = None
                consecutive_failures = 0
                next_api_attempt_at = 0.0
                last_board_state = None
                if display_changed and not args.output:
                    display = None
                LOG.info(
                    "Gespeicherte Konfiguration direkt übernommen%s",
                    "; Display wird neu initialisiert" if display_changed else "",
                )
            except (ConfigError, OSError) as exc:
                LOG.warning(
                    "Neue Konfiguration konnte nicht übernommen werden; "
                    "bisherige Werte bleiben aktiv: %s",
                    exc,
                )
        if not args.output and display is None:
            try:
                display = Ili9341Display(config.display)
                LOG.info(
                    "Displaytreiber nach einem Verbindungsfehler neu initialisiert"
                )
            except (OSError, RuntimeError) as exc:
                LOG.warning("Display ist nicht erreichbar: %s", exc)
        sync_probe = True if clock_confirmed else clock_is_synchronized()
        if sync_probe is True:
            clock_confirmed = True
        clock_ready = clock_confirmed
        night_active = (
            clock_ready
            and config.night_shutdown.enabled
            and in_night_shutdown(
                now,
                config.night_shutdown.start,
                config.night_shutdown.end,
            )
        )

        if (
            clock_ready
            and not night_active
            and current_monotonic >= next_api_attempt_at
        ):
            try:
                if stations is None:
                    stations = resolve_stations(
                        client,
                        config.stations,
                        args.cache,
                    )
                latest = client.departure_list(
                    stations,
                    now=now,
                    max_list=30,
                    max_time_offset=config.api.max_time_offset_minutes,
                )
                last_updated = now
                last_error = None
                consecutive_failures = 0
                last_success_heartbeat_at = log_success(
                    len(latest),
                    now_monotonic=current_monotonic,
                    previous_heartbeat_at=last_success_heartbeat_at,
                )
            except GeofoxError as exc:
                last_error = str(exc)
                consecutive_failures += 1
                retry_after_seconds = exc.retry_after_seconds
                LOG.warning("Aktualisierung fehlgeschlagen: %s", exc)
            else:
                retry_after_seconds = None

            api_delay = refresh_delay(
                config.api.refresh_seconds,
                consecutive_failures,
                retry_after_seconds,
            )
            next_api_attempt_at = time.monotonic() + api_delay
            if consecutive_failures:
                LOG.info("Nächster Geofox-Versuch in %d Sekunden", api_delay)

        wifi_state = None if night_active else wifi_connected(wifi_interface)
        visible_error = last_error
        if not clock_ready:
            visible_error = "Systemzeit ist noch nicht synchronisiert"
        visible_departures = departures_for_display(
            latest,
            now=now,
            last_updated=last_updated,
            stale=visible_error is not None,
            max_stale_age_minutes=config.api.max_stale_age_minutes,
        )
        if args.output or display is not None:
            try:
                last_board_state = update_board(
                    visible_departures,
                    now=now,
                    last_updated=last_updated,
                    stale=visible_error is not None,
                    error_message=visible_error,
                    wifi_is_connected=wifi_state,
                    max_rows=config.api.max_departures,
                    previous_state=last_board_state,
                    output=args.output,
                    display=display,
                    time_is_synchronized=clock_ready,
                    night_shutdown=night_active,
                )
            except (OSError, RuntimeError) as exc:
                LOG.warning(
                    "Displayübertragung fehlgeschlagen; erneuter Versuch folgt: %s",
                    exc,
                )
                display = None
                last_board_state = None

        if args.once:
            return 0 if clock_ready and last_error is None else 1
        deadline = time.monotonic() + config.api.refresh_seconds
        while not stopped:
            sleep_now = time.monotonic()
            if sleep_now >= deadline:
                break
            notifier.ping_if_due(sleep_now)
            try:
                if config_path.stat().st_mtime_ns != config_mtime_ns or (
                    credentials_path.exists()
                    and credentials_path.stat().st_mtime_ns != credentials_mtime_ns
                ):
                    break
            except OSError:
                pass
            time.sleep(min(1.0, deadline - sleep_now))
    return 0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(run())


if __name__ == "__main__":
    main()
