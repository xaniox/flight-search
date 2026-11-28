"""Airports named by code are used even when small (PRTWO-CRITERION-09).

The selection receives the airport list including small airports; only codes
reach a small airport without ``include_small``. The new behaviour is reached
through ``select_destinations`` and the CLI helpers, so each test fails on its
own until the selection filters by type.
"""

from __future__ import annotations

from airport_factory import airport

from flight_search import cli
from flight_search.airports import load_airports

# SML is a small airport near Karlsruhe inside the default region; AMS and
# MAD are medium airports (MAD beyond a 1200 km weekend radius).
AIRPORTS = (
    airport("AMS", "NL", "EU"),
    airport("MAD", "ES", "EU", lat=40.47, lon=-3.56),
    airport("SML", "NL", "EU", type="small_airport"),
)


def _select(**choice):
    from flight_search.config import KARLSRUHE
    from flight_search.destinations import DestinationChoice, select_destinations

    selected, warnings = select_destinations(
        DestinationChoice(**choice), airports=AIRPORTS, center=KARLSRUHE
    )
    return {a.iata for a in selected}, list(warnings)


def _weekend_args(*extra):
    return cli._build_parser().parse_args(
        [
            "weekend",
            "--start",
            "2026-12-04",
            "--end",
            "2026-12-20",
            *extra,
        ]
    )


def _search(*extra):
    return cli._select_airports(_weekend_args(*extra))


# --- select_destinations ---------------------------------------------------


def test_code_selects_a_small_airport_without_include_small_and_without_warning():
    # Guard: an airport named by code is selected even when it is small.
    codes, warnings = _select(codes=("SML", "AMS"))
    assert codes == {"SML", "AMS"}
    assert warnings == []


def test_region_excludes_small_airports_without_include_small():
    codes, _ = _select()
    assert codes == {"AMS", "MAD"}


def test_region_includes_small_airports_with_include_small():
    # Guard: with include_small, small airports stay in the selection.
    codes, _ = _select(include_small=True)
    assert codes == {"AMS", "MAD", "SML"}


def test_countries_exclude_small_airports_without_include_small():
    codes, _ = _select(countries=frozenset({"NL"}))
    assert codes == {"AMS"}


def test_countries_include_small_airports_with_include_small():
    # Guard: with include_small, small airports stay in the selection.
    codes, _ = _select(countries=frozenset({"NL"}), include_small=True)
    assert codes == {"AMS", "SML"}


def test_radius_excludes_small_airports_without_include_small():
    codes, _ = _select(region="weekend", max_distance_km=1200.0)
    assert codes == {"AMS"}


def test_radius_includes_small_airports_with_include_small():
    # Guard: with include_small, small airports stay in the selection.
    codes, _ = _select(region="weekend", max_distance_km=1200.0, include_small=True)
    assert codes == {"AMS", "SML"}


# --- CLI on the shipped data -----------------------------------------------


def test_weekend_dest_selects_naxos_without_include_small():
    destinations, warnings = _search("--from", "FRA", "--dest", "JNX")
    assert [a.iata for a in destinations] == ["JNX"]
    assert not any("JNX" in w for w in warnings)


def test_weekend_countries_without_include_small_contain_no_small_airport():
    # Guard: without --include-small a country selection has no small airport.
    types = {a.iata: a.type for a in load_airports(include_small=True)}
    destinations, _ = _search("--from", "FRA", "--countries", "GR")
    assert destinations
    assert all(types[a.iata] != "small_airport" for a in destinations)


def test_weekend_small_home_airport_raises_no_unknown_code_warning():
    _, warnings = _search("--from", "JNX", "--dest", "ATH")
    assert not any("JNX" in w for w in warnings)


def test_airports_command_lists_a_small_airport_given_by_dest(capsys):
    args = cli._build_parser().parse_args(["airports", "--dest", "JNX"])
    assert cli._run_airports(args) == 0
    out = capsys.readouterr().out
    assert "JNX" in out.split()
    assert "1 airports" in out
