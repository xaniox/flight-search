"""The search core: discovery, candidate selection and confirmation.

Free of argparse and rich, so the command line and later front ends share it.
The result keeps the unfiltered phase-2 options. ``SearchResult.itineraries()``
applies the time windows and airline filter, then ranks the itineraries.
The caller can limit how many to return.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from flight_search.airports import AirportInfo, build_city_groups
from flight_search.cache import Cache
from flight_search.candidates import Candidate, build_candidates, select_candidates
from flight_search.combine import FlightOption, Itinerary
from flight_search.config import SearchSettings
from flight_search.dates import DatePair, unique_dates
from flight_search.detail import OptionKey, confirm_options, rank_itineraries
from flight_search.discover import run_discovery
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow

__all__ = [
    "OptionKey",
    "SearchProgress",
    "SearchRequest",
    "SearchResult",
    "SearchStats",
    "run_search",
]


class SearchProgress(Protocol):
    """Where a search reports its phases; ``start`` returns the update callback."""

    def start(self, description: str, total: int) -> Callable[[int], None]: ...

    def stop(self) -> None: ...

    def discovered(self, failures: Sequence[str]) -> None: ...


@dataclass(frozen=True, slots=True)
class SearchRequest:
    """The resolved inputs of one search."""

    home: tuple[str, ...]
    destinations: tuple[AirportInfo, ...]
    pairs: tuple[DatePair, ...]
    depart_window: DepartureWindow
    return_window: ReturnWindow
    settings: SearchSettings
    batch_size: int
    concurrency: int
    max_candidates: int
    per_city: int
    airlines: frozenset[str] = frozenset()
    """IATA codes every leg must be sold and operated by; empty means any."""
    allow_codeshare: bool = False
    """Check only the selling airline of each leg against ``airlines``."""


@dataclass(frozen=True, slots=True)
class SearchStats:
    destination_airports: int
    cities: int
    date_pairs: int
    distinct_departure_dates: int
    distinct_return_dates: int
    batch_size: int
    candidates: int
    shortlisted: int
    discovery_requests: int


@dataclass(frozen=True, slots=True)
class SearchResult:
    request: SearchRequest
    shortlist: tuple[Candidate, ...]
    options: Mapping[OptionKey, tuple[FlightOption, ...]]
    stats: SearchStats
    failures: tuple[str, ...]

    def itineraries(self) -> list[Itinerary]:
        """Rank confirmed itineraries after applying the time and airline filters."""
        return rank_itineraries(
            self.shortlist,
            self.options,
            depart_window=self.request.depart_window,
            return_window=self.request.return_window,
            airlines=self.request.airlines,
            allow_codeshare=self.request.allow_codeshare,
        )


def run_search(
    request: SearchRequest,
    *,
    cache: Cache,
    budget: RequestBudget,
    progress: SearchProgress | None = None,
) -> SearchResult:
    """Run discovery, select the shortlist and confirm it."""
    destinations = request.destinations
    cities = build_city_groups(destinations)
    pairs = list(request.pairs)
    depart_dates, return_dates = unique_dates(pairs)
    batch_count = max(1, -(-len(destinations) // request.batch_size))

    update = (
        progress.start(
            "Pricing destinations",
            (len(depart_dates) + len(return_dates)) * batch_count,
        )
        if progress
        else None
    )
    try:
        discovery = run_discovery(
            destinations=tuple(a.iata for a in destinations),
            home=request.home,
            depart_dates=depart_dates,
            return_dates=return_dates,
            depart_window=request.depart_window,
            return_window=request.return_window,
            settings=request.settings,
            cache=cache,
            budget=budget,
            batch_size=request.batch_size,
            concurrency=request.concurrency,
            progress=update,
            airlines=request.airlines,
            allow_codeshare=request.allow_codeshare,
        )
    finally:
        if progress:
            progress.stop()
    failures = tuple(discovery.failures)
    if progress:
        progress.discovered(failures)

    candidates = build_candidates(cities, discovery.screens, pairs)
    shortlist = tuple(
        select_candidates(
            candidates, per_city=request.per_city, limit=request.max_candidates
        )
    )[: max(0, request.max_candidates)]
    options: dict[OptionKey, tuple[FlightOption, ...]] = {}
    if shortlist:
        update = (
            progress.start("Confirming candidates", len(shortlist))
            if progress
            else None
        )
        try:
            options = confirm_options(
                shortlist,
                home=request.home,
                settings=request.settings,
                cache=cache,
                budget=budget,
                depart_window=request.depart_window,
                return_window=request.return_window,
                progress=update,
            )
        finally:
            if progress:
                progress.stop()

    stats = SearchStats(
        destination_airports=len(destinations),
        cities=len(cities),
        date_pairs=len(pairs),
        distinct_departure_dates=len(depart_dates),
        distinct_return_dates=len(return_dates),
        batch_size=request.batch_size,
        candidates=len(candidates),
        shortlisted=len(shortlist),
        discovery_requests=discovery.requests,
    )
    return SearchResult(
        request=request,
        shortlist=shortlist,
        options=options,
        stats=stats,
        failures=failures,
    )
