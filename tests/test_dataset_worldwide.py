"""The shipped dataset is worldwide; its default region (PRONE-CRITERION-08)."""

from flight_search.airports import (
    build_city_groups,
    in_default_region,
    load_airports,
)


def _codes(airports) -> set[str]:
    return {a.iata for a in airports}


def test_shipped_dataset_contains_the_aegean_and_tel_aviv_codes():
    codes = _codes(load_airports(include_small=True))
    assert {"RHO", "KGS", "LCA", "PFO", "TFS", "TLV"} <= codes


def test_default_region_contains_the_missing_aegean_destinations():
    region = _codes(
        a for a in load_airports(include_small=True) if in_default_region(a)
    )
    assert {"RHO", "KGS", "LCA", "PFO", "TFS"} <= region


def test_default_region_excludes_tel_aviv_and_new_york():
    airports = load_airports(include_small=True)
    codes = _codes(airports)
    assert {"TLV", "JFK"} <= codes
    region = _codes(a for a in airports if in_default_region(a))
    assert "TLV" not in region
    assert "JFK" not in region


def test_tenerife_metro_group_holds_tfs():
    groups = {g.key: g for g in build_city_groups(load_airports(include_small=True))}
    assert "TFS" in groups["metro:tenerife"].codes
