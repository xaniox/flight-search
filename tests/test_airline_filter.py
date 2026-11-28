"""The airline filter per segment of PR 3, commit C5 (PRTHREE-CRITERION-23 to -29).

``--airlines A3,OA`` keeps an itinerary only when every leg of both directions
is sold and operated by a listed airline; ``--allow-codeshare`` checks the
selling airline only. Discovery prices an airport only from matching flights,
``SearchResult.itineraries()`` combines only matching options, and neither
cache key carries the filter.

Seams: ``SearchRequest(airlines=frozenset[str], allow_codeshare=bool)`` (both
with a default: empty and False) and the keyword arguments of the same names
of ``run_discovery``. The CLI is driven offline with the fake of the
golden-master test, whose legs report no operator, so each is operated by its
selling airline: FRA-FCO and every STR route except FCO and PMI are FR.
"""

from __future__ import annotations

import dataclasses
import json
import re
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest
from airport_factory import airport
from fake_flights import FakeAirline, SegmentLeg, SegmentResult, fake_detail_results
from test_cli_golden import AIRPORTS, BASE_ARGS, FrozenDate

from flight_search import cli, fli_api
from flight_search.cache import Cache
from flight_search.combine import FlightOption, LegInfo
from flight_search.config import SearchSettings
from flight_search.dates import DatePair
from flight_search.discover import run_discovery
from flight_search.fli_api import RequestBudget
from flight_search.search import SearchRequest, run_search
from flight_search.windows import DepartureWindow, ReturnWindow

README = Path(__file__).resolve().parent.parent / "README.md"


# --- the offline command line ---------------------------------------------------


@pytest.fixture
def offline(monkeypatch, tmp_path):
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


def _run(argv: list[str]) -> int | str | None:
    try:
        return cli.main(argv)
    except SystemExit as exc:
        return exc.code


def _weekend(offline, capsys, *extra: str) -> tuple[object, str, str]:
    capsys.readouterr()
    code = _run([*BASE_ARGS, "--cache-dir", str(offline), *extra])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def _json_payload(offline, capsys, *extra: str) -> dict:
    code, out, err = _weekend(offline, capsys, "--format", "json", *extra)
    assert code == 0, err
    return json.loads(out)


def _all_legs(payload: dict) -> list[dict]:
    return [
        leg
        for result in payload["results"]
        for direction in ("outbound", "return")
        for leg in result[direction]["legs"]
    ]


class _Stop(Exception):
    """Raised by the fake run_search once it has the request."""


def _weekend_request(monkeypatch, offline, *extra: str) -> SearchRequest:
    captured = {}

    def fake_run_search(request, **_kwargs):
        captured["request"] = request
        raise _Stop

    monkeypatch.setattr(cli, "run_search", fake_run_search)
    code = _run([*BASE_ARGS, "--cache-dir", str(offline), *extra])
    assert "request" in captured, f"the search was not reached (exit {code})"
    return captured["request"]


def _write_config(config_home: Path, text: str) -> None:
    path = config_home / "flight-search" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --- hand-built options -----------------------------------------------------------


def _leg(origin, destination, departure: datetime, airline, operating=""):
    return LegInfo(
        airline=airline,
        airline_name=airline,
        flight_number="100",
        origin=origin,
        destination=destination,
        departure=departure.isoformat(),
        arrival=(departure + timedelta(hours=2)).isoformat(),
        duration=120,
        operating_airline=operating,
    )


def _option(route, day: date, hour: int, price: float, airlines) -> FlightOption:
    """A one-way option along ``route`` (airport codes), one leg per hop.

    ``airlines`` holds one ``selling`` or ``(selling, operating)`` per leg.
    """
    legs = []
    when = datetime.combine(day, time(hour, 0))
    for index, spec in enumerate(airlines):
        selling, operating = (spec, "") if isinstance(spec, str) else spec
        legs.append(_leg(route[index], route[index + 1], when, selling, operating))
        when += timedelta(hours=3)
    return FlightOption(
        price=price,
        currency="EUR",
        departure=legs[0].departure,
        arrival=legs[-1].arrival,
        stops=len(legs) - 1,
        duration=120 * len(legs),
        legs=tuple(legs),
    )


