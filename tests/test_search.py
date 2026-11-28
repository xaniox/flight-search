"""The search core without argparse or rich (PRTWO-CRITERION-05, -06).

The new names are imported inside each test, so each test fails on its own
until ``flight_search.search`` exists.
"""

from __future__ import annotations

import ast
import dataclasses
import importlib
import inspect
from datetime import date, time, timedelta

import pytest
from airport_factory import airport
from fake_flights import fake_detail_results

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.combine import FlightOption, LegInfo
from flight_search.config import SearchSettings
from flight_search.dates import DatePair
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow

HOME = ("FRA", "STR")
# Barcelona is one metro of three airports; Lisbon and Palma are single cities.
DESTINATIONS = (
    airport("BCN", "ES", "EU", municipality="Barcelona", lat=41.30, lon=2.08),
    airport("GRO", "ES", "EU", municipality="Girona", lat=41.90, lon=2.76),
    airport("REU", "ES", "EU", municipality="Reus", lat=41.15, lon=1.17),
    airport("LIS", "PT", "EU", municipality="Lisbon", lat=38.77, lon=-9.13),
    airport("PMI", "ES", "EU", municipality="Palma", lat=39.55, lon=2.73),
)
PAIRS = (
    DatePair(date(2027, 3, 5), date(2027, 3, 7)),
    DatePair(date(2027, 3, 12), date(2027, 3, 14)),
)
BATCH_SIZE = 3


def _request(**changes):
    from flight_search.search import SearchRequest

    values = {
        "home": HOME,
        "destinations": DESTINATIONS,
        "pairs": PAIRS,
        "depart_window": DepartureWindow(),
        "return_window": ReturnWindow(),
        "settings": SearchSettings(),
        "batch_size": BATCH_SIZE,
        "concurrency": 1,
        "max_candidates": 60,
        "per_city": 3,
    }
    values.update(changes)
    return SearchRequest(**values)


def _run(monkeypatch, tmp_path, **changes):
    from flight_search.search import run_search

    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    budget = RequestBudget(1000)
    request = _request(**changes)
    # ttl 0: the cache is off, so every fetch costs one request.
    result = run_search(
        request, cache=Cache(directory=tmp_path, ttl=timedelta(0)), budget=budget
    )
    return request, result, budget


