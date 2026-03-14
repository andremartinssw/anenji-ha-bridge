"""Select platform for Anenji Inverter Bridge."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    MANUFACTURER,
    SELECT_DESCRIPTIONS,
    SELECT_REVERSE_MAPS,
    AnenjiBridgeSelectDescription,
)
from .coordinator import AnenjiBridgeCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Anenji Bridge select entities from a config entry."""
    coordinator: AnenjiBridgeCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        AnenjiBridgeSelect(coordinator, entry, desc)
        for desc in SELECT_DESCRIPTIONS
    )


class AnenjiBridgeSelect(CoordinatorEntity[AnenjiBridgeCoordinator]):
    """Representation of an Anenji Bridge select control."""

    _attr_has_entity_name = True
    entity_description: AnenjiBridgeSelectDescription

    def __init__(
        self,
        coordinator: AnenjiBridgeCoordinator,
        entry: ConfigEntry,
        description: AnenjiBridgeSelectDescription,
    ) -> None:
        """Initialize the select entity."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_options = list(description.options)
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
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if self.coordinator.data is None:
            return None

        json_key = self.entity_description.json_key
        raw_value = self.coordinator.data.get(json_key)
        if raw_value is None:
            return None

        # Look up the numeric code → display label
        reverse_map = SELECT_REVERSE_MAPS.get(json_key)
        if reverse_map:
            try:
                code = int(raw_value)
                label = reverse_map.get(code)
                if label and label in self._attr_options:
                    return label
            except (ValueError, TypeError):
                pass

        # Fallback: if the raw value is already a label
        if isinstance(raw_value, str) and raw_value in self._attr_options:
            return raw_value

        return None

    async def async_select_option(self, option: str) -> None:
        """Set the option on the inverter."""
        command = self.entity_description.options_map.get(option)
        if command:
            await self.coordinator.send_command(command)
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.warning("Unknown option '%s' for %s", option, self.entity_description.key)
