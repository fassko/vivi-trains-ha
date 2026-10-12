"""Sensor platform for Vivi Trains."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_DESTINATION,
    ATTR_MINUTES_UNTIL,
    ATTR_NEXT_DEPARTURES,
    ATTR_ROUTE_COLOR,
    ATTR_SERVICE_DAYS,
    CONF_STATION_ID,
    CONF_STATION_NAME,
    DOMAIN,
)
from .coordinator import ViviTrainsCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensors from a config entry."""
    coordinator: ViviTrainsCoordinator = hass.data[DOMAIN][entry.entry_id]
    station_name = entry.data.get(CONF_STATION_NAME, entry.data[CONF_STATION_ID])

    async_add_entities(
        [
            ViviNextDepartureSensor(coordinator, entry, station_name),
        ]
    )


class ViviNextDepartureSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing the next departure from a station."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ViviTrainsCoordinator,
        entry: ConfigEntry,
        station_name: str,
    ) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self._entry = entry
        self._station_name = station_name
        self._station_id = entry.data[CONF_STATION_ID]
        self._attr_unique_id = f"vivi_{self._station_id}_next_departure"
        self._attr_name = "Next Departure"
        self._attr_icon = "mdi:train"

    @property
    def device_info(self) -> DeviceInfo:
        """Return device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._station_id)},
            name=f"Vivi — {self._station_name}",
            manufacturer="Vivi (Latvian Rail)",
            model="Train Station Monitor",
            configuration_url="https://vivi.lv",
        )

    @property
    def native_value(self) -> str | None:
        """Return the next departure time as state."""
        if not self.coordinator.data:
            return None
        next_dep = self.coordinator.data.get("next_departure")
        if not next_dep:
            return None
        return next_dep.get("departure_time")

    @property
    def native_unit_of_measurement(self) -> str | None:
        """No unit — we show HH:MM time."""
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed attributes."""
        if not self.coordinator.data:
            return {}

        data = self.coordinator.data
        next_dep = data.get("next_departure") or {}
        departures = data.get("departures", [])

        return {
            ATTR_MINUTES_UNTIL: next_dep.get("minutes_until"),
            ATTR_DESTINATION: next_dep.get("destination"),
            ATTR_ROUTE_COLOR: next_dep.get("route_color"),
            ATTR_SERVICE_DAYS: next_dep.get("service_days"),
            "departure_datetime": next_dep.get("departure_datetime"),
            "station_name": data.get("station_name"),
            "station_id": self._station_id,
            ATTR_NEXT_DEPARTURES: [
                {
                    "time": d.get("departure_time"),
                    "minutes_until": d.get("minutes_until"),
                    "destination": d.get("destination"),
                    "route_color": d.get("route_color"),
                    "service_days": d.get("service_days"),
                }
                for d in departures
            ],
            "updated_at": data.get("updated_at"),
            "schedule_checked_at": data.get("schedule_checked_at"),
            "schedule_updated_at": data.get("schedule_updated_at"),
        }

    @property
    def available(self) -> bool:
        """Return True if coordinator has data."""
        return self.coordinator.last_update_success and self.coordinator.data is not None
