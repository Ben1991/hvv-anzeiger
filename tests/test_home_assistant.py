"""Render the shipped YAML/Jinja; no running HA installation is claimed."""

import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

from hvv_display.health import DisplayDiagnostics

ROOT = Path(__file__).resolve().parents[1]


class SecretLoader(yaml.SafeLoader):
    pass


SecretLoader.add_constructor(
    "!secret", lambda loader, node: loader.construct_scalar(node)
)


class HomeAssistantDisplayTest(unittest.TestCase):
    def setUp(self):
        loader = SecretLoader((ROOT / "home-assistant/hvv.yaml").read_text())
        try:
            self.config = loader.get_single_data()
        finally:
            loader.dispose()
        self.sensor = self.config["template"][0]["sensor"][0]
        self.problem = self.config["template"][1]["binary_sensor"][0]
        self.states = {"sensor.hvv_diagnostics": "online"}
        self.details = DisplayDiagnostics()
        self.attrs = {
            "snapshot_available": True,
            "service_running": True,
            "display_available": True,
            "display_diagnostics": self.details.snapshot(),
        }
        self.env = Environment(undefined=StrictUndefined, autoescape=False)  # noqa: S701
        self.env.globals.update(
            states=lambda entity: self.states.get(entity, "unknown"),
            state_attr=lambda entity, name: (
                self.attrs.get(name) if entity == "sensor.hvv_diagnostics" else None
            ),
        )

    def render(self, value, **variables):
        return self.env.from_string(value).render(**variables).strip()

    def error_state(self):
        self.attrs["display_diagnostics"] = self.details.snapshot()
        available = self.render(self.sensor["availability"]) == "True"
        state = self.render(self.sensor["state"]) if available else "unavailable"
        self.states["sensor.hvv_display_error"] = state
        return state

    def test_yaml_uses_independent_authenticated_health_resource(self):
        rest = self.config["sensor"][1]
        self.assertEqual(rest["resource"], "hvv_health_url")
        self.assertEqual(rest["password"], "hvv_web_password")
        self.assertEqual(rest["authentication"], "basic")
        self.assertTrue(rest["verify_ssl"])
        secrets = yaml.safe_load(
            (ROOT / "home-assistant/secrets.example.yaml").read_text()
        )
        self.assertTrue(secrets["hvv_health_url"].endswith("/api/diagnostics"))
        self.assertEqual(
            self.render(rest["value_template"], value_json=self.attrs), "online"
        )
        self.attrs["snapshot_available"] = False
        self.assertEqual(
            self.render(rest["value_template"], value_json=self.attrs), "missing"
        )
        self.assertIn(
            "sensor.hvv_diagnostics", self.config["recorder"]["exclude"]["entities"]
        )

    def test_detected_faults_clear_but_history_survives_successful_recovery(self):
        now = datetime(2026, 11, 14, tzinfo=timezone.utc)
        self.details.recovery_started()  # Preventive reset is not an error.
        self.details.frame_succeeded(now)
        self.assertEqual(self.error_state(), "none")
        self.assertEqual(self.render(self.problem["state"]), "False")
        for kind in ("initialization", "reset", "transfer"):
            with self.subTest(kind=kind):
                self.details.failed(kind, now)
                self.attrs["display_available"] = False
                self.assertEqual(self.error_state(), kind)
                self.assertEqual(self.render(self.problem["state"]), "True")
                self.details.recovery_started()
                self.details.frame_succeeded(now)
                self.attrs["display_available"] = True
                self.assertEqual(self.error_state(), "none")
                self.assertEqual(self.render(self.problem["state"]), "False")
                self.assertEqual(
                    self.render(self.sensor["attributes"]["last_error_kind"]), kind
                )
        for key, expected in (
            ("error_count", "3"),
            ("consecutive_failures", "0"),
            ("recovery_attempts", "4"),
            ("recovery_successes", "4"),
        ):
            self.assertEqual(self.render(self.sensor["attributes"][key]), expected)
        for key in ("last_error_at", "last_recovery_at"):
            self.assertEqual(
                self.render(self.sensor["attributes"][key]), now.isoformat()
            )

    def test_stopped_service_unreachable_web_and_legacy_snapshots_are_distinct(self):
        self.attrs["service_running"] = False
        self.assertEqual(self.error_state(), "service_unavailable")
        self.assertEqual(self.render(self.problem["state"]), "True")
        self.states["sensor.hvv_diagnostics"] = "unavailable"
        self.assertEqual(self.error_state(), "unavailable")
        self.assertEqual(self.render(self.problem["availability"]), "False")
        self.states["sensor.hvv_diagnostics"] = "online"
        self.attrs["display_diagnostics"] = None
        self.assertEqual(self.render(self.sensor["availability"]), "False")
        self.attrs["display_diagnostics"] = self.details.snapshot()
        self.attrs["service_running"] = True
        self.attrs["display_available"] = None
        self.assertEqual(self.error_state(), "unknown")
        self.assertEqual(self.render(self.problem["availability"]), "False")