# FRA-BCN and FRA-LIS are VY, STR-BCN and STR-LIS are FR in both directions.
HOME = ("FRA", "STR")
DESTINATIONS = (
    airport("BCN", "ES", "EU", municipality="Barcelona", lat=41.30, lon=2.08),
    airport("LIS", "PT", "EU", municipality="Lisbon", lat=38.77, lon=-9.13),
)
PAIRS = (DatePair(date(2027, 3, 5), date(2027, 3, 7)),)


def _request(**changes) -> SearchRequest:
    values = {
        "home": HOME,
        "destinations": DESTINATIONS,
        "pairs": PAIRS,
        "depart_window": DepartureWindow(),
        "return_window": ReturnWindow(),
        "settings": SearchSettings(),
        "batch_size": 10,
        "concurrency": 1,
        "max_candidates": 60,
        "per_city": 3,
    }
    values.update(changes)
    return SearchRequest(**values)


def _search(monkeypatch, tmp_path, request=None, cache=None, budget=None):
    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    return run_search(
        request or _request(),
        cache=cache or Cache(directory=tmp_path, ttl=timedelta(0)),
        budget=budget or RequestBudget(1000),
    )


def _with_options(monkeypatch, tmp_path, outs, rets, **request_changes):
    """A result for one candidate whose options are ``outs`` and ``rets``.

    The candidate is the first of the shortlist; ``outs`` and ``rets`` go from
    and to its first city airport.
    """
    result = _search(monkeypatch, tmp_path)
    candidate = result.shortlist[0]
    code = candidate.city.codes[0]
    depart, ret = candidate.pair.depart, candidate.pair.ret
    options = {
        (candidate.city.key, depart, "out"): tuple(
            _option(("FRA", *via, code), depart, hour, price, airlines)
            for via, hour, price, airlines in outs
        ),
        (candidate.city.key, ret, "ret"): tuple(
            _option((code, *via, "FRA"), ret, hour, price, airlines)
            for via, hour, price, airlines in rets
        ),
    }
    request = _request(**request_changes)
    return dataclasses.replace(
        result, request=request, shortlist=(candidate,), options=options
    )


def _leg_airlines(option: FlightOption) -> list[tuple[str, str]]:
    return [(leg.airline, leg.operating_airline) for leg in option.legs]


# --- PRTHREE-CRITERION-23: the strict rule ------------------------------------------


def test_airlines_keeps_only_itineraries_whose_every_leg_is_listed(offline, capsys):
    unfiltered = _json_payload(offline, capsys)
    assert {leg["airline"] for leg in _all_legs(unfiltered)} - {"FR"}

    # Case-insensitive, blanks trimmed.
    payload = _json_payload(offline, capsys, "--airlines", " fr ")

    legs = _all_legs(payload)
    assert legs
    assert {(leg["airline"], leg["operating_airline"]) for leg in legs} == {
        ("FR", "FR")
    }


def test_airlines_are_parsed_case_insensitive_and_trimmed(monkeypatch, offline):
    request = _weekend_request(monkeypatch, offline, "--airlines", " a3 , oA ")

    assert request.airlines == frozenset({"A3", "OA"})


def test_without_airlines_the_request_has_an_empty_list(monkeypatch, offline):
    request = _weekend_request(monkeypatch, offline)

    assert request.airlines == frozenset()
    assert request.allow_codeshare is False


def test_an_itinerary_with_one_leg_of_another_airline_is_dropped(monkeypatch, tmp_path):
    # MUC->ATH A3 + ATH->HER GQ, here FRA->ATH A3 + ATH->BCN GQ.
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[(("ATH",), 9, 60.0, ["A3", "GQ"])],
        rets=[((), 18, 30.0, ["A3"])],
        airlines=frozenset({"A3"}),
    )

    assert result.itineraries() == []


