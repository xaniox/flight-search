"""--dest with only unknown codes selects nothing (PRTWO-CRITERION-14).

Without this rule an empty set of known codes would mean "no filter" and
select every airport. The mixed known+unknown case is a guard.
"""

from __future__ import annotations

import pytest
from airport_factory import airport

from flight_search import cli
from flight_search.config import KARLSRUHE
from flight_search.destinations import DestinationChoice, select_destinations

AIRPORTS = (
    airport("FRA", "DE", "EU"),
    airport("AMS", "NL", "EU"),
    airport("LIS", "PT", "EU", lat=38.77, lon=-9.13),
)


@pytest.fixture(autouse=True)
def fake_airports(monkeypatch):
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)


def _select(*codes):
    selected, warnings = select_destinations(
        DestinationChoice(codes=codes), airports=AIRPORTS, center=KARLSRUHE
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
            "--from",
            "FRA",
            *extra,
        ]
    )


def test_only_unknown_code_selects_no_airport_and_warns_once():
    codes, warnings = _select("ZZZ")
    assert codes == set()
    assert len(warnings) == 1
    assert "ZZZ" in warnings[0]


def test_several_unknown_codes_warn_once_each():
    codes, warnings = _select("ZZZ", "YYY")
    assert codes == set()
    assert len(warnings) == 2
    assert "ZZZ" in warnings[0]
    assert "YYY" in warnings[1]


def test_weekend_dest_unknown_selects_no_airport_and_warns():
    destinations, warnings = cli._select_airports(_weekend_args("--dest", "ZZZ"))
    assert destinations == ()
    assert any("ZZZ" in w for w in warnings)


def test_weekend_dest_unknown_ends_with_exit_2_and_no_destination_message(capsys):
    code = cli.main(
        [
            "weekend",
            "--start",
            "2026-12-04",
            "--end",
            "2026-12-20",
            "--from",
            "FRA",
            "--dest",
            "ZZZ",
        ]
    )
    err = capsys.readouterr().err
    assert code == 2
    assert "ZZZ" in err
    assert "no destination airports selected" in err


def test_airports_dest_unknown_lists_no_airport(capsys):
    args = cli._build_parser().parse_args(["airports", "--dest", "ZZZ"])
    assert cli._run_airports(args) == 0
    out = capsys.readouterr().out
    assert "0 airports" in out
    assert not {a.iata for a in AIRPORTS} & set(out.split())


# --- Guards: mixed known and unknown codes keep today's behaviour -----------


def test_guard_mixed_codes_select_the_known_one_and_warn_for_the_unknown():
    codes, warnings = _select("AMS", "ZZZ")
    assert codes == {"AMS"}
    assert len(warnings) == 1
    assert "ZZZ" in warnings[0]


def test_guard_airports_dest_known_lists_only_that_airport(capsys):
    args = cli._build_parser().parse_args(["airports", "--dest", "AMS"])
    assert cli._run_airports(args) == 0
    out = capsys.readouterr().out.split()
    assert "AMS" in out
    assert "FRA" not in out
