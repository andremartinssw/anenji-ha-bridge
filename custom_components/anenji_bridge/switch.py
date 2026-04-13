"""Switch platform for Anenji Inverter Bridge."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.components.switch import SwitchEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SWITCH_DESCRIPTIONS,
    AnenjiBridgeSwitchDescription,
)
from .coordinator import AnenjiBridgeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anenji Bridge switches from a config entry."""
    coordinator: AnenjiBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AnenjiBridgeSwitch(coordinator, entry, desc)
        for desc in SWITCH_DESCRIPTIONS
    )


class AnenjiBridgeSwitch(CoordinatorEntity[AnenjiBridgeCoordinator], SwitchEntity):
    """Representation of an Anenji Bridge switch."""

    _attr_has_entity_name = True
    entity_description: AnenjiBridgeSwitchDescription

    def __init__(
        self,
        coordinator: AnenjiBridgeCoordinator,
        entry: ConfigEntry,
        description: AnenjiBridgeSwitchDescription,
    ) -> None:
        """Initialize the switch."""
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
    def is_on(self) -> bool | None:
        """Return true if the switch is on."""
        if self.coordinator.data is None:
            return None
        val = self.coordinator.data.get(self.entity_description.json_key)
        if val is None:
            return None
        return val == self.entity_description.on_value

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        await self.coordinator.send_command(self.entity_description.cmd_on)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        await self.coordinator.send_command(self.entity_description.cmd_off)
        await self.coordinator.async_request_refresh()
