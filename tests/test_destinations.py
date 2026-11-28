"""Destination selection without argparse (PRTWO-CRITERION-07).

The new names are imported inside each test, so each test fails on its own
until ``flight_search.destinations`` exists.
"""

from __future__ import annotations

import ast
import importlib
import inspect

from airport_factory import airport

# AMS (EU) and IST (TR/AS) lie inside the default region, TLV (IL/AS) and
# LED (RU/AS) outside; all four are near Karlsruhe. LIS and MAD are inside
# the region but beyond a 1200 km weekend radius.
AIRPORTS = (
    airport("AMS", "NL", "EU"),
    airport("IST", "TR", "AS"),
    airport("LED", "RU", "AS"),
    airport("LIS", "PT", "EU", lat=38.77, lon=-9.13),
    airport("MAD", "ES", "EU", lat=40.47, lon=-3.56),
    airport("TLV", "IL", "AS"),
)


def _select(**choice):
    from flight_search.config import KARLSRUHE
    from flight_search.destinations import DestinationChoice, select_destinations

    selected, warnings = select_destinations(
        DestinationChoice(**choice), airports=AIRPORTS, center=KARLSRUHE
    )
    return {a.iata for a in selected}, list(warnings)


def test_codes_override_and_warn_about_unknown_codes():
    codes, warnings = _select(codes=("TLV", "XXX", "LED"), countries=frozenset({"NL"}))

    assert codes == {"TLV", "LED"}
    assert warnings == ["Unknown or unsupported destination code: XXX"]


def test_countries_choose_from_the_whole_list():
    codes, warnings = _select(countries=frozenset({"IL", "TR"}))

    assert codes == {"TLV", "IST"}
    assert warnings == []


def test_default_region_applies_without_codes_or_countries():
    codes, warnings = _select()

    assert codes == {"AMS", "IST", "LIS", "MAD"}
    assert warnings == []


def test_weekend_region_applies_the_radius():
    assert _select(region="weekend", max_distance_km=1200.0)[0] == {"AMS", "IST"}
    # Today's rule: the radius only counts for region "weekend" ...
    assert _select(region="europe", max_distance_km=1200.0)[0] == {
        "AMS",
        "IST",
        "LIS",
        "MAD",
    }
    # ... and it also narrows a country choice.
    assert _select(
        countries=frozenset({"NL", "PT"}), region="weekend", max_distance_km=1200.0
    )[0] == {"AMS"}


def test_exclude_codes_are_removed():
    assert _select(exclude_codes=frozenset({"AMS", "LIS"}))[0] == {"IST", "MAD"}
    assert _select(codes=("AMS", "TLV"), exclude_codes=frozenset({"AMS"}))[0] == {"TLV"}
    assert _select(countries=frozenset({"IL", "TR"}), exclude_codes=frozenset({"TLV"}))[
        0
    ] == {"IST"}


def test_destinations_module_imports_no_argparse():
    destinations = importlib.import_module("flight_search.destinations")

    tree = ast.parse(inspect.getsource(destinations))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module.split(".")[0])
    assert "argparse" not in imported
