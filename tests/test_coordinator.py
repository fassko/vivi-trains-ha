"""Unit tests for Vivi Trains schedule calculations."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone


def _install_homeassistant_stubs() -> None:
    """Install minimal Home Assistant modules needed to import the integration."""
    if "homeassistant" in sys.modules:
        return

    homeassistant = types.ModuleType("homeassistant")
    components = types.ModuleType("homeassistant.components")
    http = types.ModuleType("homeassistant.components.http")
    config_entries = types.ModuleType("homeassistant.config_entries")
    core = types.ModuleType("homeassistant.core")
    exceptions = types.ModuleType("homeassistant.exceptions")
    helpers = types.ModuleType("homeassistant.helpers")
    update_coordinator = types.ModuleType("homeassistant.helpers.update_coordinator")
    util = types.ModuleType("homeassistant.util")
    dt = types.ModuleType("homeassistant.util.dt")

    class StaticPathConfig:
        def __init__(self, url_path: str, path: str, cache_headers: bool) -> None:
            self.url_path = url_path
            self.path = path
            self.cache_headers = cache_headers

    class ConfigEntry:
        pass

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs) -> None:
            super().__init_subclass__()

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

    class OptionsFlow:
        @property
        def config_entry(self):
            return self._config_entry

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    class HomeAssistant:
        pass

    class ConfigEntryNotReady(Exception):
        pass

    class DataUpdateCoordinator:
        def __init__(self, *args, **kwargs) -> None:
            pass

    class UpdateFailed(Exception):
        pass

    http.StaticPathConfig = StaticPathConfig
    config_entries.ConfigEntry = ConfigEntry
    config_entries.ConfigFlow = ConfigFlow
    config_entries.ConfigFlowResult = dict
    config_entries.OptionsFlow = OptionsFlow
    core.HomeAssistant = HomeAssistant
    core.callback = lambda func: func
    exceptions.ConfigEntryNotReady = ConfigEntryNotReady
    update_coordinator.DataUpdateCoordinator = DataUpdateCoordinator
    update_coordinator.UpdateFailed = UpdateFailed
    dt.now = lambda: datetime.now(timezone.utc)

    sys.modules.update(
        {
            "homeassistant": homeassistant,
            "homeassistant.components": components,
            "homeassistant.components.http": http,
            "homeassistant.config_entries": config_entries,
            "homeassistant.core": core,
            "homeassistant.exceptions": exceptions,
            "homeassistant.helpers": helpers,
            "homeassistant.helpers.update_coordinator": update_coordinator,
            "homeassistant.util": util,
            "homeassistant.util.dt": dt,
        }
    )


_install_homeassistant_stubs()

from custom_components.vivi_trains.coordinator import (  # noqa: E402
    ViviTrainsCoordinator,
    _minutes_from_midnight,
    _parse_time,
)


def _trip(
    departure: str,
    *,
    trip_id: str = "trip",
    days: list[int] | None = None,
    start: str = "20260101",
    end: str = "20261231",
    dates: list[str] | None = None,
    removed_dates: list[str] | None = None,
    headsign: str = "Riga",
) -> dict:
    return {
        "trip_id": trip_id,
        "dep": departure,
        "headsign": headsign,
        "color": "#F8DB22",
        "svc": {
            "days": days or [1, 1, 1, 1, 1, 1, 1],
            "start": start,
            "end": end,
        },
        "dates": dates or [],
        "removed_dates": removed_dates or [],
    }


def _coordinator_with_schedule(schedule: list[dict]) -> ViviTrainsCoordinator:
    coordinator = ViviTrainsCoordinator.__new__(ViviTrainsCoordinator)
    coordinator._schedule = schedule
    coordinator._all_stops = {"station": {"name": "Station"}}
    coordinator._loaded = True
    coordinator.station_id = "station"
    return coordinator


class TimeParsingTest(unittest.TestCase):
    def test_parse_gtfs_overnight_time(self) -> None:
        self.assertEqual(_parse_time("25:07"), (25, 7))
        self.assertEqual(_minutes_from_midnight("25:07"), 1507)


class ServiceCalendarTest(unittest.TestCase):
    def test_weekday_service_is_active_only_on_matching_day(self) -> None:
        coordinator = _coordinator_with_schedule([])
        monday = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        saturday = monday + timedelta(days=5)
        trip = _trip("12:30", days=[1, 1, 1, 1, 1, 0, 0])

        self.assertTrue(coordinator._is_service_active(trip, monday))
        self.assertFalse(coordinator._is_service_active(trip, saturday))

    def test_removed_date_overrides_regular_calendar(self) -> None:
        coordinator = _coordinator_with_schedule([])
        date = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        trip = _trip("12:30", removed_dates=["20260817"])

        self.assertFalse(coordinator._is_service_active(trip, date))

    def test_added_date_overrides_calendar_gap(self) -> None:
        coordinator = _coordinator_with_schedule([])
        date = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)
        trip = _trip(
            "12:30",
            days=[0, 0, 0, 0, 0, 0, 0],
            start="20260101",
            end="20260131",
            dates=["20260817"],
        )

        self.assertTrue(coordinator._is_service_active(trip, date))


class DepartureSelectionTest(unittest.TestCase):
    def test_returns_next_departures_sorted_and_limited(self) -> None:
        coordinator = _coordinator_with_schedule(
            [
                _trip("15:00", trip_id="late"),
                _trip("12:05", trip_id="next"),
                _trip("11:55", trip_id="departed"),
                _trip("12:30", trip_id="second"),
            ]
        )
        now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

        departures = coordinator._get_next_departures(now, 2)

        self.assertEqual([d["trip_id"] for d in departures], ["next", "second"])
        self.assertEqual([d["minutes_until"] for d in departures], [5, 30])

    def test_keeps_yesterday_service_overnight_departure_after_midnight(self) -> None:
        coordinator = _coordinator_with_schedule(
            [
                _trip("24:20", trip_id="overnight"),
                _trip("05:00", trip_id="morning"),
            ]
        )
        now = datetime(2026, 8, 18, 0, 10, tzinfo=timezone.utc)

        departures = coordinator._get_next_departures(now, 2)

        self.assertEqual(departures[0]["trip_id"], "overnight")
        self.assertEqual(departures[0]["departure_time"], "24:20")
        self.assertEqual(departures[0]["minutes_until"], 10)

    def test_ignores_yesterday_overnight_departure_that_already_left(self) -> None:
        coordinator = _coordinator_with_schedule(
            [
                _trip("24:20", trip_id="overnight"),
                _trip("05:00", trip_id="morning"),
            ]
        )
        now = datetime(2026, 8, 18, 0, 30, tzinfo=timezone.utc)

        departures = coordinator._get_next_departures(now, 1)

        self.assertEqual(departures[0]["trip_id"], "morning")


class ScheduleDataTest(unittest.TestCase):
    def test_bundled_schedule_contains_station_list_and_departures(self) -> None:
        data = ViviTrainsCoordinator.load_full_schedule()

        self.assertGreater(len(data["station_list"]), 0)
        self.assertGreater(len(data["stops"]), 0)
        self.assertGreater(len(data["schedule"]), 0)


if __name__ == "__main__":
    unittest.main()
