# ruff: noqa: E501

from __future__ import annotations

import argparse
import base64
import binascii
import errno
import hashlib
import html
import json
import logging
import os
import secrets
import shutil
import subprocess
import tempfile
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .config import ConfigError, load_config
from .credentials import load_credentials
from .geofox import (
    HAMBURG_TZ,
    GeofoxClient,
    GeofoxError,
    line_options_for_station,
    line_route_options_for_station,
    line_route_stations,
)
from .render import get_line_style, line_style_css
from .stations import resolve_stations
from .time_display import format_departure_time, minutes_until

LOG = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080
PASSWORD_HASH_ITERATIONS = 600_000
MAX_FORM_BYTES = 1_000_000
MAX_QUERY_LENGTH = 120
MAX_CITY_LENGTH = 80
MAX_STATION_ID_LENGTH = 160


def hash_web_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_HASH_ITERATIONS
    )
    return "$".join(
        (
            "pbkdf2-sha256",
            str(PASSWORD_HASH_ITERATIONS),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(digest).decode("ascii"),
        )
    )


def verify_web_password(password: str, encoded: str) -> bool:
    try:
        algorithm, iterations, encoded_salt, encoded_digest = encoded.split("$")
        if algorithm != "pbkdf2-sha256":
            return False
        salt = base64.urlsafe_b64decode(encoded_salt.encode("ascii"))
        expected = base64.urlsafe_b64decode(encoded_digest.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations)
        )
    except (ValueError, TypeError, binascii.Error):
        return False
    return secrets.compare_digest(actual, expected)


