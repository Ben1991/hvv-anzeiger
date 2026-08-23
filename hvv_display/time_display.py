from __future__ import annotations

import math
from datetime import datetime

TIME_MODES = ("countdown", "departure_time")
MINUTE_UNITS = ("min", "m", "none")


def minutes_until(departure_time: datetime, now: datetime) -> int:
    """Return a non-negative, display-friendly countdown in whole minutes."""
    return max(0, math.ceil((departure_time - now).total_seconds() / 60))


def format_departure_time(
    departure_time: datetime,
    now: datetime,
    *,
    time_mode: str = "countdown",
    minute_unit: str = "min",
    cancelled: bool = False,
) -> str:
    """Format one effective departure time for every presentation surface."""
    if cancelled:
        return "AUS"
    if time_mode == "departure_time":
        return departure_time.strftime("%H:%M")
    minutes = minutes_until(departure_time, now)
    if minute_unit == "none":
        return str(minutes)
    return f"{minutes} {minute_unit}"
