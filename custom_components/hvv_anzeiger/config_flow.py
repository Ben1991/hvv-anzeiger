"""Discovery and setup flow for HVV-Anzeiger."""

from __future__ import annotations

from urllib.parse import urlsplit

import voluptuous as vol
from aiohttp import BasicAuth, ClientError, ClientTimeout
from homeassistant import config_entries
from homeassistant.const import CONF_PASSWORD, CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .api import build_discovered_url, is_secure_url, read_json_response
from .const import API_PATH, DOMAIN


class CannotConnect(Exception):
    """The discovered backend could not be reached or validated."""


class InvalidAuth(Exception):
    """The supplied web password was rejected."""


class InsecureTransport(Exception):
    """The backend URL would send credentials over a non-local cleartext link."""


class HvvConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Configure the backend discovered by mDNS or entered manually."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovered_url: str | None = None
        self._unique_id: str | None = None

    async def async_step_zeroconf(
        self, discovery_info: ZeroconfServiceInfo
    ) -> config_entries.ConfigFlowResult:
        """Offer a discovered backend in the integrations screen."""
        hostname = discovery_info.hostname or discovery_info.host
        self._unique_id = hostname.lower().rstrip(".")
        await self.async_set_unique_id(self._unique_id)
        self._abort_if_unique_id_configured()
        scheme = discovery_info.properties.get("scheme", "https")
        if isinstance(scheme, bytes):
            scheme = scheme.decode("ascii", errors="ignore")
        if scheme not in {"http", "https"}:
            scheme = "https"
        self._discovered_url = build_discovered_url(
            hostname, discovery_info.port, scheme
        )
        self.context["title_placeholders"] = {"name": discovery_info.name}
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, str] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Ask for the backend URL and its individual web password."""
        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].strip().rstrip("/")
            password = user_input[CONF_PASSWORD]
            try:
                parsed = urlsplit(url)
                if (
                    parsed.scheme not in {"http", "https"}
                    or not parsed.hostname
                    or parsed.username
                    or parsed.password
                    or parsed.path not in {"", "/"}
                    or parsed.query
                    or parsed.fragment
                ):
                    raise CannotConnect
                if not is_secure_url(url):
                    raise InsecureTransport
                await self._async_validate(url, password)
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except InsecureTransport:
                errors["base"] = "insecure_transport"
            except (CannotConnect, ClientError, TimeoutError, ValueError):
                errors["base"] = "cannot_connect"
            else:
                unique_id = self._unique_id or parsed.hostname.lower()
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="HVV-Anzeiger",
                    data={CONF_URL: url, CONF_PASSWORD: password},
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_URL, default=self._discovered_url or "https://"): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def _async_validate(self, url: str, password: str) -> None:
        """Check the API and credentials with normal certificate validation."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                url + API_PATH,
                auth=BasicAuth("hvv-anzeiger", password, encoding="utf-8"),
                timeout=ClientTimeout(total=15),
                allow_redirects=False,
            ) as response:
                if response.status == 401:
                    raise InvalidAuth
                if response.status >= 400:
                    raise CannotConnect
                data = await read_json_response(response)
        except InvalidAuth:
            raise
        except (ClientError, TimeoutError, ValueError) as err:
            raise CannotConnect from err
        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise CannotConnect
