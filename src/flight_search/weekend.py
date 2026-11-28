"""Prepare a weekend search independently of its interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Protocol

from flight_search.airports import AirportInfo, load_airports
from flight_search.cache import Cache, default_cache_dir, parse_duration
from flight_search.candidates import request_estimate
from flight_search.config import Coordinate, SearchSettings
from flight_search.dates import (
    DateError,
    count_date_pairs,
    count_feasible_dates,
    expand_date_pairs,
    parse_date,
    parse_weekdays,
    unique_dates,
)
from flight_search.destinations import (
    BrowserDestinationChoice,
    DestinationChoice,
    select_destinations,
)
from flight_search.fli_api import RequestBudget, destination_batch_size, resolve_airport
from flight_search.search import SearchRequest
from flight_search.windows import (
    DepartureWindow,
    ReturnWindow,
    TimeWindowError,
    parse_clock,
)


class WeekendError(ValueError):
    """Invalid weekend search parameters."""

    def __init__(self, message: str, *, warnings: tuple[str, ...] = ()) -> None:
        super().__init__(message)
        self.warnings = warnings


class AirlineError(WeekendError):
    """An entry is not an IATA airline code."""


class WeekendBudgetError(WeekendError):
    """The prepared search estimate exceeds the configured budget."""

    def __init__(self, estimated_requests: int, max_requests: int) -> None:
        super().__init__(
            f"Estimated requests ({estimated_requests}) exceed the limit ({max_requests})."
        )
        self.estimated_requests = estimated_requests
        self.max_requests = max_requests


MAX_DATE_PAIRS = 100_000


class WeekendDatePairError(WeekendError):
    """The date range and nights allow more date pairs than one search builds."""

    def __init__(self, date_pairs: int, max_date_pairs: int) -> None:
        super().__init__(
            f"Date pairs ({date_pairs}) exceed the limit ({max_date_pairs}). "
            "Narrow the date range or the nights."
        )
        self.date_pairs = date_pairs
        self.max_date_pairs = max_date_pairs


class AirportLoader(Protocol):
    def __call__(self, *, include_small: bool) -> tuple[AirportInfo, ...]: ...


@dataclass(frozen=True, slots=True)
class WeekendQuery:
    start: str
    end: str
    depart_days: tuple[str, ...]
    return_days: tuple[str, ...]
    min_nights: int
    max_nights: int
    home: tuple[str, ...]
    destination: DestinationChoice | BrowserDestinationChoice
    center: Coordinate
    settings: SearchSettings
    max_requests: int
    depart_after: str | None = None
    depart_before: str | None = None
    return_depart_after: str | None = None
    return_arrive_before: str | None = None
    airline_codes: tuple[str, ...] = ()
    allow_codeshare: bool = False
    batch_size: int | None = None
    max_candidates: int = 60
    concurrency: int = 6
    per_city: int = 3


@dataclass(frozen=True, slots=True)
class WeekendPlan:
    request: SearchRequest
    warnings: tuple[str, ...]
    estimated_requests: int
    max_requests: int
    start: date
    end: date
    depart_days: frozenset[int]
    return_days: frozenset[int]
    depart_dates: tuple[date, ...]
    return_dates: tuple[date, ...]

    def create_resources(
        self, *, cache_dir: Path | None, cache_ttl: str, cache_enabled: bool
    ) -> tuple[Cache, RequestBudget]:
        if self.estimated_requests > self.max_requests:
            raise WeekendBudgetError(self.estimated_requests, self.max_requests)

        ttl = parse_duration(cache_ttl)
        cache = Cache(
            directory=cache_dir or default_cache_dir(),
            ttl=ttl,
            enabled=cache_enabled,
        )
        return cache, RequestBudget(self.max_requests)


def _airline_codes(values: tuple[str, ...], *, source: str) -> frozenset[str]:
    codes = set()
    for part in values:
        entry = part.strip()
        if not entry:
            continue
        if not (len(entry) == 2 and entry.isascii() and entry.isalnum()):
            raise AirlineError(
                f"{source} entry {entry!r} is not an airline code "
                "(two letters or digits)."
            )
        codes.add(entry.upper())
    return frozenset(codes)


def resolve_weekend_destinations(
    home: tuple[str, ...],
    choice: DestinationChoice | BrowserDestinationChoice,
    *,
    center: Coordinate,
    airport_loader: AirportLoader,
    warn_missing_home: bool = False,
) -> tuple[tuple[AirportInfo, ...], list[str]]:
    airports = airport_loader(include_small=True)
    warnings = []
    if warn_missing_home:
        known = {airport.iata for airport in airports}
        warnings.extend(
            f"Unknown or unsupported airport code: {code}"
            for code in home
            if code not in known
        )
    if not home:
        raise ValueError("At least one home airport is required")

    choice = replace(choice, exclude_codes=choice.exclude_codes | frozenset(home))
    destinations, destination_warnings = select_destinations(
        choice, airports=airports, center=center
    )
    return destinations, warnings + destination_warnings


def prepare_weekend(
    query: WeekendQuery,
    *,
    today: date,
    airport_loader: AirportLoader = load_airports,
    destination_resolver: Callable[[], tuple[tuple[AirportInfo, ...], list[str]]]
    | None = None,
    airline_source: str = "airline_codes",
    enforce_budget: bool = False,
) -> WeekendPlan:
    """Resolve inputs and estimate a search without creating resources or running it."""
    try:
        start = parse_date(query.start)
        end = parse_date(query.end)
        depart_days = parse_weekdays(query.depart_days)
        return_days = parse_weekdays(query.return_days)
        depart_count, return_count = count_feasible_dates(
            start, end, depart_days, return_days, query.min_nights, query.max_nights
        )
        depart_window = DepartureWindow(
            after=parse_clock(query.depart_after) if query.depart_after else None,
            before=parse_clock(query.depart_before) if query.depart_before else None,
        )
        return_window = ReturnWindow(
            depart_after=parse_clock(query.return_depart_after)
            if query.return_depart_after
            else None,
            arrive_before=parse_clock(query.return_arrive_before)
            if query.return_arrive_before
            else None,
        )
    except (DateError, TimeWindowError) as exc:
        raise WeekendError(str(exc)) from exc
    airlines = _airline_codes(query.airline_codes, source=airline_source)

    if start < today:
        raise WeekendError(f"start date {start} is in the past.")
    if not depart_count:
        raise WeekendError(
            "no departure/return date pairs match the "
            "weekday and night constraints inside the range."
        )
    home = query.home
    if not home:
        raise WeekendError("at least one home airport is required.")
    if len(home) > 8:
        raise WeekendError(
            "at most 8 home airports can be searched "
            "at once (Google accepts 14 airports per request and large metros "
            "use up to 6 destination airports)."
        )
    for code in home:
        try:
            resolve_airport(code)
        except ValueError as exc:
            raise WeekendError(f"unknown home airport code {code!r}.") from exc

    if destination_resolver is None:
        destinations, warnings = resolve_weekend_destinations(
            home, query.destination, center=query.center, airport_loader=airport_loader
        )
    else:
        destinations, warnings = destination_resolver()
    if not destinations:
        raise WeekendError(
            "no destination airports selected.", warnings=tuple(warnings)
        )

    batch_size = destination_batch_size(len(home), query.batch_size)
    estimated_requests = request_estimate(
        len(destinations),
        depart_count,
        return_count,
        home_airports=len(home),
        batch_size=batch_size,
        max_candidates=query.max_candidates,
    )
    if enforce_budget and estimated_requests > query.max_requests:
        raise WeekendBudgetError(estimated_requests, query.max_requests)
    date_pairs = count_date_pairs(
        start, end, depart_days, return_days, query.min_nights, query.max_nights
    )
    if date_pairs > MAX_DATE_PAIRS:
        raise WeekendDatePairError(date_pairs, MAX_DATE_PAIRS)
    pairs = expand_date_pairs(
        start, end, depart_days, return_days, query.min_nights, query.max_nights
    )
    depart_dates, return_dates = unique_dates(pairs)
    request = SearchRequest(
        home=home,
        destinations=destinations,
        pairs=tuple(pairs),
        depart_window=depart_window,
        return_window=return_window,
        settings=query.settings,
        batch_size=batch_size,
        concurrency=max(1, query.concurrency),
        max_candidates=query.max_candidates,
        per_city=max(1, query.per_city),
        airlines=airlines,
        allow_codeshare=query.allow_codeshare,
    )
    return WeekendPlan(
        request=request,
        warnings=tuple(warnings),
        estimated_requests=estimated_requests,
        max_requests=query.max_requests,
        start=start,
        end=end,
        depart_days=depart_days,
        return_days=return_days,
        depart_dates=tuple(depart_dates),
        return_dates=tuple(return_dates),
    )
