"""Home Assistant integration for the local HVV-Anzeiger backend."""

from __future__ import annotations

import logging
from datetime import timedelta

from aiohttp import BasicAuth, ClientError, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_URL
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ApiResponseTooLarge, read_json_response
from .const import API_PATH, CONF_PASSWORD, DOMAIN, PLATFORMS

type HvvConfigEntry = ConfigEntry[HvvCoordinator]


class HvvCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Poll and validate the backend's versioned display snapshot."""

    def __init__(self, hass: HomeAssistant, entry: HvvConfigEntry) -> None:
        self.url = entry.data[CONF_URL].rstrip("/") + API_PATH
        self.password = entry.data[CONF_PASSWORD]
        super().__init__(
            hass,
            logger=logging.getLogger(__name__),
            name=DOMAIN,
            update_interval=timedelta(seconds=15),
        )

    async def _async_update_data(self) -> dict[str, object]:
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                self.url,
                auth=BasicAuth("hvv-anzeiger", self.password, encoding="utf-8"),
                timeout=ClientTimeout(total=30),
                allow_redirects=False,
            ) as response:
                if response.status == 401:
                    raise UpdateFailed("Webpasswort wurde vom HVV-Anzeiger abgelehnt")
                if response.status >= 400:
                    raise UpdateFailed(
                        f"HVV-Anzeiger antwortet mit HTTP {response.status}"
                    )
                data = await read_json_response(response)
        except UpdateFailed:
            raise
        except ApiResponseTooLarge as err:
            raise UpdateFailed(str(err)) from err
        except (ClientError, TimeoutError, ValueError) as err:
            raise UpdateFailed(f"HVV-Anzeiger nicht erreichbar: {err}") from err

        if not isinstance(data, dict) or data.get("schema_version") != 1:
            raise UpdateFailed("HVV-Anzeiger liefert ein unbekanntes Datenformat")
        if not isinstance(data.get("state"), str) or not isinstance(
            data.get("departures"), list
        ):
            raise UpdateFailed("HVV-Anzeiger liefert unvollständige Daten")
        return data


async def async_setup_entry(hass: HomeAssistant, entry: HvvConfigEntry) -> bool:
    """Set up a discovered or manually configured backend."""
    coordinator = HvvCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HvvConfigEntry) -> bool:
    """Unload the sensor platform."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    return True
