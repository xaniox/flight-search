import time
from datetime import date

import pytest

from flight_search.dates import (
    DateError,
    DatePair,
    count_date_pairs,
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
    assert [p.depart.isoformat() for p in pairs] == [
        "2026-11-13",
        "2026-11-20",
        "2026-11-27",
    ]
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


ALL_DAYS = frozenset(range(7))
COUNT_CASES = [
    (date(2026, 11, 13), date(2026, 11, 30), {4}, {6}, 1, 4),
    (date(2026, 11, 13), date(2026, 11, 30), {3, 4}, {0, 6}, 2, 5),
    (date(2026, 11, 13), date(2026, 12, 20), ALL_DAYS, ALL_DAYS, 0, 3),
    (date(2026, 11, 13), date(2026, 11, 20), ALL_DAYS, ALL_DAYS, 0, 0),
    (date(2026, 11, 13), date(2026, 11, 20), {4}, {4}, 1, 100),
    (date(2026, 11, 13), date(2026, 11, 20), {4}, {6}, 30, 40),
    (date(2026, 11, 13), date(2026, 11, 13), ALL_DAYS, ALL_DAYS, 0, 3),
    (date(2026, 11, 13), date(2026, 11, 13), {4}, {4}, 1, 3),
    (date(2026, 11, 14), date(2026, 12, 1), {4}, {6}, 1, 4),
]


@pytest.mark.parametrize(
    ("start", "end", "depart", "ret", "min_nights", "max_nights"), COUNT_CASES
)
def test_count_date_pairs_equals_expanded_pairs(
    start, end, depart, ret, min_nights, max_nights
):
    args = (start, end, frozenset(depart), frozenset(ret), min_nights, max_nights)

    assert count_date_pairs(*args) == len(expand_date_pairs(*args))


def test_count_date_pairs_counts_a_huge_window_without_expanding_it():
    assert (
        count_date_pairs(
            date(2027, 1, 1), date(2035, 1, 1), ALL_DAYS, ALL_DAYS, 0, 3000
        )
        == 4_273_426
    )


def test_count_date_pairs_validates_like_expand_date_pairs():
    with pytest.raises(DateError):
        count_date_pairs(date(2026, 12, 2), date(2026, 12, 1), ALL_DAYS, ALL_DAYS, 1, 4)
    with pytest.raises(DateError):
        count_date_pairs(
            date(2026, 12, 1), date(2026, 12, 2), ALL_DAYS, ALL_DAYS, -1, 4
        )
    with pytest.raises(DateError):
        count_date_pairs(date(2026, 12, 1), date(2026, 12, 2), ALL_DAYS, ALL_DAYS, 3, 2)


def test_count_date_pairs_is_cheap_for_a_huge_range():
    start, end = date(2027, 1, 1), date(9999, 12, 31)
    every_day = frozenset(range(7))
    days = (end - start).days + 1
    span = 3000
    # Each departure pairs with the span following days, fewer near the end.
    expected = (days - span) * (span + 1) + span * (span + 1) // 2

    started = time.perf_counter()
    count = count_date_pairs(start, end, every_day, every_day, 0, span)
    elapsed = time.perf_counter() - started

    assert count == expected
    assert elapsed < 1.0, elapsed
