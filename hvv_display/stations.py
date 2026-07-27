from __future__ import annotations

import json
import logging
from dataclasses import replace
from pathlib import Path

from .geofox import GeofoxClient
from .models import Station

LOG = logging.getLogger(__name__)


def resolve_stations(
    client: GeofoxClient, stations: tuple[Station, ...], cache_path: str | Path
) -> tuple[Station, ...]:
    path = Path(cache_path)
    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        cache = {}
    if not isinstance(cache, dict):
        LOG.warning("Haltestellen-Cache hat ein ungültiges Format und wird ignoriert")
        cache = {}

    resolved: list[Station] = []
    changed = False
    for station in stations:
        key = f"{station.city}|{station.name}".casefold()
        station_id = station.station_id or cache.get(key)
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
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    return tuple(resolved)
