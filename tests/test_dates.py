from datetime import date

import pytest

from flight_search.dates import (
    DateError,
    DatePair,
    expand_date_pairs,
    parse_date,
    parse_weekdays,
    unique_dates,
)


def test_parse_weekdays_accepts_names_and_abbreviations():
    assert parse_weekdays(["fri", "THURSDAY"]) == frozenset({3, 4})
    assert parse_weekdays(["thu,fri"]) == frozenset({3, 4})


def test_parse_weekdays_rejects_unknown():
    with pytest.raises(DateError):
        parse_weekdays(["funday"])


def test_expand_date_pairs_respects_weekdays_and_nights():
    start = date(2026, 11, 13)  # Friday
    end = date(2026, 11, 30)  # Monday
    pairs = expand_date_pairs(
        start,
        end,
        parse_weekdays(["fri"]),
        parse_weekdays(["sun"]),
        min_nights=2,
        max_nights=2,
    )
    assert [p.depart.isoformat() for p in pairs] == ["2026-11-13", "2026-11-20", "2026-11-27"]
    assert all(p.ret.isoformat().endswith(("15", "22", "29")) for p in pairs)
    assert all(p.nights == 2 for p in pairs)


def test_expand_date_pairs_supports_multiple_depart_and_return_days():
    pairs = expand_date_pairs(
        date(2026, 11, 13),
        date(2026, 11, 16),
        parse_weekdays(["fri", "sat"]),
        parse_weekdays(["sun", "mon"]),
        min_nights=1,
        max_nights=3,
    )
    keys = {(p.depart.isoformat(), p.ret.isoformat()) for p in pairs}
    assert ("2026-11-13", "2026-11-15") in keys
    assert ("2026-11-14", "2026-11-15") in keys
    assert ("2026-11-14", "2026-11-16") in keys
    assert ("2026-11-13", "2026-11-16") in keys
    assert ("2026-11-16", "2026-11-15") not in keys


def test_expand_date_pairs_rejects_bad_ranges():
    with pytest.raises(DateError):
        expand_date_pairs(
            date(2026, 11, 20),
            date(2026, 11, 13),
            frozenset({4}),
            frozenset({6}),
        )
    with pytest.raises(DateError):
        expand_date_pairs(
            date(2026, 11, 13),
            date(2026, 11, 20),
            frozenset({4}),
            frozenset({6}),
            min_nights=5,
            max_nights=2,
        )


def test_parse_date():
    assert parse_date("2026-11-13") == date(2026, 11, 13)
    with pytest.raises(DateError):
        parse_date("13.11.2026")


def test_unique_dates():
    pairs = [
        DatePair(date(2026, 11, 13), date(2026, 11, 15)),
        DatePair(date(2026, 11, 13), date(2026, 11, 16)),
        DatePair(date(2026, 11, 20), date(2026, 11, 22)),
    ]
    departures, returns = unique_dates(pairs)
    assert departures == [date(2026, 11, 13), date(2026, 11, 20)]
    assert returns == [date(2026, 11, 15), date(2026, 11, 16), date(2026, 11, 22)]