def test_a_return_leg_of_another_airline_drops_the_itinerary(monkeypatch, tmp_path):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 60.0, ["A3"])],
        rets=[(("ATH",), 18, 30.0, ["A3", "GQ"])],
        airlines=frozenset({"A3"}),
    )

    assert result.itineraries() == []


def test_a_codeshare_leg_passes_when_both_airlines_are_listed(monkeypatch, tmp_path):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 60.0, [("A3", "OA")])],
        rets=[((), 18, 30.0, ["OA"])],
        airlines=frozenset({"A3", "OA"}),
    )

    itineraries = result.itineraries()

    assert len(itineraries) == 1
    assert _leg_airlines(itineraries[0].out) == [("A3", "OA")]


def test_a_codeshare_leg_fails_when_only_the_selling_airline_is_listed(
    monkeypatch, tmp_path
):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 60.0, [("A3", "OA")])],
        rets=[((), 18, 30.0, ["A3"])],
        airlines=frozenset({"A3"}),
    )

    assert result.itineraries() == []


def test_without_airlines_nothing_is_filtered(monkeypatch, tmp_path):
    # Guard: holds before the change too.
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[(("ATH",), 9, 60.0, ["A3", ("GQ", "OA")])],
        rets=[((), 18, 30.0, ["LH"])],
    )

    assert len(result.itineraries()) == 1


@pytest.mark.parametrize("entry", ["LUFT", "A", "A-"])
def test_an_airline_entry_that_is_not_two_letters_or_digits_ends_with_exit_2(
    monkeypatch, offline, capsys, entry
):
    reached = []

    def fake_run_search(request, **_kwargs):
        reached.append(request)
        raise _Stop

    monkeypatch.setattr(cli, "run_search", fake_run_search)

    code, out, err = _weekend(offline, capsys, "--airlines", f"A3,{entry}")

    assert code == 2
    assert reached == []
    message = out + err
    assert "unrecognized arguments" not in message
    assert entry in message


def test_an_airline_code_with_a_digit_is_accepted(monkeypatch, offline):
    request = _weekend_request(monkeypatch, offline, "--airlines", "3U,A3")

    assert request.airlines == frozenset({"3U", "A3"})


# --- PRTHREE-CRITERION-24: --allow-codeshare ---------------------------------------


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        ((), False),
        (("--allow-codeshare",), True),
        (("--allow-codeshare", "--no-allow-codeshare"), False),
    ],
    ids=["default", "on", "off-again"],
)
def test_allow_codeshare_is_an_on_off_switch(monkeypatch, offline, extra, expected):
    request = _weekend_request(monkeypatch, offline, "--airlines", "A3", *extra)

    assert request.allow_codeshare is expected


def test_allow_codeshare_lets_a_leg_operated_by_another_airline_pass(
    monkeypatch, tmp_path
):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 60.0, [("A3", "OA")])],
        rets=[((), 18, 30.0, ["A3"])],
        airlines=frozenset({"A3"}),
        allow_codeshare=True,
    )

    itineraries = result.itineraries()

    assert len(itineraries) == 1
    assert _leg_airlines(itineraries[0].out) == [("A3", "OA")]


def test_allow_codeshare_still_checks_the_selling_airline(monkeypatch, tmp_path):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 60.0, [("OA", "A3")])],
        rets=[((), 18, 30.0, ["A3"])],
        airlines=frozenset({"A3"}),
        allow_codeshare=True,
    )

    assert result.itineraries() == []


def test_allow_codeshare_without_airlines_has_no_effect(monkeypatch, tmp_path):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[(("ATH",), 9, 60.0, ["A3", ("GQ", "OA")])],
        rets=[((), 18, 30.0, ["LH"])],
        allow_codeshare=True,
    )

    assert len(result.itineraries()) == 1


def test_allow_codeshare_without_airlines_changes_no_cli_result(offline, capsys):
    unfiltered = _json_payload(offline, capsys)
    relaxed = _json_payload(offline, capsys, "--allow-codeshare")

    assert relaxed["results"] == unfiltered["results"]


# --- PRTHREE-CRITERION-25: discovery prices only matching flights -----------------

DAY = date(2027, 3, 5)


