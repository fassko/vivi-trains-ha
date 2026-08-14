"""The Vivi Trains integration."""
from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .coordinator import ViviTrainsCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]
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

    coordinator = ViviTrainsCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady(f"Unable to load Vivi schedule data: {err}") from err

    domain_data[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)

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
