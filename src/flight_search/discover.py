"""Phase 1: discover cheap prices for every destination airport and date.

The upstream calendar endpoint (``GetCalendarGraph``) is gated, so the current
transport fetches a page per date and batch. A batch includes all home airports
and up to 10 destinations, with a limit of 14 airports in total. The cheapest
rows returned from each batch are used to rank cities by price.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date
from time import monotonic

from fli.search.exceptions import SearchHTTPError

from flight_search import fli_api
from flight_search.cache import Cache
from flight_search.combine import (
    filter_airlines,
    filter_departures,
    filter_return_legs,
    options_from_cache,
    options_from_results,
)
from flight_search.config import SearchSettings
from flight_search.fli_api import RequestBudget
from flight_search.windows import DepartureWindow, ReturnWindow, restrictions_key

logger = logging.getLogger(__name__)


class DiscoveryAborted(RuntimeError):
    """Raised when too many discovery batches fail to continue usefully."""


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


# Version of the discovery batch cache key. Both phases also reject payloads
# with missing required fields through options_from_cache.
CACHE_FORMAT = 2


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
        "format": CACHE_FORMAT,
        "home": list(home),
        "batch": list(batch),
        "date": day.isoformat(),
        "direction": direction,
        "restrictions": restrictions_key(restrictions),
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
    airlines: frozenset[str] = frozenset(),
    allow_codeshare: bool = False,
) -> DiscoveryResult:
    """Price all destination airports for every distinct departure/return date.

    Only options that pass the airline check give a price; the cache keeps the
    unchecked options, so every airline list shares the same entries.
    """
    per_request = fli_api.destination_batch_size(len(home), batch_size)
    batches = batch_codes(sorted(destinations), per_request)

    out_restrictions = depart_window.restrictions()
    ret_restrictions = return_window.restrictions()

    screens = {code: AirportScreen(code) for code in destinations}
    failures: list[str] = []
    failure_counts: Counter[str] = Counter()
    failure_examples: dict[str, str] = {}
    jobs: list[tuple[str, date, tuple[str, ...]]] = []
    for day in depart_dates:
        for batch in batches:
            jobs.append(("out", day, batch))
    for day in return_dates:
        for batch in batches:
            jobs.append(("ret", day, batch))

    discovery_started = monotonic()
    logger.debug(
        "Starting %d batches from %s · up to %d destinations per batch · workers: %d",
        len(jobs),
        ", ".join(home),
        per_request,
        concurrency,
    )
    done = 0
    request_count = 0

    def worker(direction: str, day: date, batch: tuple[str, ...]):
        nonlocal request_count
        started = monotonic()
        restrictions = out_restrictions if direction == "out" else ret_restrictions
        key = _batch_key(home, batch, day, direction, settings, restrictions)
        source = "cache"
        error = None
        received = within_window = matched = 0
        prices: dict[str, float] = {}
        try:
            options = options_from_cache(cache.get(key))
            if options is None:
                source = "request budget"
                budget.acquire()
                source = "Google"
                request_count += 1
                results = fli_api.fetch_leg(
                    home, batch, day, direction, restrictions, settings
                )
                options = options_from_results(results)
                cache.put(key, [option.to_dict() for option in options])
            received = len(options)
            if direction == "out":
                options = filter_departures(options, depart_window)
            else:
                options = filter_return_legs(options, return_window, day)
            within_window = len(options)
            options = filter_airlines(options, airlines, allow_codeshare)
            matched = len(options)
            wanted = set(batch)
            for option in options:
                code = option.destination if direction == "out" else option.origin
                if code not in wanted:
                    continue
                previous = prices.get(code)
                if previous is None or option.price < previous:
                    prices[code] = option.price
        except Exception as exc:  # noqa: BLE001 - one bad batch must not kill the run
            kind = type(exc).__name__
            message = (
                str(exc)
                if isinstance(exc, fli_api.BudgetExceeded)
                else f"{kind}: {exc}"
            )
            if isinstance(exc, SearchHTTPError) and exc.status_code is not None:
                kind = f"HTTP {exc.status_code}"
            error = (kind, message)
            prices.clear()
        route = "Outbound" if direction == "out" else "Return"
        airports = ", ".join(batch)
        elapsed_ms = (monotonic() - started) * 1000
        if error:
            logger.debug(
                "%s %s · %s · %s failed after %.0f ms · %s",
                route,
                day,
                airports,
                source,
                elapsed_ms,
                error[1],
            )
        else:
            logger.debug(
                "%s %s · %s · %s in %.0f ms · options: %d → %d (time) → %d (airline) "
                "· priced airports: %d",
                route,
                day,
                airports,
                source,
                elapsed_ms,
                received,
                within_window,
                matched,
                len(prices),
            )
        return direction, day, batch, prices, error

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
            kind, message = error
            failure = f"{direction} {day} {','.join(batch)}: {message}"
            failures.append(failure)
            failure_counts[kind] += 1
            failure_examples.setdefault(kind, failure)
            consecutive += 1
            for code in batch:
                screens[code].errors.append(message)
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
        with ThreadPoolExecutor(
            max_workers=concurrency, thread_name_prefix="discovery"
        ) as pool:
            futures = {pool.submit(worker, *job): job for job in all_jobs}
            for future in as_completed(futures):
                handle(future.result())
                if failures:
                    failure_ratio_now = len(failures) / max(done, 1)
                    if consecutive >= min_consecutive_failures or (
                        done >= 20 and failure_ratio_now > failure_ratio
                    ):
                        aborted = True
                        for pending in futures:
                            pending.cancel()
                        break

    logger.debug(
        "%s in %.0f ms · %d/%d batches processed, %d failed · Google requests: %d",
        "Aborted" if aborted else "Finished",
        (monotonic() - discovery_started) * 1000,
        done,
        len(jobs),
        len(failures),
        request_count,
    )
    if aborted:
        counts = failure_counts.most_common()
        summary = ", ".join(f"{kind}: {count}" for kind, count in counts)
        examples = "\n".join(
            f"Example ({kind}): {failure_examples[kind]}" for kind, _ in counts[:3]
        )
        raise DiscoveryAborted(
            f"{len(failures)} of {done} processed discovery batches failed. "
            f"Causes: {summary}.\n{examples}\n"
            "Use --debug to show per-batch diagnostics."
        )

    return DiscoveryResult(screens=screens, failures=failures, requests=request_count)
