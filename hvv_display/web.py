# ruff: noqa: E501

from __future__ import annotations

import argparse
import base64
import binascii
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
from .geofox import HAMBURG_TZ, GeofoxClient, GeofoxError
from .stations import resolve_stations

LOG = logging.getLogger(__name__)
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8080


def save_credentials(path: Path, user: str, password: str) -> None:
    if not user.strip() or not password:
        raise ValueError("Geofox-Anwendungs-ID und Passwort müssen ausgefüllt sein")
    if any(character in user or character in password for character in ("\r", "\n", "\x00")):
        raise ValueError("Geofox-Zugangsdaten dürfen keine Zeilenumbrüche enthalten")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = f"GEOFOX_USER={user.strip()}\nGEOFOX_PASSWORD={password}\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
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
    except PermissionError:
        # The installed service owns config.json but not its root-owned parent
        # directory, so an atomic sibling replacement is not possible there.
        with path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        path.chmod(mode)


def _minutes_until(departure: Any, now: datetime) -> int:
    seconds = (departure.departure_time - now).total_seconds()
    return max(0, round(seconds / 60))


def _departure_payload(departures: list[Any], now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "line": departure.line,
            "destination": departure.destination,
            "station": departure.station_label,
            "time": departure.departure_time.strftime("%H:%M"),
            "minutes": _minutes_until(departure, now),
            "delay_seconds": departure.delay_seconds,
            "cancelled": departure.cancelled,
        }
        for departure in departures
    ]


def hardware_status() -> dict[str, str]:
    """Return safe, human-readable local resource information."""
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
    return f"""<!doctype html>
<html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · HVV-Anzeiger</title>
<style>
:root {{ color-scheme: dark; font-family: system-ui, sans-serif; background:#0b1220; color:#f4f7fb; }}
body {{ margin:0; background:linear-gradient(135deg,#0b1220,#17233b); min-height:100vh; }}
main {{ max-width:980px; margin:auto; padding:24px 16px 48px; }}
a {{ color:#8bd3ff; }} h1 {{ margin:0 0 8px; font-size:clamp(2rem,6vw,4rem); }}
.subtle {{ color:#aab8cb; }} .toolbar {{ display:flex; justify-content:space-between; gap:16px; align-items:center; flex-wrap:wrap; margin:20px 0; }}
.board {{ background:#05080e; border:1px solid #324057; border-radius:18px; overflow:hidden; box-shadow:0 18px 50px #0006; }}
.row {{ display:grid; grid-template-columns:76px 1fr 100px; gap:16px; align-items:center; padding:18px 22px; border-bottom:1px solid #202a3b; }}
.row:last-child {{ border:0; }} .line {{ color:#ffd447; font-size:2rem; font-weight:800; }} .destination {{ font-size:1.2rem; }}
.time {{ text-align:right; font-size:1.8rem; font-variant-numeric:tabular-nums; }} .station {{ color:#8bd3ff; font-size:.8rem; }}
.delay {{ color:#ff9d66; font-size:.85rem; }} .cancelled {{ color:#ff6b7a; text-decoration:line-through; }}
.status {{ display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin:16px 0; }} .status div {{ background:#121c2d; border:1px solid #324057; border-radius:12px; padding:14px; }} .status strong {{ display:block; font-size:1.15rem; margin-top:4px; }}
.setting {{ min-width:0; }} .control-row {{ display:flex; gap:8px; align-items:center; }} .control-row input, .control-row select {{ flex:1; min-width:0; }} .reset {{ background:#26344a; border-color:#53627a; font-size:.85rem; }}
.station-card {{ border:1px solid #53627a; border-radius:12px; padding:16px; margin:14px 0; }} .station-heading {{ display:flex; justify-content:space-between; align-items:center; gap:12px; }} .station-heading h2, .station-heading h3 {{ margin-top:0; }} .route-row {{ display:grid; grid-template-columns:1fr 2fr auto; gap:8px; margin:8px 0; }}
.station-search {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-top:14px; }} .station-search select {{ min-width:280px; flex:1; }}
button, input, textarea {{ font:inherit; border-radius:9px; border:1px solid #53627a; padding:10px 12px; background:#101a2b; color:inherit; }}
button {{ cursor:pointer; background:#207bb3; border-color:#65c6ff; font-weight:700; }} textarea {{ width:100%; min-height:420px; box-sizing:border-box; font-family:ui-monospace,monospace; font-size:.9rem; }}
label {{ display:block; margin:14px 0 6px; font-weight:700; }} .card {{ background:#121c2d; border:1px solid #324057; border-radius:14px; padding:20px; margin-top:18px; }}
.explanations {{ margin:0; padding-left:20px; line-height:1.6; }} .danger {{ background:#7e2632; border-color:#ff8793; margin-left:8px; }}
.notice {{ padding:14px 16px; border-radius:10px; background:#3b2913; color:#ffdca6; margin:16px 0; }} .empty {{ padding:42px 22px; text-align:center; color:#aab8cb; }}
</style></head><body><main>{content}</main></body></html>""".encode()


