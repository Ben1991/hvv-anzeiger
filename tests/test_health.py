import io
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from hvv_display.health import (
    MAX_SNAPSHOT_BYTES,
    STATUS_CODES,
    HealthPublisher,
    health_path,
    main,
    read_health,
)


class HealthTest(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "var" / "health.json"
        self.now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
        self.values = {
            "configuration_valid": True,
            "network_connected": True,
            "clock_synchronized": True,
            "display_available": True,
            "last_successful_fetch": self.now,
        }

    def publish(self, **changes):
        with patch("hvv_display.health.datetime") as clock:
            clock.now.return_value = self.now
            publisher = HealthPublisher(self.path)
            publisher.publish(**(self.values | changes))
        return publisher

    def read(self, **changes):
        self.publish(**changes)
        return read_health(self.path, now=self.now)

    def test_healthy_schema_is_stable_and_contains_only_status_values(self):
        data = self.read()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(
            set(data),
            {
                "schema_version",
                "version",
                "status",
                "service_running",
                "uptime_seconds",
                "configuration_valid",
                "network_connected",
                "clock_synchronized",
                "display_available",
                "night_shutdown",
                "last_successful_fetch",
                "data_age_seconds",
                "stale",
                "consecutive_failures",
                "error_kind",
                "retry_in_seconds",
                "rate_limit_active",
                "rate_limit_remaining_seconds",
                "heartbeat_age_seconds",
                "snapshot_available",
            },
        )
        self.assertEqual(data["schema_version"], 1)
        self.assertEqual(data["data_age_seconds"], 0)
        self.assertEqual(data["uptime_seconds"], 0)
        self.assertTrue(data["service_running"])
        self.assertFalse(data["stale"])
        self.assertLess(self.path.stat().st_size, MAX_SNAPSHOT_BYTES)

    def test_offline_unknown_clock_and_display_failure_are_distinct(self):
        for changes, expected in (
            ({"network_connected": False}, "degraded"),
            ({"network_connected": None}, "degraded"),
            ({"clock_synchronized": False}, "degraded"),
            ({"clock_synchronized": None}, "degraded"),
            ({"display_available": None}, "healthy"),
            ({"display_available": False}, "unavailable"),
            ({"configuration_valid": False}, "unavailable"),
            ({"service_running": False}, "unavailable"),
            ({"error_kind": "authentication"}, "unavailable"),
        ):
            with self.subTest(changes=changes):
                self.assertEqual(self.read(**changes)["status"], expected)

    def test_data_expiry_no_data_and_failed_fetch_are_stale(self):
        for changes in (
            {"last_successful_fetch": None},
            {"last_successful_fetch": self.now - timedelta(seconds=300)},
            {"consecutive_failures": 1, "error_kind": "temporary"},
        ):
            with self.subTest(changes=changes):
                data = self.read(**changes)
                self.assertTrue(data["stale"])
                self.assertEqual(data["status"], "degraded")
        self.assertFalse(
            self.read(last_successful_fetch=self.now - timedelta(seconds=299))["stale"]
        )

    def test_429_retry_and_rate_limit_count_down_without_an_api_call(self):
        self.publish(
            consecutive_failures=1,
            error_kind="rate_limit",
            retry_seconds=120,
            rate_limit_seconds=90,
        )
        status = read_health(self.path, now=self.now + timedelta(seconds=30))
        self.assertEqual(status["retry_in_seconds"], 90)
        self.assertEqual(status["rate_limit_remaining_seconds"], 60)
        self.assertTrue(status["rate_limit_active"])
        self.assertEqual(status["error_kind"], "rate_limit")
        status = read_health(self.path, now=self.now + timedelta(seconds=90))
        self.assertFalse(status["rate_limit_active"])

    def test_dead_heartbeat_is_unavailable_and_planned_night_is_healthy(self):
        self.publish()
        self.assertEqual(
            read_health(self.path, now=self.now + timedelta(seconds=91))["status"],
            "unavailable",
        )
        self.assertEqual(
            self.read(
                night_shutdown=True, network_connected=None, last_successful_fetch=None
            )["status"],
            "healthy",
        )
        self.assertEqual(
            self.read(night_shutdown=True, configuration_valid=False)["status"],
            "unavailable",
        )

    def test_unknown_fields_and_secret_paths_never_leave_the_reader(self):
        self.publish()
        data = json.loads(self.path.read_text())
        data.update(
            password="secret-password",  # noqa: S106 - redaction fixture
            path="/secret/path",
            api_response={"personal": "data"},
        )
        self.path.write_text(json.dumps(data))
        result = json.dumps(read_health(self.path, now=self.now))
        for secret in ("secret-password", "/secret/path", "personal"):
            self.assertNotIn(secret, result)

    def test_missing_unreadable_oversized_and_invalid_snapshots_are_safe(self):
        self.assertFalse(read_health(self.path)["snapshot_available"])
        self.publish()
        self.assertFalse(read_health(self.path.parent)["snapshot_available"])
        with patch.object(Path, "open", side_effect=PermissionError("/secret/path")):
            self.assertFalse(read_health(self.path)["snapshot_available"])
        for raw in (
            b"bad-json",
            b"[]",
            b"{}",
            b'{"schema_version":2}',
            b"\xff",
            b" " * (MAX_SNAPSHOT_BYTES + 1),
        ):
            with self.subTest(raw=raw[:20]):
                self.path.write_bytes(raw)
                self.assertFalse(read_health(self.path)["snapshot_available"])
        for key, value in (
            ("schema_version", 2),
            ("version", "password-secret"),
            ("version", "1" * 65 + ".0.0"),
            ("heartbeat_at", None),
            ("started_at", None),
            ("heartbeat_at", "invalid"),
            ("heartbeat_at", "2026-10-12"),
            ("heartbeat_at", 42),
            ("service_running", "yes"),
            ("consecutive_failures", -1),
            ("consecutive_failures", True),
            ("error_kind", "raw-secret-error"),
            ("error_kind", []),
        ):
            with self.subTest(key=key, value=value):
                self.publish()
                data = json.loads(self.path.read_text())
                data[key] = value
                self.path.write_text(json.dumps(data))
                self.assertFalse(read_health(self.path)["snapshot_available"])

    def test_write_failures_are_logged_once_and_do_not_crash_the_service(self):
        with patch(
            "hvv_display.health.os.replace", side_effect=PermissionError("secret")
        ):
            with self.assertLogs("hvv_display.health", "WARNING") as logs:
                publisher = self.publish()
                publisher.publish(**self.values)
            self.assertEqual(len(logs.output), 1)
            self.assertNotIn("secret", logs.output[0])
        self.assertEqual(list(self.path.parent.iterdir()), [])
        publisher.publish(**self.values, error_kind="unknown")
        self.assertEqual(read_health(self.path)["error_kind"], "technical")

    def test_health_file_default_and_environment_override(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertEqual(
                health_path("/opt/app/var/stations.json"),
                Path("/opt/app/var/health.json"),
            )
        with patch.dict("os.environ", {"HVV_HEALTH_FILE": "custom.json"}):
            self.assertEqual(health_path(), Path("custom.json"))

    def test_cleanup_and_directory_failures_do_not_escape_the_publisher(self):
        publisher = HealthPublisher(self.path)
        with patch.object(Path, "mkdir", side_effect=PermissionError):
            with self.assertLogs("hvv_display.health", "WARNING"):
                publisher.publish(**self.values)
        with patch.object(Path, "unlink", side_effect=PermissionError):
            publisher.publish(**self.values)
        self.assertTrue(read_health(self.path)["snapshot_available"])

    def test_cli_json_and_exit_codes_distinguish_all_states(self):
        for changes, expected in (
            ({}, "healthy"),
            ({"network_connected": False}, "degraded"),
            ({"configuration_valid": False}, "unavailable"),
        ):
            self.publish(**changes)
            with (
                patch("sys.argv", ["hvv-health", "--file", str(self.path)]),
                patch("sys.stdout", new_callable=io.StringIO) as output,
                patch("hvv_display.health.datetime") as clock,
            ):
                clock.now.return_value = self.now
                clock.fromisoformat.side_effect = datetime.fromisoformat
                with self.assertRaises(SystemExit) as exit_result:
                    main()
            self.assertEqual(exit_result.exception.code, STATUS_CODES[expected][1])
            self.assertEqual(json.loads(output.getvalue())["status"], expected)


if __name__ == "__main__":
    unittest.main()