def _discovery_fake(calls):
    """FRA->ATH: A3 at 07:00 for 20, GQ at 18:00 for 30, A3 operated by OA at
    18:00 for 50, A3 at 19:00 for 80; FRA->HER: only GQ at 18:00 for 40."""

    def fake(origins, destinations, travel_date, restrictions, settings, **_kwargs):
        calls.append(tuple(destinations))

        def row(destination, hour, selling, price, operating=None):
            leg = SegmentLeg(
                "FRA",
                destination,
                datetime.combine(travel_date, time(hour)),
                (selling, selling),
                operating=(operating, operating) if operating is not None else None,
            )
            return SegmentResult([leg], price=price, self_transfer=False)

        rows = []
        if "ATH" in destinations:
            rows += [
                row("ATH", 7, "A3", 20.0),
                row("ATH", 18, "GQ", 30.0),
                row("ATH", 18, "A3", 50.0, operating="OA"),
                row("ATH", 19, "A3", 80.0),
            ]
        if "HER" in destinations:
            rows.append(row("HER", 18, "GQ", 40.0))
        return rows

    return fake


def _discover(monkeypatch, cache, calls, **filter_args):
    monkeypatch.setattr(fli_api, "detail_results", _discovery_fake(calls))
    return run_discovery(
        destinations=("ATH", "HER"),
        home=("FRA",),
        depart_dates=[DAY],
        return_dates=[],
        depart_window=DepartureWindow(after=time(15, 0)),
        return_window=ReturnWindow(),
        settings=SearchSettings(),
        cache=cache,
        budget=RequestBudget(10),
        batch_size=10,
        concurrency=1,
        **filter_args,
    )


def test_discovery_prices_an_airport_only_from_matching_flights(monkeypatch, tmp_path):
    cache = Cache(directory=tmp_path, ttl=timedelta(0))

    result = _discover(monkeypatch, cache, [], airlines=frozenset({"A3"}))

    # GQ for 30 and the codeshare for 50 fail the check, the 07:00 A3 flight
    # lies outside the window.
    assert result.screens["ATH"].out == {DAY.isoformat(): 80.0}
    assert result.screens["HER"].out == {}
    assert not result.screens["HER"].ok


def test_discovery_with_allow_codeshare_prices_from_the_selling_airline(
    monkeypatch, tmp_path
):
    cache = Cache(directory=tmp_path, ttl=timedelta(0))

    result = _discover(
        monkeypatch,
        cache,
        [],
        airlines=frozenset({"A3"}),
        allow_codeshare=True,
    )

    assert result.screens["ATH"].out == {DAY.isoformat(): 50.0}
    assert result.screens["HER"].out == {}


def test_discovery_without_airlines_prices_every_flight(monkeypatch, tmp_path):
    # Guard: holds before the change too.
    cache = Cache(directory=tmp_path, ttl=timedelta(0))

    result = _discover(monkeypatch, cache, [])

    assert result.screens["ATH"].out == {DAY.isoformat(): 30.0}
    assert result.screens["HER"].out == {DAY.isoformat(): 40.0}


def test_discovery_with_airlines_reuses_the_cache_of_a_run_without(
    monkeypatch, tmp_path
):
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    calls = []
    _discover(monkeypatch, cache, calls)
    assert len(calls) == 1

    result = _discover(
        monkeypatch,
        cache,
        calls,
        airlines=frozenset({"A3"}),
        allow_codeshare=True,
    )

    assert len(calls) == 1
    assert result.requests == 0
    assert result.screens["ATH"].out == {DAY.isoformat(): 50.0}


def test_a_search_with_airlines_sends_no_request_after_one_without(
    monkeypatch, tmp_path
):
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    _search(monkeypatch, tmp_path, cache=cache)
    budget = RequestBudget(1000)

    _search(
        monkeypatch,
        tmp_path,
        request=_request(airlines=frozenset({"VY"})),
        cache=cache,
        budget=budget,
    )

    assert budget.used == 0


