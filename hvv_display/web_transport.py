# ruff: noqa: E501
"""HTTP transport, request handler and server lifecycle for the web UI."""

from __future__ import annotations

import html
import ipaddress
import json
import os
import socket
import ssl
import tempfile
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Any
from urllib.parse import parse_qs, urlsplit

from .config import load_config
from .config_backup import MAX_CONFIG_BYTES, export_config, import_config
from .health import STATUS_CODES
from .web import (
    DEFAULT_HOST,
    DEFAULT_PORT,
    LOG,
    MAX_FORM_BYTES,
    ConfigConflict,
    ConfigError,
    GeofoxError,
    WebApplication,
    _geofox_http_status,
    _page,
    _settings_field_errors,
    load_credentials,
    save_credentials,
    verify_web_password,
)


class WebServer(ThreadingHTTPServer):
    """Accept TCP first; bound TLS/HTTP work inside independent request threads."""

    def __init__(
        self,
        *args: Any,
        tls_context: ssl.SSLContext | None = None,
        connection_timeout: float = 5.0,
        max_workers: int = 32,
        max_connections_per_client: int = 8,
        **kwargs: Any,
    ) -> None:
        self.tls_context = tls_context
        self.connection_timeout = connection_timeout
        self.max_connections_per_client = max_connections_per_client
        self._workers = BoundedSemaphore(max_workers)
        self._client_lock = Lock()
        self._client_workers: dict[str, int] = {}
        super().__init__(*args, **kwargs)

    def process_request(self, request: socket.socket, client_address: Any) -> None:
        if not self._workers.acquire(blocking=False):
            self.shutdown_request(request)
            return
        client_ip = str(client_address[0])
        with self._client_lock:
            active = self._client_workers.get(client_ip, 0)
            if active >= self.max_connections_per_client:
                self._workers.release()
                self.shutdown_request(request)
                return
            self._client_workers[client_ip] = active + 1
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._release_client(client_ip)
            self._workers.release()
            raise

    def _release_client(self, client_ip: str) -> None:
        with self._client_lock:
            active = self._client_workers.get(client_ip, 0)
            if active <= 1:
                self._client_workers.pop(client_ip, None)
            else:
                self._client_workers[client_ip] = active - 1

    def process_request_thread(
        self, request: socket.socket, client_address: Any
    ) -> None:
        try:
            request.settimeout(self.connection_timeout)
            if self.tls_context is not None:
                # Never perform a TLS handshake on the listening/accepting socket.
                try:
                    request = self.tls_context.wrap_socket(
                        request, server_side=True, do_handshake_on_connect=False
                    )
                    request.do_handshake()
                except OSError:
                    request.close()
                    return
            super().process_request_thread(request, client_address)
        finally:
            self._release_client(str(client_address[0]))
            self._workers.release()


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
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "script-src 'unsafe-inline'; img-src 'self' data:; "
                "connect-src 'self'; base-uri 'none'; form-action 'self'; "
                "frame-ancestors 'none'",
            )

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

        def _unauthorized(self, *, device: bool = False) -> None:
            self.send_response(HTTPStatus.UNAUTHORIZED)
            challenge = (
                'Bearer realm="hvv-anzeiger-cyd"'
                if device
                else 'Basic realm="hvv-anzeiger"'
            )
            self.send_header("WWW-Authenticate", challenge)
            self._security_headers()
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/_healthz":
                try:
                    if ipaddress.ip_address(self.client_address[0]).is_loopback:
                        self.send_response(HTTPStatus.NO_CONTENT)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                        return
                except ValueError:
                    pass
            device_endpoint = path == "/api/esphome"
            authenticated = (
                application.authorize_device(self.headers)
                if device_endpoint
                else application.authorize(self.headers)
            )
            if not authenticated:
                self._unauthorized(device=device_endpoint)
                return
            if (
                application.must_change_password
                and not device_endpoint
                and path != "/change-password"
            ):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", "/change-password")
                self._security_headers()
                self.end_headers()
                return
            if path == "/change-password":
                self._send(application.password_change_page())
                return
            if path in {"/api/health", "/api/diagnostics", "/diagnostics"}:
                self.connection.settimeout(2)
                if not application.allow_health_request():
                    self._send_json(
                        {"error": "Zu viele Statusabfragen"},
                        HTTPStatus.TOO_MANY_REQUESTS,
                        retry_after=1,
                    )
                elif path == "/diagnostics":
                    self._send(application.diagnostics())
                else:
                    data = application.health()
                    status = (
                        HTTPStatus.OK
                        if path == "/api/diagnostics"
                        else HTTPStatus(STATUS_CODES[data["status"]][0])
                    )
                    self._send_json(data, status)
                return
            if path == "/":
                self._send(application.dashboard())
                return
            if path == "/display":
                self._send(application.display())
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
            if path == "/config-backup":
                query = parse_qs(urlsplit(self.path).query)
                self._send(
                    application.config_backup_page(
                        "Gespeichert. Der Anzeigedienst übernimmt die Konfiguration bei der nächsten Aktualisierung."
                        if query.get("saved") == ["1"]
                        else ""
                    )
                )
                return
            if path == "/config/export":
                try:
                    query = parse_qs(urlsplit(self.path).query)
                    name = query.get("backup_id", [""])[0]
                    raw = (
                        application.config_store.backup_candidate(name)
                        if name
                        else application.config_store.current()[0]
                    )
                    payload = export_config(raw)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json; charset=utf-8")
                    self.send_header(
                        "Content-Disposition",
                        'attachment; filename="hvv-konfiguration.json"',
                    )
                    self.send_header("Content-Length", str(len(payload)))
                    self._security_headers()
                    self.end_headers()
                    self.wfile.write(payload)
                except (ConfigError, OSError):
                    self._send(
                        application.config_backup_page(
                            "Export nicht möglich: Konfiguration oder Sicherung ist ungültig oder nicht lesbar."
                        ),
                        HTTPStatus.BAD_REQUEST,
                    )
                return
            if path in {"/api/smart-home", "/api/esphome"}:
                data = application.smart_home()
                self._send_json(
                    json.loads(data["display_payload"])
                    if path == "/api/esphome"
                    else data
                )
                return
            if path == "/api/departures":
                data = application.departure_view()
                data.pop("board_html", None)
                self._send_json(data)
                return
            if path == "/api/display":
                self._send_json(application.departure_view())
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
            if application.must_change_password:
                if path != "/change-password":
                    self.send_error(HTTPStatus.FORBIDDEN)
                    return
                try:
                    values = self._form_values(4096)
                    application.validate_csrf(values.get("csrf_token", [""])[0])
                    new_password = values.get("new_password", [""])[0]
                    confirmation = values.get("confirmation", [""])[0]
                    if new_password != confirmation:
                        raise ValueError("Die beiden Passwörter stimmen nicht überein.")
                    application.save_web_password(new_password)
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header("Location", "/")
                    self.end_headers()
                except (ValueError, PermissionError) as exc:
                    self._send(
                        application.password_change_page(str(exc)),
                        HTTPStatus.BAD_REQUEST,
                    )
                except OSError:
                    self._send(
                        application.password_change_page("Speichern fehlgeschlagen."),
                        HTTPStatus.BAD_REQUEST,
                    )
                return
            if path in {
                "/config/preview",
                "/config/apply",
                "/config/cancel",
                "/config/backup",
            }:
                try:
                    values = self._form_values(MAX_CONFIG_BYTES * 3 + 4096)
                    application.validate_csrf(values.get("csrf_token", [""])[0])
                    if path == "/config/preview":
                        name = values.get("backup_id", [""])[0]
                        payload = values.get("config_data", [""])[0]
                        if bool(name) == bool(payload):
                            raise ConfigError(
                                "Genau eine Sicherungsdatei oder gespeicherte Sicherung auswählen"
                            )
                        candidate = (
                            application.config_store.backup_candidate(name)
                            if name
                            else import_config(payload.encode("utf-8"))
                        )
                        token, preview = application.prepare_config(candidate)
                        self._send(application.config_preview_page(token, preview))
                        return
                    if path == "/config/apply":
                        application.apply_config_plan(
                            values.get("token", [""])[0],
                            values.get("confirmed", [""])[0] == "yes",
                        )
                    elif path == "/config/cancel":
                        application.cancel_config_plan(values.get("token", [""])[0])
                    else:
                        application.config_store.backup()
                    self.send_response(HTTPStatus.SEE_OTHER)
                    self.send_header(
                        "Location",
                        "/config-backup?saved=1"
                        if path == "/config/apply"
                        else "/config-backup",
                    )
                    self._security_headers()
                    self.end_headers()
                except ConfigConflict as exc:
                    self._send(
                        application.config_backup_page(str(exc)), HTTPStatus.CONFLICT
                    )
                except PermissionError:
                    self._send(
                        application.config_backup_page(
                            "Anfrage nicht autorisiert oder Dateizugriff verweigert; nicht angewendet."
                        ),
                        HTTPStatus.FORBIDDEN,
                    )
                except OverflowError:
                    self._send(
                        application.config_backup_page(
                            "Import ist zu groß; nicht angewendet."
                        ),
                        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                    )
                except (ConfigError, ValueError) as exc:
                    self._send(
                        application.config_backup_page(str(exc)), HTTPStatus.BAD_REQUEST
                    )
                except OSError:
                    self._send(
                        application.config_backup_page(
                            "Dateizugriff fehlgeschlagen; bestehende Konfiguration bleibt erhalten."
                        ),
                        HTTPStatus.BAD_REQUEST,
                    )
                return
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
                expected_revision = values.get(
                    "config_revision", [application.config_store.base_revision()]
                )[0]
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
                application.config_store.apply(
                    raw_config, expected_revision=expected_revision
                )
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
            except ConfigConflict as exc:
                self._send(application.settings(str(exc)), HTTPStatus.CONFLICT)
            except OverflowError as exc:
                self._send(
                    application.settings(
                        f"Nicht gespeichert: {exc}",
                        field_errors=_settings_field_errors(str(exc)),
                    ),
                    HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                )
            except GeofoxError as exc:
                self._send(
                    application.settings(
                        f"Nicht gespeichert: {exc}",
                        field_errors=_settings_field_errors(str(exc)),
                    ),
                    _geofox_http_status(exc),
                )
            except (ValueError, ConfigError, OSError, PermissionError) as exc:
                self._send(
                    application.settings(
                        f"Nicht gespeichert: {exc}",
                        field_errors=_settings_field_errors(str(exc)),
                    ),
                    HTTPStatus.BAD_REQUEST,
                )

        def log_message(self, format: str, *args: object) -> None:
            if urlsplit(getattr(self, "path", "")).path in {
                "/api/health",
                "/api/diagnostics",
                "/diagnostics",
            }:
                return
            LOG.info("web %s", format % args)

    return Handler


