"""Confirming more candidates of one city on demand (browser "weitere laden").

The new names are imported inside each test, so each test fails on its own
until the feature exists.
"""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta
from threading import Event

import pytest
from airport_factory import airport
from fake_flights import fake_detail_results
from test_search import _request
from test_web import start_search, wait_for_final_state

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.config import KARLSRUHE, SearchSettings
from flight_search.dates import DatePair
from flight_search.destinations import DestinationChoice
from flight_search.fli_api import RequestBudget
from flight_search.weekend import WeekendQuery

BARCELONA = "metro:barcelona"
PALMA = "city:ES:palma"
LISBON = "city:PT:lisbon"
# Two pairs share the outbound day 5 March, two share the return day 14 March.
SHARED_PAIRS = (
    DatePair(date(2027, 3, 5), date(2027, 3, 7)),
    DatePair(date(2027, 3, 5), date(2027, 3, 14)),
    DatePair(date(2027, 3, 12), date(2027, 3, 14)),
)
# Phase-1 estimates under the fake flights, in rank order (cheapest first):
#   Barcelona 5->14 71, 12->14 89, 5->7 98
#   Palma     5->7 94, 5->14 112, 12->14 130
#   Lisbon    5->14 105, 12->14 123, 5->7 132
# With per_city=1 the shortlist is Barcelona 5->14, Palma 5->7, Lisbon 5->14.


@pytest.fixture
def searched(monkeypatch, tmp_path):
    """A per_city=1 result plus the cache and budget that produced it."""
    from flight_search.search import run_search

    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    budget = RequestBudget(1000)
    result = run_search(
        _request(per_city=1, pairs=SHARED_PAIRS), cache=cache, budget=budget
    )
    return result, cache, budget


def city_pairs(result, city_key):
    return [c.pair for c in result.shortlist if c.city.key == city_key]


def test_run_search_keeps_all_ranked_candidates(searched):
    result, _, _ = searched

    assert len(result.candidates) == 9
    estimates = [c.estimate for c in result.candidates]
    assert estimates == sorted(estimates)
    assert all(candidate in result.candidates for candidate in result.shortlist)
    assert [c.city.key for c in result.shortlist] == [BARCELONA, PALMA, LISBON]


def test_search_result_candidates_default_to_empty():
    from flight_search.search import SearchResult

    field = {f.name: f for f in dataclasses.fields(SearchResult)}["candidates"]
    assert field.default == ()


def test_confirm_more_takes_the_next_ranked_candidate_of_that_city(searched):
    from flight_search.search import confirm_more

    result, cache, budget = searched
    before = budget.used

    more = confirm_more(result, BARCELONA, 1, cache=cache, budget=budget)

    assert city_pairs(more, BARCELONA) == [
        DatePair(date(2027, 3, 5), date(2027, 3, 14)),
        DatePair(date(2027, 3, 12), date(2027, 3, 14)),
    ]
    assert more.shortlist[: len(result.shortlist)] == result.shortlist
    assert len(more.shortlist) == len(result.shortlist) + 1
    assert more.candidates == result.candidates
    assert more.request == result.request
    assert (BARCELONA, date(2027, 3, 12), "out") in more.options
    for key, value in result.options.items():
        assert more.options[key] == value
    # Only the missing outbound day is fetched: the return day is cached.
    assert budget.used - before == 1
    assert len(more.itineraries()) > len(result.itineraries())


def test_confirm_more_takes_at_most_count_and_leaves_other_cities_alone(searched):
    from flight_search.search import confirm_more

    result, cache, budget = searched

    more = confirm_more(result, PALMA, 5, cache=cache, budget=budget)

    assert city_pairs(more, PALMA) == [
        DatePair(date(2027, 3, 5), date(2027, 3, 7)),
        DatePair(date(2027, 3, 5), date(2027, 3, 14)),
        DatePair(date(2027, 3, 12), date(2027, 3, 14)),
    ]
    assert city_pairs(more, BARCELONA) == city_pairs(result, BARCELONA)
    assert city_pairs(more, LISBON) == city_pairs(result, LISBON)
    assert {key for key in more.options if key[0] != PALMA} == {
        key for key in result.options if key[0] != PALMA
    }