def test_the_cli_with_airlines_sends_no_request_after_a_run_without(
    monkeypatch, offline, capsys
):
    _json_payload(offline, capsys)
    calls = []

    def counting(*args, **kwargs):
        calls.append(args)
        return fake_detail_results(*args, **kwargs)

    monkeypatch.setattr(fli_api, "detail_results", counting)
    payload = _json_payload(offline, capsys, "--airlines", "FR")

    assert calls == []
    assert payload["stats"]["requests"] == 0
    assert payload["query"]["airlines"] == ["FR"]


# --- PRTHREE-CRITERION-26: phase 2 picks the cheapest matching flight --------------


def test_itineraries_use_the_cheapest_matching_option(monkeypatch, tmp_path):
    result = _with_options(
        monkeypatch,
        tmp_path,
        outs=[((), 9, 40.0, ["GQ"]), ((), 10, 60.0, ["A3"])],
        rets=[((), 18, 20.0, [("A3", "OA")]), ((), 19, 30.0, ["A3"])],
        airlines=frozenset({"A3"}),
    )

    itineraries = result.itineraries()

    assert len(itineraries) == 1
    assert _leg_airlines(itineraries[0].out) == [("A3", "A3")]
    assert _leg_airlines(itineraries[0].ret) == [("A3", "A3")]
    assert itineraries[0].total == 90.0
    # The options stay unfiltered.
    prices = sorted(o.price for opts in result.options.values() for o in opts)
    assert prices == [20.0, 30.0, 40.0, 60.0]


def test_the_request_carries_the_airlines_and_the_switch(monkeypatch, tmp_path):
    request = _request(airlines=frozenset({"VY"}), allow_codeshare=True)

    result = _search(monkeypatch, tmp_path, request=request)

    assert result.request.airlines == frozenset({"VY"})
    assert result.request.allow_codeshare is True


def test_run_search_keeps_the_options_unfiltered(monkeypatch, tmp_path):
    request = _request(airlines=frozenset({"FR"}))

    result = _search(monkeypatch, tmp_path, request=request)
    unfiltered = _search(monkeypatch, tmp_path)

    assert result.options
    assert result.options == unfiltered.options
    assert {
        leg.airline for opts in result.options.values() for o in opts for leg in o.legs
    } == {"FR", "VY"}
    itineraries = result.itineraries()
    assert itineraries
    assert {
        leg.airline for it in itineraries for leg in (*it.out.legs, *it.ret.legs)
    } == {"FR"}


def test_the_default_request_has_no_airline_filter():
    request = _request()

    assert request.airlines == frozenset()
    assert request.allow_codeshare is False


# --- PRTHREE-CRITERION-27: config file and help --------------------------------------


@pytest.mark.parametrize(
    "line", ['airlines = ["A3", "OA"]', 'airlines = "A3,OA"'], ids=["list", "string"]
)
def test_config_airlines_become_the_default(
    monkeypatch, offline, xdg_config_home, line
):
    _write_config(xdg_config_home, line + "\n")

    request = _weekend_request(monkeypatch, offline)

    assert request.airlines == frozenset({"A3", "OA"})


def test_config_allow_codeshare_becomes_the_default(
    monkeypatch, offline, xdg_config_home
):
    _write_config(xdg_config_home, 'airlines = ["A3"]\nallow_codeshare = true\n')

    request = _weekend_request(monkeypatch, offline)

    assert request.allow_codeshare is True


def test_airlines_on_the_command_line_win_over_the_config(
    monkeypatch, offline, xdg_config_home
):
    _write_config(xdg_config_home, 'airlines = ["A3", "OA"]\n')

    request = _weekend_request(monkeypatch, offline, "--airlines", "LH")

    assert request.airlines == frozenset({"LH"})


def test_no_allow_codeshare_wins_over_the_config(monkeypatch, offline, xdg_config_home):
    _write_config(xdg_config_home, 'airlines = ["A3"]\nallow_codeshare = true\n')

    request = _weekend_request(monkeypatch, offline, "--no-allow-codeshare")

    assert request.allow_codeshare is False


def test_the_airports_command_ignores_the_weekend_only_airline_keys(
    monkeypatch, capsys, xdg_config_home
):
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)
    _write_config(xdg_config_home, 'airlines = ["A3"]\nallow_codeshare = true\n')

    assert _run(["airports"]) == 0


