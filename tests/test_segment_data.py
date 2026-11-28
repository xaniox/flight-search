"""Segment data of PR 3, commit C1: operating airline and self-transfer.

Every leg records the airline that operates it (the selling one when fli
reports none), every option whether it is a self-transfer; both travel through
the cache and the JSON output, and cache entries written before PR 3 are
misses in both search phases (PRTHREE-CRITERION-01 to -04).
"""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

import pytest
from fake_flights import MISSING, SegmentLeg, SegmentResult, fake_detail_results
from test_cli_golden import AIRPORTS, BASE_ARGS, FrozenDate

from flight_search import cli, fli_api
from flight_search.cache import Cache
from flight_search.combine import FlightOption, LegInfo, options_from_results
from flight_search.config import SearchSettings
from flight_search.detail import _detail_key, fetch_options
from flight_search.discover import _batch_key, run_discovery
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow

DAY = date(2026, 11, 13)


def _when(hour: int = 10) -> datetime:
    return datetime(2026, 11, 13, hour, 0)


def _single_option(leg=None, *, self_transfer=MISSING) -> FlightOption:
    leg = leg or SegmentLeg("MUC", "ATH", _when(), ("A3", "Aegean"))
    options = options_from_results([SegmentResult([leg], self_transfer=self_transfer)])
    assert len(options) == 1
    return options[0]


# --- PRTHREE-CRITERION-01 ---------------------------------------------------


def test_leg_records_operating_airline_reported_by_fli():
    leg = SegmentLeg(
        "MUC", "ATH", _when(), ("A3", "Aegean"), operating=("OA", "Olympic Air")
    )

    info = _single_option(leg).legs[0]

    assert info.airline == "A3"
    assert info.operating_airline == "OA"


def test_operating_airline_code_is_cleaned_like_airline():
    leg = SegmentLeg(
        "CTU", "ATH", _when(), ("_3U", "Sichuan"), operating=("_3U", "Sichuan")
    )

    info = _single_option(leg).legs[0]

    assert info.airline == "3U"
    assert info.operating_airline == "3U"


@pytest.mark.parametrize("operating", [None, MISSING], ids=["none", "missing"])
def test_leg_without_operator_records_selling_airline(operating):
    leg = SegmentLeg("MUC", "ATH", _when(), ("A3", "Aegean"), operating=operating)

    info = _single_option(leg).legs[0]

    assert info.airline == "A3"
    assert info.operating_airline == "A3"


def test_every_leg_of_a_connection_records_its_own_operator():
    legs = [
        SegmentLeg(
            "MUC", "ATH", _when(8), ("A3", "Aegean"), operating=("OA", "Olympic Air")
        ),
        SegmentLeg("ATH", "LCA", _when(12), ("A3", "Aegean"), operating=None),
    ]

    option = options_from_results([SegmentResult(legs)])[0]

    assert [leg.operating_airline for leg in option.legs] == ["OA", "A3"]


# --- PRTHREE-CRITERION-02 ---------------------------------------------------


@pytest.mark.parametrize(
    ("reported", "expected"),
    [(True, True), (False, False), (None, False), (MISSING, False)],
    ids=["true", "false", "none", "missing"],
)
def test_option_records_self_transfer(reported, expected):
    option = _single_option(self_transfer=reported)

    assert option.self_transfer is expected


# --- PRTHREE-CRITERION-03 ---------------------------------------------------

OLD_LEG_DICT = {
    "airline": "A3",
    "airline_name": "Aegean",
    "flight_number": "100",
    "origin": "MUC",
    "destination": "ATH",
    "departure": "2026-11-13T10:00:00",
    "arrival": "2026-11-13T12:00:00",
    "duration": 120,
    "aircraft": None,
    "overnight": False,
}
OLD_OPTION_KEYS = {
    "price": 50.0,
    "currency": "EUR",
    "departure": "2026-11-13T10:00:00",
    "arrival": "2026-11-13T12:00:00",
    "stops": 0,
    "duration": 120,
}


def _operated_option(self_transfer=True) -> FlightOption:
    leg = SegmentLeg(
        "MUC", "ATH", _when(), ("A3", "Aegean"), operating=("OA", "Olympic Air")
    )
    return _single_option(leg, self_transfer=self_transfer)


def test_leg_dict_carries_operating_airline_and_round_trips():
    leg = _operated_option().legs[0]

    data = leg.to_dict()

    assert data["operating_airline"] == "OA"
    assert LegInfo.from_dict(data) == leg


@pytest.mark.parametrize("self_transfer", [True, False])
def test_option_dict_carries_self_transfer_and_round_trips(self_transfer):
    option = _operated_option(self_transfer)

    data = option.to_dict()

    assert data["self_transfer"] is self_transfer
    assert FlightOption.from_dict(data) == option


def test_dicts_keep_every_old_key_with_its_value():
    option = _operated_option()

    data = option.to_dict()

    assert {key: data[key] for key in OLD_OPTION_KEYS} == OLD_OPTION_KEYS
    leg_data = data["legs"][0]
    assert {key: leg_data[key] for key in OLD_LEG_DICT} == OLD_LEG_DICT
    assert set(data) == set(OLD_OPTION_KEYS) | {"legs", "self_transfer"}
    assert set(leg_data) == set(OLD_LEG_DICT) | {"operating_airline"}


