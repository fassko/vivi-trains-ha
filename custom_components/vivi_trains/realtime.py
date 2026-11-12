"""Live train positions and delays from the Vivi train map websocket."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable

from .const import REALTIME_WS_URL

_LOGGER = logging.getLogger(__name__)
_DEFAULT_COLOR = "#F8DB22"


def build_map_trains(data: object) -> list[dict[str, Any]]:
    """Return the drawable trains from one train-map snapshot."""
    _, map_trains = parse_backend_feed(data)
    return map_trains


def parse_backend_feed(data: object) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    """Split a back-end payload into a trip lookup and a map snapshot."""
    if not isinstance(data, list):
        return {}, []

    by_train: dict[str, dict[str, Any]] = {}
    map_trains: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw_value = item.get("returnValue")
        if not isinstance(raw_value, dict):
            continue

        train = str(raw_value.get("train") or "").strip()
        stops = _stops(raw_value.get("stopObjArray"))
        delay = _as_int(raw_value.get("arrivingTime")) or 0
        if train:
            by_train[train] = {
                "delay": delay,
                "finished": bool(raw_value.get("finished")),
                "current_index": _as_int(raw_value.get("currentStopIndex")),
                "stops": stops,
            }

        latlon = _latlon(raw_value.get("animatedCoord")) or _latlon(raw_value.get("position"))
        if latlon is None:
            continue
        next_stop = raw_value.get("nextStopObj")
        map_trains.append({
            "train": train,
            "name": str(item.get("name") or ""),
            "color": _color(_train_color(item)),
            "delay": delay,
            "next_stop": str(next_stop.get("title") or "") if isinstance(next_stop, dict) else "",
            "gps": bool(raw_value.get("isGpsActive")),
            "lat": latlon[0],
            "lon": latlon[1],
            "polyline": _polyline(item.get("stopCoordArray")),
        })
    return by_train, map_trains


def _stops(raw_stops: object) -> list[dict[str, Any]]:
    if not isinstance(raw_stops, list):
        return []
    stops: list[dict[str, Any]] = []
    for index, stop in enumerate(raw_stops):
        if not isinstance(stop, dict):
            continue
        stop_index = _as_int(stop.get("i"))
        stops.append({
            "title": str(stop.get("title") or ""),
            "index": index if stop_index is None else stop_index,
            "departure": str(stop.get("departure") or ""),
        })
    return stops


def _polyline(raw_points: object) -> list[list[float]]:
    if not isinstance(raw_points, list):
        return []
    points: list[list[float]] = []
    for pair in raw_points:
        latlon = _latlon(pair)
        if latlon is not None:
            points.append([latlon[0], latlon[1]])
    return points


def _train_color(item: dict[str, Any]) -> object:
    color = item.get("trainColor")
    if isinstance(color, dict):
        return color.get("color")
    return None


def _color(value: object) -> str:
    text = str(value or "").strip()
    if len(text) in (4, 7) and text.startswith("#"):
        hex_digits = text[1:]
        if all(char in "0123456789abcdefABCDEF" for char in hex_digits):
            return text
    return _DEFAULT_COLOR


def _latlon(value: object) -> tuple[float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        return None
    try:
        lat = float(value[0])
        lon = float(value[1])
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    return lat, lon


def _as_int(value: object) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        try:
            return int(float(value))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None


class ViviRealtimeClient:
    """Keep one train-map connection and fan updates out to stations and the map."""

    def __init__(self, hass, on_change: Callable[[], None] | None = None) -> None:
        self.hass = hass
        self._on_change = on_change
        self.connected = False
        self._trains: dict[str, dict[str, Any]] = {}
        self._map_trains: list[dict[str, Any]] = []
        self._subscribers: set[Callable[[dict[str, Any]], None]] = set()
        self._task: asyncio.Task | None = None
        self._stopped = False
        self._key: str | None = None
        self._announced_down = False

    def start(self) -> None:
        """Start the listener if it is not already running."""
        if self._task is not None and not self._task.done():
            return
        self._stopped = False
        self._task = self.hass.async_create_task(self._run())

    def stop(self) -> None:
        """Stop the listener and clear the cached snapshot."""
        self._stopped = True
        task = self._task
        self._task = None
        if task is not None and not task.done():
            task.cancel()
        self._replace(False, {}, [])

    def train(self, trip_id: str) -> dict[str, Any] | None:
        """Return the live record for a GTFS trip, if that train is in the feed."""
        return self._trains.get(str(trip_id))

    def snapshot(self) -> dict[str, Any]:
        """Return the snapshot pushed to map subscribers."""
        return {"connected": self.connected, "trains": self._map_trains}

    def subscribe(self, callback: Callable[[dict[str, Any]], None]) -> Callable[[], None]:
        """Register a map listener and return an unsubscribe callable."""
        self._subscribers.add(callback)

        def _unsubscribe() -> None:
            self._subscribers.discard(callback)

        return _unsubscribe

    async def _run(self) -> None:
        from aiohttp import WSMsgType

        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        backoff = 3
        while not self._stopped:
            try:
                session = async_get_clientsession(self.hass)
                async with session.ws_connect(REALTIME_WS_URL, heartbeat=30) as websocket:
                    async for message in websocket:
                        if self._stopped:
                            break
                        if message.type == WSMsgType.TEXT:
                            self._handle_text(message.data)
                        elif message.type in (
                            WSMsgType.CLOSE,
                            WSMsgType.CLOSED,
                            WSMsgType.ERROR,
                        ):
                            break
            except asyncio.CancelledError:
                raise
            except Exception:
                _LOGGER.debug("Vivi live train feed disconnected", exc_info=True)
            if self._stopped:
                break
            self._replace(False, {}, [])
            if not self._announced_down:
                _LOGGER.warning("Vivi live train feed unavailable; using the timetable")
                self._announced_down = True
            try:
                await asyncio.sleep(backoff)
            except asyncio.CancelledError:
                raise
            backoff = min(backoff * 2, 60)

    def _handle_text(self, raw: str) -> None:
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict) or payload.get("type") != "back-end":
            return
        trains, map_trains = parse_backend_feed(payload.get("data"))
        if not self.connected:
            _LOGGER.info("Connected to Vivi live train feed")
        self._announced_down = False
        self._replace(True, trains, map_trains)

    def _replace(
        self,
        connected: bool,
        trains: dict[str, dict[str, Any]],
        map_trains: list[dict[str, Any]],
    ) -> None:
        key = json.dumps(
            {"connected": connected, "trains": trains, "map": map_trains},
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if key == self._key:
            return
        self.connected = connected
        self._trains = trains
        self._map_trains = map_trains
        self._key = key
        snapshot = self.snapshot()
        for callback in tuple(self._subscribers):
            try:
                callback(snapshot)
            except Exception:
                _LOGGER.exception("Vivi map subscriber failed")
        if self._on_change is not None and not self._stopped:
            self._on_change()
