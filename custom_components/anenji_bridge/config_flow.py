"""Config flow for Anenji Inverter Bridge."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import DEFAULT_PORT, DOMAIN, DEFAULT_SCAN_INTERVAL, CONF_SCAN_INTERVAL

_LOGGER = logging.getLogger(__name__)


async def _test_connection(host: str, port: int) -> str | None:
    """Test TCP connection to the bridge. Returns None on success, error string on failure."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=5
        )
        writer.write(b"JSON\n")
        await writer.drain()
        data = await asyncio.wait_for(reader.read(65536), timeout=5)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass

        # Validate JSON
        result = json.loads(data.decode().strip())
        if "device_status_msg" not in result:
            return "invalid_response"
        return None
    except TimeoutError:
        return "cannot_connect"
    except OSError:
        return "cannot_connect"
    except json.JSONDecodeError:
        return "invalid_response"


class AnenjiBridgeConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Anenji Inverter Bridge."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            scan_interval = user_input[CONF_SCAN_INTERVAL]

            # Prevent duplicate entries
            self._async_abort_entries_match({CONF_HOST: host, CONF_PORT: port})

            error = await _test_connection(host, port)
            if error:
                errors["base"] = error
            else:
                return self.async_create_entry(
                    title=f"Anenji Bridge ({host})",
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Required(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
                }
            ),
            errors=errors,
        )
