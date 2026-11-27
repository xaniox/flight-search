"""Default-region rule: the function itself (PRONE-CRITERION-04)."""

import pytest

from flight_search.airports import AirportInfo


def _airport(iata: str, country: str, continent: str) -> AirportInfo:
    return AirportInfo(
        iata=iata,
        name=f"{iata} Airport",
        municipality=iata,
        country=country,
        type="medium_airport",
        continent=continent,
        lat=49.0,
        lon=8.5,
    )


@pytest.mark.parametrize(
    ("country", "continent", "expected"),
    [
        ("DE", "EU", True),
        ("RU", "EU", True),
        ("TR", "AS", True),
        ("GE", "AS", True),
        ("AZ", "AS", True),
        ("AM", "AS", True),
        ("MA", "AF", True),
        ("EG", "AF", True),
        ("IL", "AS", False),
        ("RU", "AS", False),
        ("US", "NA", False),
    ],
)
def test_in_default_region_by_continent_or_country(country, continent, expected):
    from flight_search.airports import in_default_region

    assert in_default_region(_airport("XXX", country, continent)) is expected


@pytest.mark.parametrize("country", ["MA", "DZ", "TN", "LY", "EG", "EH"])
def test_in_default_region_covers_all_north_african_countries(country):
    from flight_search.airports import in_default_region

    assert in_default_region(_airport("XXX", country, "AF")) is True
