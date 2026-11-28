"""Resolve airport time zones and measure elapsed time at the destination."""

from __future__ import annotations

from datetime import UTC, datetime
from functools import cache
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import airportsdata

from flight_search.airports import (
    AirportInfo,
    airport_lookup,
    distance_km,
    load_airports,
)
from flight_search.combine import FlightOption
from flight_search.config import Coordinate

# These IATA entries are absent or identify a different airport in airportsdata.
_ICAO_OVERRIDES = {"HBE": "HEAX", "RUS": "AGGU", "OUI": "LFEC", "GOY": "UNIT"}
# The snapshot and source coordinates for Humera (HUE) are 57 km apart.
_MAX_MATCH_DISTANCE_KM = 60


@cache
def _snapshot_by_code() -> dict[str, AirportInfo]:
    return airport_lookup(load_airports(include_small=True))


@cache
def _timezone_catalog(
    code_type: airportsdata.CodeType,
) -> dict[str, airportsdata.Airport]:
    return airportsdata.load(code_type)


@cache
def airport_timezone(code: str) -> ZoneInfo | None:
    """Look up a time zone only when the source matches the snapshot location."""
    code = code.strip().upper()
    airport = _snapshot_by_code().get(code)
    if airport is None:
        return None

    if code in _ICAO_OVERRIDES:
        record = _timezone_catalog("ICAO").get(_ICAO_OVERRIDES[code])
    else:
        record = _timezone_catalog("IATA").get(code)

    if not record or not record["tz"]:
        return None
    source = Coordinate(record["lat"], record["lon"])
    if not distance_km(airport, source) <= _MAX_MATCH_DISTANCE_KM:
        return None
    try:
        return ZoneInfo(record["tz"])
    except (ValueError, ZoneInfoNotFoundError):
        return None


def utc_timestamp(value: str, code: str) -> int | None:
    """Convert an ISO time to epoch seconds when it identifies one instant."""
    try:
        if len(value) <= 10:
            return None
        local = datetime.fromisoformat(value)
        if local.tzinfo is not None:
            return int(local.timestamp())

        zone = airport_timezone(code)
        if zone is None:
            return None
        candidates = set()
        for fold in (0, 1):
            instant = local.replace(tzinfo=zone, fold=fold).astimezone(UTC)
            if instant.astimezone(zone).replace(tzinfo=None) == local:
                candidates.add(instant)
        if len(candidates) == 1:
            return int(candidates.pop().timestamp())
    except (TypeError, ValueError, OverflowError):
        return None
    return None


def arrival_utc(option: FlightOption) -> int | None:
    if not option.legs:
        return None
    leg = option.legs[-1]
    return utc_timestamp(leg.arrival, leg.destination)


def departure_utc(option: FlightOption) -> int | None:
    if not option.legs:
        return None
    leg = option.legs[0]
    return utc_timestamp(leg.departure, leg.origin)


def stay_minutes(outbound: FlightOption, inbound: FlightOption) -> int | None:
    arrival = arrival_utc(outbound)
    departure = departure_utc(inbound)
    if arrival is None or departure is None or departure < arrival:
        return None
    return (departure - arrival) // 60