def test_confirm_more_shares_fetches_of_equal_dates(searched):
    from flight_search.search import confirm_more

    result, cache, budget = searched
    before = budget.used

    confirm_more(result, PALMA, 2, cache=cache, budget=budget)

    # 5->14 and 12->14 need the outbound 12 and the return 14 once each.
    assert budget.used - before == 2


def test_confirm_more_without_anything_to_confirm_does_not_fetch(searched):
    from flight_search.search import confirm_more

    result, cache, budget = searched
    before = budget.used

    unknown = confirm_more(result, "city:XX:nowhere", 2, cache=cache, budget=budget)
    assert unknown == result

    done = confirm_more(result, LISBON, 10, cache=cache, budget=budget)
    after_all = budget.used
    again = confirm_more(done, LISBON, 2, cache=cache, budget=budget)

    assert again == done
    assert budget.used == after_all
    assert after_all > before


def real_app(*, extra_airports=(), **options):
    from flight_search.web import create_app

    airports = (
        airport("BCN", "ES", "EU", municipality="Barcelona", lat=41.30, lon=2.08),
        airport("FRA", "DE", "EU", municipality="Frankfurt", lat=50.03, lon=8.56),
        airport("LIS", "PT", "EU", municipality="Lisbon", lat=38.77, lon=-9.13),
        airport("PMI", "ES", "EU", municipality="Palma", lat=39.55, lon=2.73),
        *extra_airports,
    )
    start = date.today() + timedelta(days=14)
    start += timedelta(days=(4 - start.weekday()) % 7)
    query = WeekendQuery(
        start=start.isoformat(),
        end=(start + timedelta(days=16)).isoformat(),
        depart_days=("fri",),
        return_days=("sun",),
        min_nights=2,
        max_nights=2,
        home=("FRA",),
        destination=DestinationChoice(region="europe"),
        center=KARLSRUHE,
        settings=SearchSettings(currency="EUR"),
        max_requests=200,
        per_city=1,
    )
    return create_app(
        query,
        configured_regions={},
        airport_loader=lambda *, include_small: airports,
        cache_enabled=False,
        **options,
    )


@pytest.fixture
def finished(monkeypatch):
    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    client = real_app().test_client()
    path = start_search(client)
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    return client, path, state["result"]


def more_url(path, city_key=LISBON):
    return f"{path}/cities/{city_key}/more"


def test_finished_state_carries_pending_per_city(finished):
    _, _, result = finished

    pending = result["pending"]
    assert set(pending) == {pair["city_key"] for pair in result["pairs"]}
    for entry in pending.values():
        assert entry["remaining"] == 2
        assert entry["low"] <= entry["high"]
        assert entry["next_requests"] == 2
    assert result["per_city"] == 1


def test_more_endpoint_rejects_a_foreign_origin(finished):
    client, path, _ = finished

    response = client.post(more_url(path), headers={"Origin": "http://evil.example"})

    assert response.status_code == 403


def test_more_endpoint_answers_404_for_an_unknown_search(finished):
    client, _, _ = finished

    response = client.post(more_url("/api/searches/unknown"))

    assert response.status_code == 404
    assert response.get_json() == {"error": "Search not found."}


def test_more_endpoint_answers_409_while_the_search_runs(monkeypatch):
    release = Event()

    def runner(request, *, cache, budget, progress):
        assert release.wait(5)
        raise RuntimeError("stop")

    client = real_app(search_runner=runner).test_client()
    path = start_search(client)
    try:
        response = client.post(more_url(path))
        assert response.status_code == 409
    finally:
        release.set()
    wait_for_final_state(client, path)


def lisbon_dates(payload):
    return {
        group["date"]
        for group in payload["outbound_choices"]["outbound_groups"]
        if group["city_key"] == LISBON
    }


