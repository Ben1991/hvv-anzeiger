"""Validate/compile examples in isolation, without reading user secrets."""

import argparse
import base64
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONFIGS = ("hvv-display.yaml", "hvv-cyd.yaml", "hvv-s3-ili9488.yaml", "hvv-direct.yaml")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compile", choices=CONFIGS, dest="firmware")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="hvv-") as directory:
        target = Path(directory) / "esphome"
        shutil.copytree(
            ROOT / "esphome",
            target,
            ignore=shutil.ignore_patterns(".esphome", "secrets.yaml"),
        )
        values = yaml.safe_load((target / "secrets.example.yaml").read_text())
        values["api_encryption_key"] = base64.b64encode(
            secrets.token_bytes(32)
        ).decode()
        (target / "secrets.yaml").write_text(yaml.safe_dump(values))
        for name in CONFIGS:
            subprocess.run(  # noqa: S603
                [sys.executable, "-m", "esphome", "config", str(target / name)],
                check=True,
                stdout=subprocess.DEVNULL,
            )
        if args.firmware:
            subprocess.run(  # noqa: S603
                [
                    sys.executable,
                    "-m",
                    "esphome",
                    "compile",
                    str(target / args.firmware),
                ],
                check=True,
            )


if __name__ == "__main__":
    main()