class WebApplication:
    def __init__(
        self,
        config_path: Path,
        credentials_path: Path,
        cache_path: Path,
        *,
        access_token: str | None = None,
    ) -> None:
        self.config_path = config_path
        self.credentials_path = credentials_path
        self.cache_path = cache_path
        self.access_token = access_token
        self.csrf_token = secrets.token_urlsafe(32)

    def authorize(self, headers: Any) -> bool:
        if self.access_token is None:
            return True
        authorization = headers.get("Authorization", "")
        if secrets.compare_digest(authorization, f"Bearer {self.access_token}"):
            return True
        if not authorization.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(authorization[6:], validate=True).decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            return False
        username, separator, password = decoded.partition(":")
        return separator == ":" and username == "hvv-anzeiger" and secrets.compare_digest(
            password, self.access_token
        )

    def validate_csrf(self, token: str) -> None:
        if not secrets.compare_digest(token, self.csrf_token):
            raise PermissionError("Ungültige Sitzungsbestätigung")

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
            raise OSError("Systemneustart wurde abgelehnt; systemctl-Berechtigung prüfen")

    def departures(self) -> tuple[list[dict[str, Any]], str | None]:
        now = datetime.now(HAMBURG_TZ).replace(second=0, microsecond=0)
        config = load_config(self.config_path)
        credentials = load_credentials(self.credentials_path)
        client = GeofoxClient(
            config.api.base_url,
            credentials.get("GEOFOX_USER", ""),
            credentials.get("GEOFOX_PASSWORD", ""),
            version=config.api.version,
            timeout=config.api.request_timeout_seconds,
        )
        stations = resolve_stations(client, config.stations, self.cache_path)
        departures = client.departure_list(
            stations,
            now=now,
            max_list=30,
            max_time_offset=config.api.max_time_offset_minutes,
        )
        return _departure_payload(departures[: config.api.max_departures], now), None

    def station_suggestions(self, query: str, city: str) -> list[dict[str, str]]:
        query = query.strip()
        if len(query) < 2:
            raise ValueError("Bitte mindestens zwei Zeichen eingeben")
        config = load_config(self.config_path)
        credentials = load_credentials(self.credentials_path)
        client = GeofoxClient(
            config.api.base_url,
            credentials.get("GEOFOX_USER", ""),
            credentials.get("GEOFOX_PASSWORD", ""),
            version=config.api.version,
            timeout=config.api.request_timeout_seconds,
        )
        return client.find_stations(query, city.strip() or "Hamburg")

    def dashboard(self) -> bytes:
        try:
            departures, error = self.departures()
        except (ConfigError, GeofoxError, OSError) as exc:
            departures, error = [], str(exc)
        rows = "".join(
            f'<div class="row"><div><div class="line">{html.escape(item["line"])}</div>'
            f'<div class="station">{html.escape(item["station"])}</div></div>'
            f'<div class="destination">{html.escape(item["destination"])}'
            f'{" <span class=delay>(+" + str(item["delay_seconds"] // 60) + " min)</span>" if item["delay_seconds"] else ""}</div>'
            f'<div class="time {"cancelled" if item["cancelled"] else ""}">{item["time"]}<br><small>in {item["minutes"]} min</small></div></div>'
            for item in departures
        )
        if not rows:
            rows = '<div class="empty">Keine passende Abfahrt verfügbar.</div>'
        message = f'<div class="notice">{html.escape(error)}</div>' if error else ""
        status = hardware_status()
        content = f"""<div class="toolbar"><div><h1>Abfahrten</h1><div class="subtle">Lokale HVV-Anzeige · aktualisiert beim Öffnen</div></div>
<div><a href="/settings">Einstellungen</a> · <a href="/">Aktualisieren</a></div></div>{message}<section class="board" aria-label="Abfahrtsanzeige">{rows}</section>
<section class="status" aria-label="Hardware-Status"><div>CPU<strong>{html.escape(status["cpu"])}</strong></div><div>RAM<strong>{html.escape(status["ram"])}</strong></div><div>SD-Speicher<strong>{html.escape(status["storage"])}</strong></div></section>
<form method="post" action="/system/restart" onsubmit="return confirm('Raspberry Pi wirklich neu starten?');"><input type="hidden" name="csrf_token" value="{html.escape(self.csrf_token, quote=True)}"><button class="danger" type="submit">System neu starten</button></form>"""
        return _page("Abfahrten", content)

    def settings(self, message: str = "", restart_required: bool = False) -> bytes:
        raw_config = self.raw_config()
        credentials = load_credentials(self.credentials_path)
        notice = f'<div class="notice">{html.escape(message)}</div>' if message else ""
        restart_notice = ""
        if restart_required:
            restart_notice = f'''<div class="notice">Diese Änderung wird erst nach einem Neustart vollständig aktiv. Jetzt neu starten?<form method="post" action="/system/restart"><input type="hidden" name="csrf_token" value="{html.escape(self.csrf_token, quote=True)}"><button class="danger" type="submit">Jetzt neu starten</button></form></div>'''
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
            "display.bus_speed_hz": 16_000_000,
            "display.bgr": False,
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
            "night_shutdown.enabled": "Pausiert nachts Abfragen und Display.",
            "night_shutdown.start": "Beginn in Hamburger Ortszeit (HH:MM).",
            "night_shutdown.end": "Ende in Hamburger Ortszeit (HH:MM).",
        }

        def current(path: str) -> Any:
            section, key = path.split(".")
            return raw_config.get(section, {}).get(key, defaults[path])

        def scalar(path: str, input_type: str = "text") -> str:
            value = current(path)
            default = defaults[path]
            if isinstance(default, bool):
                control = (
                    f'<select id="{path}" data-path="{path}" data-type="bool" '
                    f'data-default="{str(default).lower()}">'
                    f'<option value="false" {"selected" if not value else ""}>Nein</option>'
                    f'<option value="true" {"selected" if value else ""}>Ja</option></select>'
                )
            else:
                control = (
                    f'<input id="{path}" data-path="{path}" type="{input_type}" '
                    f'value="{html.escape(str(value), quote=True)}" '
                    f'data-default="{html.escape(str(default), quote=True)}">'
                )
            return (
                f'<div class="setting"><label for="{path}">{path}</label>'
                f'<div class="control-row">{control}'
                f'<button type="button" class="reset" onclick="resetField(this)">Auf Standard zurücksetzen</button></div>'
                f'<div class="subtle help">{descriptions[path]}</div></div>'
            )

        def station_card(station: dict[str, Any], index: int) -> str:
            routes = "".join(
                f'<div class="route-row"><input data-route="line" value="{html.escape(str(route.get("line", "")), quote=True)}" placeholder="Linie" aria-label="Linie">'
                f'<input data-route="destination" value="{html.escape(str(route.get("destination", "")), quote=True)}" placeholder="Ziel" aria-label="Ziel">'
                '<button type="button" class="reset" onclick="this.parentElement.remove()">Route entfernen</button></div>'
                for route in station.get("routes", [])
            )
            return f'''<article class="station-card" data-station>
<div class="station-heading"><h3>Haltestelle {index + 1}</h3><button type="button" class="reset" onclick="this.closest('[data-station]').remove()">Haltestelle entfernen</button></div>
<div class="grid"><div><label>Name</label><input data-station-field="name" value="{html.escape(str(station.get("name", "")), quote=True)}" required><div class="subtle help">Offizieller Haltestellenname.</div></div>
<div><label>Stadt</label><input data-station-field="city" value="{html.escape(str(station.get("city", "Hamburg")), quote=True)}" required><div class="subtle help">Stadt für die Geofox-Suche.</div></div>
<div><label>Geofox-ID (optional)</label><input data-station-field="id" value="{html.escape(str(station.get("id") or ""), quote=True)}"><div class="subtle help">Nur eintragen, wenn sicher bekannt; sonst leer lassen.</div></div>
<div><label>Kürzel</label><input data-station-field="label" maxlength="3" value="{html.escape(str(station.get("label", "")), quote=True)}" required><div class="subtle help">1–3 Zeichen für die Anzeige.</div></div></div>
<div class="station-search"><button type="button" onclick="searchStation(this)">Geofox-Suche</button><select data-station-results onchange="applyStation(this)"><option value="">Treffer auswählen …</option></select><span class="subtle" data-search-message></span></div>
<h4>Linien und Ziele</h4><div data-routes>{routes}</div><button type="button" onclick="addRoute(this)">Route hinzufügen</button></article>'''

        stations = "".join(
            station_card(station, index)
            for index, station in enumerate(raw_config.get("stations", []))
        )
        if not stations:
            stations = station_card({"city": "Hamburg", "routes": []}, 0)
        raw = html.escape(json.dumps(raw_config, ensure_ascii=False))
        content = f"""<div class="toolbar"><div><h1>Einstellungen</h1><div class="subtle">Bedienbare Felder · jede Änderung wird validiert</div></div><a href="/">← Abfahrten</a></div>{notice}
<form method="post" action="/settings" accept-charset="UTF-8" onsubmit="return prepareConfig()"><section class="card"><h2>Geofox-Zugang</h2><p class="subtle">Das Passwort wird nicht angezeigt. Ein leeres Passwort lässt den bisherigen Wert unverändert.</p>
<label for="user">Anwendungs-ID</label><input id="user" name="user" value="{html.escape(credentials.get("GEOFOX_USER", ""), quote=True)}" autocomplete="username">
<label for="password">Passwort</label><input id="password" name="password" type="password" autocomplete="new-password" placeholder="unverändert lassen"></section>
<section class="card"><h2>Geofox-API</h2><div class="grid">{scalar("api.base_url")}{scalar("api.version", "number")}{scalar("api.refresh_seconds", "number")}{scalar("api.request_timeout_seconds", "number")}{scalar("api.max_departures", "number")}{scalar("api.max_time_offset_minutes", "number")}{scalar("api.max_stale_age_minutes", "number")}</div></section>
<section class="card"><h2>Display</h2><div class="grid">{scalar("display.spi_port", "number")}{scalar("display.spi_device", "number")}{scalar("display.gpio_dc", "number")}{scalar("display.gpio_reset", "number")}{scalar("display.rotate", "number")}{scalar("display.bus_speed_hz", "number")}{scalar("display.bgr")}</div></section>
<section class="card"><h2>Nachtabschaltung</h2><div class="grid">{scalar("night_shutdown.enabled")}{scalar("night_shutdown.start", "time")}{scalar("night_shutdown.end", "time")}</div></section>
<section class="card"><div class="station-heading"><div><h2>Haltestellen und Linien</h2><p class="subtle">Karten statt JSON: Namen, Kürzel und Ziele sind direkt verständlich editierbar.</p><p class="notice">Die Geofox-Treffer sind nur Vorschläge. Es gibt keine Garantie auf Vollständigkeit oder Korrektheit. Im Zweifel bitte die <a href="https://gti.geofox.de/" target="_blank" rel="noreferrer">offizielle Geofox-API-Dokumentation</a> prüfen.</p></div><button type="button" onclick="addStation()">Haltestelle hinzufügen</button></div><div id="stations">{stations}</div></section>
<textarea id="config_json" name="config_json" hidden>{raw}</textarea><input type="hidden" name="csrf_token" value="{html.escape(self.csrf_token, quote=True)}"><p><button type="submit">Speichern und prüfen</button></p></form>{restart_notice}
<script>
function resetField(button) {{ const control = button.parentElement.querySelector('[data-path]'); control.value = control.dataset.default; }}
function addRoute(button) {{ const row = document.createElement('div'); row.className = 'route-row'; row.innerHTML = '<input data-route="line" placeholder="Linie" aria-label="Linie"><input data-route="destination" placeholder="Ziel" aria-label="Ziel"><button type="button" class="reset" onclick="this.parentElement.remove()">Route entfernen</button>'; button.previousElementSibling.appendChild(row); }}
function addStation() {{ const first = document.querySelector('[data-station]'); const clone = first.cloneNode(true); clone.querySelectorAll('input').forEach(input => input.value = input.dataset.stationField === 'city' ? 'Hamburg' : ''); clone.querySelector('[data-routes]').innerHTML = ''; document.getElementById('stations').appendChild(clone); }}
async function searchStation(button) {{ const card = button.closest('[data-station]'); const query = card.querySelector('[data-station-field="name"]').value; const city = card.querySelector('[data-station-field="city"]').value; const select = card.querySelector('[data-station-results]'); const message = card.querySelector('[data-search-message]'); message.textContent = 'Suche …'; try {{ const response = await fetch('/api/stations?q=' + encodeURIComponent(query) + '&city=' + encodeURIComponent(city)); const data = await response.json(); if (!response.ok) throw new Error(data.error || 'Suche fehlgeschlagen'); select.innerHTML = '<option value="">Treffer auswählen …</option>'; data.stations.forEach(station => {{ const option = document.createElement('option'); option.value = JSON.stringify(station); option.textContent = station.combinedName; select.appendChild(option); }}); message.textContent = data.stations.length ? 'Bitte passenden Treffer auswählen.' : 'Keine Treffer.'; }} catch (error) {{ message.textContent = error.message; }} }}
function applyStation(select) {{ if (!select.value) return; const station = JSON.parse(select.value); const card = select.closest('[data-station]'); card.querySelector('[data-station-field="name"]').value = station.name; card.querySelector('[data-station-field="city"]').value = station.city; card.querySelector('[data-station-field="id"]').value = station.id; }}
function prepareConfig() {{ const config = JSON.parse(document.getElementById('config_json').value); document.querySelectorAll('[data-path]').forEach(control => {{ const [section, key] = control.dataset.path.split('.'); config[section][key] = control.dataset.type === 'bool' ? control.value === 'true' : (control.type === 'number' ? Number(control.value) : control.value); }}); config.stations = [...document.querySelectorAll('[data-station]')].map(card => ({{ name: card.querySelector('[data-station-field="name"]').value, city: card.querySelector('[data-station-field="city"]').value, id: card.querySelector('[data-station-field="id"]').value || undefined, label: card.querySelector('[data-station-field="label"]').value, routes: [...card.querySelectorAll('[data-route="line"]')].map((line, index) => ({{ line: line.value, destination: card.querySelectorAll('[data-route="destination"]')[index].value }})) }})); document.getElementById('config_json').value = JSON.stringify(config); return true; }}
</script>"""
        return _page("Einstellungen", content)


