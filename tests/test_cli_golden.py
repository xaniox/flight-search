"""Approved output of the weekend command (PRTWO-CRITERION-04).

The safety net of the search-core refactoring: ``cli.main`` runs offline
against a fake ``fli_api.detail_results``, a fixed airport list, a frozen
"today" and a tmp cache, and its stdout, stderr and exit code must equal the
approved files under ``tests/golden/`` (``<case>.txt`` and
``<case>.stderr.txt``). Record them once with ``GOLDEN_UPDATE=1``.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

import pytest
from airport_factory import airport
from fake_flights import (
    empty_detail_results,
    failing_batch_detail_results,
    fake_detail_results,
)

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
