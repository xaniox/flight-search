"""--exclude-countries removes countries from non-explicit selections (PRTWO-CRITERION-10).

Only medium and large airports are used, so these tests do not depend on the
small-airport rule. The new names are used inside each test, so each fails on
its own until the option exists.
"""

from __future__ import annotations

import pytest
from airport_factory import airport

from flight_search import cli

# LED (RU) and MSQ (BY) lie in the default region and near Karlsruhe, as do
# AMS (NL) and IST (TR); LIS (PT) is in the region but beyond a weekend radius.
AIRPORTS = (
    airport("FRA", "DE", "EU"),
    airport("AMS", "NL", "EU"),
    airport("IST", "TR", "AS"),
    airport("LED", "RU", "EU"),
    airport("MSQ", "BY", "EU"),
    airport("LIS", "PT", "EU", lat=38.77, lon=-9.13),
)


@pytest.fixture(autouse=True)
def fake_airports(monkeypatch):
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)


def _select(**choice):
    from flight_search.config import KARLSRUHE
    from flight_search.destinations import DestinationChoice, select_destinations

    selected, warnings = select_destinations(
        DestinationChoice(**choice), airports=AIRPORTS, center=KARLSRUHE
    )
    return {a.iata for a in selected}, list(warnings)


def _search_codes(*extra):
    args = cli._build_parser().parse_args(
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
    destinations, _ = cli._select_airports(args)
    return {a.iata for a in destinations}


def _listed_codes(capsys, *extra):
    args = cli._build_parser().parse_args(["airports", *extra])
    assert cli._run_airports(args) == 0
    out = capsys.readouterr().out
    return {a.iata for a in AIRPORTS if a.iata in out.split()}


# --- DestinationChoice -----------------------------------------------------


def test_exclude_countries_defaults_to_empty():
    from flight_search.destinations import DestinationChoice

    assert DestinationChoice().exclude_countries == frozenset()


def test_exclude_countries_removes_airports_from_the_region():
    codes, _ = _select(exclude_countries=frozenset({"RU", "BY"}))
    assert codes == {"FRA", "AMS", "IST", "LIS"}


def test_exclude_countries_removes_airports_from_a_country_selection():
    codes, _ = _select(
        countries=frozenset({"RU", "TR"}), exclude_countries=frozenset({"RU"})
    )
    assert codes == {"IST"}


def test_exclude_countries_removes_airports_from_a_radius_selection():
    codes, _ = _select(
        region="weekend",
        max_distance_km=1200.0,
        exclude_countries=frozenset({"RU"}),
    )
    assert codes == {"FRA", "AMS", "IST", "MSQ"}


def test_exclude_countries_does_not_touch_explicit_codes():
    codes, warnings = _select(codes=("LED", "AMS"), exclude_countries=frozenset({"RU"}))
    assert codes == {"LED", "AMS"}
    assert warnings == []


# --- CLI -------------------------------------------------------------------


def test_weekend_exclude_countries_removes_those_countries():
    assert _search_codes("--exclude-countries", "RU,BY") == {"AMS", "IST", "LIS"}


def test_weekend_exclude_countries_is_case_insensitive():
    assert _search_codes("--exclude-countries", "ru,By") == {"AMS", "IST", "LIS"}


def test_weekend_countries_minus_excluded_country_leaves_only_turkey():
    assert _search_codes("--countries", "RU,TR", "--exclude-countries", "RU") == {"IST"}


def test_weekend_explicit_dest_keeps_an_excluded_country():
    assert _search_codes("--dest", "LED", "--exclude-countries", "RU") == {"LED"}


def test_airports_exclude_countries_lists_no_airport_of_that_country(capsys):
    assert _listed_codes(capsys, "--exclude-countries", "RU") == {
        "FRA",
        "AMS",
        "IST",
        "MSQ",
        "LIS",
    }


def test_airports_exclude_countries_is_case_insensitive(capsys):
    assert _listed_codes(capsys, "--exclude-countries", "ru,by") == {
        "FRA",
        "AMS",
        "IST",
        "LIS",
    }


def test_airports_countries_minus_excluded_country_lists_only_turkey(capsys):
    assert _listed_codes(
        capsys, "--countries", "RU,TR", "--exclude-countries", "RU"
    ) == {"IST"}


def test_airports_explicit_dest_keeps_an_excluded_country(capsys):
    assert _listed_codes(capsys, "--dest", "LED", "--exclude-countries", "RU") == {
        "LED"
    }
