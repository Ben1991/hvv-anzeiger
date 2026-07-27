from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime, time
from pathlib import Path

SYSTEMD_SYNC_MARKER = Path("/run/systemd/timesync/synchronized")


def time_is_synchronized(
    *,
    marker: Path = SYSTEMD_SYNC_MARKER,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> bool | None:
    """Return the system clock sync state, or None when it cannot be determined."""
    if marker.exists():
        return True
    try:
        result = run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    value = result.stdout.strip().lower()
    if value == "yes":
        return True
    if value == "no":
        return False
    return None


def in_night_shutdown(now: datetime, start: time, end: time) -> bool:
    """Return whether a local time falls inside an overnight or daytime window."""
    current = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end
