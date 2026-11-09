"""Thin, thread-safe wrappers around the ``fli`` search API."""

from __future__ import annotations

import logging
import threading
from datetime import date
from typing import Any

from fli.core import build_flight_segments, parse_cabin_class, parse_max_stops
from fli.models import (
    Airport,
    FlightSearchFilters,
    PassengerInfo,
    SortBy,
    TimeRestrictions,
)
from fli.search import SearchFlights

from flight_search.config import SearchSettings

# fli logs one warning per row that references an airport missing from its enum.
# Those rows are still usable by us, so keep the log clean.
logging.getLogger("fli").setLevel(logging.ERROR)

# Google's search page rejects a request carrying more than 14 airports
# (verified against the 2026-11 page transport: 4 origins + 10 destinations
# works, 4 + 11 returns an empty ds:1 payload). We always send all home
# airports, so this caps the destination batch size at 10 by default.
MAX_AIRPORTS_PER_REQUEST = 14


class BudgetExceeded(RuntimeError):
    """Raised when the configured request budget would be exceeded."""


class RequestBudget:
    """Thread-safe counter guarding how many HTTP requests a run may make."""

    def __init__(self, limit: int | None = None) -> None:
        self.limit = limit
        self._count = 0
        self._lock = threading.Lock()

    def acquire(self, amount: int = 1) -> None:
        with self._lock:
            if self.limit is not None and self._count + amount > self.limit:
                raise BudgetExceeded(
                    f"Request budget of {self.limit} exhausted. "
                    "Narrow the date range, region or destinations, or raise --max-requests."
                )
            self._count += amount

    @property
    def used(self) -> int:
        with self._lock:
            return self._count


def resolve_airport(code: str) -> Airport:
    try:
        return getattr(Airport, code.upper())
    except AttributeError as exc:
        raise ValueError(f"Unknown airport IATA code {code!r}") from exc


def max_destinations(home_count: int) -> int:
    return max(1, MAX_AIRPORTS_PER_REQUEST - home_count)


def _detail_filters(
    origins: list[Airport],
    destinations: list[Airport],
    travel_date: date,
    restrictions: TimeRestrictions | None,
    settings: SearchSettings,
    return_date: date | None = None,
) -> FlightSearchFilters:
    segments, trip_type = build_flight_segments(
        origins,
        destinations,
        travel_date.isoformat(),
        return_date=return_date.isoformat() if return_date else None,
        time_restrictions=restrictions,
    )
    return FlightSearchFilters(
        trip_type=trip_type,
        passenger_info=PassengerInfo(adults=settings.adults),
        flight_segments=segments,
        stops=parse_max_stops(settings.max_stops),
        seat_type=parse_cabin_class(settings.cabin),
        sort_by=SortBy.CHEAPEST,
    )


def detail_results(
    origins: list[str],
    destinations: list[str],
    travel_date: date,
    restrictions: TimeRestrictions | None,
    settings: SearchSettings,
    *,
    return_date: date | None = None,
    top_n: int = 1,
) -> list[Any]:
    """Detailed shopping results for one date and direction."""
    filters = _detail_filters(
        [resolve_airport(c) for c in origins],
        [resolve_airport(c) for c in destinations],
        travel_date,
        restrictions,
        settings,
        return_date=return_date,
    )
    return (
        SearchFlights().search(
            filters,
            top_n=top_n,
            currency=settings.currency,
            language=settings.language,
            country=settings.country,
        )
        or []
    )


def roundtrip_price(
    origins: list[str],
    destinations: list[str],
    depart_date: date,
    return_date: date,
    settings: SearchSettings,
) -> float | None:
    """Cheapest conventional round-trip price for the same city and dates."""
    results = detail_results(
        origins,
        destinations,
        depart_date,
        None,
        settings,
        return_date=return_date,
        top_n=1,
    )
    best: float | None = None
    for item in results:
        # Round-trip searches return (outbound, inbound) tuples; Google puts the
        # full trip price on the outbound leg.
        price = item[0].price if isinstance(item, tuple) else getattr(item, "price", None)
        if price is None:
            continue
        if best is None or price < best:
            best = float(price)
    return best
