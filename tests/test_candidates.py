from datetime import date

from flight_search.airports import AirportInfo, CityGroup
from flight_search.candidates import (
    build_candidates,
    request_estimate,
    select_candidates,
)
from flight_search.dates import DatePair
from flight_search.discover import AirportScreen


def city(*codes: str) -> CityGroup:
    airports = tuple(
        AirportInfo(code, f"{code} Airport", "Testville", "ES", "medium_airport", "EU", 0, 0)
        for code in codes
    )
    return CityGroup(
        f"city:es:{codes[0].lower()}", f"City {codes[0]}", "ES", airports
    )


def test_estimate_uses_cheapest_airport_in_city():
    screens = {
        "BCN": AirportScreen("BCN", out={"2026-11-13": 100.0}, ret={"2026-11-15": 60.0}),
        "GRO": AirportScreen("GRO", out={"2026-11-13": 70.0}, ret={"2026-11-15": 90.0}),
    }
    pairs = [DatePair(date(2026, 11, 13), date(2026, 11, 15))]
    candidates = build_candidates([city("BCN", "GRO")], screens, pairs)
    assert len(candidates) == 1
    assert candidates[0].out_price == 70.0
    assert candidates[0].ret_price == 60.0
    assert candidates[0].estimate == 130.0


def test_missing_dates_are_skipped():
    screens = {
        "BCN": AirportScreen("BCN", out={"2026-11-13": 100.0}, ret={"2026-11-16": 60.0}),
    }
    pairs = [
        DatePair(date(2026, 11, 13), date(2026, 11, 15)),
        DatePair(date(2026, 11, 13), date(2026, 11, 16)),
    ]
    candidates = build_candidates([city("BCN")], screens, pairs)
    assert [c.pair.ret for c in candidates] == [date(2026, 11, 16)]


def test_failed_or_empty_screens_are_ignored():
    screens = {"BCN": AirportScreen("BCN", errors=["boom"])}
    pairs = [DatePair(date(2026, 11, 13), date(2026, 11, 15))]
    assert build_candidates([city("BCN")], screens, pairs) == []


def test_candidates_are_sorted_by_estimate():
    screens = {
        "BCN": AirportScreen("BCN", out={"2026-11-13": 100.0}, ret={"2026-11-15": 50.0}),
        "GRO": AirportScreen("GRO", out={"2026-11-13": 60.0}, ret={"2026-11-15": 50.0}),
    }
    pairs = [DatePair(date(2026, 11, 13), date(2026, 11, 15))]
    candidates = build_candidates([city("BCN"), city("GRO")], screens, pairs)
    assert [c.estimate for c in candidates] == [110.0, 150.0]


def test_select_candidates_caps_date_pairs_per_city():
    screens = {}
    pairs = []
    for day in (13, 14, 15, 16, 17):
        pairs.append(DatePair(date(2026, 11, day), date(2026, 11, day + 2)))
        screens[f"A{day}"] = AirportScreen(
            f"A{day}",
            out={date(2026, 11, day).isoformat(): 100.0},
            ret={date(2026, 11, day + 2).isoformat(): 50.0},
        )
    # One city with five date pairs must not fill the shortlist.
    cities = [city("A13", "A14", "A15", "A16", "A17")]
    candidates = build_candidates(cities, screens, pairs)
    shortlist = select_candidates(candidates, per_city=2, limit=10)
    assert len(shortlist) == 2


def test_select_candidates_keeps_distinct_cities():
    screens = {
        "BCN": AirportScreen("BCN", out={"2026-11-13": 100.0}, ret={"2026-11-15": 50.0}),
        "MAD": AirportScreen("MAD", out={"2026-11-13": 110.0}, ret={"2026-11-15": 50.0}),
    }
    pairs = [DatePair(date(2026, 11, 13), date(2026, 11, 15))]
    candidates = build_candidates([city("BCN"), city("MAD")], screens, pairs)
    shortlist = select_candidates(candidates, per_city=1, limit=10)
    assert {c.city.display for c in shortlist} == {"City BCN", "City MAD"}
    assert len(shortlist) == 2


def test_request_estimate_counts_batches():
    estimate = request_estimate(583, 8, 16, home_airports=4, max_candidates=60)
    assert estimate == (8 + 16) * 59 + 120

