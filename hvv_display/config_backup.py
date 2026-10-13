"""Shared local configuration export, preview and atomic restoration."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import logging
import os
import re
import secrets
import stat
import tempfile
import time
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import __version__
from .config import ConfigError, config_from_dict

LOG = logging.getLogger(__name__)
MAX_CONFIG_BYTES = 262_144
MAX_SNAPSHOT_BYTES = 524_288
MAX_BACKUPS = 10
FORMAT = "hvv-anzeiger-config"
PRIVATE_FORMAT = "hvv-anzeiger-private-backup"
CURRENT_SCHEMA_VERSION = 1
BACKUP_NAME = re.compile(r"backup-\d{8}T\d{12}Z-[a-f0-9]{12}\.json")
V1_FIELDS = {
    "api": {
        "base_url": str,
        "version": int,
        "refresh_seconds": int,
        "request_timeout_seconds": (int, float),
        "max_departures": int,
        "max_time_offset_minutes": int,
        "max_stale_age_minutes": int,
    },
    "display": {
        "spi_port": int,
        "spi_device": int,
        "gpio_dc": int,
        "gpio_reset": int,
        "rotate": int,
        "bus_speed_hz": int,
        "bgr": bool,
        "show_station_label": bool,
        "time_mode": str,
        "minute_unit": str,
    },
    "night_shutdown": {"enabled": bool, "start": str, "end": str},
}
V1_STATION_FIELDS = {"name": str, "city": str, "id": (str, type(None)), "label": str}
V1_ROUTE_FIELDS = {
    "line": str,
    "destination": str,
    "line_id": (str, type(None)),
    "product": (str, type(None)),
    "filter_mode": (str, type(None)),
}
FIELDS = deepcopy(V1_FIELDS)
STATION_FIELDS = deepcopy(V1_STATION_FIELDS)
ROUTE_FIELDS = deepcopy(V1_ROUTE_FIELDS)
# Released schema defaults are immutable compatibility data, not runtime defaults.
V1_DEFAULTS = {
    "api": {
        "version": 63,
        "refresh_seconds": 15,
        "request_timeout_seconds": 8,
        "max_departures": 5,
        "max_time_offset_minutes": 90,
        "max_stale_age_minutes": 5,
    },
    "display": {
        "spi_port": 0,
        "spi_device": 0,
        "gpio_dc": 24,
        "gpio_reset": 25,
        "rotate": 0,
        "bus_speed_hz": 16_000_000,
        "bgr": False,
        "show_station_label": True,
        "time_mode": "countdown",
        "minute_unit": "min",
    },
    "night_shutdown": {"enabled": False, "start": "21:00", "end": "06:30"},
}


class ConfigConflict(ConfigError):
    """The reviewed configuration has changed before confirmation."""


def _decode(payload: bytes, *, limit: int = MAX_CONFIG_BYTES) -> Any:
    if len(payload) > limit:
        raise ConfigError(f"Datei ist zu groß (höchstens {limit // 1024} KiB)")

    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def invalid_constant(_value):
        raise ValueError("Invalid JSON number")

    try:
        return json.loads(
            payload.decode("utf-8-sig"),
            object_pairs_hook=pairs,
            parse_constant=invalid_constant,
        )
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ConfigError("Datei enthält kein gültiges UTF-8-JSON") from exc


def _read(path: Path, *, limit: int = MAX_CONFIG_BYTES) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ConfigError("Nur reguläre Dateien sind zulässig")
    with path.open("rb") as source:
        payload = source.read(limit + 1)
    if len(payload) > limit:
        raise ConfigError(f"Datei ist zu groß (höchstens {limit // 1024} KiB)")
    return payload


def _fields(raw: Any, fields: dict, *, strict: bool) -> dict:
    if not isinstance(raw, dict):
        raise ConfigError("Konfigurationsabschnitt muss ein JSON-Objekt sein")
    if strict and set(raw) - set(fields):
        raise ConfigError("Datei enthält unbekannte Felder oder Zugangsdaten")
    result = {}
    for key, expected in fields.items():
        if key in raw:
            value = raw[key]
            allowed = expected if isinstance(expected, tuple) else (expected,)
            if type(value) not in allowed:
                raise ConfigError(f"Ungültiger Datentyp für {key}")
            texts = value if isinstance(value, list) else [value]
            try:
                for text in texts:
                    if isinstance(text, str):
                        text.encode("utf-8")
            except UnicodeError as exc:
                raise ConfigError("Text enthält ungültige Unicode-Zeichen") from exc
            result[key] = value
    return result


def _project_config(
    raw: Any, *, strict: bool, fields: dict, station_fields: dict, route_fields: dict
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ConfigError("Konfiguration muss ein JSON-Objekt sein")
    if strict and set(raw) - {*fields, "stations"}:
        raise ConfigError("Datei enthält unbekannte Felder oder Zugangsdaten")
    result = {
        key: _fields(raw[key], section_fields, strict=strict)
        for key, section_fields in fields.items()
        if key in raw
    }
    stations = raw.get("stations")
    if not isinstance(stations, list):
        raise ConfigError("stations muss eine Liste sein")
    result["stations"] = []
    for station in stations:
        cleaned = _fields(
            station,
            station_fields | {"serviceTypes": list, "routes": list},
            strict=strict,
        )
        for key in ("serviceTypes",):
            if key in cleaned and any(
                not isinstance(item, str) for item in cleaned[key]
            ):
                raise ConfigError("Verkehrsmittel müssen Textwerte sein")
        routes = cleaned.get("routes", [])
        cleaned["routes"] = []
        for route in routes:
            item = _fields(
                route, route_fields | {"filter_station_ids": list}, strict=strict
            )
            if any(
                not isinstance(value, str)
                for value in item.get("filter_station_ids", [])
            ):
                raise ConfigError("Filter-IDs müssen Textwerte sein")
            cleaned["routes"].append(item)
        result["stations"].append(cleaned)
    return result


def redact_config(raw: Any, *, strict: bool = False) -> dict[str, Any]:
    """Allowlist only current configuration fields; never return credential fields."""
    result = _project_config(
        raw,
        strict=strict,
        fields=FIELDS,
        station_fields=STATION_FIELDS,
        route_fields=ROUTE_FIELDS,
    )
    config_from_dict(result)
    return result


def _read_schema_v1(raw: Any, *, strict: bool) -> dict:
    if not isinstance(raw, dict) or not {"api", "display"}.issubset(raw):
        raise ConfigError("Konfiguration benötigt api, display und stations")
    result = _project_config(
        raw,
        strict=strict,
        fields=V1_FIELDS,
        station_fields=V1_STATION_FIELDS,
        route_fields=V1_ROUTE_FIELDS,
    )
    # Materialize historical defaults before current startup validation can change.
    for section, defaults in V1_DEFAULTS.items():
        if section in result or section != "api":
            result[section] = deepcopy(defaults) | result.get(section, {})
    for station in result["stations"]:
        station.setdefault("city", "Hamburg")
        station.setdefault("id", None)
        station["label"] = (
            (station.get("label") or station.get("name", "")[:1]).strip().upper()
        )
        station.setdefault("serviceTypes", [])
        for route in station["routes"]:
            for key, value in {
                "destination": "",
                "line_id": None,
                "product": None,
                "filter_mode": None,
                "filter_station_ids": [],
            }.items():
                route.setdefault(key, deepcopy(value))
    return result


SCHEMA_READERS = {1: _read_schema_v1}
SCHEMA_FIELDS = {1: (V1_FIELDS, V1_STATION_FIELDS, V1_ROUTE_FIELDS)}
SCHEMA_UPGRADERS: dict[int, Any] = {}


def migrate_config(schema_version: int, raw: Any, *, strict: bool = True) -> dict:
    if (
        type(schema_version) is not int
        or schema_version not in SCHEMA_READERS
        or not 1 <= schema_version <= CURRENT_SCHEMA_VERSION
    ):
        raise ConfigError("Unbekanntes Sicherungsschema; nicht angewendet")
    result = SCHEMA_READERS[schema_version](raw, strict=strict)
    for version in range(schema_version, CURRENT_SCHEMA_VERSION):
        upgrader = SCHEMA_UPGRADERS.get(version)
        if upgrader is None:
            raise ConfigError("Schemamigration ist nicht verfügbar; nicht angewendet")
        result = upgrader(result)
    return redact_config(result, strict=True)


def _encode(raw: Any, *, limit: int = MAX_CONFIG_BYTES) -> bytes:
    payload = (
        json.dumps(raw, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode()
    if len(payload) > limit:
        raise ConfigError(f"Datei ist zu groß (höchstens {limit // 1024} KiB)")
    return payload


def export_config(raw: Any) -> bytes:
    return _encode(
        {
            "format": FORMAT,
            "schema_version": CURRENT_SCHEMA_VERSION,
            "config": migrate_config(CURRENT_SCHEMA_VERSION, raw, strict=False),
        }
    )


def import_config(payload: bytes) -> dict[str, Any]:
    data = _decode(payload)
    if (
        isinstance(data, dict)
        and {"api", "display", "stations"}.issubset(data)
        and "format" not in data
        and "schema_version" not in data
    ):
        return migrate_config(1, data)
    if (
        not isinstance(data, dict)
        or set(data) != {"format", "schema_version", "config"}
        or data.get("format") != FORMAT
    ):
        raise ConfigError("Keine unterstützte HVV-Konfigurationssicherung")
    return migrate_config(data["schema_version"], data["config"])


def revision(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def candidate_revision(raw: dict) -> str:
    return revision(_encode(raw))


def configuration_diff(before: dict, after: dict) -> list[dict[str, Any]]:
    def flatten(value, prefix=""):
        if isinstance(value, dict):
            return {
                key: item
                for name, child in value.items()
                for key, item in flatten(child, f"{prefix}.{name}".lstrip(".")).items()
            }
        if isinstance(value, list):
            return {
                key: item
                for index, child in enumerate(value)
                for key, item in flatten(child, f"{prefix}[{index}]").items()
            }
        return {prefix: value}

    old, new = flatten(before), flatten(after)
    return [
        {"field": key, "before": old.get(key), "after": new.get(key)}
        for key in sorted(old.keys() | new.keys())
        if key not in old or key not in new or old[key] != new[key]
    ]


def _sync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    except OSError:
        LOG.warning("Verzeichnis-Synchronisierung ist nicht verfügbar")


def _discard(temporary: Path) -> None:
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        LOG.warning("Temporäre Konfigurationsdatei konnte nicht bereinigt werden")


def _temporary(path: Path, payload: bytes, owner: tuple[int, int]) -> Path:
    descriptor, name = tempfile.mkstemp(prefix=".hvv-config-", suffix=".tmp", dir=path)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            os.chmod(temporary, 0o600)
            if os.name != "nt" and os.geteuid() == 0:
                os.fchown(target.fileno(), *owner)
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        return temporary
    except BaseException:
        _discard(temporary)
        raise


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        root = (
            self.path.parent
            if self.path.parent.name == "var"
            else self.path.parent / "var"
        )
        suffix = (
            ""
            if self.path.name == "config.json"
            else "-" + revision(self.path.name.encode())[:12]
        )
        self.backups = root / ("config-backups" + suffix)

    @contextmanager
    def locked(self):
        if self.backups.is_symlink():
            raise ConfigError("Sicherungsverzeichnis darf kein symbolischer Link sein")
        parent_existed = self.backups.parent.exists()
        self.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.backups.chmod(0o700)
        owner = self.path.stat()
        self._owner = (owner.st_uid, owner.st_gid)
        if os.name != "nt" and os.geteuid() == 0:
            if not parent_existed:
                os.chown(self.backups.parent, *self._owner)
            os.chown(self.backups, *self._owner)
        descriptor = os.open(
            self.backups / ".lock",
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        acquired = False
        try:
            if os.name != "nt" and os.geteuid() == 0:
                os.fchown(descriptor, *self._owner)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ConfigError("Sperrdatei muss eine reguläre Datei sein")
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"0")
            deadline = time.monotonic() + 2
            while not acquired:
                try:
                    if os.name == "nt":
                        import msvcrt

                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    acquired = True
                except OSError:
                    if time.monotonic() >= deadline:
                        raise ConfigConflict(
                            "Konfiguration wird gerade geändert; erneut versuchen"
                        ) from None
                    time.sleep(0.05)
            # Recover only our own abandoned staging files after process/power loss.
            for parent in {self.path.parent, self.backups}:
                for abandoned in parent.glob(".hvv-config-*.tmp"):
                    if stat.S_ISREG(abandoned.lstat().st_mode):
                        abandoned.unlink()
            yield
        finally:
            try:
                if acquired:
                    if os.name == "nt":
                        os.lseek(descriptor, 0, os.SEEK_SET)
                        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(descriptor, fcntl.LOCK_UN)
            except OSError:
                LOG.warning("Dateisperre wird durch Schließen der Datei freigegeben")
            finally:
                os.close(descriptor)

    def current(self) -> tuple[dict, str]:
        payload = _read(self.path)
        return migrate_config(
            CURRENT_SCHEMA_VERSION, _decode(payload), strict=False
        ), revision(payload)

    def base_revision(self) -> str:
        return revision(_read(self.path))

    def preview(self, candidate: dict) -> dict:
        candidate = migrate_config(CURRENT_SCHEMA_VERSION, candidate)
        payload = _read(self.path)
        try:
            before = migrate_config(
                CURRENT_SCHEMA_VERSION, _decode(payload), strict=False
            )
            damaged = False
        except ConfigError:
            before, damaged = {}, True
        return {
            "base_revision": revision(payload),
            "candidate_revision": candidate_revision(candidate),
            "current_invalid": damaged,
            "changes": configuration_diff(before, candidate),
        }

    def list_backups(self) -> list[str]:
        names = []
        for path in self.backups.glob("backup-*.json"):
            try:
                if BACKUP_NAME.fullmatch(path.name) and stat.S_ISREG(
                    path.lstat().st_mode
                ):
                    names.append(path.name)
            except FileNotFoundError:
                continue
        return sorted(names, reverse=True)

    def backup_payload(self, name: str) -> bytes:
        return self._snapshot(name)[1]

    def _snapshot(self, name: str) -> tuple[int, bytes]:
        if not BACKUP_NAME.fullmatch(name):
            raise ConfigError("Ungültige Sicherungs-ID")
        payload = _read(self.backups / name, limit=MAX_SNAPSHOT_BYTES)
        try:
            record = _decode(payload, limit=MAX_SNAPSHOT_BYTES)
        except ConfigError:
            record = None
        if isinstance(record, dict) and record.get("format") == PRIVATE_FORMAT:
            try:
                decoded = base64.b64decode(record["payload_base64"], validate=True)
                version = record["schema_version"]
                if type(version) is not int or len(decoded) > MAX_CONFIG_BYTES:
                    raise ValueError("Invalid snapshot")
            except (KeyError, ValueError, TypeError, binascii.Error) as exc:
                raise ConfigError("Interne Sicherung ist beschädigt") from exc
            return version, decoded
        if len(payload) > MAX_CONFIG_BYTES:
            raise ConfigError("Interne Sicherung ist zu groß")
        # Historical unwrapped snapshots predate the versioned backup format.
        return 1, payload

    def backup_candidate(self, name: str) -> dict:
        version, payload = self._snapshot(name)
        return migrate_config(version, _decode(payload), strict=False)

    def _backup(self, payload: bytes) -> str:
        names = self.list_backups()
        for name in names[MAX_BACKUPS - 1 :]:
            (self.backups / name).unlink()
        name = (
            "backup-"
            + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            + "-"
            + secrets.token_hex(6)
            + ".json"
        )
        snapshot = _encode(
            {
                "format": PRIVATE_FORMAT,
                "schema_version": CURRENT_SCHEMA_VERSION,
                "producer_version": __version__,
                "payload_base64": base64.b64encode(payload).decode("ascii"),
            },
            limit=MAX_SNAPSHOT_BYTES,
        )
        temporary = _temporary(self.backups, snapshot, self._owner)
        try:
            os.replace(temporary, self.backups / name)
        finally:
            _discard(temporary)
        _sync_directory(self.backups)
        return name

    def backup(self) -> str:
        with self.locked():
            return self._backup(_read(self.path))

    def apply(
        self, candidate: dict, *, expected_revision: str | None = None
    ) -> str | None:
        candidate = migrate_config(CURRENT_SCHEMA_VERSION, candidate)
        payload = _encode(candidate)
        with self.locked():
            old = _read(self.path)
            if expected_revision is not None and revision(old) != expected_revision:
                raise ConfigConflict(
                    "Konfiguration wurde inzwischen geändert; Vorschau erneut öffnen"
                )
            if old == payload:
                return None
            temporary = _temporary(self.path.parent, payload, self._owner)
            try:
                name = self._backup(old)
                os.replace(temporary, self.path)
            finally:
                _discard(temporary)
            _sync_directory(self.path.parent)
            return name


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Lokale Konfigurationssicherung ohne Zugangsdaten"
    )
    parser.add_argument(
        "--config", type=Path, default=Path(os.environ.get("HVV_CONFIG", "config.json"))
    )
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("--output", type=Path)
    export.add_argument("--backup")
    commands.add_parser("backups")
    commands.add_parser("backup")
    for command in ("preview", "apply"):
        action = commands.add_parser(command)
        source = action.add_mutually_exclusive_group(required=True)
        source.add_argument("--file", type=Path)
        source.add_argument("--backup")
        if command == "apply":
            action.add_argument("--base-revision", required=True)
            action.add_argument("--candidate-revision", required=True)
            action.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    store = ConfigStore(args.config)
    try:
        if args.command == "export":
            raw = (
                store.backup_candidate(args.backup)
                if args.backup
                else store.current()[0]
            )
            payload = export_config(raw)
            if args.output:
                descriptor = os.open(
                    args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
                )
                with os.fdopen(descriptor, "wb") as target:
                    target.write(payload)
            else:
                print(payload.decode(), end="")
        elif args.command == "backups":
            print(json.dumps(store.list_backups()))
        elif args.command == "backup":
            print(store.backup())
        else:
            candidate = (
                import_config(_read(args.file))
                if args.file
                else store.backup_candidate(args.backup)
            )
            if args.command == "preview":
                print(
                    json.dumps(store.preview(candidate), ensure_ascii=False, indent=2)
                )
            else:
                if not args.confirm:
                    raise ConfigError(
                        "Anwenden benötigt --confirm nach geprüfter Vorschau"
                    )
                if candidate_revision(candidate) != args.candidate_revision:
                    raise ConfigConflict(
                        "Importdatei wurde seit der Vorschau verändert"
                    )
                print(
                    json.dumps(
                        {
                            "backup": store.apply(
                                candidate, expected_revision=args.base_revision
                            )
                        }
                    )
                )
        return 0
    except ConfigConflict as exc:
        print(f"Konflikt: {exc}")
        return 3
    except ConfigError as exc:
        print(f"Nicht angewendet: {exc}")
        return 2
    except OSError:
        print("Dateizugriff fehlgeschlagen; aktive Konfiguration bleibt erhalten")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
