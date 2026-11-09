"""Optional departure / arrival time windows.

Google's request format only accepts whole hours, and its bounds are inclusive
of the whole hour (``latest_arrival=12`` also matches 12:45). It is also not
date-aware, so a next-day 01:00 arrival passes a 12:00 hour bound.

Strategy: send permissive whole-hour bounds to Google (truncated, never
rounded up), then enforce the exact minute / date rule locally on the decoded
itineraries. When no window is given, no ``TimeRestrictions`` object is sent
at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

from fli.models import TimeRestrictions


class TimeWindowError(ValueError):
    """Invalid time window specification."""


def parse_clock(value: str) -> time:
    """Parse ``HH`` or ``HH:MM`` into a time."""
    parts = value.strip().split(":")
    try:
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError) as exc:
        raise TimeWindowError(f"Invalid time {value!r}: expected HH or HH:MM") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise TimeWindowError(f"Invalid time {value!r}: out of range")
    return time(hour, minute)


@dataclass(frozen=True, slots=True)
class DepartureWindow:
    """Outbound departure window, both bounds optional (inclusive)."""

    after: time | None = None
    before: time | None = None

    def __post_init__(self) -> None:
        if self.before is not None and self.before == time(0, 0):
            raise TimeWindowError("A latest departure of 00:00 is not meaningful")
        if self.after is not None and self.before is not None:
            if self.after >= self.before:
                raise TimeWindowError(
                    "Departure window crosses midnight or is empty: "
                    f"{self.after.strftime('%H:%M')}–{self.before.strftime('%H:%M')}. "
                    "Windows must stay inside one day."
                )

    @property
    def active(self) -> bool:
        return self.after is not None or self.before is not None

    def restrictions(self) -> TimeRestrictions | None:
        if not self.active:
            return None
        return TimeRestrictions(
            earliest_departure=self.after.hour if self.after else None,
            latest_departure=self.before.hour if self.before else None,
        )

    def matches(self, departure: datetime) -> bool:
        moment = departure.time()
        if self.after is not None and moment < self.after:
            return False
        if self.before is not None and moment > self.before:
            return False
        return True

    def label(self) -> str:
        if not self.active:
            return "any time"
        after = self.after.strftime("%H:%M") if self.after else "00:00"
        before = self.before.strftime("%H:%M") if self.before else "23:59"
        return f"{after}–{before}"

    def cache_key(self) -> dict[str, str | None]:
        return {
            "after": self.after.strftime("%H:%M") if self.after else None,
            "before": self.before.strftime("%H:%M") if self.before else None,
        }


@dataclass(frozen=True, slots=True)
class ReturnArrivalWindow:
    """Latest local arrival at the home airport for the return leg."""

    before: time | None = None

    def __post_init__(self) -> None:
        if self.before is not None and self.before == time(0, 0):
            raise TimeWindowError(
                "A latest arrival of 00:00 is not meaningful; use 23:59 for 'before midnight'"
            )

    @property
    def active(self) -> bool:
        return self.before is not None

    def restrictions(self) -> TimeRestrictions | None:
        if self.before is None:
            return None
        return TimeRestrictions(latest_arrival=self.before.hour)

    def matches(self, arrival: datetime, return_date: date) -> bool:
        if self.before is None:
            return True
        cutoff = datetime.combine(return_date, self.before)
        return arrival <= cutoff

    def label(self) -> str:
        return self.before.strftime("%H:%M") if self.before else "any time"

    def cache_key(self) -> dict[str, str | None]:
        return {"before": self.before.strftime("%H:%M") if self.before else None}
