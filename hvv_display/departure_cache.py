"""Authenticated, atomic persistence for the last successful departure snapshot."""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import stat
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .config import AppConfig
from .models import Departure

LOG = logging.getLogger(__name__)
SCHEMA_VERSION = 1
MAX_CACHE_BYTES = 128 * 1024
MAX_DEPARTURES = 30
MAX_TEXT_LENGTH = 160
KEY_BYTES = 32


@dataclass(frozen=True)
class DepartureSnapshot:
    departures: list[Departure]
    fetched_at: datetime


def departure_source(config: AppConfig) -> str:
    """Identify the filters that produced a snapshot; credentials are excluded."""
    source = {
        "api": {
            "base_url": config.api.base_url,
            "version": config.api.version,
            "max_time_offset_minutes": config.api.max_time_offset_minutes,
        },
        "stations": [asdict(station) for station in config.stations],
    }
    encoded = json.dumps(
        source, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _owner_uid() -> int | None:
    return os.getuid() if os.name != "nt" and hasattr(os, "getuid") else None


def _read_private_file(path: Path, maximum: int) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError("private file is not regular")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        uid = _owner_uid()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or (uid is not None and metadata.st_uid != uid)
            or (os.name != "nt" and stat.S_IMODE(metadata.st_mode) & 0o077)
            or metadata.st_size > maximum
        ):
            raise ValueError("private file metadata rejected")
        with os.fdopen(descriptor, "rb", closefd=False) as source:
            payload = source.read(maximum + 1)
        if len(payload) > maximum:
            raise ValueError("private file too large")
        return payload
    finally:
        os.close(descriptor)


def _private_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    parent = path.parent.lstat()
    uid = _owner_uid()
    if (
        not stat.S_ISDIR(parent.st_mode)
        or (uid is not None and parent.st_uid != uid)
        or (os.name != "nt" and parent.st_mode & 0o022)
    ):
        raise OSError("cache directory is not private")


def _write_private_file(path: Path, payload: bytes) -> None:
    _private_directory(path)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        if os.name != "nt":
            os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory_fd = os.open(path.parent, directory_flags)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _departure_data(departure: Departure) -> dict[str, Any]:
    value = {
        "line": departure.line,
        "destination": departure.destination,
        "departure_time": departure.departure_time.isoformat(),
        "delay_seconds": departure.delay_seconds,
        "cancelled": departure.cancelled,
        "station_label": departure.station_label,
        "product": departure.product,
    }
    _departure_from_data(value)
    return value


def _text(value: Any, *, required: bool = False) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str) or len(value) > MAX_TEXT_LENGTH:
        raise ValueError("invalid departure text")
    if required and not value.strip():
        raise ValueError("empty departure text")
    if any(not character.isprintable() for character in value):
        raise ValueError("departure text contains control characters")
    return value


def _departure_from_data(value: Any) -> Departure:
    if not isinstance(value, dict):
        raise ValueError("invalid departure record")
    line = _text(value.get("line"), required=True)
    destination = _text(value.get("destination"), required=True)
    station_label = _text(value.get("station_label", ""))
    product = _text(value.get("product"))
    raw_time = value.get("departure_time")
    if not isinstance(raw_time, str) or len(raw_time) > 64:
        raise ValueError("invalid departure timestamp")
    departure_time = datetime.fromisoformat(raw_time)
    if departure_time.tzinfo is None:
        raise ValueError("departure timestamp needs timezone")
    delay = value.get("delay_seconds")
    if type(delay) is not int or not 0 <= delay <= 86_400:
        raise ValueError("invalid delay")
    cancelled = value.get("cancelled")
    if type(cancelled) is not bool:
        raise ValueError("invalid cancellation flag")
    return Departure(
        line=line or "",
        destination=destination or "",
        departure_time=departure_time,
        delay_seconds=delay,
        cancelled=cancelled,
        station_label=station_label or "",
        product=product,
    )


