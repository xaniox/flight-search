"""Which destination airports a search covers, free of argparse."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace

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
    """

    codes: tuple[str, ...] = ()
    countries: frozenset[str] = frozenset()
    region: str = "europe"
    max_distance_km: float | None = None
    exclude_codes: frozenset[str] = frozenset()
    include_small: bool = False
    exclude_countries: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True, kw_only=True)
class BrowserDestinationChoice:
    """The union of selected regions and countries in the browser."""

    regions: tuple[str, ...] = ()
    countries: frozenset[str] = frozenset()
    configured_regions: Mapping[str, frozenset[str]] = field(default_factory=dict)
    max_distance_km: float | None = None
    exclude_codes: frozenset[str] = frozenset()
    include_small: bool = False
    exclude_countries: frozenset[str] = frozenset()


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
    choice: DestinationChoice | BrowserDestinationChoice,
    *,
    airports: tuple[AirportInfo, ...],
    center: Coordinate,
) -> tuple[tuple[AirportInfo, ...], list[str]]:
    """The selected airports and the warnings about unknown codes."""
    if isinstance(choice, BrowserDestinationChoice):
        return _select_browser_destinations(
            choice, airports=airports, center=center
        ), []

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
        selected = filter_airports(
            _destination_pool(airports, choice.codes, (), choice.include_small),
            codes=known_codes,
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


def _select_browser_destinations(
    choice: BrowserDestinationChoice,
    *,
    airports: tuple[AirportInfo, ...],
    center: Coordinate,
) -> tuple[AirportInfo, ...]:
    common = DestinationChoice(
        max_distance_km=choice.max_distance_km,
        exclude_codes=choice.exclude_codes,
        include_small=choice.include_small,
        exclude_countries=choice.exclude_countries,
    )
    subsets = []
    if choice.countries:
        subsets.append(replace(common, countries=choice.countries))
    for region in choice.regions:
        if region in ("europe", "weekend"):
            subsets.append(replace(common, region=region))
        elif region in choice.configured_regions:
            countries = choice.configured_regions[region]
            if countries:
                subsets.append(replace(common, countries=countries))
        else:
            raise ValueError(f"Unknown destination region: {region!r}")

    by_code: dict[str, AirportInfo] = {}
    for subset in subsets:
        selected, _ = select_destinations(subset, airports=airports, center=center)
        by_code.update((airport.iata, airport) for airport in selected)
    return tuple(by_code[code] for code in sorted(by_code))
