"""Exercise the actual Compose service, private files, TLS and restart on Linux."""

import base64
import json
import os
import ssl
import subprocess
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def command(args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)  # noqa: S603


def main():
    password = "container-smoke-password"  # noqa: S105 -- disposable test fixture
    with tempfile.TemporaryDirectory(prefix="hvv-compose-") as directory:
        fixture = Path(directory)
        data = fixture / "data"
        data.mkdir(mode=0o700)
        config = json.loads((ROOT / "config.example.json").read_text())
        now = datetime.now(ZoneInfo("Europe/Berlin"))
        config["night_shutdown"] = {
            "enabled": True,
            "start": (now - timedelta(hours=1)).strftime("%H:%M"),
            "end": (now + timedelta(hours=1)).strftime("%H:%M"),
        }
        (data / "config.json").write_text(json.dumps(config))
        (data / "credentials.env").write_text(
            "GEOFOX_USER=test\nGEOFOX_PASSWORD=test\n"
        )
        hashed = command(
            [
                "docker",
                "run",
                "--rm",
                "hvv-backend",
                "python",
                "-c",
                "from hvv_display.web import hash_web_password; "
                f"print(hash_web_password({password!r}))",
            ],
            capture_output=True,
            text=True,
        ).stdout.strip()
        (data / "web.env").write_text(f"HVV_WEB_PASSWORD_HASH={hashed}\n")
        command(
            [
                "openssl",
                "req",
                "-x509",
                "-newkey",
                "rsa:2048",
                "-nodes",
                "-days",
                "1",
                "-keyout",
                str(data / "tls.key"),
                "-out",
                str(data / "tls.crt"),
                "-subj",
                "/CN=localhost",
                "-addext",
                "subjectAltName=IP:127.0.0.1",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        context = ssl.create_default_context(cafile=str(data / "tls.crt"))
        for path in data.iterdir():
            path.chmod(0o600)
        override = fixture / "compose.json"
        override.write_text(
            json.dumps(
                {
                    "services": {
                        "hvv": {
                            "image": "hvv-backend",
                            "volumes": [f"{data}:/data"],
                        }
                    }
                }
            )
        )
        compose = [
            "docker",
            "compose",
            "-p",
            "hvv-smoke",
            "-f",
            str(ROOT / "compose.yaml"),
            "-f",
            str(override),
        ]

        def ownership(uid, gid):
            command(
                [
                    "docker",
                    "run",
                    "--rm",
                    "--user",
                    "0",
                    "-v",
                    f"{data}:/data",
                    "hvv-backend",
                    "python",
                    "-c",
                    "import os; from pathlib import Path; "
                    f"[os.chown(p, {uid}, {gid}) "
                    "for p in [Path('/data'), *Path('/data').iterdir()]]",
                ]
            )

        auth = "Basic " + base64.b64encode(f"hvv-anzeiger:{password}".encode()).decode()

        def request(route, authenticated=True):
            headers = {"Authorization": auth} if authenticated else {}
            req = Request("https://127.0.0.1:8080" + route, headers=headers)  # noqa: S310
            return urlopen(req, context=context, timeout=3)  # noqa: S310

        def ready():
            for _ in range(40):
                try:
                    with request("/api/smart-home") as response:
                        payload = json.load(response)
                    if payload["state"] != "night":
                        raise RuntimeError(
                            "Container did not load its preserved config"
                        )
                    return
                except (URLError, ConnectionError, TimeoutError):
                    time.sleep(0.5)
            raise RuntimeError("Compose backend failed TLS/authenticated readiness")

        ownership(10001, 10001)
        try:
            command(compose + ["up", "-d", "--no-build"])
            ready()
            try:
                request("/api/esphome", authenticated=False)
            except HTTPError as exc:
                if exc.code != 401:
                    raise
            else:
                raise RuntimeError(
                    "Display endpoint accepted an unauthenticated request"
                )
            with request("/api/esphome") as response:
                if json.load(response)["schema_version"] != 1:
                    raise RuntimeError("ESPHome protocol mismatch")
            # Recreating from the built image exercises the documented update
            # path and must retain the private hash, credentials and config.
            command(compose + ["up", "-d", "--no-build", "--force-recreate"])
            ready()
            print(
                "Compose install/recreate, UID 10001, private hash, "
                "TLS and API auth passed"
            )
        finally:
            command(compose + ["down"])
            ownership(os.getuid(), os.getgid())


if __name__ == "__main__":
    main()
