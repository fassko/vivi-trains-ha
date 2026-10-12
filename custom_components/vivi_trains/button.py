"""Manual schedule update button for Vivi Trains."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_STATION_ID, CONF_STATION_NAME, DOMAIN
from .schedule import ViviScheduleManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up a manual schedule check button for this station."""
    manager: ViviScheduleManager = hass.data[DOMAIN]["schedule_manager"]
    async_add_entities([ViviUpdateScheduleButton(manager, entry)])


class ViviUpdateScheduleButton(ButtonEntity):
    """Check the public GTFS feed immediately when pressed."""

    _attr_has_entity_name = True
    _attr_translation_key = "update_schedule"
    _attr_icon = "mdi:download"

    def __init__(self, manager: ViviScheduleManager, entry: ConfigEntry) -> None:
        self._manager = manager
        self._station_id = entry.data[CONF_STATION_ID]
        self._station_name = entry.data.get(CONF_STATION_NAME, self._station_id)
        self._attr_unique_id = f"vivi_{self._station_id}_update_schedule"

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=f"Vivi — {self._station_name}",
            manufacturer="Vivi (Latvian Rail)",
            model="Train Station Monitor",
            configuration_url="https://vivi.lv",
        )

    async def async_press(self) -> None:
        try:
            await self._manager.async_check_for_update(force=True)
        except Exception as err:
            raise HomeAssistantError(
                f"Unable to update Vivi train schedule: {err}"
            ) from err
