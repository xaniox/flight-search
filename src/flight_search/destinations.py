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
    """What the user asked for; ``codes`` override everything else."""

    codes: tuple[str, ...] = ()
    countries: frozenset[str] = frozenset()
    region: str = "europe"
    max_distance_km: float | None = None
    exclude_codes: frozenset[str] = frozenset()
    include_small: bool = False


def destination_pool(
    airports: tuple[AirportInfo, ...],
    codes: tuple[str, ...],
    countries: frozenset[str],
) -> tuple[AirportInfo, ...]:
    """The airports a destination choice draws from.

    Explicit codes or countries choose from the whole snapshot; otherwise the
    default region applies.
    """
    if codes or countries:
        return airports
    return tuple(a for a in airports if in_default_region(a))


def select_destinations(
    choice: DestinationChoice,
    *,
    airports: tuple[AirportInfo, ...],
    center: Coordinate,
) -> tuple[tuple[AirportInfo, ...], list[str]]:
    """The selected airports and the warnings about unknown codes."""
    if choice.codes:
        known = {a.iata for a in airports}
        warnings = [
            f"Unknown or unsupported destination code: {code}"
            for code in choice.codes
            if code not in known
        ]
        selected = filter_airports(
            airports,
            codes=tuple(code for code in choice.codes if code in known),
            exclude=choice.exclude_codes,
        )
        return selected, warnings

    weekend = choice.region == "weekend"
    selected = filter_airports(
        destination_pool(airports, (), choice.countries),
        countries=choice.countries,
        max_distance_km=choice.max_distance_km if weekend else None,
        center=center,
        exclude=choice.exclude_codes,
    )
    return selected, []