@pytest.fixture
def offline_weekend(monkeypatch, tmp_path):
    """The offline setup of the golden-master test of ``weekend``."""
    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)
    monkeypatch.setattr(cli, "date", FrozenDate)
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    for name in ("FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE", "CLICOLOR_FORCE"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "cache"


def test_weekend_json_carries_operating_airline_and_self_transfer(
    offline_weekend, capsys
):
    code = cli.main(
        [*BASE_ARGS, "--cache-dir", str(offline_weekend), "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["results"]
    for result in payload["results"]:
        for direction in ("outbound", "return"):
            option = result[direction]
            assert option["self_transfer"] is False
            assert option["legs"]
            for leg in option["legs"]:
                # The fake reports no operator, so the selling airline operates.
                assert leg["operating_airline"] == leg["airline"]


# --- PRTHREE-CRITERION-04 ---------------------------------------------------

PRE_PR3_OPTION = {
    "price": 999.0,
    "currency": "EUR",
    "departure": "2026-11-13T17:15:00",
    "arrival": "2026-11-13T19:15:00",
    "stops": 0,
    "duration": 120,
    "legs": [
        {
            "airline": "LH",
            "airline_name": "Lufthansa",
            "flight_number": "100",
            "origin": "FRA",
            "destination": "BCN",
            "departure": "2026-11-13T17:15:00",
            "arrival": "2026-11-13T19:15:00",
            "duration": 120,
            "aircraft": None,
            "overnight": False,
        }
    ],
}


def _without_operating_airline() -> dict:
    """Written before PR 3: neither field."""
    return json.loads(json.dumps(PRE_PR3_OPTION))


def _legs_without_operating_airline() -> dict:
    option = _without_operating_airline()
    option["self_transfer"] = False
    return option


def _option_without_self_transfer() -> dict:
    option = _without_operating_airline()
    option["legs"][0]["operating_airline"] = "LH"
    return option


STALE_PAYLOADS = {
    "pre_pr3": _without_operating_airline,
    "legs_lack_operating_airline": _legs_without_operating_airline,
    "option_lacks_self_transfer": _option_without_self_transfer,
}


def _fresh_fetch(calls):
    """One 17:15 flight FRA->BCN (out) or BCN->FRA (ret) for 50 EUR."""

    def fake_detail(
        origins,
        destinations,
        travel_date,
        restrictions,
        settings,
        *,
        return_date=None,
        top_n=1,
    ):
        calls.append((tuple(origins), tuple(destinations), travel_date))
        when = datetime.combine(travel_date, time(17, 15))
        leg = SegmentLeg(
            origins[0], destinations[0], when, ("LH", "Lufthansa"), operating=None
        )
        return [SegmentResult([leg], price=50.0, self_transfer=False)]

    return fake_detail


def _assert_stored_fresh(stored):
    assert isinstance(stored, list)
    assert len(stored) == 1
    assert stored[0]["price"] == 50.0
    assert stored[0]["self_transfer"] is False
    assert stored[0]["legs"][0]["operating_airline"] == "LH"


@pytest.mark.parametrize("stale", sorted(STALE_PAYLOADS))
def test_discovery_treats_entry_without_segment_data_as_miss(
    stale, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _fresh_fetch(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    window = DepartureWindow()
    key = _batch_key(
        ("FRA",), ("BCN",), DAY, "out", SearchSettings(), window.restrictions()
    )
    cache.put(key, [STALE_PAYLOADS[stale]()])

    result = run_discovery(
        destinations=("BCN",),
        home=("FRA",),
        depart_dates=[DAY],
        return_dates=[],
        depart_window=window,
        return_window=ReturnWindow(),
        settings=SearchSettings(),
        cache=cache,
        budget=RequestBudget(10),
        batch_size=10,
        concurrency=1,
    )

    assert result.failures == []
    assert result.requests == 1
    assert len(calls) == 1
    assert result.screens["BCN"].out == {DAY.isoformat(): 50.0}
    _assert_stored_fresh(cache.get(key))


@pytest.mark.parametrize("stale", sorted(STALE_PAYLOADS))
def test_detail_fetch_treats_entry_without_segment_data_as_miss(
    stale, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(fli_api, "detail_results", _fresh_fetch(calls))
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    budget = RequestBudget(10)
    key = _detail_key(("FRA",), ("BCN",), DAY, "out", SearchSettings(), None)
    cache.put(key, [STALE_PAYLOADS[stale]()])

    options = fetch_options(
        home=("FRA",),
        city_codes=("BCN",),
        day=DAY,
        direction="out",
        restrictions=None,
        settings=SearchSettings(),
        cache=cache,
        budget=budget,
    )

    assert len(calls) == 1
    assert budget.used == 1
    assert [option.price for option in options] == [50.0]
    assert options[0].legs[0].operating_airline == "LH"
    assert options[0].self_transfer is False
    _assert_stored_fresh(cache.get(key))
