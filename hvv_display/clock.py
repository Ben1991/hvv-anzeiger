from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime, time
from pathlib import Path

SYSTEMD_SYNC_MARKER = Path("/run/systemd/timesync/synchronized")


def _is_container() -> bool:
    """Containers use the host kernel clock and usually have no systemd."""
    return Path("/.dockerenv").exists() or Path("/run/.containerenv").exists()


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
        return True if _is_container() else None
    if result.returncode != 0:
        return True if _is_container() else None
    value = result.stdout.strip().lower()
    if value == "yes":
        return True
    if value == "no":
        return False
    return True if _is_container() else None


def in_night_shutdown(now: datetime, start: time, end: time) -> bool:
    """Return whether a local time falls inside an overnight or daytime window."""
    current = now.timetz().replace(tzinfo=None)
    if start < end:
        return start <= current < end
    return current >= start or current < end