def _weekend_help(capsys) -> str:
    capsys.readouterr()
    assert _run(["weekend", "--help"]) == 0
    return " ".join(capsys.readouterr().out.split())


def _option_help(help_text: str, option: str) -> str:
    """The help of ``option`` in the listing, up to the next other option."""
    listing = help_text[help_text.index("options:") :]
    start = listing.index(option)
    help_text = listing
    rest = help_text[start + len(option) :]
    following = re.search(r" --(?!airlines|allow-codeshare|no-allow-codeshare)", rest)
    return rest[: following.start()] if following else rest


def test_help_describes_the_airline_filter(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "1000")

    help_text = _weekend_help(capsys)

    assert "--airlines" in help_text
    assert "--allow-codeshare" in help_text
    assert "--no-allow-codeshare" in help_text
    airlines_help = _option_help(help_text, "--airlines").lower()
    # The strict rule: selling and operating airline of every leg.
    assert "selling" in airlines_help
    assert "operating" in airlines_help
    assert "every leg" in airlines_help
    assert "--allow-codeshare" in airlines_help
    # A leg without a reported operator counts as operated by its seller.
    assert "operator" in airlines_help
    # The batch risk: the cheapest matching flight Google returned.
    assert "cheapest matching" in airlines_help
    assert "batch" in airlines_help
    assert "missing" in airlines_help


# --- PRTHREE-CRITERION-28: the run names an active filter ---------------------------


def test_the_header_names_the_strict_filter(offline, capsys):
    code, out, err = _weekend(offline, capsys, "--airlines", "FR,LH,VY")

    assert code == 0, err
    assert "airlines FR, LH, VY (selling and operating airline of every leg)" in [
        line.strip() for line in out.splitlines()
    ]


def test_the_header_names_the_codeshare_filter(offline, capsys):
    code, out, err = _weekend(
        offline, capsys, "--airlines", "FR,LH,VY", "--allow-codeshare"
    )

    assert code == 0, err
    assert "airlines FR, LH, VY (selling airline of every leg, codeshares allowed)" in [
        line.strip() for line in out.splitlines()
    ]


def test_without_airlines_the_header_has_no_airline_line(offline, capsys):
    # Guard: holds before the change too.
    code, out, err = _weekend(offline, capsys)

    assert code == 0, err
    assert not any(line.strip().startswith("airlines") for line in out.splitlines())


@pytest.mark.parametrize(
    ("extra", "airlines", "allow_codeshare"),
    [
        ((), [], False),
        (("--airlines", "FR,LH,VY"), ["FR", "LH", "VY"], False),
        (("--airlines", "FR,LH,VY", "--allow-codeshare"), ["FR", "LH", "VY"], True),
    ],
    ids=["none", "strict", "codeshare"],
)
def test_the_json_query_carries_the_filter(
    offline, capsys, extra, airlines, allow_codeshare
):
    payload = _json_payload(offline, capsys, *extra)

    assert payload["query"]["airlines"] == airlines
    assert payload["query"]["allow_codeshare"] is allow_codeshare


# --- PRTHREE-CRITERION-29: the README ----------------------------------------------


def _readme_section(heading: str) -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index(heading)
    end = text.find("\n## ", start + len(heading))
    return text[start:] if end == -1 else text[start:end]


def test_the_readme_options_table_documents_the_filter():
    rows = [
        line
        for line in _readme_section("## Options worth knowing").splitlines()
        if line.startswith("|") and "--airlines" in line
    ]

    assert rows, "no row for --airlines in the options table"
    row = " ".join(rows).lower()
    assert "--allow-codeshare" in row
    assert "selling" in row
    assert "operating" in row
    assert "every leg" in row
    assert "batch" in row


def test_the_readme_config_section_lists_the_airline_keys():
    section = _readme_section("## Configuration")

    assert re.search(r"\ballow_codeshare\b", section)
    assert re.search(r"(?<![-\w])airlines\b", section)


