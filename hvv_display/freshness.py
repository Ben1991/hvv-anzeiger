"""Shared retry and expiry rules for hardware and browser displays."""

from datetime import datetime, timedelta, timezone

from .models import Departure

MAX_REFRESH_BACKOFF_SECONDS = 300


def refresh_delay(
    refresh_seconds: int,
    consecutive_failures: int,
    retry_after_seconds: int | None = None,
) -> int:
    if consecutive_failures <= 0:
        return refresh_seconds
    backoff = min(
        MAX_REFRESH_BACKOFF_SECONDS,
        refresh_seconds * (2 ** min(consecutive_failures, 5)),
    )
    return max(backoff, retry_after_seconds or 0)


def departures_for_display(
    departures: list[Departure],
    *,
    now: datetime,
    last_updated: datetime | None,
    stale: bool,
    max_stale_age_minutes: int,
) -> list[Departure]:
    if not stale:
        return departures
    if last_updated is None:
        return []
    age = now.astimezone(timezone.utc) - last_updated.astimezone(timezone.utc)
    return [] if age >= timedelta(minutes=max_stale_age_minutes) else departures