def _imported_modules(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _option(origin, destination, day, hour, price, number):
    departure = f"{day.isoformat()}T{hour:02d}:00:00"
    arrival = f"{day.isoformat()}T{hour + 2:02d}:00:00"
    leg = LegInfo(
        airline="LH",
        airline_name="Lufthansa",
        flight_number=str(number),
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        duration=120,
    )
    return FlightOption(
        price=price,
        currency="EUR",
        departure=departure,
        arrival=arrival,
        stops=0,
        duration=120,
        legs=(leg,),
    )


def _sort_key(itinerary):
    return (itinerary.total, itinerary.depart_date, itinerary.return_date)


# --- PRTWO-CRITERION-05 ------------------------------------------------------


def test_run_search_returns_result_with_request_shortlist_options_stats_failures(
    monkeypatch, tmp_path
):
    from flight_search.search import SearchResult

    request, result, _ = _run(monkeypatch, tmp_path)

    assert isinstance(result, SearchResult)
    assert result.request is request
    assert isinstance(result.shortlist, tuple)
    assert result.shortlist
    assert result.stats is not None
    assert result.failures == ()
    # Barcelona, Lisbon and Palma, each with both date pairs (per_city 3).
    assert {c.city.key for c in result.shortlist} == {
        "metro:barcelona",
        "city:PT:lisbon",
        "city:ES:palma",
    }
    assert len(result.shortlist) == 6


def test_run_search_options_are_keyed_by_city_day_and_direction(monkeypatch, tmp_path):
    _, result, _ = _run(monkeypatch, tmp_path)

    expected = set()
    for candidate in result.shortlist:
        expected.add((candidate.city.key, candidate.pair.depart, "out"))
        expected.add((candidate.city.key, candidate.pair.ret, "ret"))
    assert set(result.options) == expected
    for key, options in result.options.items():
        assert isinstance(options, tuple)
        assert options
        assert all(isinstance(option, FlightOption) for option in options)
        _, day, direction = key
        for option in options:
            assert option.departure.startswith(day.isoformat())
            home_side = option.origin if direction == "out" else option.destination
            assert home_side in HOME


def test_run_search_keeps_options_outside_the_window(monkeypatch, tmp_path):
    _, result, _ = _run(
        monkeypatch, tmp_path, depart_window=DepartureWindow(after=time(17, 0))
    )

    outbound = [
        option
        for (_, _, direction), options in result.options.items()
        if direction == "out"
        for option in options
    ]
    # The fake's 07:10 departure lies outside the window but stays in options.
    assert any(option.departure.endswith("T07:10:00") for option in outbound)


def test_run_search_budget_counts_discovery_jobs_plus_two_per_candidate(
    monkeypatch, tmp_path
):
    _, result, budget = _run(monkeypatch, tmp_path)

    batches = -(-len(DESTINATIONS) // BATCH_SIZE)
    depart_dates = {pair.depart for pair in PAIRS}
    return_dates = {pair.ret for pair in PAIRS}
    discovery_jobs = (len(depart_dates) + len(return_dates)) * batches
    assert budget.used == discovery_jobs + 2 * len(result.shortlist)


def test_search_module_imports_neither_argparse_nor_rich():
    search = importlib.import_module("flight_search.search")

    imported = _imported_modules(search)
    assert "argparse" not in imported
    assert "rich" not in imported


# --- PRTWO-CRITERION-06 ------------------------------------------------------


def test_itineraries_apply_the_departure_window(monkeypatch, tmp_path):
    _, result, _ = _run(
        monkeypatch, tmp_path, depart_window=DepartureWindow(after=time(17, 0))
    )

    itineraries = result.itineraries()
    assert itineraries
    assert all(not it.out.departure.endswith("T07:10:00") for it in itineraries)
    assert all(it.out.departure[11:16] >= "17:00" for it in itineraries)


def test_itineraries_apply_the_return_window(monkeypatch, tmp_path):
    _, result, _ = _run(
        monkeypatch,
        tmp_path,
        return_window=ReturnWindow(depart_after=time(18, 0)),
    )

    itineraries = result.itineraries()
    returns = [
        option
        for (_, _, direction), options in result.options.items()
        if direction == "ret"
        for option in options
    ]
    # The fake's 10:15 return stays in options but not in the itineraries.
    assert any(option.departure.endswith("T10:15:00") for option in returns)
    assert itineraries
    assert all(it.ret.departure[11:16] >= "18:00" for it in itineraries)


def _hand_built(result, options_by_candidate):
    """The result with its options replaced: one (outs, rets) per candidate."""
    options = {}
    for candidate, (outs, rets) in zip(
        result.shortlist, options_by_candidate, strict=False
    ):
        options[(candidate.city.key, candidate.pair.depart, "out")] = tuple(outs)
        options[(candidate.city.key, candidate.pair.ret, "ret")] = tuple(rets)
    for candidate in result.shortlist[len(options_by_candidate) :]:
        options[(candidate.city.key, candidate.pair.depart, "out")] = ()
        options[(candidate.city.key, candidate.pair.ret, "ret")] = ()
    return dataclasses.replace(result, options=options)


def test_itineraries_combine_the_cheapest_option_per_airport_pair(
    monkeypatch, tmp_path
):
    _, result, _ = _run(monkeypatch, tmp_path)
    first = result.shortlist[0]
    code = first.city.codes[0]
    depart, ret = first.pair.depart, first.pair.ret
    dear = _option("FRA", code, depart, 18, 80.0, 1)
    cheap = _option("FRA", code, depart, 19, 60.0, 2)
    back = _option(code, "FRA", ret, 18, 30.0, 3)

    itineraries = _hand_built(result, [([dear, cheap], [back])]).itineraries()

    assert len(itineraries) == 1
    assert itineraries[0].out == cheap
    assert itineraries[0].total == 90.0


def test_itineraries_drop_a_signature_seen_in_an_earlier_candidate(
    monkeypatch, tmp_path
):
    _, result, _ = _run(monkeypatch, tmp_path)
    first, second = result.shortlist[0], result.shortlist[1]
    out = _option("FRA", first.city.codes[0], first.pair.depart, 18, 40.0, 1)
    back = _option(first.city.codes[0], "FRA", first.pair.ret, 18, 30.0, 2)
    other_back = _option(second.city.codes[0], "STR", second.pair.ret, 19, 35.0, 3)

    itineraries = _hand_built(
        result, [([out], [back]), ([out], [back, other_back])]
    ).itineraries()

    signatures = [(it.out.signature, it.ret.signature) for it in itineraries]
    assert len(signatures) == len(set(signatures)) == 2
    assert itineraries[0].city_key == first.city.key
    assert itineraries[1].city_key == second.city.key
    assert itineraries[1].ret == other_back


def test_itineraries_sort_by_total_then_depart_then_return_date(monkeypatch, tmp_path):
    _, result, _ = _run(monkeypatch, tmp_path)
    shortlist = result.shortlist
    per_candidate = []
    # The later candidates are cheaper; two candidates tie on the total.
    for index, candidate in enumerate(shortlist[:4]):
        code = candidate.city.codes[0]
        price = {0: 90.0, 1: 70.0, 2: 50.0, 3: 50.0}[index]
        per_candidate.append(
            (
                [_option("FRA", code, candidate.pair.depart, 18, price, 10 + index)],
                [_option(code, "FRA", candidate.pair.ret, 18, 20.0, 20 + index)],
            )
        )

    itineraries = _hand_built(result, per_candidate).itineraries()

    assert [_sort_key(it) for it in itineraries] == sorted(
        _sort_key(it) for it in itineraries
    )
    assert [it.total for it in itineraries] == [70.0, 70.0, 90.0, 110.0]
    assert itineraries[0].depart_date <= itineraries[1].depart_date


def test_itineraries_are_not_cut_to_a_top_n(monkeypatch, tmp_path):
    _, result, _ = _run(monkeypatch, tmp_path)
    first = result.shortlist[0]
    depart, ret = first.pair.depart, first.pair.ret
    # 2 home x 3 foreign airports in each direction: 6 x 6 = 36 itineraries.
    outs = [
        _option(home, code, depart, 18, 40.0 + i + j, 100 + 10 * i + j)
        for i, home in enumerate(HOME)
        for j, code in enumerate(("BCN", "GRO", "REU"))
    ]
    rets = [
        _option(code, home, ret, 19, 30.0 + i + j, 200 + 10 * i + j)
        for i, home in enumerate(HOME)
        for j, code in enumerate(("BCN", "GRO", "REU"))
    ]

    itineraries = _hand_built(result, [(outs, rets)]).itineraries()

    assert len(itineraries) == 36


def test_itineraries_returns_new_objects_on_each_call(monkeypatch, tmp_path):
    _, result, _ = _run(monkeypatch, tmp_path)

    first = result.itineraries()
    assert first
    first[0].booking_url = "https://example.invalid/changed"
    first[0].roundtrip_price = 1.0
    second = result.itineraries()

    assert all(a is not b for a, b in zip(first, second, strict=True))
    assert second[0].booking_url is None
    assert second[0].roundtrip_price is None


# --- PRTWO-CRITERION-15: --max-candidates below 1 confirms nothing -----------


def _discovery_jobs(pairs) -> int:
    batches = -(-len(DESTINATIONS) // BATCH_SIZE)
    depart_dates = {pair.depart for pair in pairs}
    return_dates = {pair.ret for pair in pairs}
    return (len(depart_dates) + len(return_dates)) * batches


def _count_leg_fetches(monkeypatch) -> list:
    """Every ``fli_api.fetch_leg`` call: the discovery jobs and the phase-2 fetches."""
    calls = []
    real_fetch_leg = fli_api.fetch_leg

    def counting_fetch_leg(home, codes, day, direction, restrictions, settings):
        calls.append((tuple(codes), day, direction))
        return real_fetch_leg(home, codes, day, direction, restrictions, settings)

    monkeypatch.setattr(fli_api, "fetch_leg", counting_fetch_leg)
    return calls


@pytest.mark.parametrize("max_candidates", [0, -1])
def test_run_search_with_max_candidates_below_one_confirms_nothing(
    monkeypatch, tmp_path, max_candidates
):
    fetches = _count_leg_fetches(monkeypatch)

    _, result, budget = _run(monkeypatch, tmp_path, max_candidates=max_candidates)

    assert result.stats.candidates > 0
    assert result.shortlist == ()
    assert result.stats.shortlisted == 0
    assert len(fetches) == _discovery_jobs(PAIRS)
    assert budget.used == _discovery_jobs(PAIRS)
    assert result.itineraries() == []


def test_weekend_max_candidates_0_prints_no_itineraries_confirmed_and_exits_1(
    monkeypatch, tmp_path, capsys
):
    from test_cli_golden import AIRPORTS, BASE_ARGS, FrozenDate

    from flight_search import cli

    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)
    monkeypatch.setattr(cli, "date", FrozenDate)
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    fetches = _count_leg_fetches(monkeypatch)

    code = cli.main(
        [
            *BASE_ARGS,
            "--cache-dir",
            str(tmp_path / "cache"),
            "--max-candidates",
            "0",
        ]
    )
    captured = capsys.readouterr()

    # 3 departure + 3 return dates, one batch of the 6 default-region airports:
    # the 6 discovery jobs and not a single phase-2 fetch.
    assert len(fetches) == 6
    assert "No itineraries confirmed." in captured.err
    assert code == 1


# --- PRTWO-CRITERION-16: a repeated (city, day, direction) with the cache off --

# Friday 5 March to Sunday 7 and to Monday 8: both pairs share the departure day.
SHARED_DEPART_PAIRS = (
    DatePair(date(2027, 3, 5), date(2027, 3, 7)),
    DatePair(date(2027, 3, 5), date(2027, 3, 8)),
)


def test_run_search_without_cache_fetches_a_repeated_city_day_direction_again(
    monkeypatch, tmp_path
):
    fetches = _count_leg_fetches(monkeypatch)

    _, result, budget = _run(monkeypatch, tmp_path, pairs=SHARED_DEPART_PAIRS)

    outbound = [(c.city.key, c.pair.depart) for c in result.shortlist]
    # Each city is shortlisted with both pairs, so its outbound day repeats.
    assert len(outbound) > len(set(outbound))
    assert len(fetches) == _discovery_jobs(SHARED_DEPART_PAIRS) + 2 * len(
        result.shortlist
    )
    assert budget.used == _discovery_jobs(SHARED_DEPART_PAIRS) + 2 * len(
        result.shortlist
    )


def test_confirm_options_docstring_says_the_cache_answers_a_repeat_only_when_on():
    from flight_search.detail import confirm_options

    doc = " ".join((confirm_options.__doc__ or "").split()).lower()
    assert "only when the cache is on" in doc or "with the cache on" in doc