def run(
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    *,
    config: str = "config.json",
    credentials: str | None = None,
    cache: str = "var/stations.json",
    departure_cache: str = "var/departures.json",
    access_token: str | None = None,
    device_token: str | None = None,
    must_change_password: bool = False,
    tls_certfile: str | None = None,
    tls_keyfile: str | None = None,
    discovery_hostname: str | None = None,
) -> None:
    local_host = host in {"127.0.0.1", "localhost", "::1"}
    if not local_host and not access_token:
        raise ValueError(
            "Für einen nicht-lokalen Webhost muss HVV_WEB_PASSWORD_HASH gesetzt sein"
        )
    if (
        not local_host
        and access_token
        and verify_web_password("hvv-anzeiger", access_token)
        and not must_change_password
    ):
        raise ValueError("Vor dem LAN-Start ein individuelles Webpasswort einrichten")
    if (tls_certfile is None) != (tls_keyfile is None):
        raise ValueError(
            "TLS-Zertifikat und TLS-Schlüssel müssen gemeinsam gesetzt sein"
        )
    if not local_host and not tls_certfile:
        raise ValueError(
            "Für einen nicht-lokalen Webhost muss TLS mit Zertifikat und Schlüssel aktiviert sein"
        )
    application = WebApplication(
        Path(config),
        Path(
            credentials or os.environ.get("HVV_CREDENTIALS_FILE", "var/credentials.env")
        ),
        Path(cache),
        access_token=access_token,
        device_token=device_token or os.environ.get("HVV_ESPHOME_API_TOKEN"),
        must_change_password=(
            must_change_password
            or os.environ.get("HVV_WEB_PASSWORD_MUST_CHANGE") == "1"
        ),
        web_env_path=Path(os.environ.get("HVV_WEB_ENV_FILE", "var/web.env")),
        departure_cache_path=Path(departure_cache),
    )
    context = None
    if tls_certfile:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.load_cert_chain(tls_certfile, tls_keyfile)
    # Resolve through the compatibility facade at runtime so callers that
    # patched hvv_display.web.WebServer before the split keep working.
    from . import web

    server = web.WebServer((host, port), make_handler(application), tls_context=context)
    server.application = application  # type: ignore[attr-defined]
    scheme = "https" if tls_certfile else "http"
    advertiser = None
    if not local_host:
        try:
            from .home_assistant_discovery import HomeAssistantAdvertiser

            advertiser = HomeAssistantAdvertiser(
                port,
                scheme,
                discovery_hostname or os.environ.get("HVV_WEB_DISCOVERY_HOSTNAME"),
            )
            LOG.info("Home-Assistant-Erkennung über mDNS aktiviert")
        except Exception:
            LOG.exception("mDNS-Ankündigung für Home Assistant fehlgeschlagen")
    LOG.info("Lokale Weboberfläche erreichbar unter %s://%s:%d", scheme, host, port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if advertiser is not None:
            advertiser.close()
