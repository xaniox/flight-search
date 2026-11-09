"""Phase 2: confirm candidates with detailed searches and combine open jaws."""

from __future__ import annotations

from datetime import date
from typing import Callable, Iterable

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.candidates import Candidate
from flight_search.combine import (
    FlightOption,
    Itinerary,
    combine_itineraries,
    filter_departures,
    filter_return_legs,
    options_from_results,
)
from flight_search.config import SearchSettings
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow


def _restrictions_key(restrictions) -> dict | None:
    if restrictions is None:
        return None
    return restrictions.model_dump(exclude_none=True)


def _detail_key(
    home: tuple[str, ...],
    city_codes: tuple[str, ...],
    day: date,
    direction: str,
    settings: SearchSettings,
    restrictions,
) -> dict:
    return {
        "phase": "detail",
        "home": list(home),
        "city": list(city_codes),
        "date": day.isoformat(),
        "direction": direction,
        "restrictions": _restrictions_key(restrictions),
        "settings": settings.cache_key(),
    }


def fetch_options(
    *,
    home: tuple[str, ...],
    city_codes: tuple[str, ...],
    day: date,
    direction: str,
    restrictions,
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
) -> list[FlightOption]:
    key = _detail_key(home, city_codes, day, direction, settings, restrictions)
    cached = cache.get(key)
    if isinstance(cached, list):
        return [FlightOption.from_dict(item) for item in cached]

    budget.acquire()
    if direction == "out":
        results = fli_api.detail_results(
            list(home), list(city_codes), day, restrictions, settings
        )
    else:
        results = fli_api.detail_results(
            list(city_codes), list(home), day, restrictions, settings
        )
    options = options_from_results(results)
    cache.put(key, [option.to_dict() for option in options])
    return options


def _roundtrip(
    *,
    home: tuple[str, ...],
    city_codes: tuple[str, ...],
    depart_date: date,
    return_date: date,
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
) -> float | None:
    key = {
        "phase": "roundtrip",
        "home": list(home),
        "city": list(city_codes),
        "depart": depart_date.isoformat(),
        "return": return_date.isoformat(),
        "settings": settings.cache_key(),
    }
    cached = cache.get(key)
    if isinstance(cached, (int, float)):
        return float(cached)
    if cached == "none":
        return None
    # A round-trip search costs 1 + top_n fetches; top_n=1 keeps it at two.
    budget.acquire(2)
    price = fli_api.roundtrip_price(
        list(home), list(city_codes), depart_date, return_date, settings
    )
    cache.put(key, price if price is not None else "none")
    return price


def evaluate_candidates(
    candidates: list[Candidate],
    *,
    home: tuple[str, ...],
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
    depart_window: DepartureWindow,
    return_window: ReturnWindow,
    pool_size: int,
    max_candidates: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> list[Itinerary]:
    """Confirm the shortlisted candidates with complete, per-city searches.

    Phase 1 only returns the cheapest page rows, so its prices are an upper
    bound for each city, not a provable lower bound. We therefore confirm a
    fixed shortlist (``--max-candidates``) and rank the confirmed itineraries;
    the result is the best of the shortlist rather than a globally proven
    optimum.
    """
    if max_candidates is not None:
        candidates = candidates[:max_candidates]

    results: list[Itinerary] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    total = len(candidates)

    for index, candidate in enumerate(candidates, 1):
        city_codes = candidate.city.codes
        out_options = fetch_options(
            home=home,
            city_codes=city_codes,
            day=candidate.pair.depart,
            direction="out",
            restrictions=depart_window.restrictions(),
            settings=settings,
            cache=cache,
            budget=budget,
        )
        ret_options = fetch_options(
            home=home,
            city_codes=city_codes,
            day=candidate.pair.ret,
            direction="ret",
            restrictions=return_window.restrictions(),
            settings=settings,
            cache=cache,
            budget=budget,
        )
        out_options = filter_departures(out_options, depart_window)
        ret_options = filter_return_legs(
            ret_options, return_window, candidate.pair.ret
        )
        for itinerary in combine_itineraries(
            city_key=candidate.city.key,
            city=candidate.city.display,
            country=candidate.city.country,
            city_codes=candidate.city.codes,
            depart_date=candidate.pair.depart,
            return_date=candidate.pair.ret,
            outbound_options=out_options,
            return_options=ret_options,
        ):
            signature = (itinerary.out.signature, itinerary.ret.signature)
            if signature in seen:
                continue
            seen.add(signature)
            results.append(itinerary)

        if progress:
            progress(index)

    results.sort(key=lambda item: (item.total, item.depart_date, item.return_date))
    return results[:pool_size]


def add_roundtrip_comparison(
    itineraries: Iterable[Itinerary],
    *,
    home: tuple[str, ...],
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
) -> None:
    """Fill ``roundtrip_price`` for each itinerary, reusing per city/date results."""
    for itinerary in itineraries:
        itinerary.roundtrip_price = _roundtrip(
            home=home,
            city_codes=itinerary.city_codes,
            depart_date=itinerary.depart_date,
            return_date=itinerary.return_date,
            settings=settings,
            cache=cache,
            budget=budget,
        )
