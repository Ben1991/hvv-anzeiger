"""Snapshot untrusted runtime data into the installer's private staging tree.

Linux-only: every source component is opened relative to a pinned directory
descriptor, without following links. Never use a check followed by pathname cp.
"""

from __future__ import annotations

import argparse
import ctypes
import os
import shutil
import stat
import tempfile
from pathlib import Path


def _sync_parent(path: Path) -> None:
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _exchange(first: Path, second: Path) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    ]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(first), -100, os.fsencode(second), 2) != 0:
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number))


def activate_install(application: Path, staging: Path) -> None:
    """The live name always points to a complete old or prepared new tree."""
    backup = application.with_name(application.name + ".previous")
    if (
        application.is_symlink()
        or staging.is_symlink()
        or backup.exists()
        or application.parent.resolve() != staging.parent.resolve()
    ):
        raise ValueError("Unsichere oder nicht benachbarte Aktivierungspfade")
    if not application.exists():
        os.replace(staging, application)
    else:
        _exchange(application, staging)
        try:
            os.replace(staging, backup)
        except BaseException:
            _exchange(application, staging)
            raise
    _sync_parent(application)


def relocate_entrypoints(application: Path, staging: Path) -> None:
    """Rewrite generated shebangs before publication, never reinstall live code."""
    old = os.fsencode(staging / ".venv")
    new = os.fsencode(application / ".venv")
    for path in (staging / ".venv/bin").iterdir():
        if path.is_symlink() or not path.is_file():
            continue
        payload = path.read_bytes()
        if old in payload:
            path.write_bytes(payload.replace(old, new))


def rollback_install(application: Path, previous: Path) -> None:
    if application.is_symlink() or previous.is_symlink():
        raise ValueError("Installationsverweise werden nicht getauscht")
    _exchange(application, previous)
    _sync_parent(application)


def publish_unit(source: Path, destination: Path, *, preserve: bool = False) -> None:
    descriptor, name = tempfile.mkstemp(prefix=".hvv-unit-", dir=destination.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            metadata = source.stat()
            os.fchmod(
                target.fileno(), stat.S_IMODE(metadata.st_mode) if preserve else 0o644
            )
            if preserve and os.geteuid() == 0:
                os.fchown(target.fileno(), metadata.st_uid, metadata.st_gid)
            target.write(source.read_bytes())
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, destination)
        _sync_parent(destination)
    finally:
        temporary.unlink(missing_ok=True)


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
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--activate", action="store_true")
    action.add_argument("--relocate", action="store_true")
    action.add_argument("--publish-unit", action="store_true")
    action.add_argument("--restore-file", action="store_true")
    action.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if args.activate:
        activate_install(args.application, args.staging)
    elif args.rollback:
        rollback_install(args.application, args.staging)
    elif args.relocate:
        relocate_entrypoints(args.application, args.staging)
    elif args.publish_unit:
        publish_unit(args.application, args.staging)
    elif args.restore_file:
        publish_unit(args.application, args.staging, preserve=True)
    else:
        copy_install_state(args.application, args.staging)


if __name__ == "__main__":
    main()
