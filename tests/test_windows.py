from datetime import date, datetime, time

import pytest

from flight_search.windows import (
    DepartureWindow,
    ReturnWindow,
    TimeWindowError,
    parse_clock,
)


def test_parse_clock():
    assert parse_clock("17") == time(17, 0)
    assert parse_clock("17:30") == time(17, 30)
    assert parse_clock("00:01") == time(0, 1)
    for bad in ("24:00", "12:60", "noon", ""):
        with pytest.raises(TimeWindowError):
            parse_clock(bad)


def test_no_window_sends_no_restrictions():
    assert DepartureWindow().restrictions() is None
    assert ReturnWindow().restrictions() is None


def test_departure_window_truncates_to_hours_for_google():
    window = DepartureWindow(after=time(17, 30), before=time(21, 15))
    restrictions = window.restrictions()
    # Google only understands whole hours; 17:30/21:15 must not be rounded up,
    # otherwise valid in-window flights would be excluded.
    assert restrictions.earliest_departure == 17
    assert restrictions.latest_departure == 21


def test_departure_window_matches_exact_minutes():
    window = DepartureWindow(after=time(17, 30), before=time(21, 15))
    assert window.matches(datetime(2026, 11, 13, 17, 30))
    assert window.matches(datetime(2026, 11, 13, 21, 15))
    assert not window.matches(datetime(2026, 11, 13, 17, 29))
    assert not window.matches(datetime(2026, 11, 13, 21, 16))


def test_departure_window_rejects_cross_midnight_and_empty():
    with pytest.raises(TimeWindowError):
        DepartureWindow(after=time(22, 0), before=time(6, 0))
    with pytest.raises(TimeWindowError):
        DepartureWindow(after=time(18, 0), before=time(18, 0))
    with pytest.raises(TimeWindowError):
        DepartureWindow(before=time(0, 0))


def test_return_arrival_is_date_aware():
    window = ReturnWindow(arrive_before=time(22, 0))
    return_date = date(2026, 11, 15)
    departure = datetime(2026, 11, 15, 18, 0)
    assert window.matches(departure, datetime(2026, 11, 15, 21, 59), return_date)
    assert window.matches(departure, datetime(2026, 11, 15, 22, 0), return_date)
    # A red-eye arriving next day must not pass a same-day cutoff.
    assert not window.matches(departure, datetime(2026, 11, 16, 1, 0), return_date)
    assert not window.matches(departure, datetime(2026, 11, 15, 22, 1), return_date)


def test_return_arrival_restrictions_use_hour():
    window = ReturnWindow(arrive_before=time(22, 30))
    restrictions = window.restrictions()
    assert restrictions.latest_arrival == 22
    assert restrictions.earliest_departure is None
    assert restrictions.latest_departure is None


def test_return_departure_matches_exact_minutes():
    window = ReturnWindow(depart_after=time(15, 30))
    return_date = date(2026, 11, 15)
    arrival = datetime(2026, 11, 15, 17, 30)
    assert window.matches(datetime(2026, 11, 15, 15, 30), arrival, return_date)
    assert window.matches(datetime(2026, 11, 15, 23, 0), arrival, return_date)
    assert not window.matches(datetime(2026, 11, 15, 15, 29), arrival, return_date)


def test_return_restrictions_encode_departure_and_arrival():
    window = ReturnWindow(depart_after=time(15, 30), arrive_before=time(22, 15))
    restrictions = window.restrictions()
    # Hour-truncated for Google, exact minutes enforced locally.
    assert restrictions.earliest_departure == 15
    assert restrictions.latest_arrival == 22
    assert restrictions.latest_departure is None


def test_return_window_requires_both_constraints_to_match():
    window = ReturnWindow(depart_after=time(15, 0), arrive_before=time(22, 0))
    ret = date(2026, 11, 15)
    assert window.matches(
        datetime(2026, 11, 15, 16, 0), datetime(2026, 11, 15, 21, 0), ret
    )
    assert not window.matches(
        datetime(2026, 11, 15, 14, 0), datetime(2026, 11, 15, 21, 0), ret
    )
    assert not window.matches(
        datetime(2026, 11, 15, 16, 0), datetime(2026, 11, 16, 1, 0), ret
    )


def test_return_window_label():
    window = ReturnWindow(depart_after=time(15, 0), arrive_before=time(22, 0))
    assert window.label() == "depart ≥ 15:00 · arrive ≤ 22:00"
    assert ReturnWindow().label() == "any time"
