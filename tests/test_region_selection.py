"""Default region applied only without explicit choice (PRONE-CRITERION-05)."""

import pytest

from flight_search import cli
from flight_search.airports import AirportInfo


def _airport(iata, country, continent, lat=49.0, lon=8.5):
    return AirportInfo(
        iata=iata,
        name=f"{iata} Airport",
        municipality=iata,
        country=country,
        type="medium_airport",
        continent=continent,
        lat=lat,
        lon=lon,
    )


# FRA is the home airport; AMS (EU) and IST (TR/AS) are inside the default
# region, TLV (IL/AS) and LED (RU/AS) outside; all are near Karlsruhe.
# LIS (PT/EU) is inside the region but beyond the weekend radius.
AIRPORTS = (
    _airport("FRA", "DE", "EU"),
    _airport("AMS", "NL", "EU"),
    _airport("IST", "TR", "AS"),
    _airport("TLV", "IL", "AS"),
    _airport("LED", "RU", "AS"),
    _airport("LIS", "PT", "EU", lat=38.77, lon=-9.13),
)


@pytest.fixture(autouse=True)
def fake_airports(monkeypatch):
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)


def _weekend_args(*extra):
    return cli._build_parser().parse_args(
        [
            "weekend",
            "--start",
            "2026-12-04",
            "--end",
            "2026-12-20",
            "--from",
            "FRA",
            *extra,
        ]
    )


def _search_codes(*extra):
    destinations, _ = cli._select_airports(_weekend_args(*extra))
    return {a.iata for a in destinations}


def _listed_codes(capsys, *extra):
    args = cli._build_parser().parse_args(["airports", *extra])
    assert cli._run_airports(args) == 0
    out = capsys.readouterr().out
    return {a.iata for a in AIRPORTS if a.iata in out.split()}


def test_search_europe_region_limits_to_default_region():
    assert _search_codes() == {"AMS", "IST", "LIS"}


def test_search_weekend_region_applies_default_region_and_radius():
    assert _search_codes("--region", "weekend") == {"AMS", "IST"}


def test_search_countries_ignore_default_region():
    assert _search_codes("--countries", "IL,TR") == {"TLV", "IST"}


def test_search_dest_ignores_default_region():
    assert _search_codes("--dest", "TLV,LED") == {"TLV", "LED"}


def test_airports_listing_europe_region_limits_to_default_region(capsys):
    assert _listed_codes(capsys) == {"FRA", "AMS", "IST", "LIS"}


def test_airports_listing_weekend_region_applies_default_region_and_radius(capsys):
    assert _listed_codes(capsys, "--region", "weekend") == {"FRA", "AMS", "IST"}


def test_airports_listing_countries_ignore_default_region(capsys):
    assert _listed_codes(capsys, "--countries", "IL,RU") == {"TLV", "LED"}


def test_airports_listing_dest_ignores_default_region(capsys):
    assert _listed_codes(capsys, "--dest", "TLV,LED") == {"TLV", "LED"}


@pytest.mark.parametrize("option", ["--countries", "--dest"])
def test_airports_listing_empty_explicit_choice_applies_default_region(capsys, option):
    default = _listed_codes(capsys)
    assert _listed_codes(capsys, option, ",") == default
    assert default == {"FRA", "AMS", "IST", "LIS"}
