"""Which destination airports a search covers, free of argparse."""

from __future__ import annotations

from dataclasses import dataclass

from flight_search.airports import (
    AirportInfo,
    filter_airports,
    in_default_region,
)
from flight_search.config import Coordinate


@dataclass(frozen=True, slots=True)
class DestinationChoice:
    """What the user asked for; ``codes`` override everything else.

    ``exclude_countries`` (upper-case ISO codes) leaves those countries out of
    region, country and radius selections, never out of explicit ``codes``.
    ``radius_on_codes`` applies the ``weekend`` radius to explicit ``codes``
    too, as the ``airports`` listing always did.
    """

    codes: tuple[str, ...] = ()
    countries: frozenset[str] = frozenset()
    region: str = "europe"
    max_distance_km: float | None = None
    exclude_codes: frozenset[str] = frozenset()
    include_small: bool = False
    exclude_countries: frozenset[str] = frozenset()
    radius_on_codes: bool = False


def _destination_pool(
    airports: tuple[AirportInfo, ...],
    codes: tuple[str, ...],
    countries: frozenset[str],
    include_small: bool = False,
    exclude_countries: frozenset[str] = frozenset(),
) -> tuple[AirportInfo, ...]:
    """The airports a destination choice draws from.

    Small airports count only when named by code or when ``include_small`` is
    set. Explicit codes or countries choose from the whole snapshot; otherwise
    the default region applies. ``exclude_countries`` applies only when no
    codes are given, so explicit codes are always kept.
    """
    if not include_small:
        named = {code.upper() for code in codes}
        airports = tuple(a for a in airports if not a.is_small or a.iata in named)
    if codes:
        return airports
    if exclude_countries:
        airports = tuple(a for a in airports if a.country not in exclude_countries)
    if countries:
        return airports
    return tuple(a for a in airports if in_default_region(a))


def select_destinations(
    choice: DestinationChoice,
    *,
    airports: tuple[AirportInfo, ...],
    center: Coordinate,
) -> tuple[tuple[AirportInfo, ...], list[str]]:
    """The selected airports and the warnings about unknown codes."""
    weekend = choice.region == "weekend"
    if choice.codes:
        known = {a.iata for a in airports}
        warnings = [
            f"Unknown or unsupported destination code: {code}"
            for code in choice.codes
            if code not in known
        ]
        known_codes = tuple(code for code in choice.codes if code in known)
        if not known_codes:
            return (), warnings
        radius = weekend and choice.radius_on_codes
        selected = filter_airports(
            _destination_pool(airports, choice.codes, (), choice.include_small),
            codes=known_codes,
            max_distance_km=choice.max_distance_km if radius else None,
            center=center,
            exclude=choice.exclude_codes,
        )
        return selected, warnings

    selected = filter_airports(
        _destination_pool(
            airports,
            (),
            choice.countries,
            choice.include_small,
            choice.exclude_countries,
        ),
        countries=choice.countries,
        max_distance_km=choice.max_distance_km if weekend else None,
        center=center,
        exclude=choice.exclude_codes,
    )
    return selected, []
