from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from .geofox import GeofoxClient
from .models import Station
from .storage import atomic_write

LOG = logging.getLogger(__name__)


def resolve_stations(
    client: GeofoxClient, stations: tuple[Station, ...], cache_path: str | Path
) -> tuple[Station, ...]:
    path = Path(cache_path)
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, RecursionError):
        cache = {}
    if not isinstance(cache, dict):
        LOG.warning("Haltestellen-Cache hat ein ungültiges Format und wird ignoriert")
        cache = {}

    resolved: list[Station] = []
    changed = False
    for station in stations:
        key = f"{station.city}|{station.name}".casefold()
        cached_id = cache.get(key)
        if not isinstance(cached_id, str) or not cached_id.strip():
            cached_id = None
        station_id = station.station_id or cached_id
        if not station_id:
            match = client.find_station(station.name, station.city)
            station_id = match["id"]
            cache[key] = station_id
            changed = True
            LOG.info(
                "Haltestelle aufgelöst: %s, %s -> %s",
                station.city,
                station.name,
                station_id,
            )
        resolved.append(replace(station, station_id=str(station_id)))

    if changed:
        try:
            atomic_write(
                path,
                (json.dumps(cache, ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"
                ),
            )
        except OSError:
            # This cache is replaceable. A read-only/full disk must not discard
            # a successful lookup or prevent live departure requests.
            LOG.warning("Haltestellen-Cache konnte nicht gespeichert werden")
    return tuple(resolved)
