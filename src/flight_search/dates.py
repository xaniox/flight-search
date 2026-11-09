"""Date-range expansion for weekday-constrained getaways."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

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


def expand_date_pairs(
    start: date,
    end: date,
    depart_days: frozenset[int],
    return_days: frozenset[int],
    min_nights: int = 1,
    max_nights: int = 4,
) -> list[DatePair]:
    """All (depart, return) pairs inside the range matching the weekday rules."""
    if start > end:
        raise DateError(f"Start date {start} is after end date {end}")
    if min_nights < 0:
        raise DateError("min_nights must be >= 0")
    if max_nights < min_nights:
        raise DateError("max_nights must be >= min_nights")

    departures = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in depart_days
    ]
    returns = [
        start + timedelta(days=offset)
        for offset in range((end - start).days + 1)
        if (start + timedelta(days=offset)).weekday() in return_days
    ]

    pairs: list[DatePair] = []
    for dep in departures:
        for ret in returns:
            nights = (ret - dep).days
            if min_nights <= nights <= max_nights:
                pairs.append(DatePair(dep, ret))
    pairs.sort(key=lambda p: (p.depart, p.ret))
    return pairs


def unique_dates(pairs: list[DatePair]) -> tuple[list[date], list[date]]:
    """Distinct departure / return dates, which is what drives request count."""
    departures = sorted({p.depart for p in pairs})
    returns = sorted({p.ret for p in pairs})
    return departures, returns
