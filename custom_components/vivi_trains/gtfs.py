"""Convert Vivi's GTFS archive into the compact schedule used by the integration."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import defaultdict


def build_schedule(archive: bytes) -> dict:
    """Parse and validate the GTFS files before replacing a working schedule."""
    with zipfile.ZipFile(io.BytesIO(archive)) as source:
        def rows(name: str) -> list[dict[str, str]]:
            if name in ("calendar", "calendar_dates") and f"{name}.txt" not in source.namelist():
                return []
            if source.getinfo(f"{name}.txt").file_size > 20 * 1024 * 1024:
                raise ValueError(f"GTFS file is too large: {name}.txt")
            with source.open(f"{name}.txt") as file:
                return list(csv.DictReader(io.TextIOWrapper(file, encoding="utf-8-sig")))

        stops_rows = rows("stops")
        routes = {row["route_id"]: row for row in rows("routes")}
        calendar = {row["service_id"]: row for row in rows("calendar")}
        exceptions: dict[str, dict[str, list[str]]] = defaultdict(
            lambda: {"1": [], "2": []}
        )
        for row in rows("calendar_dates"):
            kind = row["exception_type"]
            if kind not in ("1", "2"):
                raise ValueError(f"Unknown GTFS exception type: {kind}")
            exceptions[row["service_id"]][kind].append(row["date"])

        trips = {row["trip_id"]: row for row in rows("trips")}
        stop_times = rows("stop_times")

    stops = {
        row["stop_id"]: {
            "name": row["stop_name"],
            "lat": float(row["stop_lat"]),
            "lon": float(row["stop_lon"]),
        }
        for row in stops_rows
    }
    if not stops or not trips or not stop_times:
        raise ValueError("Vivi GTFS feed has no stops, trips, or stop times")

    station_list = sorted(
        ({"id": stop_id, "name": stop["name"]} for stop_id, stop in stops.items()),
        key=lambda station: station["name"],
    )
    schedule: dict[str, list[dict]] = defaultdict(list)
    for row in stop_times:
        trip_id = row["trip_id"]
        stop_id = row["stop_id"]
        if trip_id not in trips or stop_id not in stops:
            raise ValueError(f"Invalid GTFS stop time: {trip_id} at {stop_id}")
        trip = trips[trip_id]
        route = routes.get(trip["route_id"])
        if route is None:
            raise ValueError(f"Missing GTFS route: {trip['route_id']}")
        service_id = trip["service_id"]
        service = calendar.get(service_id)
        dates = exceptions[service_id]
        if service is None and not dates["1"]:
            raise ValueError(f"Missing GTFS service: {service_id}")
        departure = row["departure_time"]
        if not departure:
            continue
        item = {
            "trip_id": trip_id,
            "dep": ":".join(departure.split(":")[:2]),
            "headsign": trip["trip_headsign"],
            "color": f"#{route['route_color'] or 'F8DB22'}",
            "svc": {
                "days": (
                    [int(service[day]) for day in (
                        "monday", "tuesday", "wednesday", "thursday",
                        "friday", "saturday", "sunday",
                    )]
                    if service else [0] * 7
                ),
                "start": service["start_date"] if service else "",
                "end": service["end_date"] if service else "",
            },
            "dates": sorted(dates["1"]),
        }
        if dates["2"]:
            item["removed_dates"] = sorted(dates["2"])
        schedule[stop_id].append(item)

    for departures in schedule.values():
        departures.sort(key=lambda item: (item["dep"], item["trip_id"]))

    return {
        "stops": stops,
        "station_list": station_list,
        "schedule": dict(schedule),
    }
