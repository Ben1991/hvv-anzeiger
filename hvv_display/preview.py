from __future__ import annotations

import argparse
from datetime import datetime, timedelta

from .geofox import HAMBURG_TZ
from .models import Departure
from .render import render_board


def main() -> None:
    parser = argparse.ArgumentParser(description="Erzeugt eine Display-Vorschau")
    parser.add_argument("output", nargs="?", default="preview.png")
    args = parser.parse_args()

    now = datetime.now(HAMBURG_TZ).replace(second=0, microsecond=0)
    departures = [
        Departure(
            "186", "S Othmarschen", now + timedelta(minutes=3), station_label="W"
        ),
        Departure(
            "21", "U Niendorf Nord", now + timedelta(minutes=7), station_label="R"
        ),
        Departure(
            "184",
            "S Halstenbek",
            now + timedelta(minutes=12),
            delay_seconds=120,
            station_label="W",
        ),
        Departure(
            "384", "S Elbgaustraße", now + timedelta(minutes=18), station_label="W"
        ),
        Departure(
            "186", "S Othmarschen", now + timedelta(minutes=24), station_label="W"
        ),
    ]
    render_board(departures, now=now, last_updated=now).save(args.output)


if __name__ == "__main__":
    main()
