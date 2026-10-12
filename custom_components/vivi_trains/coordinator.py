"""DataUpdateCoordinator for Vivi Trains."""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_DEPARTURES_COUNT,
    CONF_STATION_ID,
    DAY_NAMES,
    DEFAULT_DEPARTURES_COUNT,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MAX_DEPARTURES_COUNT,
    SCHEDULE_DATA_FILE,
)

_LOGGER = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .schedule import ViviScheduleManager


def _parse_time(t: str) -> tuple[int, int]:
    """Parse 'HH:MM' or '24:MM' (overnight) into (hour, minute)."""
    parts = t.split(":")
    return int(parts[0]), int(parts[1])


def _minutes_from_midnight(t: str) -> int:
    h, m = _parse_time(t)
    return h * 60 + m


def _normalize_departures_count(value: Any) -> int:
    """Return a safe departures count from config entry data/options."""
    try:
        count = int(value)
    except (TypeError, ValueError):
        return DEFAULT_DEPARTURES_COUNT

    return min(max(count, 1), MAX_DEPARTURES_COUNT)


class ViviTrainsCoordinator(DataUpdateCoordinator):
    """Coordinator that loads the Vivi schedule and computes next departures."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry,
        schedule_manager: ViviScheduleManager | None = None,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=DEFAULT_SCAN_INTERVAL),
        )
        self.entry = entry
        self.station_id: str = entry.data[CONF_STATION_ID]
        self.departures_count = _normalize_departures_count(
            entry.options.get(
                CONF_DEPARTURES_COUNT,
                entry.data.get(CONF_DEPARTURES_COUNT, DEFAULT_DEPARTURES_COUNT),
            )
        )
        self._schedule: list[dict] = []
        self._all_stops: dict[str, dict] = {}
        self._loaded = False
        self.schedule_manager = schedule_manager

    # ------------------------------------------------------------------
    # Public helpers (used by sensor and config_flow)
    # ------------------------------------------------------------------

    @staticmethod
    def load_full_schedule() -> dict:
        """Load the bundled schedule JSON. Returns full dict."""
        data_file = os.path.join(os.path.dirname(__file__), SCHEDULE_DATA_FILE)
        with open(data_file, encoding="utf-8") as fh:
            return json.load(fh)

    @staticmethod
    def get_station_list() -> list[dict]:
        """Return sorted list of {id, name} for all stations."""
        data = ViviTrainsCoordinator.load_full_schedule()
        return sorted(data.get("station_list", []), key=lambda s: s["name"])

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Load schedule data from disk (once)."""
        if self._loaded:
            return
        data = (
            self.schedule_manager.data
            if self.schedule_manager is not None
            else self.load_full_schedule()
        )
        self.replace_schedule(data)

    def replace_schedule(self, data: dict) -> None:
        """Make a validated schedule available without reloading the entry."""
        self._all_stops = data.get("stops", {})
        self._schedule = data.get("schedule", {}).get(self.station_id, [])
        self._loaded = True

    def _is_service_active(self, trip: dict, service_date: datetime) -> bool:
        """Return True if this trip runs on the given date."""
        svc = trip.get("svc", {})
        date_str = service_date.strftime("%Y%m%d")

        # Check specific date additions (exception_type=1)
        added_dates = trip.get("dates", [])
        if date_str in added_dates:
            return True

        # Check removed dates (exception_type=2)
        removed_dates = trip.get("removed_dates", [])
        if date_str in removed_dates:
            return False

        # Check calendar range
        start = svc.get("start", "19700101")
        end = svc.get("end", "99991231")
        if not (start <= date_str <= end):
            return False

        # Check day-of-week (0=Mon … 6=Sun)
        days = svc.get("days", [0, 0, 0, 0, 0, 0, 0])
        dow = service_date.weekday()  # 0=Monday
        return bool(days[dow])

    def _get_next_departures(self, now: datetime, count: int) -> list[dict]:
        """Return the next `count` departures from self.station_id after `now`."""
        self._ensure_loaded()

        results: list[dict] = []
        service_midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        # GTFS times may exceed 24:00. Include yesterday's service day so
        # 24:xx/25:xx departures just after midnight are still considered.
        for service_day_offset in range(-1, 3):
            check_date = service_midnight + timedelta(days=service_day_offset)

            for trip in self._schedule:
                dep_str = trip.get("dep", "")
                if not dep_str:
                    continue

                dep_minutes = _minutes_from_midnight(dep_str)
                dep_dt = check_date + timedelta(minutes=dep_minutes)

                if not self._is_service_active(trip, check_date):
                    continue

                if dep_dt <= now:
                    continue  # already departed

                minutes_until = int((dep_dt - now).total_seconds() // 60)

                results.append({
                    "departure_time": dep_str,
                    "departure_datetime": dep_dt.isoformat(),
                    "minutes_until": minutes_until,
                    "destination": trip.get("headsign", ""),
                    "trip_id": trip.get("trip_id", ""),
                    "route_color": trip.get("color", "#F8DB22"),
                    "service_days": self._format_days(trip.get("svc", {}).get("days", [])),
                })

            if len(results) >= count:
                break

        return sorted(results, key=lambda x: x["minutes_until"])[:count]

    @staticmethod
    def _format_days(days: list[int]) -> str:
        """Format days array to a readable string like 'Mon–Fri'."""
        if not days or len(days) < 7:
            return ""
        active = [DAY_NAMES[i] for i, d in enumerate(days) if d]
        if len(active) == 7:
            return "Daily"
        if active == ["Mon", "Tue", "Wed", "Thu", "Fri"]:
            return "Mon–Fri"
        if active == ["Sat", "Sun"]:
            return "Sat–Sun"
        if active == ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]:
            return "Mon–Sat"
        return ", ".join(active)

    # ------------------------------------------------------------------
    # DataUpdateCoordinator hook
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch new departure data."""
        try:
            # Load schedule in executor to avoid blocking event loop
            await self.hass.async_add_executor_job(self._ensure_loaded)

            now = dt_util.now()

            departures = await self.hass.async_add_executor_job(
                self._get_next_departures, now, self.departures_count
            )

            station_info = self._all_stops.get(self.station_id, {})

            return {
                "station_id": self.station_id,
                "station_name": station_info.get("name", self.station_id),
                "departures": departures,
                "next_departure": departures[0] if departures else None,
                "updated_at": dt_util.now().isoformat(),
                "schedule_checked_at": (
                    self.schedule_manager.checked_at
                    if self.schedule_manager else None
                ),
                "schedule_updated_at": (
                    self.schedule_manager.updated_at
                    if self.schedule_manager else None
                ),
            }
        except FileNotFoundError as err:
            raise UpdateFailed(f"Schedule data file not found: {err}") from err
        except Exception as err:
            raise UpdateFailed(f"Error computing departures: {err}") from err