def test_more_endpoint_confirms_the_next_candidates_of_one_city(finished):
    client, path, before = finished
    lisbon_before = [p for p in before["pairs"] if p["city_key"] == LISBON]

    response = client.post(more_url(path))

    assert response.status_code == 200
    after = response.get_json()
    assert set(after) == {
        "pairs",
        "outbound_choices",
        "per_city",
        "pending",
        "currency",
    }
    assert after["per_city"] == 1
    lisbon_after = [p for p in after["pairs"] if p["city_key"] == LISBON]
    assert len(lisbon_after) > len(lisbon_before)
    assert after["pending"][LISBON]["remaining"] == 1
    for city_key, entry in before["pending"].items():
        if city_key != LISBON:
            assert after["pending"][city_key] == entry
    others = lambda payload: [
        p["city_key"] for p in payload["pairs"] if p["city_key"] != LISBON
    ]
    assert others(after) == others(before)

    last = client.post(more_url(path))
    assert last.status_code == 200
    assert LISBON not in last.get_json()["pending"]
    assert len(last.get_json()["pairs"]) > len(after["pairs"])


def test_more_endpoint_keeps_booking_links_of_new_flights_working(finished):
    client, path, before = finished
    old_dates = lisbon_dates(before)

    after = client.post(more_url(path)).get_json()

    new_groups = [
        group
        for group in after["outbound_choices"]["outbound_groups"]
        if group["city_key"] == LISBON and group["date"] not in old_dates
    ]
    assert new_groups
    choices = after["outbound_choices"]
    checked = 0
    for group in new_groups:
        for return_group_id in group["return_groups"]:
            for outbound_id in group["options"]:
                for return_id in choices["return_groups"][return_group_id]["options"]:
                    response = client.get(
                        f"{path}/booking?outbound={outbound_id}&return={return_id}"
                    )
                    assert response.status_code == 302
                    checked += 1
    assert checked


def test_pending_by_city_reports_remaining_range_and_distinct_requests(searched):
    from flight_search.web_results import pending_by_city

    result, _, _ = searched

    numbers = ("remaining", "low", "high", "next_requests")
    pending = pending_by_city(result, 2)
    assert {
        city: {k: entry[k] for k in numbers} for city, entry in pending.items()
    } == {
        BARCELONA: {"remaining": 2, "low": 89.0, "high": 98.0, "next_requests": 2},
        # 5->14 and 12->14 share the return day: out 12 and ret 14, once each.
        PALMA: {"remaining": 2, "low": 112.0, "high": 130.0, "next_requests": 2},
        LISBON: {"remaining": 2, "low": 123.0, "high": 132.0, "next_requests": 2},
    }


def test_pending_by_city_counts_only_the_next_candidates_and_missing_fetches(
    searched,
):
    from flight_search.web_results import pending_by_city

    result, _, _ = searched

    pending = pending_by_city(result, 1)

    # Barcelona's next candidate is 12->14; its return day 14 is already fetched.
    assert pending[BARCELONA] == {
        "city": "Barcelona",
        "country": "ES",
        "remaining": 2,
        "low": 89.0,
        "high": 98.0,
        "next_requests": 1,
    }
    # Palma's next candidate is 5->14; its outbound day 5 is already fetched.
    assert pending[PALMA]["next_requests"] == 1
    assert pending[PALMA]["remaining"] == 2


def test_pending_by_city_drops_cities_with_nothing_left(searched):
    from flight_search.search import confirm_more
    from flight_search.web_results import pending_by_city

    result, cache, budget = searched

    more = confirm_more(result, PALMA, 5, cache=cache, budget=budget)
    pending = pending_by_city(more, 2)

    assert set(pending) == {BARCELONA, LISBON}
    # Day 12 outbound and day 14 return of Barcelona 12->14 + 5->7: out 12, ret 7.
    assert pending[BARCELONA]["next_requests"] == 2
    everything = result
    for key in (BARCELONA, LISBON):
        everything = confirm_more(everything, key, 5, cache=cache, budget=budget)
    assert (
        pending_by_city(
            confirm_more(everything, PALMA, 5, cache=cache, budget=budget), 2
        )
        == {}
    )


