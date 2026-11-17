"""A small file-backed Geofox request gate shared by service processes."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path


class GeofoxRequestGate:
    """Serialize API calls and persist pacing/backoff across processes."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def request(self, interval: float) -> Iterator[Callable[[int | None], None]]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            self.path,
            os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            if os.name == "nt":  # pragma: no cover - Linux services use flock
                import msvcrt

                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b" ")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_LOCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_EX)

            def read_state() -> dict[str, float]:
                os.lseek(descriptor, 0, os.SEEK_SET)
                try:
                    value = json.loads(os.read(descriptor, 4096) or b"{}")
                except (json.JSONDecodeError, UnicodeDecodeError):
                    return {"last_request_at": 0.0, "retry_until": 0.0}
                if not isinstance(value, dict):
                    return {"last_request_at": 0.0, "retry_until": 0.0}
                try:
                    last_request_at = float(value.get("last_request_at", 0))
                    retry_until = float(value.get("retry_until", 0))
                except (TypeError, ValueError, OverflowError):
                    return {"last_request_at": 0.0, "retry_until": 0.0}
                return {
                    "last_request_at": max(0.0, last_request_at)
                    if math.isfinite(last_request_at)
                    else 0.0,
                    "retry_until": max(0.0, retry_until)
                    if math.isfinite(retry_until)
                    else 0.0,
                }

            state = read_state()

            def save_state() -> None:
                payload = json.dumps(state, separators=(",", ":")).encode("ascii")
                os.lseek(descriptor, 0, os.SEEK_SET)
                os.write(descriptor, payload)
                os.ftruncate(descriptor, len(payload))
                os.fsync(descriptor)

            while True:
                now = time.time()
                wait_until = max(
                    state["retry_until"], state["last_request_at"] + interval
                )
                if wait_until <= now:
                    break
                time.sleep(wait_until - now)

            state["last_request_at"] = time.time()
            save_state()

            def update_retry(seconds: int | None) -> None:
                if seconds:
                    state["retry_until"] = max(
                        state["retry_until"], time.time() + seconds
                    )
                    save_state()

            yield update_retry
        finally:
            if os.name == "nt":  # pragma: no cover - Linux services use flock
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
