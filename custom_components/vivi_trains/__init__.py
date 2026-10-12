"""The Vivi Trains integration."""
from __future__ import annotations

import logging
import asyncio
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, SCHEDULE_MANAGER, SCHEDULE_MANAGER_LOCK
from .coordinator import ViviTrainsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "button"]
FRONTEND_PATH = Path(__file__).parent / "frontend"
FRONTEND_URL = f"/{DOMAIN}_frontend"
STATIC_REGISTERED = "static_registered"


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up shared Vivi Trains resources."""
    await _async_register_frontend_path(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Vivi Trains from a config entry."""
    await _async_register_frontend_path(hass)
    domain_data = hass.data.setdefault(DOMAIN, {})
    manager_lock = domain_data.setdefault(SCHEDULE_MANAGER_LOCK, asyncio.Lock())
    async with manager_lock:
        manager = domain_data.get(SCHEDULE_MANAGER)
        if manager is None:
            from .schedule import ViviScheduleManager

            manager = ViviScheduleManager(hass)
            await manager.async_initialize()
            domain_data[SCHEDULE_MANAGER] = manager
        coordinator = ViviTrainsCoordinator(hass, entry, manager)
        manager.add_coordinator(coordinator)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        async with manager_lock:
            manager.remove_coordinator(coordinator)
            if not manager.has_coordinators:
                manager.stop()
                domain_data.pop(SCHEDULE_MANAGER, None)
        raise ConfigEntryNotReady(f"Unable to load Vivi schedule data: {err}") from err

    domain_data[entry.entry_id] = coordinator
    manager.start()

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        domain_data = hass.data[DOMAIN]
        coordinator = domain_data.pop(entry.entry_id, None)
        manager = domain_data.get(SCHEDULE_MANAGER)
        if coordinator is not None and manager is not None:
            manager.remove_coordinator(coordinator)
            if not manager.has_coordinators:
                manager.stop()
                domain_data.pop(SCHEDULE_MANAGER, None)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)


async def _async_register_frontend_path(hass: HomeAssistant) -> None:
    """Register the Lovelace card static path once."""
    domain_data = hass.data.setdefault(DOMAIN, {})

    if domain_data.get(STATIC_REGISTERED):
        return

    await hass.http.async_register_static_paths(
        [StaticPathConfig(FRONTEND_URL, str(FRONTEND_PATH), True)]
    )
    domain_data[STATIC_REGISTERED] = True
