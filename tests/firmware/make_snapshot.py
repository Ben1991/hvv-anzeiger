"""Feed the actual Python producer's payload to the native consumer tests."""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hvv_display.config import load_config  # noqa: E402
from hvv_display.geofox import HAMBURG_TZ  # noqa: E402
from hvv_display.models import Departure  # noqa: E402
from hvv_display.smart_home import smart_home_payload  # noqa: E402
from hvv_display.web import _departure_payload  # noqa: E402

root = Path(__file__).resolve().parents[2]
now = datetime(2026, 10, 15, 12, tzinfo=HAMBURG_TZ)
view = {
    "data_age_seconds": 0,
    "departures": _departure_payload(
        [
            Departure("U3", "Barmbek", now, station_label="W"),
            Departure(
                "S3",
                "Altona",
                now + timedelta(minutes=5),
                cancelled=True,
                delay_seconds=120,
            ),
        ],
        now,
    ),
}
payload = smart_home_payload(view, load_config(root / "config.example.json"), now)
Path(sys.argv[1]).write_text(payload["display_payload"], encoding="utf-8")
