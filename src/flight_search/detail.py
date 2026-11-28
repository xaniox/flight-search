"""Phase 2: confirm candidates with detailed searches and combine open jaws."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import date
from typing import Literal

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.candidates import Candidate
from flight_search.combine import (
    FlightOption,
    Itinerary,
    combine_itineraries,
    filter_departures,
    filter_return_legs,
    options_from_cache,
    options_from_results,
)
from flight_search.config import SearchSettings
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow, restrictions_key


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
        "restrictions": restrictions_key(restrictions),
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
    cached = options_from_cache(cache.get(key))
    if cached is not None:
        return cached

    budget.acquire()
    results = fli_api.fetch_leg(
        home, city_codes, day, direction, restrictions, settings
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


OptionKey = tuple[str, date, Literal["out", "ret"]]
"""(city key, day, direction) of one phase-2 fetch."""


def confirm_options(
    candidates: Sequence[Candidate],
    *,
    home: tuple[str, ...],
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
    depart_window: DepartureWindow,
    return_window: ReturnWindow,
    progress: Callable[[int], None] | None = None,
) -> dict[OptionKey, tuple[FlightOption, ...]]:
    """Fetch the complete, unfiltered options of every shortlisted candidate.

    Each candidate costs one fetch per direction, in shortlist order, even when
    an earlier candidate already asked for the same city, day and direction.
    With the cache on, the cache answers the repeat, so request and cache
    counts stay as before. With the cache off, the repeat is fetched again and
    its answer overwrites the earlier entry for that city, day and direction.

    Phase 1 only returns the cheapest page rows, so its prices are an upper
    bound for each city, not a provable lower bound. We therefore confirm a
    fixed shortlist (``--max-candidates``) and rank the confirmed itineraries;
    the result is the best of the shortlist rather than a globally proven
    optimum.
    """
    options: dict[OptionKey, tuple[FlightOption, ...]] = {}
    for index, candidate in enumerate(candidates, 1):
        city = candidate.city
        for day, direction, window in (
            (candidate.pair.depart, "out", depart_window),
            (candidate.pair.ret, "ret", return_window),
        ):
            options[(city.key, day, direction)] = tuple(
                fetch_options(
                    home=home,
                    city_codes=city.codes,
                    day=day,
                    direction=direction,
                    restrictions=window.restrictions(),
                    settings=settings,
                    cache=cache,
                    budget=budget,
                )
            )
        if progress:
            progress(index)
    return options


def rank_itineraries(
    candidates: Iterable[Candidate],
    options: Mapping[OptionKey, Sequence[FlightOption]],
    *,
    depart_window: DepartureWindow,
    return_window: ReturnWindow,
) -> list[Itinerary]:
    """Combine each candidate's options inside the windows, cheapest first.

    An itinerary whose (outbound, return) signature an earlier candidate
    already produced is dropped. Every call builds new Itinerary objects.
    """
    results: list[Itinerary] = []
    seen: set[tuple[tuple[str, ...], tuple[str, ...]]] = set()
    for candidate in candidates:
        city = candidate.city
        depart, ret = candidate.pair.depart, candidate.pair.ret
        out_options = filter_departures(
            options.get((city.key, depart, "out"), ()), depart_window
        )
        ret_options = filter_return_legs(
            options.get((city.key, ret, "ret"), ()), return_window, ret
        )
        for itinerary in combine_itineraries(
            city_key=city.key,
            city=city.display,
            country=city.country,
            city_codes=city.codes,
            depart_date=depart,
            return_date=ret,
            outbound_options=out_options,
            return_options=ret_options,
        ):
            signature = (itinerary.out.signature, itinerary.ret.signature)
            if signature in seen:
                continue
            seen.add(signature)
            results.append(itinerary)

    results.sort(key=lambda item: item.sort_key)
    return results


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
