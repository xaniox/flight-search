import pytest
from airport_factory import airport

from flight_search.airports import (
    AirportInfo,
    build_city_groups,
    filter_airports,
    load_airports,
)


@pytest.fixture(scope="module")
def airports():
    return load_airports()


def test_dataset_contains_expected_airports(airports):
    codes = {a.iata for a in airports}
    assert {
        "FRA",
        "STR",
        "FKB",
        "SXB",
        "BCN",
        "GRO",
        "RAK",
        "CAI",
        "IST",
        "SAW",
        "ESB",
        "AYT",
        "TBS",
        "BUS",
        "GYD",
        "EVN",
    } <= codes
    assert len(airports) > 400
    assert all(not a.is_small for a in airports)


def test_turkey_and_caucasus_countries_are_included(airports):
    by_code = {a.iata: a for a in airports}
    assert by_code["IST"].country == "TR"
    assert by_code["TBS"].country == "GE"
    assert by_code["GYD"].country == "AZ"
    assert by_code["EVN"].country == "AM"
    assert {a.iata for a in filter_airports(airports, countries=frozenset({"TR"}))} >= {
        "IST",
        "SAW",
        "ESB",
        "AYT",
        "ADB",
        "BJV",
    }


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
    from flight_search.airports import distance_km

    lookup = {a.iata: a for a in airports}
    assert distance_km(lookup["FRA"]) < 200
    assert 900 < distance_km(lookup["BCN"]) < 1200
    near = filter_airports(airports, max_distance_km=400)
    assert "FRA" in {a.iata for a in near}
    assert "BCN" not in {a.iata for a in near}


def test_explicit_and_country_filters(airports):
    selected = filter_airports(airports, codes=("BCN", "GRO"))
    assert {a.iata for a in selected} == {"BCN", "GRO"}
    spanish = filter_airports(airports, countries=frozenset({"ES"}))
    assert spanish and all(a.country == "ES" for a in spanish)
    excluded = filter_airports(
        airports, codes=("BCN", "GRO"), exclude=frozenset({"GRO"})
    )
    assert {a.iata for a in excluded} == {"BCN"}


def test_airport_info_city_fallback():
    info = AirportInfo(
        "XXX", "Some Airport", "", "DE", "medium_airport", "EU", 0.0, 0.0
    )
    assert info.city == "Some Airport"


def _group_codes(airports):
    from flight_search.airports import build_city_groups

    return sorted(
        tuple(a.iata for a in g.airports) for g in build_city_groups(airports)
    )


def test_same_named_airports_far_apart_are_separate_groups():
    portland_or = airport(
        "PDX",
        "US",
        municipality="Portland",
        lat=45.59,
        lon=-122.60,
    )
    portland_me = airport(
        "PWM",
        "US",
        municipality="Portland",
        lat=43.65,
        lon=-70.31,
    )
    assert _group_codes([portland_or, portland_me]) == [("PDX",), ("PWM",)]


def test_same_named_airports_within_100_km_stay_one_group():
    from flight_search.airports import build_city_groups

    kef = airport(
        "KEF",
        "IS",
        municipality="Reykjavík",
        lat=63.985,
        lon=-22.606,
    )
    rkv = airport(
        "RKV",
        "IS",
        municipality="Reykjavík",
        lat=64.129,
        lon=-21.938,
    )
    groups = build_city_groups([kef, rkv])
    assert [tuple(a.iata for a in g.airports) for g in groups] == [("KEF", "RKV")]
    assert groups[0].key == "city:IS:reykjavík"


def test_city_group_links_through_any_member_single_linkage():
    # A-B and B-C are about 80 km, A-C about 160 km: one group by chaining.
    a = airport(
        "PDX",
        "US",
        municipality="Springfield",
        lat=40.00,
        lon=-100.0,
    )
    b = airport(
        "PWM",
        "US",
        municipality="Springfield",
        lat=40.72,
        lon=-100.0,
    )
    c = airport(
        "JFK",
        "US",
        municipality="Springfield",
        lat=41.44,
        lon=-100.0,
    )
    assert _group_codes([a, b, c]) == [("JFK", "PDX", "PWM")]
