"""Validate CYD Geofox credentials without printing YAML or ESPHome output."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

FIELDS = ("geofox_user_cpp", "geofox_password_cpp")
CPP_STRING = re.compile(r'"(?:[^"\\\x00-\x1f\x7f]|\\["\\bfnrt]|\\u002[267])*"')


def valid_literal(value):
    if not isinstance(value, str) or not CPP_STRING.fullmatch(value):
        return False
    decoded = json.loads(value)
    return bool(decoded.strip()) and not any(ord(char) < 32 or ord(char) == 127 for char in decoded)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", type=Path)
    parser.add_argument("--esphome", choices=("config", "compile"))
    args = parser.parse_args()

    try:
        with args.profile.with_name("secrets.yaml").open(encoding="utf-8-sig") as stream:
            values = yaml.safe_load(stream)
    except (OSError, UnicodeError, yaml.YAMLError):
        sys.exit("secrets.yaml fehlt neben dem CYD-Profil oder enthält ungültiges YAML.")
    if not isinstance(values, dict):
        sys.exit("secrets.yaml muss eine YAML-Zuordnung enthalten.")

    for name in FIELDS:
        if not valid_literal(values.get(name)):
            sys.exit(f"{name} fehlt oder ist ungültig. Erwartet wird ein nichtleeres C++-Stringliteral in secrets.yaml.")

    if args.esphome:
        result = subprocess.run(
            [sys.executable, "-m", "esphome", args.esphome, str(args.profile)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if result.returncode:
            sys.exit(f"ESPHome {args.esphome} fehlgeschlagen. Prüfe Profil, Stationen, WLAN/API-Secrets und ESPHome-Installation.")


if __name__ == "__main__":
    main()
