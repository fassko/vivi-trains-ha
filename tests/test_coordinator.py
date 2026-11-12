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
    dt.utcnow = lambda: datetime.now(timezone.utc)
    dt.parse_datetime = datetime.fromisoformat

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
    _normalize_departures_count,
    _parse_time,
)
from custom_components.vivi_trains.realtime import build_map_trains  # noqa: E402


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

    def test_after_last_train_shows_the_next_day(self) -> None:
        coordinator = _coordinator_with_schedule(
            [
                _trip("23:40", trip_id="last"),
                _trip("06:10", trip_id="morning"),
            ]
        )
        now = datetime(2026, 8, 17, 23, 50, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["trip_id"], "morning")
        self.assertEqual(departure["clock_time"], "06:10")
        self.assertEqual(departure["day_label"], "Tomorrow")
        self.assertNotEqual(departure["trip_id"], "last")

    def test_searches_a_week_ahead_for_the_next_operating_day(self) -> None:
        coordinator = _coordinator_with_schedule(
            [_trip("08:00", trip_id="monday", days=[1, 0, 0, 0, 0, 0, 0])]
        )
        tuesday = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(tuesday, 1)[0]

        self.assertEqual(departure["clock_time"], "08:00")
        self.assertEqual(departure["day_label"], "Mon")
        self.assertTrue(departure["departure_datetime"].startswith("2026-08-24"))

    def test_overnight_gtfs_time_is_shown_as_the_next_day_clock(self) -> None:
        data = ViviTrainsCoordinator.load_full_schedule()
        coordinator = _coordinator_with_schedule(data["schedule"]["230"])
        now = datetime(2026, 11, 12, 23, 40, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["departure_time"], "24:31")
        self.assertEqual(departure["clock_time"], "00:31")
        self.assertEqual(departure["day_label"], "Tomorrow")

    def test_after_carnikava_overnight_train_shows_the_next_morning(self) -> None:
        data = ViviTrainsCoordinator.load_full_schedule()
        coordinator = _coordinator_with_schedule(data["schedule"]["230"])
        now = datetime(2026, 11, 13, 0, 40, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["trip_id"], "6101")
        self.assertEqual(departure["clock_time"], "05:07")
        self.assertNotEqual(departure["trip_id"], "6170")


class LiveDelayTest(unittest.TestCase):
    def test_adds_delay_while_the_train_has_not_reached_the_station(self) -> None:
        coordinator = _coordinator_with_schedule([_trip("12:05", trip_id="6119")])
        coordinator._live_trains = {
            "6119": _live(delay=3, current_index=2, stop_index=4),
        }
        now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["delay_minutes"], 3)
        self.assertEqual(departure["minutes_until"], 8)
        self.assertEqual(departure["clock_time"], "12:08")

    def test_keeps_a_late_train_until_its_predicted_time(self) -> None:
        coordinator = _coordinator_with_schedule([_trip("12:05", trip_id="6119")])
        coordinator._live_trains = {
            "6119": _live(delay=3, current_index=2, stop_index=4),
        }
        now = datetime(2026, 8, 17, 12, 6, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["minutes_until"], 2)
        self.assertEqual(departure["clock_time"], "12:08")

    def test_omits_a_train_that_has_passed_the_station(self) -> None:
        coordinator = _coordinator_with_schedule(
            [_trip("12:05", trip_id="6119", end="20260817")]
        )
        coordinator._live_trains = {
            "6119": _live(delay=0, current_index=10, stop_index=4),
        }
        now = datetime(2026, 8, 17, 11, 50, tzinfo=timezone.utc)

        self.assertEqual(coordinator._get_next_departures(now, 1), [])

    def test_live_pass_does_not_remove_the_same_train_on_a_later_day(self) -> None:
        coordinator = _coordinator_with_schedule([_trip("12:05", trip_id="6119")])
        coordinator._live_trains = {
            "6119": _live(delay=0, current_index=10, stop_index=4),
        }
        now = datetime(2026, 8, 17, 11, 0, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertTrue(departure["departure_datetime"].startswith("2026-08-18"))
        self.assertEqual(departure["delay_minutes"], 0)

    def test_without_a_live_snapshot_uses_the_timetable(self) -> None:
        coordinator = _coordinator_with_schedule([_trip("12:05", trip_id="6119")])
        now = datetime(2026, 8, 17, 12, 0, tzinfo=timezone.utc)

        departure = coordinator._get_next_departures(now, 1)[0]

        self.assertEqual(departure["delay_minutes"], 0)
        self.assertEqual(departure["minutes_until"], 5)
        self.assertEqual(departure["clock_time"], "12:05")


def _live(*, delay: int, current_index: int, stop_index: int) -> dict:
    return {
        "delay": delay,
        "finished": False,
        "current_index": current_index,
        "stops": [{
            "title": "Station",
            "index": stop_index,
            "departure": "2026-08-17 12:05:00",
        }],
    }


class MapSnapshotTest(unittest.TestCase):
    def test_keeps_position_color_delay_and_polyline(self) -> None:
        trains = build_map_trains([
            {
                "name": "Skulte - Rīga",
                "trainColor": {"color": "#B388FF"},
                "stopCoordArray": [["56.9", "24.1"], [56.7, 24.6]],
                "returnValue": {
                    "train": "6119",
                    "arrivingTime": 4,
                    "isGpsActive": True,
                    "animatedCoord": [56.7, 24.6],
                    "nextStopObj": {"title": "Carnikava"},
                },
            },
            {
                "name": "No position",
                "returnValue": {"train": "1", "arrivingTime": 1},
            },
        ])

        self.assertEqual(len(trains), 1)
        self.assertEqual(trains[0]["train"], "6119")
        self.assertEqual(trains[0]["lat"], 56.7)
        self.assertEqual(trains[0]["lon"], 24.6)
        self.assertEqual(trains[0]["color"], "#B388FF")
        self.assertEqual(trains[0]["delay"], 4)
        self.assertEqual(trains[0]["next_stop"], "Carnikava")
        self.assertEqual(trains[0]["polyline"], [[56.9, 24.1], [56.7, 24.6]])
        self.assertTrue(trains[0]["gps"])


class DeparturesCountTest(unittest.TestCase):
    def test_normalizes_string_count_from_options(self) -> None:
        self.assertEqual(_normalize_departures_count("10"), 10)

    def test_normalizes_invalid_count_to_default(self) -> None:
        self.assertEqual(_normalize_departures_count("many"), 5)

    def test_clamps_count_to_supported_range(self) -> None:
        self.assertEqual(_normalize_departures_count("0"), 1)
        self.assertEqual(_normalize_departures_count("99"), 20)

    def test_coordinator_accepts_string_count_option(self) -> None:
        entry = types.SimpleNamespace(
            data={"station_id": "station", "departures_count": 5},
            options={"departures_count": "12"},
        )

        coordinator = ViviTrainsCoordinator(None, entry)

        self.assertEqual(coordinator.departures_count, 12)


class ScheduleDataTest(unittest.TestCase):
    def test_bundled_schedule_contains_station_list_and_departures(self) -> None:
        data = ViviTrainsCoordinator.load_full_schedule()

        self.assertGreater(len(data["station_list"]), 0)
        self.assertGreater(len(data["stops"]), 0)
        self.assertGreater(len(data["schedule"]), 0)


if __name__ == "__main__":
    unittest.main()
