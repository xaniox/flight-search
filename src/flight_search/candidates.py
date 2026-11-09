"""Phase 1 output -> ranked (city, date-pair) candidates."""

from __future__ import annotations

from dataclasses import dataclass

from flight_search.airports import CityGroup
from flight_search.dates import DatePair
from flight_search.discover import AirportScreen


@dataclass(slots=True)
class Candidate:
    city: CityGroup
    pair: DatePair
    out_price: float
    ret_price: float
    estimate: float


def build_candidates(
    cities: list[CityGroup],
    screens: dict[str, AirportScreen],
    pairs: list[DatePair],
) -> list[Candidate]:
    """Join city groups, discovery prices and date pairs.

    ``estimate`` is the cheapest outbound price seen for the city on the
    departure date plus the cheapest return price seen on the return date.
    Phase 1 only returns the cheapest page rows per batch, so this is an
    estimate (an upper bound on the true city minimum), not a provable bound.
    """
    candidates: list[Candidate] = []
    for city in cities:
        codes = [code for code in city.codes if code in screens and screens[code].ok]
        if not codes:
            continue
        for pair in pairs:
            depart_key = pair.depart.isoformat()
            return_key = pair.ret.isoformat()
            out_values = [
                screens[code].out[depart_key]
                for code in codes
                if depart_key in screens[code].out
            ]
            ret_values = [
                screens[code].ret[return_key]
                for code in codes
                if return_key in screens[code].ret
            ]
            if not out_values or not ret_values:
                continue
            out_min = min(out_values)
            ret_min = min(ret_values)
            candidates.append(
                Candidate(
                    city=city,
                    pair=pair,
                    out_price=out_min,
                    ret_price=ret_min,
                    estimate=out_min + ret_min,
                )
            )
    candidates.sort(
        key=lambda c: (
            c.estimate,
            c.pair.depart,
            c.pair.ret,
            c.city.display.lower(),
        )
    )
    return candidates


def request_estimate(
    destination_airports: int,
    depart_dates: int,
    return_dates: int,
    home_airports: int = 4,
    batch_size: int | None = None,
    max_candidates: int = 60,
) -> int:
    """Approximate total page fetches for a run."""
    if destination_airports == 0:
        return 0
    per_request = batch_size or max(1, 14 - home_airports)
    batches = (destination_airports + per_request - 1) // per_request
    discovery = (depart_dates + return_dates) * batches
    return discovery + max_candidates * 2


def select_candidates(
    candidates: list[Candidate],
    *,
    per_city: int = 3,
    limit: int = 60,
) -> list[Candidate]:
    """Keep the cheapest candidates while giving many cities a chance.

    Without a per-city cap a single cheap city can occupy every confirmation
    slot, which makes ``--best-per-city`` useless and hides other destinations.
    """
    selected: list[Candidate] = []
    seen: dict[str, int] = {}
    for candidate in candidates:
        used = seen.get(candidate.city.key, 0)
        if used >= per_city:
            continue
        seen[candidate.city.key] = used + 1
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected
