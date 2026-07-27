from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Route:
    line: str
    destination: str


@dataclass(frozen=True)
class Station:
    name: str
    city: str
    routes: tuple[Route, ...]
    station_id: str | None = None

    def as_geofox_name(self) -> dict[str, str]:
        if not self.station_id:
            raise ValueError(f"Haltestelle {self.name!r} hat noch keine Geofox-ID")
        return {
            "name": self.name,
            "city": self.city,
            "id": self.station_id,
            "type": "STATION",
        }


@dataclass(frozen=True)
class Departure:
    line: str
    destination: str
    departure_time: datetime
    delay_seconds: int = 0
    cancelled: bool = False
