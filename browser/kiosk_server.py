"""Local browser-test fixture: real web routes, deterministic Geofox substitute."""

import argparse
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

from hvv_display.geofox import HAMBURG_TZ
from hvv_display.models import Departure
from hvv_display.web import WebApplication, make_handler


class FixtureClient:
    def departure_list(self, *args, **kwargs):
        now = datetime.now(HAMBURG_TZ).replace(second=0, microsecond=0)
        return [
            Departure(
                "U2",
                "Niendorf Nord über eine sehr lange Umsteigehaltestelle",
                now + timedelta(minutes=4),
                delay_seconds=180,
                station_label="WEISTRITZSTRASSE",
                product="UBAHN",
            ),
            Departure(
                "S1",
                "Hamburg Airport",
                now + timedelta(minutes=7),
                cancelled=True,
                station_label="RECKNITZSTRASSE",
                product="SBAHN",
            ),
            Departure(
                "BuslinieMitSehrLangemNamen12345",
                "ZielMitSehrLangemUnunterbrochenemText123456789",
                now + timedelta(minutes=12),
                station_label="RECKNITZSTRASSE",
                product="BUS",
            ),
        ]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    app = WebApplication(
        Path("browser/fixtures/config-filtered.json"),
        Path("browser/fixtures/missing.env"),
        Path("browser/fixtures/missing-cache.json"),
    )
    app._client = FixtureClient
    ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app)).serve_forever()
