from dataclasses import replace
from datetime import date

import pytest

from flight_search.airports import AirportInfo
from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.destinations import select_destinations
from flight_search.weekend import WeekendQuery, prepare_weekend

AIRPORTS = (
    AirportInfo(
        "FRA", "Frankfurt", "Frankfurt", "DE", "large_airport", "EU", 50.04, 8.56
    ),
    AirportInfo(
        "STR", "Stuttgart", "Stuttgart", "DE", "large_airport", "EU", 48.69, 9.22
    ),
    AirportInfo(
        "FKB",
        "Karlsruhe/Baden-Baden",
        "Baden-Baden",
        "DE",
        "medium_airport",
        "EU",
        48.78,
        8.08,
    ),
    AirportInfo("MUC", "Munich", "Munich", "DE", "large_airport", "EU", 48.35, 11.79),
    AirportInfo("WMS", "Worms", "Worms", "DE", "small_airport", "EU", 49.61, 8.37),
    AirportInfo("LIS", "Lisbon", "Lisbon", "PT", "large_airport", "EU", 38.77, -9.13),
    AirportInfo(
        "JFK", "John F. Kennedy", "New York", "US", "large_airport", "NA", 40.64, -73.78
    ),
)


def airport_loader(*, include_small):
    return tuple(
        airport for airport in AIRPORTS if include_small or not airport.is_small
    )


def prepared_destination_codes(choice):
    plan = prepare_weekend(
        WeekendQuery(
            start="2026-12-04",
            end="2026-12-06",
            depart_days=("fri",),
            return_days=("sun",),
            min_nights=2,
            max_nights=2,
            home=("FRA", "STR"),
            destination=choice,
            center=KARLSRUHE,
            settings=SearchSettings(),
            max_requests=200,
        ),
        today=date(2026, 12, 1),
        airport_loader=airport_loader,
    )
    return [airport.iata for airport in plan.request.destinations]


def test_prepared_browser_destinations_union_regions_and_countries():
    from flight_search.destinations import BrowserDestinationChoice

    weekend = BrowserDestinationChoice(regions=("weekend",), max_distance_km=400)
    mixed = replace(
        weekend,
        regions=("weekend", "transatlantic"),
        configured_regions={"transatlantic": frozenset({"DE", "US"})},
        countries=frozenset({"PT"}),
    )

    assert sorted(prepared_destination_codes(weekend)) == ["FKB", "MUC"]
    assert sorted(prepared_destination_codes(mixed)) == ["FKB", "JFK", "LIS", "MUC"]


def test_prepared_browser_destinations_apply_exclusions_and_small_airport_setting():
    from flight_search.destinations import BrowserDestinationChoice

    choice = BrowserDestinationChoice(
        regions=("europe", "custom"),
        configured_regions={"custom": frozenset({"DE", "PT"})},
        countries=frozenset({"DE", "PT"}),
        exclude_codes=frozenset({"MUC"}),
        exclude_countries=frozenset({"PT"}),
    )

    assert prepared_destination_codes(choice) == ["FKB"]
    assert sorted(prepared_destination_codes(replace(choice, include_small=True))) == [
        "FKB",
        "WMS",
    ]


def test_browser_destination_selection_keeps_empty_choices_empty_and_rejects_unknown_regions():
    from flight_search.destinations import BrowserDestinationChoice

    selected, _ = select_destinations(
        BrowserDestinationChoice(), airports=AIRPORTS, center=KARLSRUHE
    )
    assert selected == ()

    with pytest.raises(ValueError, match="missing-region"):
        select_destinations(
            BrowserDestinationChoice(
                regions=("europe", "missing-region"), countries=frozenset({"DE"})
            ),
            airports=AIRPORTS,
            center=KARLSRUHE,
        )
