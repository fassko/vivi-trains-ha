"""Config flow for Vivi Trains integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.core import callback

from .const import (
    CONF_DEPARTURES_COUNT,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DEFAULT_DEPARTURES_COUNT,
    DOMAIN,
)
from .coordinator import ViviTrainsCoordinator

_LOGGER = logging.getLogger(__name__)


class ViviTrainsConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Vivi Trains."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise config flow."""
        self._stations: list[dict] = []

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — station selection."""
        errors: dict[str, str] = {}

        # Load station list (blocking I/O → executor)
        if not self._stations:
            try:
                self._stations = await self.hass.async_add_executor_job(
                    ViviTrainsCoordinator.get_station_list
                )
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Failed to load station list")
                return self.async_abort(reason="cannot_connect")

        if user_input is not None:
            station_id = user_input[CONF_STATION_ID]

            # Look up name for the chosen station
            station_name = next(
                (s["name"] for s in self._stations if s["id"] == station_id),
                station_id,
            )

            # Prevent duplicate entries for the same station
            await self.async_set_unique_id(f"vivi_{station_id}")
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Vivi — {station_name}",
                data={
                    CONF_STATION_ID: station_id,
                    CONF_STATION_NAME: station_name,
                    CONF_DEPARTURES_COUNT: user_input.get(
                        CONF_DEPARTURES_COUNT, DEFAULT_DEPARTURES_COUNT
                    ),
                },
            )

        # Build a selector-friendly dict: {display_label: station_id}
        station_options = {s["id"]: s["name"] for s in self._stations}

        schema = vol.Schema(
            {
                vol.Required(CONF_STATION_ID): vol.In(station_options),
                vol.Optional(
                    CONF_DEPARTURES_COUNT, default=DEFAULT_DEPARTURES_COUNT
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=20)),
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={
                "station_count": str(len(self._stations)),
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return ViviTrainsOptionsFlow(config_entry)


class ViviTrainsOptionsFlow(OptionsFlow):
    """Handle options for Vivi Trains."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialise options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_count = self.config_entry.options.get(
            CONF_DEPARTURES_COUNT,
            self.config_entry.data.get(CONF_DEPARTURES_COUNT, DEFAULT_DEPARTURES_COUNT),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_DEPARTURES_COUNT, default=current_count): vol.All(
                    vol.Coerce(int), vol.Range(min=1, max=20)
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
