from __future__ import annotations

import os
from pathlib import Path


def _env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def load_credentials(path: str | Path) -> dict[str, str]:
    """Read only the two Geofox variables from a shell-style env file."""
    credentials: dict[str, str] = {}
    credential_path = Path(path)
    if credential_path.is_file():
        for line in credential_path.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in {"GEOFOX_USER", "GEOFOX_PASSWORD"}:
                credentials[key.strip()] = _env_value(value)
    for key in ("GEOFOX_USER", "GEOFOX_PASSWORD"):
        if os.environ.get(key) and key not in credentials:
            credentials[key] = os.environ[key]
    return credentials
