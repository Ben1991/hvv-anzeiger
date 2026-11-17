"""Real process termination at persistence boundaries; no physical power test."""

import os
import stat
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display import storage
from hvv_display.config import load_config
from hvv_display.credentials import load_credentials
from hvv_display.departure_cache import DepartureCache, departure_source
from hvv_display.storage import atomic_write
from hvv_display.web import (
    WebApplication,
    load_web_password_hash,
    save_credentials,
    verify_web_password,
)

ROOT = Path(__file__).resolve().parents[1]

# A child really stops at the selected boundary and is killed without finally
# blocks or atexit handlers. All payloads below are synthetic test data.
WRITER = """
import sys
from pathlib import Path
from hvv_display import storage
target, marker = map(Path, sys.argv[1:3])
phase = sys.argv[3]
def stop():
    marker.write_text('ready')
    sys.stdin.buffer.read(1)
sync = storage.os.fsync
replace = storage.os.replace
def fsync(fd):
    if phase == 'before_sync':
        stop()
    return sync(fd)
def publish(source, destination):
    if phase == 'before_rename':
        stop()
    replace(source, destination)
    if phase == 'after_rename':
        stop()
storage.os.fsync = fsync
storage.os.replace = publish
payload = b'GEOFOX_USER=new-user\\n'
payload += b'GEOFOX_PASSWORD=new-test-value\\n'
storage.atomic_write(target, payload)
"""


