import pytest

from flight_search.airports import (
    AirportInfo,
    build_city_groups,
    distance_from_karlsruhe,
    filter_airports,
    load_airports,
)


@pytest.fixture(scope="module")
def airports():
    return load_airports()


def test_dataset_contains_expected_airports(airports):
    codes = {a.iata for a in airports}
    assert {"FRA", "STR", "FKB", "SXB", "BCN", "GRO", "RAK", "CAI"} <= codes
    assert len(airports) > 400
    assert all(not a.is_small for a in airports)


def test_small_airports_are_opt_in():
    assert len(load_airports(include_small=True)) >= len(load_airports())


def test_metro_grouping_merges_barcelona_airports(airports):
    groups = {group.key: group for group in build_city_groups(airports)}
    barcelona = groups["metro:barcelona"]
    assert {"BCN", "GRO", "REU"} <= set(barcelona.codes)
    assert barcelona.display == "Barcelona"


def test_metro_grouping_keeps_single_airport_cities_separate(airports):
    groups = build_city_groups(airports)
    keys = {group.key for group in groups}
    assert "city:ES:barcelona" not in keys
    assert "city:FR:paris" not in keys  # merged into the Paris metro


def test_name_overrides_fix_municipality_names(airports):
    groups = {group.key: group for group in build_city_groups(airports)}
    assert groups["city:HR:zagreb"].display == "Zagreb"
    assert groups["city:FR:marseille"].display == "Marseille"
    assert groups["city:FR:nice"].display == "Nice"


def test_distance_and_region_filter(airports):
    lookup = {a.iata: a for a in airports}
    assert distance_from_karlsruhe(lookup["FRA"]) < 200
    assert 900 < distance_from_karlsruhe(lookup["BCN"]) < 1200
    near = filter_airports(airports, max_distance_km=400)
    assert "FRA" in {a.iata for a in near}
    assert "BCN" not in {a.iata for a in near}


def test_explicit_and_country_filters(airports):
    selected = filter_airports(airports, codes=("BCN", "GRO"))
    assert {a.iata for a in selected} == {"BCN", "GRO"}
    spanish = filter_airports(airports, countries=frozenset({"ES"}))
    assert spanish and all(a.country == "ES" for a in spanish)
    excluded = filter_airports(airports, codes=("BCN", "GRO"), exclude=frozenset({"GRO"}))
    assert {a.iata for a in excluded} == {"BCN"}


def test_airport_info_city_fallback():
    info = AirportInfo("XXX", "Some Airport", "", "DE", "medium_airport", "EU", 0.0, 0.0)
    assert info.city == "Some Airport"
