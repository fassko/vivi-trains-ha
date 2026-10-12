"""Tests for GTFS conversion and shared schedule replacement."""

from __future__ import annotations

import io
import sys
import types
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from test_coordinator import _install_homeassistant_stubs

_install_homeassistant_stubs()

if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientTimeout = lambda **kwargs: kwargs
    sys.modules["aiohttp"] = aiohttp

aiohttp_client = types.ModuleType("homeassistant.helpers.aiohttp_client")
aiohttp_client.async_get_clientsession = lambda hass: None
event = types.ModuleType("homeassistant.helpers.event")
event.async_track_time_interval = lambda *args: lambda: None
storage = types.ModuleType("homeassistant.helpers.storage")


class FakeStore:
    def __init__(self, *args) -> None:
        self.saved = None

    async def async_load(self):
        return self.saved

    async def async_save(self, data):
        self.saved = data


storage.Store = FakeStore
sys.modules["homeassistant.helpers.aiohttp_client"] = aiohttp_client
sys.modules["homeassistant.helpers.event"] = event
sys.modules["homeassistant.helpers.storage"] = storage

from custom_components.vivi_trains.gtfs import build_schedule  # noqa: E402
from custom_components.vivi_trains.schedule import ViviScheduleManager  # noqa: E402


def _small_gtfs() -> bytes:
    files = {
        "stops.txt": "stop_id,stop_name,stop_lat,stop_lon\n1,Rīga,56.9,24.1\n2,Ogre,56.8,24.6\n",
        "routes.txt": "route_id,route_color\nr,B388FF\n",
        "calendar.txt": "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\ns,1,1,1,1,1,0,0,20260101,20991231\n",
        "calendar_dates.txt": "service_id,date,exception_type\ns,20261012,2\ns,20261017,1\n",
        "trips.txt": "trip_id,route_id,service_id,trip_headsign\nt,r,s,Rīga - Ogre\n",
        "stop_times.txt": "trip_id,stop_id,departure_time\nt,1,24:05:00\nt,2,24:35:00\n",
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()


class GTFSConversionTest(unittest.TestCase):
    def test_converts_calendar_exceptions_and_overnight_times(self) -> None:
        data = build_schedule(_small_gtfs())
        departure = data["schedule"]["1"][0]
        self.assertEqual(departure["dep"], "24:05")
        self.assertEqual(departure["dates"], ["20261017"])
        self.assertEqual(departure["removed_dates"], ["20261012"])
        self.assertEqual(departure["color"], "#B388FF")

    def test_rejects_missing_trip(self) -> None:
        archive = _small_gtfs()
        with zipfile.ZipFile(io.BytesIO(archive)) as source:
            files = {name: source.read(name) for name in source.namelist()}
        files["trips.txt"] = files["trips.txt"].replace(b"t,r,s", b"x,r,s")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as source:
            for name, content in files.items():
                source.writestr(name, content)
        with self.assertRaises(ValueError):
            build_schedule(buffer.getvalue())


class FakeResponse:
    def __init__(self, data: bytes) -> None:
        self.content = self
        self.data = data

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def raise_for_status(self):
        pass

    async def iter_chunked(self, size):
        for offset in range(0, len(self.data), 11):
            yield self.data[offset:offset + 11]


class FakeSession:
    def __init__(self, data: bytes) -> None:
        self.data = data
        self.requests = 0

    def get(self, *args, **kwargs):
        self.requests += 1
        return FakeResponse(self.data)


class FakeCoordinator:
    def __init__(self) -> None:
        self.data = None
        self.refreshes = 0

    def replace_schedule(self, data):
        self.data = data

    async def async_request_refresh(self):
        self.refreshes += 1


class ScheduleManagerTest(unittest.IsolatedAsyncioTestCase):
    async def test_weekly_check_is_due_only_after_seven_days(self):
        manager = ViviScheduleManager(types.SimpleNamespace())
        manager.checked_at = datetime.now(timezone.utc).isoformat()
        self.assertFalse(manager._check_due())
        manager.checked_at = (
            datetime.now(timezone.utc) - timedelta(days=8)
        ).isoformat()
        self.assertTrue(manager._check_due())

    async def test_changed_feed_refreshes_all_stations_and_unchanged_feed_does_not(self):
        async def executor(func, *args):
            return func(*args)

        hass = types.SimpleNamespace(async_add_executor_job=executor)
        manager = ViviScheduleManager(hass)
        manager.data = {"stops": {"old": {}}, "station_list": [{"id": "old"}], "schedule": {"old": []}}
        first = FakeCoordinator()
        second = FakeCoordinator()
        manager.add_coordinator(first)
        manager.add_coordinator(second)
        session = FakeSession(_small_gtfs())
        with patch("custom_components.vivi_trains.schedule.async_get_clientsession", return_value=session):
            self.assertTrue(await manager.async_check_for_update(force=True))
            self.assertFalse(await manager.async_check_for_update(force=True))
        self.assertEqual(session.requests, 2)
        self.assertEqual(first.refreshes, 1)
        self.assertEqual(second.refreshes, 1)
        self.assertEqual(first.data["stops"]["1"]["name"], "Rīga")
        self.assertEqual(manager._store.saved["checksum"], manager.checksum)

    async def test_failed_download_keeps_existing_schedule(self):
        async def executor(func, *args):
            return func(*args)

        hass = types.SimpleNamespace(async_add_executor_job=executor)
        manager = ViviScheduleManager(hass)
        old = {"stops": {"1": {}}, "station_list": [{"id": "1"}], "schedule": {"1": []}}
        manager.data = old
        session = FakeSession(b"not a zip")
        with patch("custom_components.vivi_trains.schedule.async_get_clientsession", return_value=session):
            with self.assertRaises(zipfile.BadZipFile):
                await manager.async_check_for_update(force=True)
        self.assertIs(manager.data, old)
        self.assertIsNone(manager._store.saved)


if __name__ == "__main__":
    unittest.main()
