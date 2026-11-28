"""Date-range expansion for weekday-constrained getaways."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from datetime import date

from flight_search.config import WEEKDAY_NAMES


class DateError(ValueError):
    """Invalid date range or weekday specification."""


@dataclass(frozen=True, slots=True)
class DatePair:
    depart: date
    ret: date

    @property
    def nights(self) -> int:
        return (self.ret - self.depart).days


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise DateError(f"Invalid date {value!r}: expected YYYY-MM-DD") from exc


def parse_weekdays(values: list[str] | tuple[str, ...]) -> frozenset[int]:
    """Parse weekday names/abbreviations into Monday=0 indices."""
    if not values:
        raise DateError("At least one weekday is required")
    result: set[int] = set()
    for raw in values:
        for token in raw.replace(",", " ").split():
            key = token.strip().lower()[:3]
            if key not in WEEKDAY_NAMES:
                raise DateError(
                    f"Unknown weekday {token!r}. Use mon,tue,wed,thu,fri,sat,sun."
                )
            result.add(WEEKDAY_NAMES.index(key))
    return frozenset(result)


def _validate_range(start: date, end: date, min_nights: int, max_nights: int) -> None:
    if start > end:
        raise DateError(f"Start date {start} is after end date {end}")
    if min_nights < 0:
        raise DateError("min_nights must be >= 0")
    if max_nights < min_nights:
        raise DateError("max_nights must be >= min_nights")


def _count_weekday(start: int, end: int, weekday: int) -> int:
    first = start + (weekday - (start - 1)) % 7
    return max(0, 1 + (end - first) // 7)


def count_feasible_dates(
    start: date,
    end: date,
    depart_days: frozenset[int],
    return_days: frozenset[int],
    min_nights: int,
    max_nights: int,
) -> tuple[int, int]:
    """Count distinct dates that participate in at least one permitted pair."""
    _validate_range(start, end, min_nights, max_nights)
    depart_gaps: dict[int, int] = {}
    return_gaps: dict[int, int] = {}
    for depart in depart_days:
        for ret in return_days:
            gap = min_nights + (ret - depart - min_nights) % 7
            if gap <= max_nights:
                depart_gaps[depart] = min(gap, depart_gaps.get(depart, gap))
                return_gaps[ret] = min(gap, return_gaps.get(ret, gap))

    # The shortest compatible gap leaves the widest interval of feasible dates.
    first, last = start.toordinal(), end.toordinal()
    return (
        sum(_count_weekday(first, last - gap, day) for day, gap in depart_gaps.items()),
        sum(_count_weekday(first + gap, last, day) for day, gap in return_gaps.items()),
    )


def _return_ranges(
    start: date,
    end: date,
    depart_days: frozenset[int],
    return_days: frozenset[int],
    min_nights: int,
    max_nights: int,
) -> tuple[list[int], list[tuple[int, int, int]]]:
    """Return ordinals and, per departure ordinal, the slice of permitted returns."""
    _validate_range(start, end, min_nights, max_nights)
    first, last = start.toordinal(), end.toordinal()
    returns = [day for day in range(first, last + 1) if (day - 1) % 7 in return_days]
    ranges = [
        (
            day,
            bisect_left(returns, day + min_nights),
            bisect_right(returns, day + max_nights),
        )
        for day in range(first, last + 1)
        if (day - 1) % 7 in depart_days
    ]
    return returns, ranges


def count_date_pairs(
    start: date,
    end: date,
    depart_days: frozenset[int],
    return_days: frozenset[int],
    min_nights: int = 1,
    max_nights: int = 4,
) -> int:
    """The number of pairs ``expand_date_pairs`` returns, without building them.

    Counts per departure weekday and trip length, so the cost grows with the
    nights, not with the days of the range.
    """
    _validate_range(start, end, min_nights, max_nights)
    first, last = start.toordinal(), end.toordinal()
    return sum(
        _count_weekday(first, last - gap, depart)
        for depart in depart_days
        for gap in range(min_nights, min(max_nights, last - first) + 1)
        if (depart + gap) % 7 in return_days
    )


def expand_date_pairs(
    start: date,
    end: date,
    depart_days: frozenset[int],
    return_days: frozenset[int],
    min_nights: int = 1,
    max_nights: int = 4,
) -> list[DatePair]:
    """All (depart, return) pairs inside the range matching the weekday rules."""
    returns, ranges = _return_ranges(
        start, end, depart_days, return_days, min_nights, max_nights
    )
    return [
        DatePair(date.fromordinal(day), date.fromordinal(returns[index]))
        for day, first, after in ranges
        for index in range(first, after)
    ]


def unique_dates(pairs: list[DatePair]) -> tuple[list[date], list[date]]:
    """Distinct departure / return dates, which is what drives request count."""
    departures = sorted({p.depart for p in pairs})
    returns = sorted({p.ret for p in pairs})
    return departures, returns
