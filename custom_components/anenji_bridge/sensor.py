"""Sensor platform for Anenji Inverter Bridge."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SENSOR_DESCRIPTIONS,
    AnenjiBridgeSensorDescription,
)
from .coordinator import AnenjiBridgeCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anenji Bridge sensors from a config entry."""
    coordinator: AnenjiBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AnenjiBridgeSensor(coordinator, entry, desc)
        for desc in SENSOR_DESCRIPTIONS
    )


class AnenjiBridgeSensor(CoordinatorEntity[AnenjiBridgeCoordinator]):
    """Representation of an Anenji Bridge sensor."""

    _attr_has_entity_name = True
    entity_description: AnenjiBridgeSensorDescription

    def __init__(
        self,
        coordinator: AnenjiBridgeCoordinator,
        entry: ConfigEntry,
        description: AnenjiBridgeSensorDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Anenji Inverter",
            "manufacturer": MANUFACTURER,
            "model": "SRNE-based Hybrid Inverter",
            "configuration_url": f"http://{coordinator.host}:{coordinator.port}",
        }

    @property
    def available(self) -> bool:
        """Return True if the bridge is responding."""
        return (
            super().available
            and self.coordinator.data is not None
            and self.coordinator.data.get("device_status_msg") != "Offline"
        )

    @property
    def native_value(self):
        """Return the state of the sensor."""
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.json_key)