def save_credentials(path: Path, user: str, password: str) -> None:
    if not user.strip() or not password:
        raise ValueError("Geofox-Anwendungs-ID und Passwort müssen ausgefüllt sein")
    if any(
        character in user or character in password for character in ("\r", "\n", "\x00")
    ):
        raise ValueError("Geofox-Zugangsdaten dürfen keine Zeilenumbrüche enthalten")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"GEOFOX_USER={user.strip()}\nGEOFOX_PASSWORD={password}\n"
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    ) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    try:
        temporary.chmod(0o600)
        temporary.replace(path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def save_config(path: Path, raw_config: dict[str, Any]) -> None:
    payload = json.dumps(raw_config, ensure_ascii=False, indent=2) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        try:
            temporary.chmod(mode)
            temporary.replace(path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EROFS):
            raise
        with path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(mode)


def _minutes_until(departure: Any, now: datetime) -> int:
    return minutes_until(departure.departure_time, now)


def _departure_payload(
    departures: list[Any],
    now: datetime,
    *,
    time_mode: str = "countdown",
    minute_unit: str = "min",
) -> list[dict[str, Any]]:
    return [
        {
            "line": departure.line,
            "product": departure.product,
            "destination": departure.destination,
            "station": departure.station_label,
            "time": departure.departure_time.strftime("%H:%M"),
            "display_time": format_departure_time(
                departure.departure_time,
                now,
                time_mode=time_mode,
                minute_unit=minute_unit,
                cancelled=departure.cancelled,
            ),
            "minutes": _minutes_until(departure, now),
            "time_mode": time_mode,
            "delay_seconds": departure.delay_seconds,
            "cancelled": departure.cancelled,
        }
        for departure in departures
    ]


def hardware_status() -> dict[str, str]:
    cpu_count = os.cpu_count() or 1
    try:
        load = os.getloadavg()[0]
        cpu = f"{min(999, round(load / cpu_count * 100))}% Auslastung"
    except (AttributeError, OSError):
        cpu = "nicht verfügbar"
    try:
        values = {}
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition(":")
            if key in {"MemTotal", "MemAvailable"}:
                values[key] = int(value.strip().split()[0])
        total = values["MemTotal"]
        available = values["MemAvailable"]
        ram = f"{(total - available) / total * 100:.0f}% belegt ({available // 1024} MiB frei)"
    except (FileNotFoundError, KeyError, ValueError, OSError):
        ram = "nicht verfügbar"
    try:
        usage = shutil.disk_usage("/")
        storage = f"{usage.free / usage.total * 100:.0f}% frei ({usage.free // 1_073_741_824} GiB)"
    except OSError:
        storage = "nicht verfügbar"
    return {"cpu": cpu, "ram": ram, "storage": storage}


def _page(title: str, content: str) -> bytes:
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · HVV-Anzeiger</title><style>
:root{{color-scheme:dark;font-family:system-ui,sans-serif;background:#0b1220;color:#f4f7fb}}body{{margin:0;background:linear-gradient(135deg,#0b1220,#17233b);min-height:100vh}}main{{max-width:980px;margin:auto;padding:24px 16px 48px}}a{{color:#8bd3ff}}h1{{margin:0 0 8px;font-size:clamp(2rem,6vw,4rem)}}.subtle{{color:#aab8cb}}.toolbar{{display:flex;justify-content:space-between;gap:16px;align-items:center;flex-wrap:wrap;margin:20px 0}}.board{{background:#05080e;border:1px solid #324057;border-radius:18px;overflow:hidden;box-shadow:0 18px 50px #0006}}.row{{display:grid;grid-template-columns:76px 1fr 100px;gap:16px;align-items:center;padding:18px 22px;border-bottom:1px solid #202a3b}}.row:last-child{{border:0}}.line{{display:inline-block;min-width:42px;padding:2px 8px;text-align:center;font-size:1.35rem;font-weight:800;line-height:1.2}}.destination{{font-size:1.2rem}}.time{{text-align:right;font-size:1.8rem;font-variant-numeric:tabular-nums}}.station{{color:#8bd3ff;font-size:.8rem}}.delay{{color:#ff9d66;font-size:.85rem}}.cancelled{{color:#ff6b7a;text-decoration:line-through}}.status,.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin:16px 0}}.status div,.card{{background:#121c2d;border:1px solid #324057;border-radius:14px;padding:20px}}.status strong{{display:block;font-size:1.15rem;margin-top:4px}}.setting{{min-width:0}}.control-row,.station-search{{display:flex;gap:8px;align-items:center;flex-wrap:wrap}}.control-row input,.control-row select{{flex:1;min-width:0}}.reset{{background:#26344a;border-color:#53627a;font-size:.85rem}}.station-card{{border:1px solid #53627a;border-radius:12px;padding:16px;margin:14px 0}}.station-heading{{display:flex;justify-content:space-between;align-items:center;gap:12px}}.route-row{{display:grid;grid-template-columns:1fr 2fr auto;gap:8px;margin:8px 0}}.station-search{{margin-top:10px}}.station-search select{{min-width:280px;flex:1}}button,input,textarea,select{{font:inherit;border-radius:9px;border:1px solid #53627a;padding:10px 12px;background:#101a2b;color:inherit}}button{{cursor:pointer;background:#207bb3;border-color:#65c6ff;font-weight:700}}button:disabled{{opacity:.55;cursor:wait}}label{{display:block;margin:14px 0 6px;font-weight:700}}.card{{margin-top:18px}}.danger{{background:#7e2632;border-color:#ff8793;margin-left:8px}}.notice{{padding:14px 16px;border-radius:10px;background:#3b2913;color:#ffdca6;margin:16px 0}}.ok{{color:#8ee6ad}}.error{{color:#ff9aa5}}.empty{{padding:42px 22px;text-align:center;color:#aab8cb}}.spinner{{display:inline-block;width:14px;height:14px;border:2px solid #53627a;border-top-color:#8bd3ff;border-radius:50%;animation:spin .8s linear infinite;vertical-align:-2px}}@keyframes spin{{to{{transform:rotate(360deg)}}}}details.help-box{{margin-top:12px}}code{{overflow-wrap:anywhere}}{line_style_css()}
</style></head><body><main>{content}</main></body></html>""".encode()


class WebApplication:
    def __init__(
        self,
        config_path: Path,
        credentials_path: Path,
        cache_path: Path,
        *,
        access_token: str | None = None,
        web_env_path: Path | None = None,
    ) -> None:
        self.config_path = config_path
        self.credentials_path = credentials_path
        self.cache_path = cache_path
        self.access_token = access_token
        self.web_env_path = web_env_path or Path(
            os.environ.get("HVV_WEB_ENV_FILE", "var/web.env")
        )
        self.csrf_token = secrets.token_urlsafe(32)
        self._line_catalog: list[dict[str, Any]] | None = None

    def authorize(self, headers: Any) -> bool:
        if self.access_token is None:
            return True
        authorization = headers.get("Authorization", "")
        if not authorization.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, separator, password = decoded.partition(":")
        return (
            separator == ":"
            and username == "hvv-anzeiger"
            and verify_web_password(password, self.access_token)
        )

    def validate_csrf(self, token: str) -> None:
        if not secrets.compare_digest(token, self.csrf_token):
            raise PermissionError("Ungültige Sitzungsbestätigung")

    def save_web_password(self, password: str) -> None:
        if not password or any(
            character in password for character in ("\r", "\n", "\x00", '"', "\\")
        ):
            raise ValueError(
                "Das Webpasswort darf nicht leer sein oder Sonderzeichen für die Env-Datei enthalten"
            )
        self.web_env_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.web_env_path.with_name(f".{self.web_env_path.name}.tmp")
        encoded = hash_web_password(password)
        temporary.write_text(f'HVV_WEB_PASSWORD_HASH="{encoded}"\n', encoding="utf-8")
        os.chmod(temporary, 0o600)
        os.replace(temporary, self.web_env_path)
        self.access_token = encoded

    def raw_config(self) -> dict[str, Any]:
        raw = json.loads(self.config_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ConfigError("Konfiguration muss ein JSON-Objekt sein")
        return raw

    @staticmethod
    def restart_system() -> None:
        result = subprocess.run(
            ["/usr/bin/sudo", "-n", "systemctl", "reboot"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode:
            raise OSError(
                "Systemneustart wurde abgelehnt; systemctl-Berechtigung prüfen"
            )

    def _client(
        self, *, user: str | None = None, password: str | None = None
    ) -> GeofoxClient:
        config = load_config(self.config_path)
        credentials = load_credentials(self.credentials_path)
        return GeofoxClient(
            config.api.base_url,
            user if user is not None else credentials.get("GEOFOX_USER", ""),
            password
            if password is not None
            else credentials.get("GEOFOX_PASSWORD", ""),
            version=config.api.version,
            timeout=config.api.request_timeout_seconds,
        )

    def departures(self) -> tuple[list[dict[str, Any]], str | None]:
        now = datetime.now(HAMBURG_TZ).replace(second=0, microsecond=0)
        config = load_config(self.config_path)
        client = self._client()
        stations = resolve_stations(client, config.stations, self.cache_path)
        departures = client.departure_list(
            stations,
            now=now,
            max_list=30,
            max_time_offset=config.api.max_time_offset_minutes,
        )
        return (
            _departure_payload(
                departures[: config.api.max_departures],
                now,
                time_mode=config.display.time_mode,
                minute_unit=config.display.minute_unit,
            ),
            None,
        )

    def station_suggestions(self, query: str, city: str) -> list[dict[str, Any]]:
        query = query.strip()
        city = city.strip() or "Hamburg"
        if len(query) < 2:
            raise ValueError("Bitte mindestens zwei Zeichen eingeben")
        if len(query) > MAX_QUERY_LENGTH or len(city) > MAX_CITY_LENGTH:
            raise ValueError("Suchbegriff oder Stadt ist zu lang")
        return self._client().find_stations(query, city)

    def line_suggestions(self, station_id: str) -> list[dict[str, str]]:
        station_id = station_id.strip()
        if not station_id or len(station_id) > MAX_STATION_ID_LENGTH:
            raise ValueError("Geofox-ID ist ungültig")
        if any(character in station_id for character in ("\r", "\n", "\x00")):
            raise ValueError("Geofox-ID ist ungültig")
        client = self._client()
        if self._line_catalog is None:
            self._line_catalog = client.list_lines()
        options = line_options_for_station(self._line_catalog, station_id)
        return [
            {
                "id": option.line_id,
                "name": option.name,
                "product": option.product,
                "productLabel": option.product_label,
                "carrier": option.carrier,
            }
            for option in options
        ]

    @staticmethod
    def _validate_geofox_identifier(value: str, label: str) -> str:
        value = value.strip()
        if not value or len(value) > MAX_STATION_ID_LENGTH:
            raise ValueError(f"{label} ist ungültig")
        if any(character in value for character in ("\r", "\n", "\x00")):
            raise ValueError(f"{label} ist ungültig")
        return value

    def line_route_suggestions(
        self, station_id: str, line_id: str
    ) -> list[dict[str, Any]]:
        station_id = self._validate_geofox_identifier(station_id, "Geofox-ID")
        line_id = self._validate_geofox_identifier(line_id, "Linien-ID")
        client = self._client()
        if self._line_catalog is None:
            self._line_catalog = client.list_lines()
        available = {
            option.line_id
            for option in line_options_for_station(self._line_catalog, station_id)
        }
        if line_id not in available:
            raise ValueError("Linie ist an dieser Haltestelle nicht verfügbar")
        options = line_route_options_for_station(
            self._line_catalog, line_id, station_id
        )
        return [
            {
                "label": option.label,
                "stationIds": list(option.station_ids),
                "stations": [
                    {"id": station[0], "name": station[1]}
                    for station in option.stations
                ],
            }
            for option in options
        ]

    def line_station_suggestions(
        self, station_id: str, line_id: str, query: str = ""
    ) -> list[dict[str, str]]:
        station_id = self._validate_geofox_identifier(station_id, "Geofox-ID")
        line_id = self._validate_geofox_identifier(line_id, "Linien-ID")
        query = query.strip()
        if len(query) > MAX_QUERY_LENGTH:
            raise ValueError("Suchbegriff ist zu lang")
        client = self._client()
        if self._line_catalog is None:
            self._line_catalog = client.list_lines()
        available = {
            option.line_id
            for option in line_options_for_station(self._line_catalog, station_id)
        }
        if line_id not in available:
            raise ValueError("Linie ist an dieser Haltestelle nicht verfügbar")
        options = line_route_options_for_station(
            self._line_catalog, line_id, station_id
        )
        return list(line_route_stations(options, query))

    def validate_station_config(
        self, raw_config: dict[str, Any], *, user: str, password: str
    ) -> dict[str, Any]:
        stations = raw_config.get("stations")
        if not isinstance(stations, list) or not stations:
            raise ValueError("Mindestens eine Haltestelle muss konfiguriert sein")
        client = self._client(user=user, password=password)
        for index, station in enumerate(stations):
            if not isinstance(station, dict):
                raise ValueError(f"Haltestelle {index + 1} ist ungültig")
            name = str(station.get("name") or "").strip()
            city = str(station.get("city") or "Hamburg").strip()
            station_id = str(station.get("id") or "").strip()
            if not name or not station_id:
                raise ValueError(
                    f"Haltestelle {index + 1}: Bitte einen Geofox-Vorschlag auswählen"
                )
            if (
                len(name) > MAX_QUERY_LENGTH
                or len(city) > MAX_CITY_LENGTH
                or len(station_id) > MAX_STATION_ID_LENGTH
            ):
                raise ValueError(f"Haltestelle {index + 1}: Eingabe ist zu lang")
            matches = client.find_stations(name, city)
            match = next(
                (item for item in matches if item.get("id") == station_id), None
            )
            if match is None:
                raise ValueError(
                    f"Haltestelle {index + 1}: Geofox findet die ausgewählte Haltestelle nicht mehr"
                )
            station["name"] = match["name"]
            station["city"] = match["city"]
            station["id"] = match["id"]
            station["serviceTypes"] = match.get("serviceTypes", [])
            routes = station.get("routes")
            if not isinstance(routes, list) or not routes:
                raise ValueError(
                    f"Haltestelle {index + 1}: Mindestens eine Linie auswählen"
                )
            if any(not isinstance(route, dict) for route in routes):
                raise ValueError(f"Haltestelle {index + 1}: Linie ist ungültig")
            line_ids = {
                str(route.get("line_id")).strip()
                for route in routes
                if route.get("line_id")
            }
            if line_ids:
                if self._line_catalog is None:
                    self._line_catalog = client.list_lines()
                available = {
                    option.line_id: option
                    for option in line_options_for_station(
                        self._line_catalog, station["id"]
                    )
                }
                for route in routes:
                    line_id = str(route.get("line_id") or "").strip()
                    if not line_id:
                        if route.get("filter_mode") or route.get("filter_station_ids"):
                            raise ValueError(
                                f"Haltestelle {index + 1}: Filter benötigt eine Geofox-Linien-ID"
                            )
                        continue
                    option = available.get(line_id)
                    if option is None:
                        raise ValueError(
                            f"Haltestelle {index + 1}: Linie ist an dieser Haltestelle nicht verfügbar"
                        )
                    route["line"] = option.name
                    route["product"] = option.product
                    mode = str(route.get("filter_mode") or "").strip()
                    raw_station_ids = route.get("filter_station_ids")
                    if mode not in ("direction", "destination"):
                        raise ValueError(
                            f"Haltestelle {index + 1}: Für Linie {option.name} Richtung oder Zielstation auswählen"
                        )
                    if not isinstance(raw_station_ids, list) or not raw_station_ids:
                        raise ValueError(
                            f"Haltestelle {index + 1}: Filter für Linie {option.name} ist ungültig"
                        )
                    station_ids = tuple(
                        str(station_id).strip()
                        for station_id in raw_station_ids
                        if str(station_id).strip()
                    )
                    route_options = line_route_options_for_station(
                        self._line_catalog, line_id, station["id"]
                    )
                    if mode == "direction":
                        matches = [
                            candidate
                            for candidate in route_options
                            if candidate.station_ids == station_ids
                        ]
                        if len(matches) != 1:
                            raise ValueError(
                                f"Haltestelle {index + 1}: Die gewählte Richtung konnte für {option.name} nicht eindeutig bestimmt werden"
                            )
                        route["destination"] = matches[0].label
                        route["filter_station_ids"] = list(matches[0].station_ids)
                    else:
                        if len(station_ids) != 1:
                            raise ValueError(
                                f"Haltestelle {index + 1}: Eine Zielstation auswählen"
                            )
                        valid_stations = {
                            station_option[0]: station_option[1]
                            for route_option in route_options
                            for station_option in route_option.stations
                        }
                        target_name = valid_stations.get(station_ids[0])
                        if target_name is None:
                            raise ValueError(
                                f"Haltestelle {index + 1}: Zielstation liegt ab dieser Haltestelle nicht auf Linie {option.name}"
                            )
                        route["destination"] = target_name
                        route["filter_station_ids"] = [station_ids[0]]
                    route["filter_mode"] = mode
        return raw_config

    def dashboard(self) -> bytes:
        try:
            departures, error = self.departures()
        except (ConfigError, GeofoxError, OSError) as exc:
            departures, error = [], str(exc)
        rows = (
            "".join(
                f'<div class="row"><div><div class="line line-badge line-badge-{get_line_style(item.get("line", ""), item.get("product")).token}">{html.escape(str(item.get("line", "")))}</div><div class="station">{html.escape(str(item.get("station", "")))}</div></div><div class="destination">{html.escape(str(item.get("destination", "")))}{(" <span class=delay>(+" + str(item["delay_seconds"] // 60) + " min)</span>") if item["delay_seconds"] else ""}</div><div class="time {"cancelled" if item["cancelled"] else ""}">{html.escape(str(item.get("display_time", item["time"]))) }{"" if item.get("time_mode") == "departure_time" else "<br><small>in " + str(item["minutes"]) + " min</small>"}</div></div>'
                for item in departures
            )
            or '<div class="empty">Keine passende Abfahrt verfügbar.</div>'
        )
        message = f'<div class="notice">{html.escape(error)}</div>' if error else ""
        status = hardware_status()
        content = f'''<div class="toolbar"><div><h1>Abfahrten</h1><div class="subtle">Lokale HVV-Anzeige · aktualisiert beim Öffnen</div></div><div><a href="/settings">Einstellungen</a> · <a href="/">Aktualisieren</a></div></div>{message}<section class="board" aria-label="Abfahrtsanzeige">{rows}</section><section class="status" aria-label="Hardware-Status"><div>CPU<strong>{html.escape(status["cpu"])}</strong></div><div>RAM<strong>{html.escape(status["ram"])}</strong></div><div>SD-Speicher<strong>{html.escape(status["storage"])}</strong></div></section><form method="post" action="/system/restart" onsubmit="return confirm('Raspberry Pi wirklich neu starten?');"><input type="hidden" name="csrf_token" value="{html.escape(self.csrf_token, quote=True)}"><button class="danger" type="submit">System neu starten</button></form>'''
        return _page("Abfahrten", content)

    def settings(self, message: str = "", restart_required: bool = False) -> bytes:
        raw_config = self.raw_config()
        credentials = load_credentials(self.credentials_path)
        notice = f'<div class="notice">{html.escape(message)}</div>' if message else ""
        defaults = {
            "api.base_url": "https://gti.geofox.de/gti/public",
            "api.version": 63,
            "api.refresh_seconds": 15,
            "api.request_timeout_seconds": 8,
            "api.max_departures": 5,
            "api.max_time_offset_minutes": 90,
            "api.max_stale_age_minutes": 5,
            "display.spi_port": 0,
            "display.spi_device": 0,
            "display.gpio_dc": 24,
            "display.gpio_reset": 25,
            "display.rotate": 0,
            "display.bus_speed_hz": 16000000,
            "display.bgr": False,
            "display.time_mode": "countdown",
            "display.minute_unit": "min",
            "night_shutdown.enabled": False,
            "night_shutdown.start": "21:00",
            "night_shutdown.end": "06:30",
        }
        descriptions = {
            "api.base_url": "Offizielle HTTPS-Adresse der Geofox-Schnittstelle.",
            "api.version": "API-Version des Geofox-Vertrags.",
            "api.refresh_seconds": "Sekunden zwischen Abfragen; mindestens 15.",
            "api.request_timeout_seconds": "Maximale Wartezeit pro Anfrage.",
            "api.max_departures": "Sichtbare Abfahrten; 1 bis 5.",
            "api.max_time_offset_minutes": "Wie weit in die Zukunft gesucht wird.",
            "api.max_stale_age_minutes": "Wie lange alte Daten sichtbar bleiben.",
            "display.spi_port": "Nummer des SPI-Busses.",
            "display.spi_device": "Chip-Select des Displays.",
            "display.gpio_dc": "GPIO für Data/Command.",
            "display.gpio_reset": "GPIO für Display-Reset.",
            "display.rotate": "Drehung: 0 bis 3 Vierteldrehungen.",
            "display.bus_speed_hz": "SPI-Takt in Hertz.",
            "display.bgr": "Bei vertauschten Rot-/Blaukanälen aktivieren.",
            "display.time_mode": "Minuten bis Abfahrt oder konkrete Abfahrtszeit; gilt für Display und Web.",
            "display.minute_unit": "Einheit für den Countdown; bei Abfahrtszeit nicht relevant.",
            "night_shutdown.enabled": "Pausiert nachts Abfragen und Display.",
            "night_shutdown.start": "Beginn in Hamburger Ortszeit (HH:MM).",
            "night_shutdown.end": "Ende in Hamburger Ortszeit (HH:MM).",
        }

        def scalar(path: str, input_type: str = "text") -> str:
            section, key = path.split(".")
            value = raw_config.get(section, {}).get(key, defaults[path])
            default = defaults[path]
            if isinstance(default, bool):
                control = f'<select id="{path}" data-path="{path}" data-type="bool" data-default="{str(default).lower()}"><option value="false" {"selected" if not value else ""}>Nein</option><option value="true" {"selected" if value else ""}>Ja</option></select>'
            elif path == "display.time_mode":
                control = f'<select id="{path}" data-path="{path}" data-default="countdown"><option value="countdown" {"selected" if value == "countdown" else ""}>Minuten bis Abfahrt</option><option value="departure_time" {"selected" if value == "departure_time" else ""}>Abfahrtszeit</option></select>'
            elif path == "display.minute_unit":
                control = f'<select id="{path}" data-path="{path}" data-default="min"><option value="min" {"selected" if value == "min" else ""}>min</option><option value="m" {"selected" if value == "m" else ""}>m</option><option value="none" {"selected" if value == "none" else ""}>keine Einheit</option></select>'
            else:
                control = f'<input id="{path}" data-path="{path}" type="{input_type}" value="{html.escape(str(value), quote=True)}" data-default="{html.escape(str(default), quote=True)}">'
            return f'<div class="setting"><label for="{path}">{path}</label><div class="control-row">{control}<button type="button" class="reset" onclick="resetField(this)">Auf Standard zurücksetzen</button></div><div class="subtle">{descriptions[path]}</div></div>'

        def station_card(station: dict[str, Any], index: int) -> str:
            selected_lines = [
                {
                    "id": str(route.get("line_id") or ""),
                    "name": str(route.get("line") or ""),
                    "product": str(route.get("product") or ""),
                }
                for route in station.get("routes", [])
                if isinstance(route, dict) and route.get("line_id")
            ]
            selected_lines_json = html.escape(
                json.dumps(selected_lines, ensure_ascii=False), quote=True
            )
            routes = "".join(
                f'<div class="route-row"><input data-route="line" value="{html.escape(str(route.get("line", "")), quote=True)}" placeholder="Linie" aria-label="Linie"><input data-route="destination" value="{html.escape(str(route.get("destination", "")), quote=True)}" placeholder="Ziel" aria-label="Ziel"><input type="hidden" data-route-line-id value="{html.escape(str(route.get("line_id") or ""), quote=True)}"><input type="hidden" data-route-product value="{html.escape(str(route.get("product") or ""), quote=True)}"><input type="hidden" data-route-filter-mode value="{html.escape(str(route.get("filter_mode") or ""), quote=True)}"><input type="hidden" data-route-filter-ids value="{html.escape(json.dumps(route.get("filter_station_ids") or [], ensure_ascii=False), quote=True)}"><button type="button" class="reset" onclick="this.parentElement.remove()">Route entfernen</button></div>'
                for route in station.get("routes", [])
            )
            valid = bool(station.get("id"))
            service_types = json.dumps(
                station.get("serviceTypes", []), ensure_ascii=False
            )
            return f'''<article class="station-card" data-station data-valid="{str(valid).lower()}">
<div class="station-heading"><h3>Haltestelle {index + 1}</h3><button type="button" class="reset" onclick="this.closest('[data-station]').remove()">Haltestelle entfernen</button></div>
<div class="grid"><div><label>Name</label><input data-station-field="name" maxlength="{MAX_QUERY_LENGTH}" value="{html.escape(str(station.get("name", "")), quote=True)}" required autocomplete="off"><div class="subtle">Mindestens 2 Zeichen. Vorschläge erscheinen automatisch.</div></div><div><label>Stadt</label><input data-station-field="city" maxlength="{MAX_CITY_LENGTH}" value="{html.escape(str(station.get("city", "Hamburg")), quote=True)}" required><div class="subtle">Wird nach Auswahl aus Geofox übernommen.</div></div><div><label>Geofox-ID</label><input data-station-field="id" maxlength="{MAX_STATION_ID_LENGTH}" value="{html.escape(str(station.get("id") or ""), quote=True)}" readonly tabindex="-1"><div class="subtle">Technisches Metadatum; wird automatisch gesetzt.</div></div><div><label>Kürzel</label><input data-station-field="label" maxlength="3" value="{html.escape(str(station.get("label", "")), quote=True)}" required><div class="subtle">1–3 Zeichen für die Anzeige.</div></div></div>
<input type="hidden" data-station-field="serviceTypes" value="{html.escape(service_types, quote=True)}">
<div class="station-search"><select data-station-results aria-label="Geofox-Haltestellenvorschläge"><option value="">Treffer auswählen …</option></select><span class="subtle" data-search-message>{'<span class="ok">✓ Geofox-Haltestelle ausgewählt</span>' if valid else "Bitte Haltestelle aus einem Geofox-Vorschlag auswählen."}</span></div>
<details class="help-box"><summary>Richtung oder Zielstation?</summary><p><strong>Richtung</strong> wählt später den Linienast; auch Fahrten, die vorher enden, können angezeigt werden. <strong>Zu Zielstation</strong> zeigt nur Fahrten, die diese Station tatsächlich erreichen. Beispiel: U2 Richtung Niendorf Nord kann einen Kurzläufer nach Niendorf Markt enthalten; „Zu Zielstation Niendorf Nord“ nicht.</p></details>
<h4>Linien und Ziele</h4><div data-line-picker data-selected-lines="{selected_lines_json}"><div class="control-row"><button type="button" data-load-lines onclick="loadLines(this)" {"disabled" if not valid else ""}>Verfügbare Linien laden</button><span class="subtle" data-lines-message>{'Mehrere Verkehrsmittel gemeinsam auswählen und danach Richtung oder Zielstation festlegen.' if valid else 'Nach der Haltestellenauswahl hier die verfügbaren Linien laden.'}</span></div><div data-line-options role="group" aria-label="Verfügbare Linien"></div><div data-route-configs></div></div><div data-routes>{routes}</div><details><summary>Legacy-Konfiguration manuell bearbeiten</summary><p class="subtle">Bestehende Bus-Konfigurationen bleiben kompatibel. Für neue Haltestellen bitte die Geofox-Linienauswahl verwenden.</p><button type="button" onclick="addRoute(this)">Route hinzufügen</button></details></article>'''

        stations = "".join(
            station_card(station, index)
            for index, station in enumerate(raw_config.get("stations", []))
        ) or station_card({"city": "Hamburg", "routes": []}, 0)
        raw = html.escape(json.dumps(raw_config, ensure_ascii=False))
        content = f'''<div class="toolbar"><div><h1>Einstellungen</h1><div class="subtle">Bedienbare Felder · jede Änderung wird validiert</div></div><a href="/">← Abfahrten</a></div>{notice}
<form method="post" action="/settings" accept-charset="UTF-8" onsubmit="return prepareConfig()"><section class="card"><h2>Weboberfläche</h2><p class="subtle">Benutzername: <code>hvv-anzeiger</code>. Ein leeres Passwortfeld lässt den bisherigen Wert unverändert.</p><label for="web_password">Neues Webpasswort</label><input id="web_password" name="web_password" type="password" autocomplete="new-password" placeholder="unverändert lassen"></section>
<section class="card"><h2>Geofox-Zugang</h2><label for="user">Anwendungs-ID</label><input id="user" name="user" value="{html.escape(credentials.get("GEOFOX_USER", ""), quote=True)}" autocomplete="username"><label for="password">Passwort</label><input id="password" name="password" type="password" autocomplete="new-password" placeholder="unverändert lassen"></section>
<section class="card"><h2>Geofox-API</h2><div class="grid">{scalar("api.base_url")}{scalar("api.version", "number")}{scalar("api.refresh_seconds", "number")}{scalar("api.request_timeout_seconds", "number")}{scalar("api.max_departures", "number")}{scalar("api.max_time_offset_minutes", "number")}{scalar("api.max_stale_age_minutes", "number")}</div></section>
<section class="card"><h2>Display</h2><div class="grid">{scalar("display.spi_port", "number")}{scalar("display.spi_device", "number")}{scalar("display.gpio_dc", "number")}{scalar("display.gpio_reset", "number")}{scalar("display.rotate", "number")}{scalar("display.bus_speed_hz", "number")}{scalar("display.bgr")}{scalar("display.time_mode")}{scalar("display.minute_unit")}</div></section>
<section class="card"><h2>Nachtabschaltung</h2><div class="grid">{scalar("night_shutdown.enabled")}{scalar("night_shutdown.start", "time")}{scalar("night_shutdown.end", "time")}</div></section>
<section class="card"><div class="station-heading"><div><h2>Haltestellen und Linien</h2><p class="subtle">Haltestelle eintippen, Geofox-Vorschlag auswählen; Name, Stadt und ID werden automatisch übernommen.</p></div><button type="button" onclick="addStation()">Haltestelle hinzufügen</button></div><div id="stations">{stations}</div></section>
<textarea id="config_json" name="config_json" hidden>{raw}</textarea><input type="hidden" name="csrf_token" value="{html.escape(self.csrf_token, quote=True)}"><p><button id="save-settings" type="submit">Speichern und prüfen</button></p></form>
<script>
let requestSequence=0; let debounceTimers=new WeakMap(); let controllers=new WeakMap(); let lineControllers=new WeakMap(); let lineSequences=new WeakMap();
function resetField(button){{const control=button.parentElement.querySelector('[data-path]');control.value=control.dataset.default;syncTimeDisplayControls()}}
function syncTimeDisplayControls(){{const mode=document.getElementById('display.time_mode');const unit=document.getElementById('display.minute_unit');if(!mode||!unit)return;unit.disabled=mode.value==='departure_time';unit.closest('.setting').querySelector('.subtle').textContent=unit.disabled?'Bei Abfahrtszeit nicht relevant.':'Einheit für den Countdown; bei Abfahrtszeit nicht relevant.'}}
function addRoute(button){{const row=document.createElement('div');row.className='route-row';row.innerHTML='<input data-route="line" placeholder="Linie" aria-label="Linie"><input data-route="destination" placeholder="Ziel" aria-label="Ziel"><input type="hidden" data-route-line-id><input type="hidden" data-route-product><input type="hidden" data-route-filter-mode><input type="hidden" data-route-filter-ids value="[]"><button type="button" class="reset" onclick="this.parentElement.remove()">Route entfernen</button>';button.closest('[data-station]').querySelector('[data-routes]').appendChild(row)}}
function invalidateStation(card){{card.dataset.valid='false';card.querySelector('[data-station-field="id"]').value='';card.querySelector('[data-station-field="serviceTypes"]').value='[]';card.querySelector('[data-search-message]').textContent='Bitte Haltestelle aus einem Geofox-Vorschlag auswählen.';card.querySelector('[data-line-options]').replaceChildren();card.querySelector('[data-route-configs]').replaceChildren();card.querySelector('[data-lines-message]').textContent='Nach der Haltestellenauswahl hier die verfügbaren Linien laden.';card.querySelector('[data-load-lines]').disabled=true;lineControllers.get(card)?.abort();lineSequences.set(card,(lineSequences.get(card)||0)+1);card.querySelector('[data-routes]').replaceChildren();card.querySelector('[data-line-picker]').dataset.selectedLines='[]'}}
function bindStation(card){{const name=card.querySelector('[data-station-field="name"]');const city=card.querySelector('[data-station-field="city"]');[name,city].forEach(input=>input.addEventListener('input',()=>{{invalidateStation(card);scheduleStationSearch(card)}}));}}
function scheduleStationSearch(card){{clearTimeout(debounceTimers.get(card));const query=card.querySelector('[data-station-field="name"]').value.trim();if(query.length<2) return;debounceTimers.set(card,setTimeout(()=>searchStation(card),350))}}
async function searchStation(card){{const query=card.querySelector('[data-station-field="name"]').value.trim();const city=card.querySelector('[data-station-field="city"]').value.trim();const select=card.querySelector('[data-station-results]');const message=card.querySelector('[data-search-message]');const sequence=++requestSequence;controllers.get(card)?.abort();const controller=new AbortController();controllers.set(card,controller);select.disabled=true;message.innerHTML='<span class="spinner" aria-hidden="true"></span> Geofox wird abgefragt …';try{{const response=await fetch('/api/stations?q='+encodeURIComponent(query)+'&city='+encodeURIComponent(city),{{signal:controller.signal}});const data=await response.json();if(sequence!==requestSequence)return;if(!response.ok)throw new Error(data.error||'Geofox-Suche fehlgeschlagen');select.replaceChildren(new Option('Treffer auswählen …',''));data.stations.forEach(station=>{{const option=new Option(station.combinedName,JSON.stringify(station));select.appendChild(option)}});message.textContent=data.stations.length?'Bitte passenden Treffer auswählen.':'Keine passende Haltestelle gefunden.'}}catch(error){{if(error.name!=='AbortError')message.textContent=error.message}}finally{{if(sequence===requestSequence)select.disabled=false}}}}
function applyStation(select){{if(!select.value)return;const station=JSON.parse(select.value);const card=select.closest('[data-station]');card.querySelector('[data-station-field="name"]').value=station.name;card.querySelector('[data-station-field="city"]').value=station.city;card.querySelector('[data-station-field="id"]').value=station.id;card.querySelector('[data-station-field="serviceTypes"]').value=JSON.stringify(station.serviceTypes||[]);card.dataset.valid='true';card.querySelector('[data-search-message]').innerHTML='<span class="ok">✓ Geofox-Haltestelle ausgewählt</span>';card.querySelector('[data-load-lines]').disabled=false;card.querySelector('[data-routes]').replaceChildren();loadLines(card.querySelector('[data-load-lines]'))}}
function addStation(){{const first=document.querySelector('[data-station]');const clone=first.cloneNode(true);clone.querySelectorAll('input').forEach(input=>input.value=input.dataset.stationField==='city'?'Hamburg':(input.dataset.stationField==='serviceTypes'?'[]':''));clone.querySelector('[data-routes]').replaceChildren();clone.querySelector('[data-line-options]').replaceChildren();clone.querySelector('[data-route-configs]').replaceChildren();clone.querySelector('[data-line-picker]').dataset.selectedLines='[]';clone.querySelector('[data-station-results]').replaceChildren(new Option('Treffer auswählen …',''));invalidateStation(clone);document.getElementById('stations').appendChild(clone);bindStation(clone)}}
function renderRouteConfig(input, options){{const card=input.closest('[data-station]');const container=card.querySelector('[data-route-configs]');[...container.children].filter(item=>item.dataset.routeConfig===input.value).forEach(item=>item.remove());const config=document.createElement('div');config.className='route-config';config.dataset.routeConfig=input.value;const title=document.createElement('strong');title.textContent=input.dataset.line+' · Filter';const help=document.createElement('span');help.className='subtle';help.textContent='Richtung zeigt auch Kurzläufer; Zielstation ist strenger.';const mode=document.createElement('select');mode.dataset.routeMode='true';mode.setAttribute('aria-label','Filtermodus für '+input.dataset.line);mode.append(new Option('Richtung','direction'),new Option('Zu Zielstation …','destination'));const filter=document.createElement('select');filter.dataset.routeFilter='true';filter.setAttribute('aria-label','Richtung oder Zielstation für '+input.dataset.line);const target=document.createElement('input');target.type='search';target.dataset.routeTarget='true';target.placeholder='Zielstation suchen …';target.setAttribute('autocomplete','off');const targetList=document.createElement('datalist');targetList.id='route-targets-'+Math.random().toString(36).slice(2);target.setAttribute('list',targetList.id);const fill=()=>{{filter.replaceChildren();targetList.replaceChildren();if(mode.value==='direction'){{target.hidden=true;filter.hidden=false;options.forEach(option=>filter.append(new Option(option.label,JSON.stringify(option.stationIds))))}}else{{target.hidden=false;filter.hidden=true;const seen=new Set();options.forEach(option=>option.stations.forEach(station=>{{if(!seen.has(station.id)){{seen.add(station.id);const suggestion=new Option(station.name,station.name);suggestion.dataset.stationId=station.id;targetList.append(suggestion)}}}}));const selectedIds=input.dataset.filterIds?JSON.parse(input.dataset.filterIds):[];const selected=[...targetList.options].find(option=>option.dataset.stationId===selectedIds[0]);target.value=selected?.value||'';target.dataset.stationId=selected?.dataset.stationId||''}}}};mode.value=input.dataset.filterMode||'direction';mode.addEventListener('change',fill);target.addEventListener('input',()=>{{const selected=[...targetList.options].find(option=>option.value===target.value);target.dataset.stationId=selected?.dataset.stationId||'';loadTargetStations(input,target,targetList)}});config.append(title,help,mode,target,targetList,filter);container.append(config);fill();const selectedIds=input.dataset.filterIds?JSON.parse(input.dataset.filterIds):[];if(mode.value==='direction'){{const wanted=JSON.stringify(selectedIds);[...filter.options].find(option=>option.value===wanted)?.setAttribute('selected','selected')}}}}
async function loadTargetStations(input,target,targetList){{clearTimeout(target.dataset.targetTimer);const query=target.value.trim();if(query.length<2)return;target.dataset.targetTimer=setTimeout(async()=>{{const card=input.closest('[data-station]');const stationId=card.querySelector('[data-station-field="id"]').value.trim();const sequence=(Number(target.dataset.targetSequence||'0')+1);target.dataset.targetSequence=sequence;try{{const response=await fetch('/api/line-stations?station_id='+encodeURIComponent(stationId)+'&line_id='+encodeURIComponent(input.value)+'&q='+encodeURIComponent(query));const data=await response.json();if(Number(target.dataset.targetSequence)!==sequence)return;if(!response.ok)throw new Error(data.error||'Zielstationen konnten nicht geladen werden');targetList.replaceChildren(...data.stations.map(station=>{{const option=new Option(station.name,station.name);option.dataset.stationId=station.id;return option}}));const selected=[...targetList.options].find(option=>option.value===target.value);target.dataset.stationId=selected?.dataset.stationId||''}}catch(error){{target.dataset.stationId=''}}}},250)}}
async function loadRouteOptions(input){{const card=input.closest('[data-station]');const stationId=card.querySelector('[data-station-field="id"]').value.trim();const sequence=(Number(input.dataset.routeSequence||'0')+1);input.dataset.routeSequence=sequence;input.disabled=true;try{{const response=await fetch('/api/line-routes?station_id='+encodeURIComponent(stationId)+'&line_id='+encodeURIComponent(input.value));const data=await response.json();if(Number(input.dataset.routeSequence)!==sequence)return;if(!response.ok)throw new Error(data.error||'Richtungen konnten nicht geladen werden');input.dataset.routeOptions=JSON.stringify(data.routes);renderRouteConfig(input,data.routes);if(!data.routes.length)throw new Error('Für diese Linie konnte keine eindeutige Strecke ermittelt werden')}}catch(error){{if(Number(input.dataset.routeSequence)===sequence){{input.checked=false;card.querySelector('[data-lines-message]').textContent=error.message}}}}finally{{if(Number(input.dataset.routeSequence)===sequence)input.disabled=false}}}}
function renderLineOptions(card, lines){{
    const picker=card.querySelector('[data-line-picker]');
    const box=card.querySelector('[data-line-options]');
    let selected=[];
    try{{selected=JSON.parse(picker.dataset.selectedLines||'[]')}}catch(error){{selected=[]}}
    box.replaceChildren();
    card.querySelector('[data-route-configs]').replaceChildren();
    lines.forEach(line=>{{
        const chosen=selected.find(item=>item.id===line.id)||{{}};
        const label=document.createElement('label');
        label.className='line-option';
        const input=document.createElement('input');
        input.type='checkbox';
        input.dataset.lineOption='true';
        input.value=line.id;
        input.dataset.line=line.name;
        input.dataset.product=line.product;
        input.dataset.filterMode=chosen.filterMode||'';
        input.dataset.filterIds=JSON.stringify(chosen.filterStationIds||[]);
        input.checked=Boolean(chosen.id);
        input.addEventListener('change',()=>{{
            if(input.checked){{
                loadRouteOptions(input);
            }}else{{
                card.querySelector('[data-route-configs]')
                    .querySelector('[data-route-config="'+CSS.escape(input.value)+'"]')
                    ?.remove();
            }}
        }});
        label.append(input,document.createTextNode(line.name+' · '+line.productLabel+(line.carrier?' · '+line.carrier:'')));
        box.append(label);
        if(input.checked)loadRouteOptions(input);
    }});
}}
async function loadLines(button){{const card=button.closest('[data-station]');const stationId=card.querySelector('[data-station-field="id"]').value.trim();const message=card.querySelector('[data-lines-message]');if(!stationId){{message.textContent='Bitte zuerst eine Geofox-Haltestelle auswählen.';return}}const sequence=(lineSequences.get(card)||0)+1;lineSequences.set(card,sequence);lineControllers.get(card)?.abort();const controller=new AbortController();lineControllers.set(card,controller);button.disabled=true;message.innerHTML='<span class="spinner" aria-hidden="true"></span> Linien werden geladen …';try{{const response=await fetch('/api/lines?station_id='+encodeURIComponent(stationId),{{signal:controller.signal}});const data=await response.json();if(lineSequences.get(card)!==sequence)return;if(!response.ok)throw new Error(data.error||'Linien konnten nicht geladen werden');renderLineOptions(card,data.lines);message.textContent=data.lines.length?'Linien aller verfügbaren Verkehrsmittel auswählen.':'Für diese Haltestelle wurden keine Linien gefunden.'}}catch(error){{if(error.name!=='AbortError')message.textContent=error.message}}finally{{if(lineSequences.get(card)===sequence)button.disabled=false}}}}
function selectedRoutes(card){{const manual=[...card.querySelectorAll('[data-route="line"]')].map(line=>{{const row=line.closest('.route-row');let ids=[];try{{ids=JSON.parse(row.querySelector('[data-route-filter-ids]')?.value||'[]')}}catch(error){{ids=[]}}return {{line:line.value.trim(),destination:row.querySelector('[data-route="destination"]').value.trim(),line_id:row.querySelector('[data-route-line-id]').value.trim()||undefined,product:row.querySelector('[data-route-product]').value.trim()||undefined,filter_mode:row.querySelector('[data-route-filter-mode]')?.value.trim()||undefined,filter_station_ids:Array.isArray(ids)?ids:[]}}}}).filter(route=>route.line);const selected=[...card.querySelectorAll('[data-line-option]')].filter(input=>input.checked).map(input=>{{const config=card.querySelector('[data-route-config="'+CSS.escape(input.value)+'"]');const mode=config?.querySelector('[data-route-mode]')?.value;const filter=config?.querySelector('[data-route-filter]');const target=config?.querySelector('[data-route-target]');let ids=[];let destination='';if(mode==='direction'&&filter?.value){{ids=JSON.parse(filter.value);destination=filter.selectedOptions[0]?.textContent||''}}else if(mode==='destination'&&target?.dataset.stationId){{ids=[target.dataset.stationId];destination=target.value.trim()}}return {{line:input.dataset.line,destination,line_id:input.value,product:input.dataset.product,filter_mode:mode||undefined,filter_station_ids:ids}}}});return selected.length?[...selected,...manual.filter(route=>!route.line_id)]:manual}}
function prepareConfig(){{const invalid=[...document.querySelectorAll('[data-station]')].find(card=>card.dataset.valid!=='true');if(invalid){{invalid.querySelector('[data-search-message]').innerHTML='<span class="error">Bitte zuerst einen gültigen Geofox-Vorschlag auswählen.</span>';invalid.scrollIntoView({{behavior:'smooth',block:'center'}});return false}}const config=JSON.parse(document.getElementById('config_json').value);document.querySelectorAll('[data-path]').forEach(control=>{{const [section,key]=control.dataset.path.split('.');config[section][key]=control.dataset.type==='bool'?control.value==='true':(control.type==='number'?Number(control.value):control.value)}});config.stations=[...document.querySelectorAll('[data-station]')].map(card=>({{name:card.querySelector('[data-station-field="name"]').value,city:card.querySelector('[data-station-field="city"]').value,id:card.querySelector('[data-station-field="id"]').value,label:card.querySelector('[data-station-field="label"]').value,serviceTypes:JSON.parse(card.querySelector('[data-station-field="serviceTypes"]').value||'[]'),routes:selectedRoutes(card)}}));document.getElementById('config_json').value=JSON.stringify(config);document.getElementById('save-settings').disabled=true;document.getElementById('save-settings').textContent='Geofox prüft …';return true}}
document.querySelectorAll('[data-station]').forEach(bindStation);document.querySelectorAll('[data-station-results]').forEach(select=>select.addEventListener('change',()=>applyStation(select)));document.getElementById('display.time_mode')?.addEventListener('change',syncTimeDisplayControls);syncTimeDisplayControls();
</script>'''
        return _page("Einstellungen", content)


def _geofox_http_status(exc: GeofoxError) -> HTTPStatus:
    if exc.http_status == 429:
        return HTTPStatus.TOO_MANY_REQUESTS
    if exc.http_status in (401, 403):
        return HTTPStatus.BAD_GATEWAY
    if exc.kind == "temporary" or exc.http_status in (500, 503):
        return HTTPStatus.SERVICE_UNAVAILABLE
    return HTTPStatus.BAD_REQUEST


def make_handler(application: WebApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _form_values(self, max_length: int) -> dict[str, list[str]]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Ungültige Anfragegröße") from exc
            if length < 0:
                raise ValueError("Ungültige Anfragegröße")
            if length > max_length:
                raise OverflowError("Anfrage ist zu groß")
            payload = self.rfile.read(length)
            try:
                form_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                form_text = payload.decode("latin-1")
            return parse_qs(form_text, keep_blank_values=True)

        def _security_headers(self) -> None:
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")

        def _send(self, payload: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(payload)

        def _send_json(
            self,
            data: dict[str, Any],
            status: HTTPStatus = HTTPStatus.OK,
            *,
            retry_after: int | None = None,
        ) -> None:
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            if retry_after:
                self.send_header("Retry-After", str(retry_after))
            self._security_headers()
            self.end_headers()
            self.wfile.write(payload)

        def _unauthorized(self) -> None:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="hvv-anzeiger"')
            self._security_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not application.authorize(self.headers):
                self._unauthorized()
                return
            path = urlsplit(self.path).path
            if path == "/":
                self._send(application.dashboard())
                return
            if path == "/settings":
                query = parse_qs(urlsplit(self.path).query)
                self._send(
                    application.settings(
                        "Gespeichert. Die laufende Anwendung übernimmt die Änderung bei der nächsten Aktualisierung; ein Neustart ist nicht nötig."
                        if query.get("saved", [""])[0] == "1"
                        else ""
                    )
                )
                return
            if path == "/api/departures":
                try:
                    departures, error = application.departures()
                    self._send_json({"departures": departures, "error": error})
                except (ConfigError, GeofoxError, OSError) as exc:
                    self._send_json(
                        {"departures": [], "error": str(exc)},
                        HTTPStatus.SERVICE_UNAVAILABLE,
                    )
                return
            if path == "/api/stations":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    stations = application.station_suggestions(
                        query.get("q", [""])[0], query.get("city", ["Hamburg"])[0]
                    )
                    self._send_json({"stations": stations})
                except GeofoxError as exc:
                    self._send_json(
                        {"stations": [], "error": str(exc)},
                        _geofox_http_status(exc),
                        retry_after=exc.retry_after_seconds,
                    )
                except (ConfigError, OSError, ValueError) as exc:
                    self._send_json(
                        {"stations": [], "error": str(exc)}, HTTPStatus.BAD_REQUEST
                    )
                return
            if path == "/api/lines":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    lines = application.line_suggestions(
                        query.get("station_id", [""])[0]
                    )
                    self._send_json({"lines": lines})
                except GeofoxError as exc:
                    self._send_json(
                        {"lines": [], "error": str(exc)},
                        _geofox_http_status(exc),
                        retry_after=exc.retry_after_seconds,
                    )
                except (ConfigError, OSError, ValueError) as exc:
                    self._send_json(
                        {"lines": [], "error": str(exc)}, HTTPStatus.BAD_REQUEST
                    )
                return
            if path == "/api/line-routes":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    routes = application.line_route_suggestions(
                        query.get("station_id", [""])[0],
                        query.get("line_id", [""])[0],
                    )
                    self._send_json({"routes": routes})
                except GeofoxError as exc:
                    self._send_json(
                        {"routes": [], "error": str(exc)},
                        _geofox_http_status(exc),
                        retry_after=exc.retry_after_seconds,
                    )
                except (ConfigError, OSError, ValueError) as exc:
                    self._send_json(
                        {"routes": [], "error": str(exc)}, HTTPStatus.BAD_REQUEST
                    )
                return
            if path == "/api/line-stations":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    stations = application.line_station_suggestions(
                        query.get("station_id", [""])[0],
                        query.get("line_id", [""])[0],
                        query.get("q", [""])[0],
                    )
                    self._send_json({"stations": stations})
                except GeofoxError as exc:
                    self._send_json(
                        {"stations": [], "error": str(exc)},
                        _geofox_http_status(exc),
                        retry_after=exc.retry_after_seconds,
                    )
                except (ConfigError, OSError, ValueError) as exc:
                    self._send_json(
                        {"stations": [], "error": str(exc)}, HTTPStatus.BAD_REQUEST
                    )
                return
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            if not application.authorize(self.headers):
                self._unauthorized()
                return
            path = urlsplit(self.path).path
            if path == "/system/restart":
                try:
                    values = self._form_values(4096)
                    application.validate_csrf(values.get("csrf_token", [""])[0])
                    application.restart_system()
                    self._send(_page("Neustart", "<h1>Neustart ausgelöst</h1>"))
                except OverflowError as exc:
                    self._send(
                        _page("Fehler", f"<h1>{html.escape(str(exc))}</h1>"),
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    )
                except (
                    OSError,
                    PermissionError,
                    ValueError,
                    UnicodeDecodeError,
                ) as exc:
                    self._send(
                        _page("Fehler", f"<h1>{html.escape(str(exc))}</h1>"),
                        HTTPStatus.FORBIDDEN,
                    )
                return
            if path != "/settings":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                values = self._form_values(MAX_FORM_BYTES)
                application.validate_csrf(values.get("csrf_token", [""])[0])
                raw_config = json.loads(values.get("config_json", [""])[0])
                if not isinstance(raw_config, dict):
                    raise ValueError("Konfiguration muss ein JSON-Objekt sein")
                current = load_credentials(application.credentials_path)
                user = values.get("user", [""])[0].strip()
                supplied_password = values.get("password", [""])[0]
                password = supplied_password or current.get("GEOFOX_PASSWORD", "")
                raw_config = application.validate_station_config(
                    raw_config, user=user, password=password
                )
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".json", delete=False
                ) as handle:
                    handle.write(json.dumps(raw_config, ensure_ascii=False))
                    temporary = Path(handle.name)
                try:
                    load_config(temporary)
                finally:
                    temporary.unlink(missing_ok=True)
                web_password = values.get("web_password", [""])[0]
                if web_password:
                    application.save_web_password(web_password)
                save_config(application.config_path, raw_config)
                if supplied_password:
                    save_credentials(
                        application.credentials_path, user, supplied_password
                    )
                elif user != current.get("GEOFOX_USER", ""):
                    save_credentials(application.credentials_path, user, password)
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/settings?saved=1")
                self._security_headers()
                self.end_headers()
            except OverflowError as exc:
                self._send(
                    application.settings(f"Nicht gespeichert: {exc}"),
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            except GeofoxError as exc:
                self._send(
                    application.settings(f"Nicht gespeichert: {exc}"),
                    _geofox_http_status(exc),
                )
            except (ValueError, ConfigError, OSError, PermissionError) as exc:
                self._send(
                    application.settings(f"Nicht gespeichert: {exc}"),
                    HTTPStatus.BAD_REQUEST,
                )

        def log_message(self, format: str, *args: object) -> None:
            LOG.info("web %s", format % args)

    return Handler


def run(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    config: str = "config.json",
    credentials: str | None = None,
    cache: str = "var/stations.json",
    access_token: str | None = None,
) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"} and not access_token:
        raise ValueError(
            "Für einen nicht-lokalen Webhost muss HVV_WEB_PASSWORD_HASH gesetzt sein"
        )
    application = WebApplication(
        Path(config),
        Path(
            credentials or os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env")
        ),
        Path(cache),
        access_token=access_token,
        web_env_path=Path(os.environ.get("HVV_WEB_ENV_FILE", "var/web.env")),
    )
    server = ThreadingHTTPServer((host, port), make_handler(application))
    server.application = application  # type: ignore[attr-defined]
    LOG.info("Lokale Weboberfläche erreichbar unter http://%s:%d", host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lokale Weboberfläche für den HVV-Anzeiger"
    )
    parser.add_argument("--host", default=os.environ.get("HVV_WEB_HOST", DEFAULT_HOST))
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("HVV_WEB_PORT", DEFAULT_PORT))
    )
    parser.add_argument("--config", default=os.environ.get("HVV_CONFIG", "config.json"))
    parser.add_argument(
        "--credentials",
        default=os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env"),
    )
    parser.add_argument(
        "--cache", default=os.environ.get("HVV_STATION_CACHE", "var/stations.json")
    )
    parser.add_argument(
        "--access-token",
        default=os.environ.get("HVV_WEB_PASSWORD_HASH"),
        help="Gesalzener Passwort-Hash für nicht-lokale Zugriffe",
    )
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    run(
        args.host,
        args.port,
        config=args.config,
        credentials=args.credentials,
        cache=args.cache,
        access_token=args.access_token,
    )


if __name__ == "__main__":
    main()
