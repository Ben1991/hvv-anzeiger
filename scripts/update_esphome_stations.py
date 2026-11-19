#!/usr/bin/env python3
"""Safely replace the station JSON in a local ESPHome profile."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Haltestellen im lokalen ESPHome-Profil prüfen oder ersetzen."
    )
    parser.add_argument(
        "--profile", type=Path, default=Path("esphome/hvv-cyd.local.yaml")
    )
    parser.add_argument("--stations-file", required=True, type=Path)
    parser.add_argument("--write", action="store_true")
    parser.add_argument(
        "--expected-sha256",
        help="Nur schreiben, wenn die Profil-Datei noch diesen SHA-256-Wert hat.",
    )
    return parser


def _load_stations(path: Path) -> list[dict[str, Any]]:
    try:
        stations = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Datei nicht gefunden: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungültiges JSON in {path}: {exc}") from exc
    if not isinstance(stations, list) or not 1 <= len(stations) <= 4:
        raise ValueError("Es müssen ein bis vier Haltestellen angegeben werden.")

    labels: set[str] = set()
    for index, station in enumerate(stations, 1):
        if not isinstance(station, dict):
            raise ValueError(f"Haltestelle {index} muss ein JSON-Objekt sein.")
        for key in ("name", "city", "id", "label"):
            if not isinstance(station.get(key), str) or not station[key].strip():
                raise ValueError(f"Haltestelle {index}: '{key}' muss gesetzt sein.")
        label = station["label"].strip()
        if len(label) > 3 or label.casefold() in labels:
            raise ValueError(
                "Labels müssen eindeutig sein und höchstens 3 Zeichen haben."
            )
        labels.add(label.casefold())
        routes = station.get("routes", [])
        if not isinstance(routes, list):
            raise ValueError(f"Haltestelle {index}: 'routes' muss ein Array sein.")
        for route_index, route in enumerate(routes, 1):
            if not isinstance(route, dict):
                raise ValueError(
                    f"Haltestelle {index}, Linie {route_index} muss ein Objekt sein."
                )
            for key in ("line", "destination"):
                if not isinstance(route.get(key), str) or not route[key].strip():
                    raise ValueError(
                        f"Haltestelle {index}, Linie {route_index}: '{key}' muss "
                        "gesetzt sein."
                    )
    return stations


def _yaml_single_quoted(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _replace_stations(profile: str, stations: list[dict[str, Any]]) -> str:
    pattern = re.compile(r"(?m)^(\s*hvv_stations_json:\s*)'(.*)'\s*$")
    matches = list(pattern.finditer(profile))
    if len(matches) != 1:
        raise ValueError(
            "Das Profil muss genau eine einfach zitierte Zeile "
            "'hvv_stations_json' enthalten."
        )
    encoded = json.dumps(stations, ensure_ascii=False, separators=(",", ":"))
    match = matches[0]
    return (
        profile[: match.start()]
        + match.group(1)
        + _yaml_single_quoted(encoded)
        + profile[match.end() :]
    )


def main() -> int:
    args = _parser().parse_args()
    try:
        current = args.profile.read_bytes()
        current_hash = hashlib.sha256(current).hexdigest()
        if args.write and args.expected_sha256 and args.expected_sha256 != current_hash:
            raise ValueError(
                "Das Profil wurde seit der Prüfung geändert; bitte erneut prüfen."
            )
        profile = current.decode("utf-8")
        stations = _load_stations(args.stations_file)
        updated = _replace_stations(profile, stations)

        # Parse back the edited YAML scalar content and JSON to catch quoting errors.
        match = re.search(r"(?m)^\s*hvv_stations_json:\s*'(.*)'\s*$", updated)
        if not match:
            raise ValueError(
                "Die aktualisierte YAML-Zeile konnte nicht geprüft werden."
            )
        decoded_json = match.group(1).replace("''", "'")
        if json.loads(decoded_json) != stations:
            raise ValueError("Die Haltestellendaten haben die Prüfung nicht bestanden.")

        if not args.write:
            print(f"Profil: {args.profile}")
            print(f"SHA-256: {current_hash}")
            print(json.dumps(stations, ensure_ascii=False, indent=2))
            return 0

        backup = args.profile.with_name(
            f"{args.profile.name}.{datetime.now().strftime('%Y%m%d-%H%M%S-%f')}.bak"
        )
        backup.write_bytes(current)
        temporary = args.profile.with_name(args.profile.name + ".tmp")
        try:
            temporary.write_text(updated, encoding="utf-8", newline="")
            os.replace(temporary, args.profile)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Haltestellen aktualisiert. Sicherung: {backup}")
        return 0
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
