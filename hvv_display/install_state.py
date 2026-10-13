"""Snapshot untrusted runtime data into the installer's private staging tree.

Linux-only: every source component is opened relative to a pinned directory
descriptor, without following links. Never use a check followed by pathname cp.
"""

from __future__ import annotations

import argparse
import os
import shutil
import stat
from pathlib import Path


def _directory(name: str, parent: int | None = None) -> int:
    return os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)


def _copy_file(name: str, parent: int, destination: Path) -> None:
    descriptor = os.open(
        name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent
    )
    with os.fdopen(descriptor, "rb") as source:
        metadata = os.fstat(source.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
            raise ValueError("Nur reguläre Dateien ohne weitere Hardlinks übernehmen")
        # Destination belongs to root in a private staging directory.
        with destination.open("wb") as target:
            shutil.copyfileobj(source, target)
        destination.chmod((stat.S_IMODE(metadata.st_mode) & 0o660) | 0o600)


def _copy_tree(source: int, destination: Path) -> None:
    for name in os.listdir(source):
        metadata = os.stat(name, dir_fd=source, follow_symlinks=False)
        target = destination / name
        if stat.S_ISDIR(metadata.st_mode):
            descriptor = _directory(name, source)
            try:
                target.mkdir(mode=0o700)
                _copy_tree(descriptor, target)
            finally:
                os.close(descriptor)
        elif stat.S_ISREG(metadata.st_mode):
            _copy_file(name, source, target)
        else:
            raise ValueError(
                "Dateiverweise und Spezialdateien im Datenbereich abgelehnt"
            )


def copy_install_state(application: Path, staging: Path) -> None:
    """Keep old regular configs and the documented config.json -> var alias."""
    try:
        app = _directory(str(application))
    except FileNotFoundError:
        return
    try:
        try:
            runtime = _directory("var", app)
        except FileNotFoundError:
            runtime = None
        try:
            if runtime is not None:
                _copy_tree(runtime, staging / "var")
            try:
                config = os.stat("config.json", dir_fd=app, follow_symlinks=False)
            except FileNotFoundError:
                return
            if stat.S_ISLNK(config.st_mode):
                alias = os.readlink("config.json", dir_fd=app)
                if alias not in {
                    "var/config.json",
                    str(application / "var/config.json"),
                }:
                    raise ValueError("Unbekannter Konfigurationsverweis abgelehnt")
                if runtime is None:
                    raise ValueError("Konfigurationsverweis ohne Datenverzeichnis")
                _copy_file("config.json", runtime, staging / "config.json")
            else:
                _copy_file("config.json", app, staging / "config.json")
        finally:
            if runtime is not None:
                os.close(runtime)
    finally:
        os.close(app)


def main() -> None:
    parser = argparse.ArgumentParser(description="Sichere Installationsdatenübernahme")
    parser.add_argument("application", type=Path)
    parser.add_argument("staging", type=Path)
    args = parser.parse_args()
    copy_install_state(args.application, args.staging)


if __name__ == "__main__":
    main()
