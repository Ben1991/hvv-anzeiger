#!/usr/bin/env python3
"""Replace only the stations section of an HVV-Anzeiger configuration."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Haltestellen ersetzen, die vollständige Konfiguration validieren "
            "und standardmäßig nur als Vorschau ausgeben."
        )
    )
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--stations-file", required=True, type=Path)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Validierte Konfiguration atomar schreiben und vorher sichern.",
    )
    return parser


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Datei nicht gefunden: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Ungültiges JSON in {path}: {exc}") from exc


def _stations(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("stations")
    if not isinstance(value, list) or not value:
        raise ValueError(
            "Die Haltestellendatei muss ein nicht leeres JSON-Array oder "
            "ein Objekt mit einem nicht leeren Feld 'stations' enthalten."
        )
    if not all(isinstance(item, dict) for item in value):
        raise ValueError("Jede Haltestelle muss ein JSON-Objekt sein.")
    return value


def _project_root(config_path: Path) -> Path:
    candidates = [config_path.resolve().parent, Path.cwd().resolve()]
    candidates.extend(Path(__file__).resolve().parents)
    for candidate in candidates:
        if (candidate / "hvv_display" / "config.py").is_file():
            return candidate
    raise ValueError(
        "Projektwurzel mit hvv_display/config.py wurde nicht gefunden."
    )


def _validate(config: dict[str, Any], root: Path) -> None:
    sys.path.insert(0, str(root))
    from hvv_display.config import ConfigError, load_config

    with tempfile.TemporaryDirectory(prefix="hvv-config-") as directory:
        candidate = Path(directory) / "config.json"
        candidate.write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            load_config(candidate)
        except ConfigError as exc:
            raise ValueError(f"Konfiguration ist ungültig: {exc}") from exc


def _backup_path(config_path: Path) -> Path:
    timestamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    candidate = config_path.with_name(f"{config_path.name}.bak-{timestamp}")
    counter = 1
    while candidate.exists():
        candidate = config_path.with_name(
            f"{config_path.name}.bak-{timestamp}-{counter}"
        )
        counter += 1
    return candidate


def _write(config_path: Path, config: dict[str, Any]) -> Path:
    backup = _backup_path(config_path)
    shutil.copy2(config_path, backup)
    payload = json.dumps(config, ensure_ascii=False, indent=2) + "\n"
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config_path.parent,
            prefix=f".{config_path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        shutil.copymode(config_path, temporary)
        temporary.replace(config_path)
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return backup


def main() -> int:
    args = _parser().parse_args()
    try:
        raw_config = _read_json(args.config)
        if not isinstance(raw_config, dict):
            raise ValueError("Die Konfiguration muss ein JSON-Objekt sein.")
        updated = dict(raw_config)
        updated["stations"] = _stations(_read_json(args.stations_file))
        _validate(updated, _project_root(args.config))
        if args.write:
            backup = _write(args.config, updated)
            print(f"Konfiguration aktualisiert. Sicherung: {backup}")
        else:
            print(json.dumps(updated, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
