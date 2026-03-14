"""DataUpdateCoordinator for Anenji Inverter Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)

CONNECT_TIMEOUT = 5
READ_TIMEOUT = 5


class AnenjiBridgeCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that polls the Anenji bridge TCP server."""

    def __init__(self, hass: HomeAssistant, host: str, port: int) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.host = host
        self.port = port

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the bridge."""
        try:
            data = await self._query_bridge("JSON")
            return json.loads(data)
        except (TimeoutError, OSError) as err:
            raise UpdateFailed(f"Cannot connect to bridge at {self.host}:{self.port}: {err}") from err
        except json.JSONDecodeError as err:
            raise UpdateFailed(f"Invalid JSON from bridge: {err}") from err

    async def send_command(self, command: str) -> str:
        """Send a command to the bridge and return the response."""
        try:
            return await self._query_bridge(command)
        except (TimeoutError, OSError) as err:
            _LOGGER.error("Failed to send command '%s' to bridge: %s", command, err)
            raise

    async def _query_bridge(self, payload: str) -> str:
        """Open a TCP connection, send payload, read response."""
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port),
            timeout=CONNECT_TIMEOUT,
        )
        try:
            writer.write(payload.encode() + b"\n")
            await writer.drain()
            data = await asyncio.wait_for(reader.read(65536), timeout=READ_TIMEOUT)
            return data.decode().strip()
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # noqa: BLE001
                pass
