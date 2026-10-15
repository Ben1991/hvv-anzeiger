"""Versioned, bounded display contract for Home Assistant and ESPHome."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from .config import AppConfig
from .render import get_line_style

SCHEMA_VERSION = 1
MAX_DISPLAY_BYTES = 8192


def smart_home_payload(
    view: dict[str, Any],
    config: AppConfig | None,
    now: datetime,
    *,
    night_shutdown: bool = False,
) -> dict[str, Any]:
    """Export only display data; never credentials, paths or raw API errors.

    valid_for_seconds is a lease, not a new freshness timestamp. Repeatedly
    polling a failed backend must not extend the life of its cached departures.
    """
    max_age = config.api.max_stale_age_minutes * 60 if config else 300
    age = view.get("data_age_seconds")
    valid_for = max(0, max_age - age) if age is not None else 0
    if night_shutdown:
        state = "night"
        valid_for = 60
    elif config is None or age is None:
        state = "unavailable"
    elif view.get("expired") or valid_for == 0:
        state = "expired"
    elif view.get("stale") or view.get("error"):
        state = "stale"
    else:
        state = "ok"
    rows = []
    if state in {"ok", "stale"}:
        for item in view.get("departures", [])[:5]:
            style = get_line_style(item["line"], item.get("product"))
            rows.append(
                {
                    "line": item["line"][:12],
                    "destination": item["destination"][:64],
                    "station": item.get("station", "")[:12],
                    "time": item["time"],
                    "departure_epoch": int(
                        datetime.fromisoformat(item["departure_time"]).timestamp()
                    ),
                    "cancelled": bool(item.get("cancelled")),
                    "delay_seconds": item.get("delay_seconds", 0),
                    "background": int(style.background.lstrip("#"), 16),
                    "foreground": int(style.foreground.lstrip("#"), 16),
                    "shape": style.shape,
                }
            )
    display = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": int(now.timestamp()),
        "state": state,
        "valid_for_seconds": min(valid_for, max_age, 86400),
        "time_mode": config.display.time_mode if config else "countdown",
        "minute_unit": config.display.minute_unit if config else "min",
        "departures": rows,
    }
    encoded = json.dumps(display, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_DISPLAY_BYTES:
        raise ValueError("Display snapshot exceeds protocol limit")
    return {
        "schema_version": SCHEMA_VERSION,
        "state": state,
        "generated_at": now.isoformat(),
        "last_updated": view.get("last_updated"),
        "data_age_seconds": age,
        "stale": state in {"stale", "expired", "unavailable"},
        "night_shutdown": night_shutdown,
        "departures": view.get("departures", []) if rows else [],
        "display_payload": encoded,
    }
