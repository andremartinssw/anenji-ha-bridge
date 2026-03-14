"""Number platform for Anenji Inverter Bridge."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    NUMBER_DESCRIPTIONS,
    AnenjiBridgeNumberDescription,
)
from .coordinator import AnenjiBridgeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anenji Bridge number entities from a config entry."""
    coordinator: AnenjiBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AnenjiBridgeNumber(coordinator, entry, desc)
        for desc in NUMBER_DESCRIPTIONS
    )


class AnenjiBridgeNumber(CoordinatorEntity[AnenjiBridgeCoordinator]):
    """Representation of an Anenji Bridge number control."""

    _attr_has_entity_name = True
    entity_description: AnenjiBridgeNumberDescription

    def __init__(
        self,
        coordinator: AnenjiBridgeCoordinator,
        entry: ConfigEntry,
        description: AnenjiBridgeNumberDescription,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": "Anenji Inverter",
            "manufacturer": MANUFACTURER,
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
    def native_value(self) -> float | None:
        """Return the current value."""
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self.entity_description.json_key)
        if val is None:
            return None
        return float(val)

    async def async_set_native_value(self, value: float) -> None:
        """Set the value on the inverter."""
        # Integer commands for amps/SOC, float for voltages
        if self.entity_description.native_step == 1:
            cmd = f"{self.entity_description.cmd_prefix}{int(value)}"
        else:
            cmd = f"{self.entity_description.cmd_prefix}{value}"

        await self.coordinator.send_command(cmd)
        await self.coordinator.async_request_refresh()
