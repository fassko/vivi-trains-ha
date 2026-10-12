"""Shared, persistent Vivi schedule updates for all configured stations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import timedelta

from aiohttp import ClientTimeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import DOMAIN, GTFS_URL, SCHEDULE_CHECK_INTERVAL_DAYS
from .coordinator import ViviTrainsCoordinator
from .gtfs import build_schedule

_LOGGER = logging.getLogger(__name__)
_MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


def _schedule_checksum(data: dict) -> str:
    """Compare timetable content, ignoring ZIP metadata and unrelated GTFS files."""
    content = json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class ViviScheduleManager:
    """Download once per week and share updates between station coordinators."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._store = Store(hass, 1, f"{DOMAIN}.schedule")
        self._lock = asyncio.Lock()
        self._coordinators: set[ViviTrainsCoordinator] = set()
        self._unsub = None
        self._startup_task: asyncio.Task | None = None
        self.data: dict = {}
        self.checksum: str | None = None
        self.checked_at: str | None = None
        self.updated_at: str | None = None

    async def async_initialize(self) -> None:
        """Load the last downloaded schedule, falling back to bundled data."""
        saved = await self._store.async_load()
        if isinstance(saved, dict) and self._valid_data(saved.get("schedule")):
            self.data = saved["schedule"]
            self.checksum = saved.get("checksum")
            self.checked_at = saved.get("checked_at")
            self.updated_at = saved.get("updated_at")
        else:
            self.data = await self.hass.async_add_executor_job(
                ViviTrainsCoordinator.load_full_schedule
            )
        if self.checksum is None:
            self.checksum = await self.hass.async_add_executor_job(
                _schedule_checksum, self.data
            )

    @staticmethod
    def _valid_data(data: object) -> bool:
        return (
            isinstance(data, dict)
            and isinstance(data.get("stops"), dict)
            and bool(data["stops"])
            and isinstance(data.get("station_list"), list)
            and bool(data["station_list"])
            and isinstance(data.get("schedule"), dict)
            and bool(data["schedule"])
        )

    def add_coordinator(self, coordinator: ViviTrainsCoordinator) -> None:
        self._coordinators.add(coordinator)

    def remove_coordinator(self, coordinator: ViviTrainsCoordinator) -> None:
        self._coordinators.discard(coordinator)

    @property
    def has_coordinators(self) -> bool:
        return bool(self._coordinators)

    def _check_due(self) -> bool:
        if not self.checked_at:
            return True
        try:
            checked = dt_util.parse_datetime(self.checked_at)
            if checked is None:
                return True
            return dt_util.utcnow() - checked >= timedelta(
                days=SCHEDULE_CHECK_INTERVAL_DAYS
            )
        except (TypeError, ValueError):
            return True

    def start(self) -> None:
        """Start a daily due check; fetch on startup when a week has passed."""
        if self._unsub is not None:
            return
        self._unsub = async_track_time_interval(
            self.hass, self._async_periodic_check, timedelta(days=1)
        )
        if self._check_due():
            self._startup_task = self.hass.async_create_task(
                self._async_periodic_check(dt_util.now())
            )

    def stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        if self._startup_task is not None and not self._startup_task.done():
            self._startup_task.cancel()

    async def _async_periodic_check(self, _now) -> None:
        try:
            await self.async_check_for_update()
        except Exception:
            _LOGGER.exception("Unable to check Vivi train schedule")

    async def async_check_for_update(self, *, force: bool = False) -> bool:
        """Check Vivi's feed, persist changes, and refresh all stations."""
        async with self._lock:
            if not force and not self._check_due():
                return False

            session = async_get_clientsession(self.hass)
            async with session.get(
                GTFS_URL, timeout=ClientTimeout(total=45)
            ) as response:
                response.raise_for_status()
                archive_data = bytearray()
                async for chunk in response.content.iter_chunked(64 * 1024):
                    archive_data.extend(chunk)
                    if len(archive_data) > _MAX_ARCHIVE_BYTES:
                        raise ValueError("Vivi GTFS archive exceeds 10 MB")
            archive = bytes(archive_data)

            new_data = await self.hass.async_add_executor_job(build_schedule, archive)
            if not self._valid_data(new_data):
                raise ValueError("Vivi GTFS feed has no usable schedule")
            checksum = await self.hass.async_add_executor_job(
                _schedule_checksum, new_data
            )
            changed = checksum != self.checksum
            if changed:
                today = dt_util.now().strftime("%Y%m%d")
                service_dates = [
                    date
                    for departures in new_data["schedule"].values()
                    for trip in departures
                    for date in (trip["svc"]["end"], *trip["dates"])
                    if date
                ]
                if not service_dates or max(service_dates) < today:
                    raise ValueError("Vivi GTFS feed has no current service")
            else:
                new_data = self.data

            checked_at = dt_util.utcnow().isoformat()
            updated_at = checked_at if changed else self.updated_at
            await self._store.async_save({
                "schedule": new_data,
                "checksum": checksum,
                "checked_at": checked_at,
                "updated_at": updated_at,
            })

            self.data = new_data
            self.checksum = checksum
            self.checked_at = checked_at
            self.updated_at = updated_at
            if changed:
                for coordinator in tuple(self._coordinators):
                    coordinator.replace_schedule(new_data)
                await asyncio.gather(
                    *(coordinator.async_request_refresh()
                      for coordinator in tuple(self._coordinators))
                )
                _LOGGER.info("Updated Vivi train schedule from GTFS feed")
            else:
                _LOGGER.debug("Vivi train schedule is already current")
            return changed