def make_handler(application: WebApplication) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _form_values(self, max_length: int) -> dict[str, list[str]]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise ValueError("Ungültige Anfragegröße") from exc
            if length < 0:
                raise ValueError("Ungültige Anfragegröße")
            payload = self.rfile.read(min(length, max_length))
            try:
                form_text = payload.decode("utf-8")
            except UnicodeDecodeError:
                # Some embedded browsers still submit form bodies as Latin-1.
                form_text = payload.decode("latin-1")
            return parse_qs(form_text, keep_blank_values=True)

        def _send(self, payload: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def _unauthorized(self) -> None:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            self.send_header("WWW-Authenticate", 'Basic realm="hvv-anzeiger"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            if not application.authorize(self.headers):
                self._unauthorized()
                return
            path = urlsplit(self.path).path
            if path == "/":
                self._send(application.dashboard())
            elif path == "/settings":
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    saved = query.get("saved", [""])[0] == "1"
                    self._send(application.settings(
                        "Gespeichert. Die laufende Anwendung übernimmt die Änderung bei der nächsten Aktualisierung; ein Neustart ist nicht nötig."
                        if saved else "",
                        restart_required=False,
                    ))
                except (ConfigError, OSError) as exc:
                    self._send(application.settings(str(exc)), HTTPStatus.INTERNAL_SERVER_ERROR)
            elif path == "/api/departures":
                try:
                    departures, error = application.departures()
                    payload = json.dumps({"departures": departures, "error": error}).encode()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except (ConfigError, GeofoxError, OSError):
                    self._send(application.dashboard())
            elif path == "/api/stations":
                query = parse_qs(urlsplit(self.path).query)
                try:
                    stations = application.station_suggestions(
                        query.get("q", [""])[0], query.get("city", ["Hamburg"])[0]
                    )
                    payload = json.dumps(
                        {"stations": stations}, ensure_ascii=False
                    ).encode()
                    self.send_response(HTTPStatus.OK)
                except (ConfigError, GeofoxError, OSError, ValueError) as exc:
                    payload = json.dumps(
                        {"stations": [], "error": str(exc)}, ensure_ascii=False
                    ).encode()
                    self.send_response(HTTPStatus.BAD_REQUEST)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(payload)
            else:
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
                except (OSError, PermissionError, ValueError, UnicodeDecodeError) as exc:
                    self._send(application.dashboard() + f"<!-- {html.escape(str(exc))} -->".encode(), HTTPStatus.FORBIDDEN)
                return
            if path != "/settings":
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            try:
                values = self._form_values(1_000_000)
                application.validate_csrf(values.get("csrf_token", [""])[0])
                raw_config = json.loads(values.get("config_json", [""])[0])
                if not isinstance(raw_config, dict):
                    raise ValueError("Konfiguration muss ein JSON-Objekt sein")
                candidate = self.server.application.config_path  # type: ignore[attr-defined]
                with tempfile.NamedTemporaryFile(
                    mode="w", encoding="utf-8", suffix=".json", delete=False
                ) as handle:
                    handle.write(json.dumps(raw_config, ensure_ascii=False))
                    temporary = Path(handle.name)
                try:
                    load_config(temporary)
                finally:
                    temporary.unlink(missing_ok=True)
                user = values.get("user", [""])[0].strip()
                password = values.get("password", [""])[0]
                current = load_credentials(application.credentials_path)
                save_config(candidate, raw_config)
                if password:
                    save_credentials(application.credentials_path, user, password)
                elif user != current.get("GEOFOX_USER", ""):
                    save_credentials(application.credentials_path, user, current.get("GEOFOX_PASSWORD", ""))
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/settings?saved=1")
                self.end_headers()
            except (ValueError, ConfigError, OSError, PermissionError) as exc:
                self._send(application.settings(f"Nicht gespeichert: {exc}"), HTTPStatus.BAD_REQUEST)

        def log_message(self, format: str, *args: object) -> None:
            LOG.info("web %s", format % args)

    return Handler


def run(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, config: str = "config.json", credentials: str | None = None, cache: str = "var/stations.json", access_token: str | None = None) -> None:
    if host not in {"127.0.0.1", "localhost", "::1"} and not access_token:
        raise ValueError("Für einen nicht-lokalen Webhost muss HVV_WEB_TOKEN gesetzt sein")
    config_path = Path(config)
    credentials_path = Path(credentials or os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env"))
    application = WebApplication(config_path, credentials_path, Path(cache), access_token=access_token)
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
    parser = argparse.ArgumentParser(description="Lokale Weboberfläche für den HVV-Anzeiger")
    parser.add_argument("--host", default=os.environ.get("HVV_WEB_HOST", DEFAULT_HOST))
    parser.add_argument("--port", type=int, default=int(os.environ.get("HVV_WEB_PORT", DEFAULT_PORT)))
    parser.add_argument("--config", default=os.environ.get("HVV_CONFIG", "config.json"))
    parser.add_argument("--credentials", default=os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env"))
    parser.add_argument("--cache", default=os.environ.get("HVV_STATION_CACHE", "var/stations.json"))
    parser.add_argument("--access-token", default=os.environ.get("HVV_WEB_TOKEN"), help="Bearer-Token für nicht-lokale Zugriffe")
    args = parser.parse_args()
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO").upper())
    run(args.host, args.port, config=args.config, credentials=args.credentials, cache=args.cache, access_token=args.access_token)


if __name__ == "__main__":
    main()
