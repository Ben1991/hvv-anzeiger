"""Publish complete private files, including filesystem durability barriers."""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

LOG = logging.getLogger(__name__)


def atomic_write(path: Path, payload: bytes) -> None:
    """Publish old or new contents; never truncate the live file in place.

    Unique same-directory temporary files remain harmless after SIGKILL. A
    successful return means file contents and the rename have been synced on
    POSIX. This cannot compensate for failing storage or dishonest hardware.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary, path)
        if os.name != "nt":  # pragma: no branch - Windows has no directory fsync
            directory = os.open(
                path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            )
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            LOG.warning("Temporäre Speicherdatei konnte nicht bereinigt werden")