class DepartureCache:
    """A bounded HMAC-protected cache with restrictive permissions and atomic writes."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.key_path = self.path.with_name("departures.key")

    def _load_key(self) -> bytes:
        key = _read_private_file(self.key_path, KEY_BYTES)
        if len(key) != KEY_BYTES:
            raise ValueError("invalid cache key")
        return key

    def _create_key(self) -> bytes:
        _private_directory(self.key_path)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(self.key_path, flags, 0o600)
        except FileExistsError:
            return self._load_key()
        key = secrets.token_bytes(KEY_BYTES)
        try:
            if os.name != "nt":
                os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as target:
                target.write(key)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            self.key_path.unlink(missing_ok=True)
            raise
        return key

    def load(
        self,
        source: str,
        *,
        now: datetime | None = None,
    ) -> DepartureSnapshot | None:
        try:
            if len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
                raise ValueError("invalid source fingerprint")
            raw = _read_private_file(self.path, MAX_CACHE_BYTES)
            envelope = json.loads(raw.decode("utf-8"))
            if (
                not isinstance(envelope, dict)
                or envelope.get("schema_version") != SCHEMA_VERSION
            ):
                raise ValueError("unsupported cache schema")
            signature = envelope.get("signature")
            if not isinstance(signature, str) or len(signature) != 64:
                raise ValueError("invalid cache signature")
            payload = {
                key: value for key, value in envelope.items() if key != "signature"
            }
            expected = hmac.new(
                self._load_key(), _canonical_json(payload), hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(signature, expected):
                raise ValueError("cache signature mismatch")
            if envelope.get("source") != source:
                raise ValueError("cache belongs to another configuration")
            raw_departures = envelope.get("departures")
            if (
                not isinstance(raw_departures, list)
                or len(raw_departures) > MAX_DEPARTURES
            ):
                raise ValueError("invalid departure list")
            departures = [_departure_from_data(item) for item in raw_departures]
            fetched_at_raw = envelope.get("fetched_at")
            if not isinstance(fetched_at_raw, str) or len(fetched_at_raw) > 64:
                raise ValueError("invalid fetch timestamp")
            fetched_at = datetime.fromisoformat(fetched_at_raw)
            if fetched_at.tzinfo is None:
                raise ValueError("fetch timestamp needs timezone")
            reference = now or datetime.now(timezone.utc)
            age = reference.astimezone(timezone.utc) - fetched_at.astimezone(
                timezone.utc
            )
            if age < timedelta(seconds=-5):
                raise ValueError("cache timestamp is in the future")
            return DepartureSnapshot(departures, fetched_at)
        except (
            OSError,
            UnicodeError,
            ValueError,
            TypeError,
            KeyError,
            OverflowError,
            RecursionError,
        ) as exc:
            LOG.warning("Abfahrtscache ignoriert (%s)", exc)
            return None

    def save(
        self,
        departures: list[Departure],
        fetched_at: datetime,
        source: str,
    ) -> None:
        if len(source) != 64 or any(c not in "0123456789abcdef" for c in source):
            raise ValueError("invalid source fingerprint")
        if len(departures) > MAX_DEPARTURES:
            raise ValueError("too many departures for cache")
        if fetched_at.tzinfo is None:
            raise ValueError("fetch timestamp needs timezone")
        payload = {
            "schema_version": SCHEMA_VERSION,
            "source": source,
            "fetched_at": fetched_at.isoformat(),
            "departures": [_departure_data(item) for item in departures],
        }
        signature = hmac.new(
            self._create_key(), _canonical_json(payload), hashlib.sha256
        ).hexdigest()
        envelope = {**payload, "signature": signature}
        encoded = _canonical_json(envelope)
        if len(encoded) > MAX_CACHE_BYTES:
            raise ValueError("departure cache exceeds size limit")
        _write_private_file(self.path, encoded)
