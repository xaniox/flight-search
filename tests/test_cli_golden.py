"""Approved output of the weekend command (PRTWO-CRITERION-04).

The safety net of the search-core refactoring: ``cli.main`` runs offline
against a fake ``fli_api.detail_results``, a fixed airport list, a frozen
"today" and a tmp cache, and its stdout, stderr and exit code must equal the
approved files under ``tests/golden/`` (``<case>.txt`` and
``<case>.stderr.txt``). Record them once with ``GOLDEN_UPDATE=1``.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import sys
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from airport_factory import airport
from fake_flights import (
    empty_detail_results,
    failing_batch_detail_results,
    fake_detail_results,
)
from fli.search.exceptions import SearchHTTPError, SearchParseError

from flight_search import cli, fli_api

GOLDEN_DIR = Path(__file__).parent / "golden"

# Home airports FRA and STR; Barcelona (BCN, GRO) and Rome (FCO, CIA) are
# metros with two airports each, so open jaws occur; TLV lies outside the
# default region and must never show up.
AIRPORTS = (
    airport("BCN", "ES", "EU", municipality="Barcelona", lat=41.30, lon=2.08),
    airport("CIA", "IT", "EU", municipality="Rome", lat=41.80, lon=12.59),
    airport("FCO", "IT", "EU", municipality="Rome", lat=41.80, lon=12.25),
    airport("FRA", "DE", "EU", municipality="Frankfurt", lat=50.03, lon=8.56),
    airport("GRO", "ES", "EU", municipality="Girona", lat=41.90, lon=2.76),
    airport("LIS", "PT", "EU", municipality="Lisbon", lat=38.77, lon=-9.13),
    airport("PMI", "ES", "EU", municipality="Palma", lat=39.55, lon=2.73),
    airport("STR", "DE", "EU", municipality="Stuttgart", lat=48.69, lon=9.22),
    airport("TLV", "IL", "AS", municipality="Tel Aviv", lat=32.01, lon=34.89),
)

# Fridays 5, 12 and 19 March 2027 to the Sundays after them; "today" is fixed
# well before, so the start date is never in the past.
TODAY = date(2027, 1, 15)
BASE_ARGS = (
    "weekend",
    "--from",
    "FRA,STR",
    "--start",
    "2027-03-05",
    "--end",
    "2027-03-21",
    "--depart-after",
    "15",
    "--top",
    "6",
)


class FrozenDate(date):
    @classmethod
    def today(cls):
        return TODAY


@pytest.fixture
def offline(monkeypatch, tmp_path):
    monkeypatch.setattr(fli_api, "detail_results", fake_detail_results)
    monkeypatch.setattr(cli, "load_airports", lambda include_small=False: AIRPORTS)
    # cli looks today up as ``date.today()`` on its module-level ``date``.
    monkeypatch.setattr(cli, "date", FrozenDate)
    # A fixed, colourless, non-interactive console.
    monkeypatch.setenv("COLUMNS", "120")
    monkeypatch.setenv("LINES", "40")
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
    for name in ("FORCE_COLOR", "TTY_COMPATIBLE", "TTY_INTERACTIVE", "CLICOLOR_FORCE"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "cache"


CASES = {
    "text": (),
    "json": ("--format", "json"),
    "best_per_city": ("--best-per-city",),
    "compare_roundtrip": ("--compare-roundtrip",),
    "dry_run": ("--dry-run",),
    "no_cache": ("--no-cache",),
    "no_destinations": ("--countries", "ZZ"),
    # An unknown --dest code warns on stderr, the known one is searched.
    "dest_warning": ("--dest", "PMI,ZZZ"),
    # Batches of two sorted codes: (BCN, CIA), (FCO, GRO), (LIS, PMI); the fake
    # fails only the outbound LIS/PMI batch of 12 March, 1 of 18 requests.
    "discovery_failures": ("--batch-size", "2"),
    "no_candidates": (),
}
EXPECTED_EXIT = {"dry_run": 0, "no_destinations": 2, "no_candidates": 1}
FAKES = {
    "discovery_failures": failing_batch_detail_results,
    "no_candidates": empty_detail_results,
}


def _check_golden(filename: str, out: str) -> None:
    path = GOLDEN_DIR / filename
    if os.environ.get("GOLDEN_UPDATE") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(out, encoding="utf-8")
    assert path.exists(), f"missing golden file {path}; record with GOLDEN_UPDATE=1"
    assert out == path.read_text(encoding="utf-8")


@pytest.mark.parametrize("case", sorted(CASES))
def test_weekend_output_matches_golden(case, offline, capsys, monkeypatch):
    if case in FAKES:
        monkeypatch.setattr(fli_api, "detail_results", FAKES[case])
    code = cli.main([*BASE_ARGS, "--cache-dir", str(offline), *CASES[case]])
    captured = capsys.readouterr()
    assert code == EXPECTED_EXIT.get(case, 0)
    if case == "no_destinations":
        assert "no destination airports selected" in captured.err
    _check_golden(f"{case}.txt", captured.out)
    _check_golden(f"{case}.stderr.txt", captured.err)


def test_discovery_abort_reports_the_causes(offline, capsys, monkeypatch):
    def fail(origins, destinations, *args, **kwargs):
        if destinations == ["GRO"]:
            raise SearchParseError("Search page carried no ds:1 payload")
        raise SearchHTTPError("Rate limited", status_code=429)

    monkeypatch.setattr(fli_api, "detail_results", fail)
    code = cli.main(
        [
            *BASE_ARGS,
            "--cache-dir",
            str(offline),
            "--batch-size",
            "1",
            "--concurrency",
            "1",
            "--format",
            "json",
            "--quiet",
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert captured.out == ""
    assert "8 of 8 processed discovery batches failed" in captured.err
    assert "HTTP 429: 7" in captured.err
    assert "SearchParseError: 1" in captured.err
    assert "out 2027-03-05 GRO" in captured.err
    assert "Search page carried no ds:1 payload" in captured.err


def test_debug_logs_discovery_requests_and_cache_hits_to_stderr(offline, capsys):
    args = [*BASE_ARGS, "--cache-dir", str(offline), "--format", "json", "--quiet"]
    assert cli.main(args) == 0
    first = capsys.readouterr()
    assert first.err == ""

    assert cli.main([*args, "--debug"]) == 0
    second = capsys.readouterr()
    assert '"results"' in second.out
    assert "| Outbound 2027-03-05" not in second.out
    assert re.search(
        r"Discovery.* \| Outbound 2027-03-05 .* · cache in \d+ ms", second.err
    )
    assert re.search(r"options: \d+ → \d+ \(time\) → \d+ \(airline\)", second.err)

    assert cli.main([*args, "--no-cache", "--debug"]) == 0
    third = capsys.readouterr()
    assert re.search(
        r"Discovery.* \| Outbound 2027-03-05 .* · Google in \d+ ms", third.err
    )


def test_debug_logs_and_interactive_progress_use_separate_lines(
    offline, capsys, monkeypatch
):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    terminal = Terminal()
    monkeypatch.setattr(sys, "stderr", terminal)
    monkeypatch.setenv("TERM", "xterm")
    monkeypatch.delenv("NO_COLOR")

    assert (
        cli.main(
            [
                *BASE_ARGS,
                "--cache-dir",
                str(offline),
                "--format",
                "json",
                "--debug",
                "--concurrency",
                "1",
            ]
        )
        == 0
    )

    assert json.loads(capsys.readouterr().out)["results"]
    raw = terminal.getvalue()
    assert "\x1b[2K" in raw
    assert "Pricing destinations" in raw
    plain = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", raw)
    debug_lines = [line for line in plain.splitlines() if " DEBUG " in line]
    assert any(re.search(r"Discovery +\| Starting", line) for line in debug_lines)
    assert all(re.match(r"\d{4}-\d{2}-\d{2} ", line) for line in debug_lines)


def test_debug_logs_confirmation_roundtrip_and_upstream_to_stderr(
    offline, capsys, monkeypatch
):
    def log_detail_results(*args, **kwargs):
        logging.getLogger("fli.search._tfs").debug("fli debug marker")
        return fake_detail_results(*args, **kwargs)

    monkeypatch.setattr(fli_api, "detail_results", log_detail_results)
    args = [
        *BASE_ARGS,
        "--cache-dir",
        str(offline),
        "--format",
        "json",
        "--quiet",
        "--debug",
        "--compare-roundtrip",
    ]

    assert cli.main(args) == 0
    cold = capsys.readouterr()
    assert json.loads(cold.out)["results"]
    assert re.search(r"Transport.* \| fli debug marker", cold.err)
    assert re.search(r"Search +\| Finished", cold.err)
    assert re.search(r"Confirmation +\| .* · Google in \d+ ms", cold.err)
    assert re.search(r"Round-trip +\| .* · Google in \d+ ms", cold.err)

    unexpected_request = Mock(side_effect=AssertionError("unexpected upstream request"))
    monkeypatch.setattr(fli_api, "detail_results", unexpected_request)
    assert cli.main(args) == 0
    warm = capsys.readouterr()
    unexpected_request.assert_not_called()
    assert json.loads(warm.out)["results"]
    assert re.search(r"Search +\| Finished", warm.err)
    assert re.search(r"Confirmation +\| .* · cache in \d+ ms", warm.err)
    assert re.search(r"Round-trip +\| .* · cache in \d+ ms", warm.err)


def test_too_many_date_pairs_exit_2_without_expanding_them(
    offline, capsys, monkeypatch
):
    from flight_search import weekend

    def unexpected_expansion(*args, **kwargs):
        pytest.fail("CLI expanded date pairs before the pair limit check")

    monkeypatch.setattr(weekend, "expand_date_pairs", unexpected_expansion)
    code = cli.main(
        [
            "weekend",
            "--from",
            "FRA",
            "--start",
            "2027-03-05",
            "--end",
            "2035-03-05",
            "--depart-days",
            "mon,tue,wed,thu,fri,sat,sun",
            "--return-days",
            "mon,tue,wed,thu,fri,sat,sun",
            "--min-nights",
            "0",
            "--max-nights",
            "3000",
            "--max-requests",
            "100000000",
            "--cache-dir",
            str(offline),
        ]
    )

    captured = capsys.readouterr()
    assert code == 2
    assert "exceed the limit" in (captured.out + captured.err)
    assert "date pairs" in (captured.out + captured.err).lower()
