from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from .config import ConfigError, load_config
from .geofox import HAMBURG_TZ, GeofoxClient, GeofoxError
from .hardware import Ili9341Display
from .models import Departure
from .render import render_board
from .stations import resolve_stations

LOG = logging.getLogger(__name__)
MAX_REFRESH_BACKOFF_SECONDS = 300


def refresh_delay(refresh_seconds: int, consecutive_failures: int) -> int:
    """Return a bounded retry delay; the first failure doubles the normal interval."""
    if consecutive_failures <= 0:
        return refresh_seconds
    return min(
        MAX_REFRESH_BACKOFF_SECONDS,
        refresh_seconds * (2 ** min(consecutive_failures, 5)),
    )


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
    parser.add_argument("--once", action="store_true", help="Nur einmal aktualisieren")
    parser.add_argument(
        "--output",
        help="PNG schreiben statt Hardware anzusteuern (hilfreich zur Diagnose)",
    )
    return parser.parse_args()


def run() -> int:
    args = _arguments()
    try:
        config = load_config(args.config)
        client = GeofoxClient(
            config.api.base_url,
            os.environ.get("GEOFOX_USER", ""),
            os.environ.get("GEOFOX_PASSWORD", ""),
            version=config.api.version,
            timeout=config.api.request_timeout_seconds,
        )
        stations = resolve_stations(client, config.stations, args.cache)
        display = None if args.output else Ili9341Display(config.display)
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
    last_updated: datetime | None = None
    consecutive_failures = 0
    last_error: str | None = None
    next_api_attempt_at = 0.0
    while not stopped:
        now = datetime.now(HAMBURG_TZ)
        if time.monotonic() >= next_api_attempt_at:
            try:
                latest = client.departure_list(
                    stations,
                    now=now,
                    max_list=30,
                    max_time_offset=config.api.max_time_offset_minutes,
                )
                last_updated = now
                last_error = None
                consecutive_failures = 0
                LOG.info("%d passende Abfahrten geladen", len(latest))
            except GeofoxError as exc:
                last_error = str(exc)
                consecutive_failures += 1
                LOG.warning("Aktualisierung fehlgeschlagen: %s", exc)

            api_delay = refresh_delay(
                config.api.refresh_seconds,
                consecutive_failures,
            )
            next_api_attempt_at = time.monotonic() + api_delay
            if consecutive_failures:
                LOG.info("Nächster Geofox-Versuch in %d Sekunden", api_delay)

        image = render_board(
            latest,
            now=now,
            last_updated=last_updated,
            stale=last_error is not None,
            error_message=last_error,
            max_rows=config.api.max_departures,
        )
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)
        else:
            display.show(image)

        if args.once:
            return 0 if last_error is None else 1
        deadline = time.monotonic() + config.api.refresh_seconds
        while not stopped and time.monotonic() < deadline:
            time.sleep(min(0.25, deadline - time.monotonic()))
    return 0


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    sys.exit(run())


if __name__ == "__main__":
    main()
