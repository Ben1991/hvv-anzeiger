"""Departure board sensor for the HVV-Anzeiger backend."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HvvCoordinator
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one board entity for this backend device."""
    coordinator: HvvCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HvvBoardSensor(coordinator, entry)])


class HvvBoardSensor(CoordinatorEntity[HvvCoordinator], SensorEntity):
    """Expose board state and departures as one device sensor."""

    _attr_has_entity_name = True
    _attr_name = "Abfahrtsanzeige"
    _attr_icon = "mdi:train"

    def __init__(self, coordinator: HvvCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_board"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="HVV-Anzeiger",
            manufacturer="HVV-Anzeiger",
            model="Lokaler Fahrplan-Hintergrunddienst",
            configuration_url=entry.data["url"],
        )

    @property
    def native_value(self) -> str | None:
        """Return the current display-data state."""
        return str(self.coordinator.data["state"])

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        """Expose departure rows without recording a duplicate sensor per row."""
        return {
            "departures": self.coordinator.data.get("departures", []),
            "display_payload": self.coordinator.data.get("display_payload"),
            "generated_at": self.coordinator.data.get("generated_at"),
            "data_age_seconds": self.coordinator.data.get("data_age_seconds"),
            "night_shutdown": self.coordinator.data.get("night_shutdown"),
        }