@pytest.fixture
def searched_uncached(monkeypatch, tmp_path):
    """A per_city=1 result whose cache is off, so every fetch is a request."""
    from flight_search.search import run_search

    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1), enabled=False)
    budget = RequestBudget(1000)
    result = run_search(
        _request(per_city=1, pairs=SHARED_PAIRS), cache=cache, budget=budget
    )
    return result, cache, budget


def test_pending_entries_carry_the_display_name_and_country(searched):
    from flight_search.web_results import pending_by_city

    result, _, _ = searched

    pending = pending_by_city(result, 1)

    assert pending[BARCELONA]["city"] == "Barcelona"
    assert pending[BARCELONA]["country"] == "ES"
    assert pending[LISBON]["city"] == "Lisbon"
    assert pending[LISBON]["country"] == "PT"


def test_confirm_more_spends_the_requests_the_button_promised(searched_uncached):
    from flight_search.search import confirm_more
    from flight_search.web_results import pending_by_city

    result, cache, budget = searched_uncached
    promised = pending_by_city(result, 2)[PALMA]["next_requests"]
    before = budget.used

    confirm_more(result, PALMA, 2, cache=cache, budget=budget)

    assert budget.used - before == promised


def test_confirm_more_never_refetches_a_confirmed_city_day_direction(
    searched_uncached, monkeypatch
):
    from flight_search import detail, search
    from flight_search.search import confirm_more

    result, cache, budget = searched_uncached
    codes = {c.city.key: c.city.codes for c in result.candidates}
    fetched = []
    original = detail.fetch_options

    def counting(**kwargs):
        fetched.append((kwargs["city_codes"], kwargs["day"], kwargs["direction"]))
        return original(**kwargs)

    monkeypatch.setattr(search, "fetch_options", counting)

    confirm_more(result, PALMA, 2, cache=cache, budget=budget)

    assert fetched

    already = {(codes[key], day, direction) for key, day, direction in result.options}
    assert [fetch for fetch in fetched if fetch in already] == []
    assert len(fetched) == len(set(fetched))


SLASH_AIRPORT = airport(
    "MPL", "FR", "EU", municipality="Montpellier/Méditerranée", lat=43.58, lon=3.96
)


def test_more_endpoint_works_for_a_city_key_with_a_slash(monkeypatch):
    from urllib.parse import quote

    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    client = real_app(extra_airports=(SLASH_AIRPORT,)).test_client()
    path = start_search(client)
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    keys = [key for key in state["result"]["pending"] if "/" in key]
    assert keys, state["result"]["pending"]

    response = client.post(f"{path}/cities/{quote(keys[0], safe='')}/more")

    assert response.status_code == 200, response.get_data(as_text=True)
    assert keys[0] not in response.get_json()["pending"] or (
        response.get_json()["pending"][keys[0]]["remaining"]
        < state["result"]["pending"][keys[0]]["remaining"]
    )


def failed_search(monkeypatch):
    def runner(request, *, cache, budget, progress):
        raise RuntimeError("boom")

    client = real_app(search_runner=runner).test_client()
    path = start_search(client)
    state = wait_for_final_state(client, path)
    assert state["status"] == "error"
    return client, path


def test_more_endpoint_on_a_failed_search_does_not_claim_it_still_runs(monkeypatch):
    client, path = failed_search(monkeypatch)

    response = client.post(more_url(path))

    assert response.status_code == 409
    assert "not finished" not in response.get_json()["error"]


def test_more_endpoint_foreign_origin_text_is_about_loading(finished):
    client, path, _ = finished

    response = client.post(more_url(path), headers={"Origin": "http://evil.example"})

    assert response.status_code == 403
    assert "Searches must start" not in response.get_json()["error"]
