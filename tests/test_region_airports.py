"""Default-region rule: the function itself (PRONE-CRITERION-04, -06)."""

import pytest
from airport_factory import airport as _airport

from flight_search.airports import in_default_region


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


# GR, CY, ES, PT completely (PRONE-CRITERION-06)
@pytest.mark.parametrize(
    ("iata", "country", "continent"),
    [
        ("RHO", "GR", "AS"),
        ("LCA", "CY", "AS"),
        ("TFS", "ES", "AF"),
        ("FNC", "PT", "AF"),
        ("PDL", "PT", "NA"),
    ],
)
def test_greece_cyprus_spain_portugal_are_inside_whatever_the_continent(
    iata, country, continent
):
    assert in_default_region(_airport(iata, country, continent)) is True


def test_russia_in_asia_stays_outside():
    assert in_default_region(_airport("OVB", "RU", "AS")) is False
