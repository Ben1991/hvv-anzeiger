"""Bounded, credential-free snapshots of the display service (schema version 1)."""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import stat
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import __version__

LOG = logging.getLogger(__name__)
MAX_SNAPSHOT_BYTES = 8192
STATUS_CODES = {"healthy": (200, 0), "degraded": (503, 1), "unavailable": (500, 2)}
ERROR_KINDS = {"none", "technical", "temporary", "rate_limit", "authentication"}


def health_path(cache: str | Path = "var/stations.json") -> Path:
    return Path(
        os.environ.get("HVV_HEALTH_FILE", str(Path(cache).with_name("health.json")))
    )


def _timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Invalid timestamp")
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("Timestamp needs timezone")
    return parsed.astimezone(timezone.utc)


def _seconds(value: Any) -> int:
    if type(value) is not int or not 0 <= value <= 2**53:
        raise ValueError("Invalid duration")
    return value


def _boolean(value: Any, *, optional: bool = False) -> bool | None:
    if type(value) is bool or (optional and value is None):
        return value
    raise ValueError("Invalid flag")


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _empty_status() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "version": __version__,
        "status": "unavailable",
        "service_running": False,
        "uptime_seconds": None,
        "configuration_valid": None,
        "network_connected": None,
        "clock_synchronized": None,
        "display_available": None,
        "night_shutdown": False,
        "last_successful_fetch": None,
        "data_age_seconds": None,
        "stale": True,
        "consecutive_failures": 0,
        "error_kind": "none",
        "retry_in_seconds": 0,
        "rate_limit_active": False,
        "rate_limit_remaining_seconds": 0,
        "heartbeat_age_seconds": None,
        "snapshot_available": False,
    }


def read_health(path: Path, *, now: datetime | None = None) -> dict[str, Any]:
    """Read only a small regular file; never query Geofox, systemd or the network."""
    result = _empty_status()
    now = now or datetime.now(timezone.utc)
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            return result
        with path.open("rb") as source:
            raw = source.read(MAX_SNAPSHOT_BYTES + 1)
        if len(raw) > MAX_SNAPSHOT_BYTES:
            return result
        data = json.loads(raw)
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            return result
        version = data["version"]
        if (
            not isinstance(version, str)
            or len(version) > 64
            or not re.fullmatch(r"\d+\.\d+\.\d+", version)
        ):
            return result
        heartbeat = _timestamp(data["heartbeat_at"])
        started = _timestamp(data["started_at"])
        if heartbeat is None or started is None:
            return result
        age = max(0, math.floor((now - heartbeat).total_seconds()))
        running = _boolean(data["service_running"]) and age <= _seconds(
            data["heartbeat_timeout_seconds"]
        )
        valid = _boolean(data["configuration_valid"])
        network = _boolean(data["network_connected"], optional=True)
        clock = _boolean(data["clock_synchronized"], optional=True)
        display = _boolean(data["display_available"], optional=True)
        night = _boolean(data["night_shutdown"])
        success = _timestamp(data["last_successful_fetch"])
        data_age = (
            max(0, math.floor((now - success).total_seconds())) if success else None
        )
        failures = _seconds(data["consecutive_failures"])
        kind = data["error_kind"]
        if kind not in ERROR_KINDS:
            return result
        retry_at = _timestamp(data["retry_at"])
        rate_until = _timestamp(data["rate_limit_until"])
        retry = max(0, math.ceil((retry_at - now).total_seconds())) if retry_at else 0
        rate = (
            max(0, math.ceil((rate_until - now).total_seconds())) if rate_until else 0
        )
        stale = (
            success is None
            or failures > 0
            or data_age >= _seconds(data["max_data_age_seconds"])
        )
        if not running or not valid or display is False or kind == "authentication":
            status = "unavailable"
        elif not night and (
            stale or network is not True or clock is not True or rate > 0
        ):
            status = "degraded"
        else:
            status = "healthy"
        result.update(
            version=version,
            status=status,
            service_running=bool(running),
            uptime_seconds=max(
                0,
                math.floor(
                    (
                        (now if running else min(now, heartbeat)) - started
                    ).total_seconds()
                ),
            ),
            configuration_valid=valid,
            network_connected=network,
            clock_synchronized=clock,
            display_available=display,
            night_shutdown=night,
            last_successful_fetch=_iso(success),
            data_age_seconds=data_age,
            stale=stale,
            consecutive_failures=failures,
            error_kind=kind,
            retry_in_seconds=retry,
            rate_limit_active=rate > 0,
            rate_limit_remaining_seconds=rate,
            heartbeat_age_seconds=age,
            snapshot_available=True,
        )
    except (OSError, ValueError, TypeError, KeyError, OverflowError):
        return _empty_status()
    return result


class HealthPublisher:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.started_at = datetime.now(timezone.utc)
        self._write_failed = False

    def publish(
        self,
        *,
        configuration_valid: bool,
        network_connected: bool | None = None,
        clock_synchronized: bool | None = None,
        display_available: bool | None = None,
        night_shutdown: bool = False,
        last_successful_fetch: datetime | None = None,
        consecutive_failures: int = 0,
        error_kind: str = "none",
        retry_seconds: int = 0,
        rate_limit_seconds: int = 0,
        refresh_seconds: int = 15,
        max_data_age_seconds: int = 300,
        service_running: bool = True,
    ) -> None:
        now = datetime.now(timezone.utc)
        data = {
            "schema_version": 1,
            "version": __version__,
            "started_at": _iso(self.started_at),
            "heartbeat_at": _iso(now),
            "heartbeat_timeout_seconds": max(90, refresh_seconds * 3),
            "service_running": service_running,
            "configuration_valid": configuration_valid,
            "network_connected": network_connected,
            "clock_synchronized": clock_synchronized,
            "display_available": display_available,
            "night_shutdown": night_shutdown,
            "last_successful_fetch": _iso(last_successful_fetch),
            "consecutive_failures": consecutive_failures,
            "error_kind": error_kind if error_kind in ERROR_KINDS else "technical",
            "retry_at": _iso(now + timedelta(seconds=max(0, retry_seconds))),
            "rate_limit_until": _iso(
                now + timedelta(seconds=max(0, rate_limit_seconds))
            ),
            "max_data_age_seconds": max_data_age_seconds,
        }
        temporary = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.path.parent, delete=False
            ) as target:
                temporary = Path(target.name)
                json.dump(data, target)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
            self._write_failed = False
        except OSError:
            if not self._write_failed:
                LOG.warning("Gesundheitsstatus konnte nicht gespeichert werden")
            self._write_failed = True
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lokaler Gesundheitsstatus ohne API-Abruf"
    )
    parser.add_argument("--file", type=Path, default=health_path())
    args = parser.parse_args()
    result = read_health(args.file)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit(STATUS_CODES[result["status"]][1])


if __name__ == "__main__":
    main()
