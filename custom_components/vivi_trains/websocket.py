"""Dashboard subscription for the live train map."""

from __future__ import annotations

import voluptuous as vol

from homeassistant.components import websocket_api

from .const import DOMAIN, SCHEDULE_MANAGER

_EMPTY_MAP = {"connected": False, "trains": []}


@websocket_api.websocket_command({
    vol.Required("type"): "vivi_trains/subscribe_trains",
})
@websocket_api.async_response
async def ws_subscribe_trains(hass, connection, msg) -> None:
    """Push the current train-map snapshot, then each later change."""
    manager = hass.data.get(DOMAIN, {}).get(SCHEDULE_MANAGER)
    realtime = getattr(manager, "realtime", None)

    def send(snapshot) -> None:
        connection.send_message(websocket_api.event_message(msg["id"], snapshot))

    if realtime is None:
        connection.send_result(msg["id"])
        send(_EMPTY_MAP)
        return

    connection.subscriptions[msg["id"]] = realtime.subscribe(send)
    connection.send_result(msg["id"])
    send(realtime.snapshot())


def async_register_commands(hass) -> None:
    """Register the map subscription once."""
    websocket_api.async_register_command(hass, ws_subscribe_trains)
