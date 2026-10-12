import base64
import json
import re
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from http.server import ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener

from hvv_display.config import ConfigError, config_from_dict, load_config
from hvv_display.config_backup import MAX_CONFIG_BYTES, ConfigConflict, export_config
from hvv_display.web import WebApplication, hash_web_password, make_handler


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class WebBackupTest(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.config = self.root / "config.json"
        self.original = Path("config.example.json").read_bytes()
        self.config.write_bytes(self.original)
        self.raw = json.loads(self.original)
        self.credentials = self.root / "credentials.env"
        self.credentials.write_text(
            "GEOFOX_USER=private-application-id\nGEOFOX_PASSWORD=private-api-secret\n"
        )
        self.web_env = self.root / "web.env"
        self.web_env.write_text("HVV_WEB_PASSWORD_HASH=private-web-hash\n")
        self.app = WebApplication(
            self.config,
            self.credentials,
            self.root / "var" / "stations.json",
            web_env_path=self.web_env,
        )
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(self.app))
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def request(self, path, values=None, auth=None):
        headers = {"Authorization": auth} if auth else {}
        data = urlencode(values).encode() if values is not None else None
        request = Request(self.base + path, data=data, headers=headers)  # noqa: S310
        opener = build_opener(NoRedirect())
        try:
            response = opener.open(request, timeout=5)  # noqa: S310
        except HTTPError as error:
            response = error
        with response:
            return response.code, response.read(), response.headers

    def preview(self, raw):
        status, body, _ = self.request(
            "/config/preview",
            {
                "csrf_token": self.app.csrf_token,
                "config_data": export_config(raw).decode(),
            },
        )
        self.assertEqual(status, 200, body)
        return re.search(rb'name="token" value="([a-f0-9]+)"', body)[1].decode(), body

    def changed(self, rotate=2):
        candidate = deepcopy(self.raw)
        candidate["display"]["rotate"] = rotate
        return candidate

    def test_export_backup_download_and_navigation_never_read_credentials(self):
        with patch.object(self.app, "_client", side_effect=AssertionError("No API")):
            status, body, headers = self.request("/config/export")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertIn("attachment", headers["Content-Disposition"])
            self.assertEqual(
                config_from_dict(json.loads(body)["config"]), config_from_dict(self.raw)
            )
            self.assertNotIn(b"private-application-id", body)
            self.assertNotIn(b"private-api-secret", body)
            self.assertNotIn(b"private-web-hash", body)
            status, _, _ = self.request(
                "/config/backup", {"csrf_token": self.app.csrf_token}
            )
            self.assertEqual(status, 303)
            backup = self.app.config_store.list_backups()[0]
            self.assertEqual(self.request("/config/export?backup_id=" + backup)[0], 200)
            status, page, _ = self.request("/config-backup")
            self.assertEqual(status, 200)
            self.assertIn(b"Wiederherstellung pr", page)
            self.assertIn(b"Sicherung &amp; Wiederherstellung", self.app.settings())
            self.assertEqual(
                self.request("/config/export?backup_id=../credentials.env")[0], 400
            )

    def test_import_preview_cancel_confirm_and_restore_are_separate_steps(self):
        credentials, web_env = self.credentials.read_bytes(), self.web_env.read_bytes()
        with patch.object(self.app, "_client", side_effect=AssertionError("No API")):
            token, body = self.preview(self.changed())
            self.assertIn(b"Bilddrehung", body)
            self.assertEqual(self.config.read_bytes(), self.original)
            self.assertEqual(self.app.config_store.list_backups(), [])
            self.assertEqual(
                self.request(
                    "/config/apply", {"csrf_token": self.app.csrf_token, "token": token}
                )[0],
                400,
            )
            self.assertEqual(
                self.request(
                    "/config/cancel",
                    {"csrf_token": self.app.csrf_token, "token": token},
                )[0],
                303,
            )
            self.assertEqual(self.config.read_bytes(), self.original)
            self.assertEqual(
                self.request(
                    "/config/apply",
                    {
                        "csrf_token": self.app.csrf_token,
                        "token": token,
                        "confirmed": "yes",
                    },
                )[0],
                409,
            )
            token, _ = self.preview(self.changed())
            self.assertEqual(
                self.request(
                    "/config/apply",
                    {
                        "csrf_token": self.app.csrf_token,
                        "token": token,
                        "confirmed": "yes",
                    },
                )[0],
                303,
            )
            self.assertEqual(load_config(self.config).display.rotate, 2)
            backup = self.app.config_store.list_backups()[0]
            status, body, _ = self.request(
                "/config/preview",
                {"csrf_token": self.app.csrf_token, "backup_id": backup},
            )
            self.assertEqual(status, 200)
            restore_token = re.search(rb'name="token" value="([a-f0-9]+)"', body)[
                1
            ].decode()
            self.assertEqual(
                self.request(
                    "/config/apply",
                    {
                        "csrf_token": self.app.csrf_token,
                        "token": restore_token,
                        "confirmed": "yes",
                    },
                )[0],
                303,
            )
            self.assertEqual(load_config(self.config).display.rotate, 0)
        self.assertEqual(self.credentials.read_bytes(), credentials)
        self.assertEqual(self.web_env.read_bytes(), web_env)
        self.assertEqual(len(self.app.config_store.list_backups()), 2)

    def test_auth_csrf_invalid_and_oversized_imports_leave_config_untouched(self):
        self.app.access_token = hash_web_password("test-password")
        auth = "Basic " + base64.b64encode(b"hvv-anzeiger:test-password").decode()
        for path in ("/config-backup", "/config/export"):
            self.assertEqual(self.request(path)[0], 401)
        self.assertEqual(self.request("/config/preview", {"config_data": "{}"})[0], 401)
        self.assertEqual(
            self.request("/config/preview", {"config_data": "{}"}, auth)[0], 403
        )
        self.assertEqual(
            self.request(
                "/config/preview",
                {"csrf_token": self.app.csrf_token, "config_data": "{}"},
                auth,
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "/config/preview",
                {"csrf_token": self.app.csrf_token, "backup_id": "../credentials.env"},
                auth,
            )[0],
            400,
        )
        self.assertEqual(
            self.request(
                "/config/preview",
                {
                    "csrf_token": self.app.csrf_token,
                    "config_data": "x" * (MAX_CONFIG_BYTES * 3 + 4096),
                },
                auth,
            )[0],
            413,
        )
        self.assertEqual(self.config.read_bytes(), self.original)
        self.assertEqual(self.app.config_store.list_backups(), [])

    def test_concurrent_http_confirmations_reject_stale_preview(self):
        tokens = [self.preview(self.changed(value))[0] for value in (1, 2)]

        def apply(token):
            return self.request(
                "/config/apply",
                {"csrf_token": self.app.csrf_token, "token": token, "confirmed": "yes"},
            )[0]

        with ThreadPoolExecutor(max_workers=2) as workers:
            self.assertCountEqual(list(workers.map(apply, tokens)), [303, 409])
        self.assertEqual(len(self.app.config_store.list_backups()), 1)

    def test_expired_or_too_many_previews_are_bounded_and_escape_values(self):
        candidate = self.changed()
        candidate["stations"][0]["name"] = "<script>untrusted</script>"
        with patch("hvv_display.web.time.monotonic", return_value=0):
            token, preview = self.app.prepare_config(candidate)
            page = self.app.config_preview_page(token, preview)
            self.assertIn(b"&lt;script&gt;untrusted&lt;/script&gt;", page)
            self.assertNotIn(b"<script>untrusted</script>", page)
            for _ in range(19):
                self.app.prepare_config(candidate)
            with self.assertRaises(ConfigError):
                self.app.prepare_config(candidate)
        with patch("hvv_display.web.time.monotonic", return_value=601):
            with self.assertRaises(ConfigConflict):
                self.app.apply_config_plan(token, True)
            self.app.prepare_config(candidate)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_failed_restore_write_does_not_touch_config_or_secrets(self):
        token, _ = self.preview(self.changed())
        with patch.object(
            self.app.config_store, "apply", side_effect=OSError("secret-system-path")
        ):
            status, body, _ = self.request(
                "/config/apply",
                {"csrf_token": self.app.csrf_token, "token": token, "confirmed": "yes"},
            )
        self.assertEqual(status, 400)
        self.assertNotIn(b"secret-system-path", body)
        self.assertEqual(self.config.read_bytes(), self.original)

    def test_settings_revision_and_values_come_from_one_snapshot(self):
        with (
            patch.object(
                self.app.config_store,
                "current",
                return_value=(self.changed(), "a" * 64),
            ),
            patch.object(
                self.app.config_store,
                "base_revision",
                side_effect=AssertionError("No second read"),
            ),
        ):
            page = self.app.settings()
        self.assertIn(b'name="config_revision" value="' + b"a" * 64 + b'"', page)


if __name__ == "__main__":
    unittest.main()