class PowerLossTest(unittest.TestCase):
    def test_killed_version_switch_never_leaves_live_application_path_missing(self):
        script = """
import sys
from pathlib import Path
from hvv_display import install_state as module
app, marker, stage = map(Path, sys.argv[1:4])
phase = sys.argv[4]
def stop():
    marker.write_text('ready')
    sys.stdin.buffer.read(1)
exchange, rename = module._exchange, module.os.replace
def swap(first, second):
    if phase == 'before_exchange': stop()
    exchange(first, second)
    if phase == 'after_exchange': stop()
def replace(source, destination):
    if phase == 'before_backup': stop()
    rename(source, destination)
    if phase == 'after_backup': stop()
module._exchange, module.os.replace = swap, replace
module.activate_install(app, stage)
"""
        for phase in (
            "before_exchange",
            "after_exchange",
            "before_backup",
            "after_backup",
        ):
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                app, stage = Path(directory) / "app", Path(directory) / "stage"
                app.mkdir()
                stage.mkdir()
                for tree, value in ((app, "old"), (stage, "new")):
                    (tree / "version").write_text(value)
                    (tree / "module").write_text(value + "-complete")
                self.kill_at_checkpoint(
                    script, app, Path(directory) / "ready", stage, phase
                )
                expected = "old" if phase == "before_exchange" else "new"
                self.assertEqual((app / "version").read_text(), expected)
                self.assertEqual((app / "module").read_text(), expected + "-complete")

    def kill_at_checkpoint(self, script, *arguments):
        marker = Path(arguments[1])
        child = subprocess.Popen(  # noqa: S603 - fixed scripts, isolated fixtures
            [sys.executable, "-c", script, *map(str, arguments)],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            deadline = time.monotonic() + 10
            while not marker.exists():
                if child.poll() is not None:
                    self.fail(child.communicate()[1].decode())
                if time.monotonic() > deadline:
                    self.fail("writer did not reach crash checkpoint")
                time.sleep(0.01)
            child.kill()
            child.communicate(timeout=5)
            self.assertNotEqual(child.returncode, 0)
        finally:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def test_killed_writer_leaves_complete_old_or_new_credentials_and_can_restart(self):
        for phase in ("before_sync", "before_rename", "after_rename"):
            with self.subTest(phase=phase), TemporaryDirectory() as directory:
                target = Path(directory) / "credentials.env"
                save_credentials(target, "old-user", "old-test-value")
                self.kill_at_checkpoint(
                    WRITER, target, Path(directory) / "ready", phase
                )
                expected = "new-user" if phase == "after_rename" else "old-user"
                self.assertEqual(load_credentials(target)["GEOFOX_USER"], expected)
                self.assertEqual(
                    load_credentials(target)["GEOFOX_PASSWORD"],
                    "new-test-value" if phase == "after_rename" else "old-test-value",
                )
                # Leftover temporary files must not block the next process.
                save_credentials(target, "restart-user", "restart-test-value")
                self.assertEqual(
                    load_credentials(target)["GEOFOX_USER"], "restart-user"
                )
                if os.name != "nt":
                    self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_kernel_releases_cache_lock_when_owner_is_killed(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "departures.json"
            marker = Path(directory) / "ready"
            script = """
import sys
from pathlib import Path
from hvv_display.departure_cache import _exclusive_cache_lock
with _exclusive_cache_lock(Path(sys.argv[1])):
    Path(sys.argv[2]).write_text('ready')
    sys.stdin.buffer.read(1)
"""
            self.kill_at_checkpoint(script, target, marker)
            source = departure_source(load_config(ROOT / "config.example.json"))
            writer = """
import sys
from pathlib import Path
from datetime import datetime, timezone
from hvv_display.departure_cache import DepartureCache
DepartureCache(Path(sys.argv[1])).save([], datetime.now(timezone.utc), sys.argv[2])
"""
            subprocess.run(  # noqa: S603 - fixed recovery script
                [sys.executable, "-c", writer, str(target), source],
                cwd=ROOT,
                check=True,
                timeout=10,
                capture_output=True,
            )
            self.assertIsNotNone(DepartureCache(target).load(source))

    def test_killed_config_writer_does_not_block_next_valid_configuration(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "config.json"
            target.write_bytes((ROOT / "config.example.json").read_bytes())
            script = """
import sys
from pathlib import Path
from hvv_display.config_backup import ConfigStore
with ConfigStore(Path(sys.argv[1])).locked():
    Path(sys.argv[1]).with_name('.hvv-config-abandoned.tmp').write_bytes(b'incomplete')
    Path(sys.argv[2]).write_text('ready')
    sys.stdin.buffer.read(1)
"""
            self.kill_at_checkpoint(script, target, Path(directory) / "ready")
            apply = """
import sys, json
from pathlib import Path
from hvv_display.config_backup import ConfigStore
path = Path(sys.argv[1])
candidate = json.loads(path.read_bytes())
candidate['api']['refresh_seconds'] = 30
ConfigStore(path).apply(candidate)
"""
            subprocess.run(  # noqa: S603 - fixed recovery script
                [sys.executable, "-c", apply, str(target)],
                cwd=ROOT,
                check=True,
                timeout=10,
                capture_output=True,
            )
            self.assertEqual(load_config(target).api.refresh_seconds, 30)
            self.assertFalse(target.with_name(".hvv-config-abandoned.tmp").exists())

    def test_sync_order_and_write_failures_preserve_complete_live_file(self):
        with TemporaryDirectory() as directory:
            target = Path(directory) / "private.env"
            atomic_write(target, b"old-complete")
            events = []
            sync, rename = os.fsync, os.replace

            def track_sync(fd):
                events.append(
                    "file" if stat.S_ISREG(os.fstat(fd).st_mode) else "directory"
                )
                sync(fd)

            def track_rename(source, destination):
                events.append("rename")
                rename(source, destination)

            with (
                patch.object(storage.os, "fsync", side_effect=track_sync),
                patch.object(storage.os, "replace", side_effect=track_rename),
            ):
                atomic_write(target, b"new-complete")
            expected = (
                ["file", "rename", "directory"]
                if os.name != "nt"
                else ["file", "rename"]
            )
            self.assertEqual(events, expected)
            for operation in ("fsync", "replace"):
                with patch.object(
                    storage.os, operation, side_effect=OSError("disk error")
                ):
                    with self.assertRaises(OSError):
                        atomic_write(target, b"not-published")
                self.assertEqual(target.read_bytes(), b"new-complete")
                self.assertEqual(list(target.parent.glob(".private.env.*")), [])

    def test_failed_directory_sync_is_reported_after_complete_rename(self):
        if os.name == "nt":
            self.skipTest("Windows has no directory fsync")
        with TemporaryDirectory() as directory:
            target = Path(directory) / "state"
            with patch.object(storage.os, "fsync", side_effect=[None, OSError("disk")]):
                with self.assertRaises(OSError):
                    atomic_write(target, b"complete")
            self.assertEqual(target.read_bytes(), b"complete")

    def test_cleanup_failure_does_not_hide_original_write_failure(self):
        with TemporaryDirectory() as directory:
            with (
                patch.object(storage.os, "fsync", side_effect=OSError("write error")),
                patch.object(Path, "unlink", side_effect=PermissionError),
            ):
                with self.assertLogs("hvv_display.storage", level="WARNING"):
                    with self.assertRaisesRegex(OSError, "write error"):
                        atomic_write(Path(directory) / "state", b"data")

    def test_password_is_private_and_only_activated_after_confirmed_persistence(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            app = WebApplication(
                ROOT / "config.example.json",
                root / "credentials",
                root / "stations",
                web_env_path=root / "web.env",
            )
            app.save_web_password("old-synthetic-password")
            before = app.web_env_path.read_bytes()
            with patch(
                "hvv_display.storage.os.fsync", side_effect=OSError("disk error")
            ):
                with self.assertRaises(OSError):
                    app.save_web_password("new-synthetic-password")
            self.assertEqual(app.web_env_path.read_bytes(), before)
            self.assertTrue(
                verify_web_password("old-synthetic-password", app.access_token)
            )
            app.save_web_password("new-synthetic-password")
            restarted = WebApplication(
                ROOT / "config.example.json",
                root / "credentials",
                root / "stations",
                web_env_path=app.web_env_path,
                access_token=load_web_password_hash(app.web_env_path),
            )
            self.assertTrue(
                verify_web_password("new-synthetic-password", restarted.access_token)
            )