def test_no_priced_candidates_names_the_airline_filter(offline, capsys):
    code, _, err = _weekend(offline, capsys, "--airlines", "A3")

    assert code == 1, err
    assert "No priced candidates" in err
    assert "--airlines" in err and re.search(r"\bA3\b", err), err


def test_no_confirmed_itineraries_names_the_airline_filter(
    monkeypatch, offline, capsys
):
    def detail_results(origins, destinations, *args, **kwargs):
        rows = fake_detail_results(origins, destinations, *args, **kwargs)
        # Discovery requests both destination airports at once. Confirmation
        # requests a single city, so its rows keep their original airlines.
        if {"BCN", "PMI"} in (set(origins), set(destinations)):
            for row in rows:
                for leg in row.legs:
                    leg.airline = FakeAirline("A3", "Aegean Airlines")
        return rows

    monkeypatch.setattr(fli_api, "detail_results", detail_results)

    code, _, err = _weekend(offline, capsys, "--dest", "BCN,PMI", "--airlines", "A3")

    assert code == 1, err
    assert "No itineraries confirmed" in err
    assert "--airlines" in err and re.search(r"\bA3\b", err), err


@pytest.mark.parametrize("source", ["flag", "config"])
def test_json_ignores_codeshares_without_airlines(
    offline, capsys, xdg_config_home, source
):
    if source == "config":
        _write_config(xdg_config_home, "allow_codeshare = true\n")
    extra = ("--allow-codeshare",) if source == "flag" else ()

    query = _json_payload(offline, capsys, *extra)["query"]

    assert query["airlines"] == []
    assert query["allow_codeshare"] is False


def test_invalid_config_airline_names_its_source_and_accepts_a_cli_override(
    offline, capsys, xdg_config_home
):
    _write_config(xdg_config_home, 'airlines = ["OAL"]\n')

    assert _json_payload(offline, capsys, "--airlines", "FR")["query"]["airlines"] == [
        "FR"
    ]

    code, _, err = _weekend(offline, capsys)

    assert code == 2, err
    assert "config.toml" in err and re.search(r"\bairlines\b", err), err
    assert re.search(r"\bOAL\b", err), err


def test_roundtrip_benchmark_identifies_its_unfiltered_airline_scope(
    monkeypatch, offline, capsys
):
    def detail_results(origins, destinations, *args, return_date=None, **kwargs):
        rows = fake_detail_results(
            origins, destinations, *args, return_date=return_date, **kwargs
        )
        if return_date is not None:
            for pair in rows:
                for result in pair:
                    result.price = 70.0
                    result.legs[0].airline = FakeAirline("FR", "Ryanair")
        else:
            for result in rows:
                result.price = (
                    60.0 if result.legs[0].departure_airport.name == "FRA" else 30.0
                )
                result.legs[0].airline = FakeAirline("A3", "Aegean Airlines")
        return rows

    monkeypatch.setattr(fli_api, "detail_results", detail_results)
    flags = (
        "--from",
        "FRA",
        "--dest",
        "BCN",
        "--airlines",
        "A3",
        "--compare-roundtrip",
    )
    payload = _json_payload(offline, capsys, *flags)
    code, out, err = _weekend(offline, capsys, *flags)

    assert code == 0, err
    assert "+€20" in out
    assert payload["query"]["airlines"] == ["A3"]
    assert {leg["airline"] for leg in _all_legs(payload)} == {"A3"}
    assert payload["results"]
    for result in payload["results"]:
        assert result["roundtrip_price"] == 70.0
        assert result["roundtrip_delta"] == 20.0

    help_text = _option_help(_weekend_help(capsys), "--no-compare-roundtrip").lower()
    assert {
        "JSON benchmark airlines": payload["query"].get("roundtrip_airlines"),
        "benchmark note near the table": any(
            "vs RT" in line and "across all airlines" in line.lower()
            for line in out.splitlines()
        ),
        "benchmark airline scope in help": "all airlines" in help_text,
    } == {
        "JSON benchmark airlines": [],
        "benchmark note near the table": True,
        "benchmark airline scope in help": True,
    }
