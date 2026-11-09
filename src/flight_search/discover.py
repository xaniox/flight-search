"""Phase 1: discover cheap prices for every destination airport and date.

The upstream calendar endpoint (``GetCalendarGraph``) is gated, so the current
transport costs one page fetch per date. The page accepts at most 14 airports
per request; with all home airports batched in, that means 10 destinations per
request. Each request still covers all home airports and returns the cheapest
rows for the batch, which is enough to rank cities by price.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.combine import (
    filter_departures,
    filter_return_legs,
    options_from_results,
)
from flight_search.config import SearchSettings
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow


class DiscoveryAborted(RuntimeError):
    """Raised when Google rejects too many requests to continue usefully."""


@dataclass(slots=True)
class AirportScreen:
    """Cheapest price seen per date for one destination airport."""

    iata: str
    out: dict[str, float] = field(default_factory=dict)
    ret: dict[str, float] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.out or self.ret)


@dataclass(slots=True)
class DiscoveryResult:
    screens: dict[str, AirportScreen]
    failures: list[str]
    requests: int


def batch_codes(codes: Iterable[str], size: int) -> list[tuple[str, ...]]:
    ordered = list(codes)
    if size < 1:
        raise ValueError("batch size must be >= 1")
    return [tuple(ordered[i : i + size]) for i in range(0, len(ordered), size)]


def _restrictions_key(restrictions) -> dict | None:
    if restrictions is None:
        return None
    return restrictions.model_dump(exclude_none=True)


def _batch_key(
    home: tuple[str, ...],
    batch: tuple[str, ...],
    day: date,
    direction: str,
    settings: SearchSettings,
    restrictions,
) -> dict:
    return {
        "phase": "discover",
        "home": list(home),
        "batch": list(batch),
        "date": day.isoformat(),
        "direction": direction,
        "restrictions": _restrictions_key(restrictions),
        "settings": settings.cache_key(),
    }


def run_discovery(
    destinations: tuple[str, ...],
    home: tuple[str, ...],
    depart_dates: list[date],
    return_dates: list[date],
    depart_window: DepartureWindow,
    return_window: ReturnWindow,
    settings: SearchSettings,
    cache: Cache,
    budget: RequestBudget,
    *,
    batch_size: int | None = None,
    concurrency: int = 6,
    progress: Callable[[int], None] | None = None,
    failure_ratio: float = 0.1,
    min_consecutive_failures: int = 8,
) -> DiscoveryResult:
    """Price all destination airports for every distinct departure/return date."""
    per_request = batch_size or fli_api.max_destinations(len(home))
    per_request = max(1, min(per_request, fli_api.max_destinations(len(home))))
    batches = batch_codes(sorted(destinations), per_request)

    out_restrictions = depart_window.restrictions()
    ret_restrictions = return_window.restrictions()

    screens = {code: AirportScreen(code) for code in destinations}
    failures: list[str] = []
    jobs: list[tuple[str, date, tuple[str, ...]]] = []
    for day in depart_dates:
        for batch in batches:
            jobs.append(("out", day, batch))
    for day in return_dates:
        for batch in batches:
            jobs.append(("ret", day, batch))

    total = len(jobs)
    done = 0
    request_count = 0

    def worker(direction: str, day: date, batch: tuple[str, ...]):
        nonlocal request_count
        restrictions = out_restrictions if direction == "out" else ret_restrictions
        key = _batch_key(home, batch, day, direction, settings, restrictions)
        cached = cache.get(key)
        if isinstance(cached, dict):
            return direction, day, batch, {str(k): float(v) for k, v in cached.items()}, None

        try:
            budget.acquire()
            request_count += 1
            if direction == "out":
                results = fli_api.detail_results(
                    list(home), list(batch), day, restrictions, settings
                )
            else:
                results = fli_api.detail_results(
                    list(batch), list(home), day, restrictions, settings
                )
            options = options_from_results(results)
            if direction == "out":
                options = filter_departures(options, depart_window)
                wanted = set(batch)
                prices: dict[str, float] = {}
                for option in options:
                    code = option.destination
                    if code not in wanted:
                        continue
                    previous = prices.get(code)
                    if previous is None or option.price < previous:
                        prices[code] = option.price
            else:
                options = filter_return_legs(options, return_window, day)
                wanted = set(batch)
                prices = {}
                for option in options:
                    code = option.origin
                    if code not in wanted:
                        continue
                    previous = prices.get(code)
                    if previous is None or option.price < previous:
                        prices[code] = option.price
            cache.put(key, prices)
            return direction, day, batch, prices, None
        except fli_api.BudgetExceeded as exc:
            return direction, day, batch, {}, str(exc)
        except Exception as exc:  # noqa: BLE001 - one bad batch must not kill the run
            return direction, day, batch, {}, f"{type(exc).__name__}: {exc}"

    consecutive = 0
    aborted = False
    all_jobs = list(jobs)

    def handle(result) -> None:
        nonlocal done, consecutive
        direction, day, batch, prices, error = result
        done += 1
        if progress:
            progress(done)
        if error:
            failures.append(f"{direction} {day} {','.join(batch)}: {error}")
            consecutive += 1
            for code in batch:
                screens[code].errors.append(error)
            return
        consecutive = 0
        day_key = day.isoformat()
        for code, price in prices.items():
            screen = screens[code]
            target = screen.out if direction == "out" else screen.ret
            previous = target.get(day_key)
            if previous is None or price < previous:
                target[day_key] = float(price)

    if concurrency <= 1:
        for job in all_jobs:
            handle(worker(*job))
            if failures and consecutive >= min_consecutive_failures:
                aborted = True
                break
    else:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(worker, *job): job for job in all_jobs}
            for future in as_completed(futures):
                handle(future.result())
                if failures:
                    failure_ratio_now = len(failures) / max(done, 1)
                    if (
                        consecutive >= min_consecutive_failures
                        or (
                            done >= 20
                            and failure_ratio_now > failure_ratio
                        )
                    ):
                        aborted = True
                        for pending in futures:
                            pending.cancel()
                        break

    if aborted:
        raise DiscoveryAborted(
            f"Google rejected {len(failures)} of {done} discovery requests. "
            "This usually means throttling or a changed page format. "
            "Try again later, use --region weekend, or narrow --countries."
        )

    return DiscoveryResult(screens=screens, failures=failures, requests=request_count)
