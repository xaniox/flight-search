"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from flight_search.airports import (
    AirportDataError,
    AirportInfo,
    build_city_groups,
    distance_from_karlsruhe,
    filter_airports,
    load_airports,
)
from flight_search.cache import Cache, default_cache_dir, parse_duration
from flight_search.candidates import build_candidates, request_estimate, select_candidates
from flight_search.config import (
    DEFAULT_COUNTRY,
    DEFAULT_CURRENCY,
    DEFAULT_HOME_AIRPORTS,
    DEFAULT_LANGUAGE,
    SearchSettings,
)
from flight_search.dates import (
    DateError,
    expand_date_pairs,
    parse_date,
    parse_weekdays,
    unique_dates,
)
from flight_search.detail import add_roundtrip_comparison, evaluate_candidates
from flight_search.discover import DiscoveryAborted, run_discovery
from flight_search import fli_api
from flight_search.fli_api import RequestBudget
from flight_search.links import attach_links
from flight_search.refresh import refresh_airports
from flight_search.render import (
    dump_json,
    format_window_line,
    render_best_per_city,
    render_results,
    results_payload,
)
from flight_search.windows import (
    DepartureWindow,
    ReturnWindow,
    TimeWindowError,
    parse_clock,
)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in value.split(",") if part.strip())


def _csv_lower(value: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def _weekday_label(days: frozenset[int]) -> str:
    names = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    return ", ".join(names[day] for day in sorted(days))


def _date_label(value: date) -> str:
    return value.strftime("%a %d %b %Y")


@dataclass(slots=True)
class Reporter:
    console: Console
    quiet: bool
    progress: Progress | None = None

    def start(self, description: str, total: int):
        if self.quiet:
            return lambda done: None
        if self.console.is_terminal:
            progress = Progress(
                SpinnerColumn(),
                TextColumn("{task.description}"),
                BarColumn(),
                TextColumn("{task.completed}/{task.total}"),
                TimeElapsedColumn(),
                console=self.console,
                transient=True,
            )
            task = progress.add_task(description, total=total)
            progress.start()
            self.progress = progress
            return lambda done: progress.update(task, completed=done)

        state = {"last": 0}

        def update(done: int) -> None:
            if done == total or done - state["last"] >= 50:
                state["last"] = done
                self.console.print(f"{description}: {done}/{total}", highlight=False)

        return update

    def stop(self) -> None:
        if self.progress is not None:
            self.progress.stop()
            self.progress = None


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="flight-search",
        description="Find cheap weekend getaways and open-jaw itineraries via Google Flights.",
    )
    parser.add_argument("--version", action="version", version="flight-search 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    weekend = subparsers.add_parser(
        "weekend",
        help="Search weekend getaways across a date range.",
    )
    weekend.add_argument(
        "--from",
        dest="home_airports",
        default=",".join(DEFAULT_HOME_AIRPORTS),
        help="Comma-separated home airports (default: FKB,STR,SXB,FRA).",
    )
    weekend.add_argument(
        "--dest",
        default=None,
        help="Explicit destination airport codes (comma-separated); overrides --region.",
    )
    weekend.add_argument(
        "--region",
        choices=("europe", "weekend"),
        default="europe",
        help="europe = all Europe/North Africa airports; weekend = within --max-distance-km.",
    )
    weekend.add_argument(
        "--max-distance-km",
        type=float,
        default=1200.0,
        help="Radius used by --region weekend (default: 1200).",
    )
    weekend.add_argument(
        "--countries",
        default="",
        help="Restrict destinations to ISO country codes, e.g. ES,IT,MA.",
    )
    weekend.add_argument(
        "--exclude",
        default="",
        help="Additional destination airport codes to exclude (comma-separated).",
    )
    weekend.add_argument(
        "--include-small",
        action="store_true",
        help="Include small scheduled airports (more requests).",
    )
    weekend.add_argument(
        "--depart-days",
        default="fri",
        help="Weekdays allowed for departure (default: fri).",
    )
    weekend.add_argument(
        "--return-days",
        default="sun",
        help="Weekdays allowed for the return (default: sun).",
    )
    weekend.add_argument("--start", required=True, help="Start of the date range (YYYY-MM-DD).")
    weekend.add_argument("--end", required=True, help="End of the date range (YYYY-MM-DD).")
    weekend.add_argument("--min-nights", type=int, default=1)
    weekend.add_argument("--max-nights", type=int, default=4)
    weekend.add_argument(
        "--depart-after",
        default=None,
        help="Earliest outbound departure, local time (HH or HH:MM).",
    )
    weekend.add_argument(
        "--depart-before",
        default=None,
        help="Latest outbound departure, local time (HH or HH:MM).",
    )
    weekend.add_argument(
        "--return-depart-after",
        default=None,
        help="Earliest return departure from the destination, local time (HH or HH:MM).",
    )
    weekend.add_argument(
        "--return-arrive-before",
        default=None,
        help="Latest return arrival at the home airport, local time (HH or HH:MM).",
    )
    weekend.add_argument(
        "--max-stops",
        default="ANY",
        help="ANY, 0/NON_STOP, 1/ONE_STOP or 2+ (default: ANY).",
    )
    weekend.add_argument(
        "--cabin",
        default="ECONOMY",
        help="ECONOMY, PREMIUM_ECONOMY, BUSINESS or FIRST.",
    )
    weekend.add_argument("--adults", type=int, default=1)
    weekend.add_argument("--currency", default=DEFAULT_CURRENCY)
    weekend.add_argument("--country", default=DEFAULT_COUNTRY)
    weekend.add_argument("--language", default=DEFAULT_LANGUAGE)
    weekend.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of results to display (default: 20).",
    )
    weekend.add_argument(
        "--best-per-city",
        action="store_true",
        help="Also show the cheapest confirmed itinerary per destination city.",
    )
    weekend.add_argument(
        "--compare-roundtrip",
        action="store_true",
        help="Price conventional same-airport round-trips for comparison.",
    )
    weekend.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: text).",
    )
    weekend.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Also write the JSON payload to this file.",
    )
    weekend.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help="Cache directory (default: ~/.cache/flight-search).",
    )
    weekend.add_argument(
        "--cache-ttl",
        default="12h",
        help="Cache lifetime, e.g. 30m, 12h, 2d or 0 to disable (default: 12h).",
    )
    weekend.add_argument("--no-cache", action="store_true")
    weekend.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Parallel requests (Google is limited to 10/s globally; default: 6).",
    )
    weekend.add_argument(
        "--max-requests",
        type=int,
        default=6000,
        help="Hard ceiling on HTTP requests for the run (default: 6000).",
    )
    weekend.add_argument(
        "--max-candidates",
        type=int,
        default=60,
        help="City/date-pair candidates confirmed in phase 2 (default: 60).",
    )
    weekend.add_argument(
        "--per-city",
        type=int,
        default=3,
        help="Maximum date pairs per city among the confirmed candidates (default: 3).",
    )
    weekend.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Destination airports per phase-1 request (auto; max 14 minus home airports).",
    )
    weekend.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the plan and request estimate without searching.",
    )
    weekend.add_argument("--verbose", action="store_true", help="Print full leg details.")
    weekend.add_argument("--quiet", action="store_true", help="Disable progress output.")

    airports = subparsers.add_parser("airports", help="List the airport dataset.")
    airports.add_argument("--countries", default="")
    airports.add_argument("--include-small", action="store_true")
    airports.add_argument(
        "--region",
        choices=("europe", "weekend"),
        default="europe",
    )
    airports.add_argument("--max-distance-km", type=float, default=1200.0)
    airports.add_argument(
        "--dest",
        default=None,
        help="Only show these codes (comma-separated).",
    )

    refresh = subparsers.add_parser(
        "refresh-airports",
        help="Regenerate the vendored airport dataset from OurAirports.",
    )
    refresh.add_argument("--url", default=None)

    return parser


def _select_airports(args) -> tuple[tuple[AirportInfo, ...], list[str]]:
    all_airports = load_airports(include_small=args.include_small)
    home = _csv_tuple(args.home_airports)
    known = {a.iata for a in all_airports}
    warnings = [f"Unknown or unsupported airport code: {code}" for code in home if code not in known]
    if not home:
        raise ValueError("At least one home airport is required")

    excluded = set(home) | set(_csv_tuple(args.exclude))
    wanted_codes = _csv_tuple(args.dest) if args.dest else ()

    if wanted_codes:
        missing = [code for code in wanted_codes if code not in known]
        warnings.extend(f"Unknown or unsupported destination code: {code}" for code in missing)
        destinations = filter_airports(
            all_airports,
            codes=tuple(code for code in wanted_codes if code in known),
            exclude=frozenset(excluded),
        )
    else:
        countries = frozenset(_csv_tuple(args.countries))
        max_distance = args.max_distance_km if args.region == "weekend" else None
        destinations = filter_airports(
            all_airports,
            countries=countries,
            max_distance_km=max_distance,
            exclude=frozenset(excluded),
        )
    return destinations, warnings


def _build_settings(args) -> SearchSettings:
    return SearchSettings(
        cabin=args.cabin.upper(),
        max_stops=args.max_stops.upper(),
        adults=args.adults,
        currency=args.currency.upper(),
        country=args.country.upper() if args.country else None,
        language=args.language or None,
    )


def _run_weekend(args) -> int:
    console = Console()
    error_console = Console(stderr=True)
    reporter = Reporter(console=error_console, quiet=args.quiet)

    try:
        start = parse_date(args.start)
        end = parse_date(args.end)
        depart_days = parse_weekdays([args.depart_days])
        return_days = parse_weekdays([args.return_days])
        pairs = expand_date_pairs(
            start, end, depart_days, return_days, args.min_nights, args.max_nights
        )
        depart_window = DepartureWindow(
            after=parse_clock(args.depart_after) if args.depart_after else None,
            before=parse_clock(args.depart_before) if args.depart_before else None,
        )
        return_window = ReturnWindow(
            depart_after=parse_clock(args.return_depart_after)
            if args.return_depart_after
            else None,
            arrive_before=parse_clock(args.return_arrive_before)
            if args.return_arrive_before
            else None,
        )
    except (DateError, TimeWindowError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2

    if start < date.today():
        error_console.print(
            f"[bold red]Error:[/bold red] start date {start} is in the past."
        )
        return 2

    if not pairs:
        error_console.print(
            "[bold red]Error:[/bold red] no departure/return date pairs match the "
            "weekday and night constraints inside the range."
        )
        return 2

    home = _csv_tuple(args.home_airports)
    if not home:
        error_console.print("[bold red]Error:[/bold red] at least one home airport is required.")
        return 2
    if len(home) > 8:
        error_console.print(
            "[bold red]Error:[/bold red] at most 8 home airports can be searched "
            "at once (Google accepts 14 airports per request and large metros "
            "use up to 6 destination airports)."
        )
        return 2
    for code in home:
        try:
            fli_api.resolve_airport(code)
        except ValueError:
            error_console.print(
                f"[bold red]Error:[/bold red] unknown home airport code {code!r}."
            )
            return 2

    try:
        destinations, warnings = _select_airports(args)
    except (AirportDataError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2

    for warning in warnings:
        error_console.print(f"[yellow]warning:[/yellow] {warning}")

    if not destinations:
        error_console.print("[bold red]Error:[/bold red] no destination airports selected.")
        return 2

    cities = build_city_groups(destinations)
    depart_dates, return_dates = unique_dates(pairs)
    settings = _build_settings(args)
    batch_size = max(1, args.batch_size) if args.batch_size else max(1, 14 - len(home))
    estimated = request_estimate(
        len(destinations),
        len(depart_dates),
        len(return_dates),
        home_airports=len(home),
        batch_size=batch_size,
        max_candidates=args.max_candidates,
    )

    if args.format == "text":
        console.print()
        console.print(f"[bold]Weekend getaways from {', '.join(home)}[/bold]")
        console.print(
            f"{_date_label(start)} – {_date_label(end)} · depart {_weekday_label(depart_days)}"
            f" · return {_weekday_label(return_days)} · {args.min_nights}–{args.max_nights} nights"
        )
        console.print(
            format_window_line(depart_window.label(), return_window.label())
        )
        console.print(
            f"{len(destinations)} destination airports in {len(cities)} cities · "
            f"{len(pairs)} date pairs · up to ~{estimated} requests "
            f"({len(depart_dates)} depart + {len(return_dates)} return dates × "
            f"{max(1, (len(destinations) + batch_size - 1) // batch_size)} batches)"
        )
        console.print()


    if args.dry_run:
        error_console.print("[bold]Dry run — no requests made.[/bold]")
        for pair in pairs[:10]:
            error_console.print(f"  {pair.depart} → {pair.ret} ({pair.nights} nights)")
        if len(pairs) > 10:
            error_console.print(f"  … and {len(pairs) - 10} more date pairs")
        return 0

    if estimated > args.max_requests:
        error_console.print(
            f"[bold red]Error:[/bold red] this run needs ~{estimated} requests, "
            f"above --max-requests {args.max_requests}. Narrow the region or raise the limit."
        )
        return 2

    ttl = parse_duration(args.cache_ttl)
    cache = Cache(
        directory=args.cache_dir or default_cache_dir(),
        ttl=ttl,
        enabled=not args.no_cache,
    )
    budget = RequestBudget(args.max_requests)

    batch_count = max(1, (len(destinations) + batch_size - 1) // batch_size)
    update = reporter.start(
        "Pricing destinations",
        (len(depart_dates) + len(return_dates)) * batch_count,
    )
    try:
        discovery = run_discovery(
            destinations=tuple(a.iata for a in destinations),
            home=home,
            depart_dates=depart_dates,
            return_dates=return_dates,
            depart_window=depart_window,
            return_window=return_window,
            settings=settings,
            cache=cache,
            budget=budget,
            batch_size=batch_size,
            concurrency=max(1, args.concurrency),
            progress=update,
        )
    except DiscoveryAborted as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2
    finally:
        reporter.stop()

    screens = discovery.screens
    failures = discovery.failures
    if failures:
        error_console.print(
            f"[yellow]warning:[/yellow] {len(failures)} discovery requests failed; "
            f"first: {failures[0]}"
        )

    candidates = build_candidates(cities, screens, pairs)
    if not candidates:
        error_console.print(
            "[bold red]No priced candidates.[/bold red] Google returned no rows for the "
            "selected airports/dates. Try a wider date range or region."
        )
        return 1

    shortlist = select_candidates(
        candidates, per_city=max(1, args.per_city), limit=args.max_candidates
    )
    pool_size = max(args.top, 100) if args.best_per_city else args.top
    update = reporter.start("Confirming candidates", len(shortlist))
    try:
        pool = evaluate_candidates(
            shortlist,
            home=home,
            settings=settings,
            cache=cache,
            budget=budget,
            depart_window=depart_window,
            return_window=return_window,
            pool_size=pool_size,
            max_candidates=args.max_candidates,
            progress=update,
        )
    except Exception as exc:  # noqa: BLE001
        error_console.print(f"[bold red]Error:[/bold red] {type(exc).__name__}: {exc}")
        return 2
    finally:
        reporter.stop()

    if not pool:
        error_console.print(
            "[bold red]No itineraries confirmed.[/bold red] Calendar prices did not "
            "reproduce in detailed searches; try another date range."
        )
        return 1

    attach_links(pool, settings)
    displayed = pool[: args.top]
    if args.compare_roundtrip:
        update = reporter.start("Pricing round-trips", len(displayed))
        try:
            add_roundtrip_comparison(
                displayed,
                home=home,
                settings=settings,
                cache=cache,
                budget=budget,
            )
            update(len(displayed))
        finally:
            reporter.stop()

    stats = {
        "destination_airports": len(destinations),
        "cities": len(cities),
        "date_pairs": len(pairs),
        "distinct_departure_dates": len(depart_dates),
        "distinct_return_dates": len(return_dates),
        "batch_size": batch_size,
        "candidates": len(candidates),
        "shortlisted": len(shortlist),
        "confirmed_pool": len(pool),
        "discovery_requests": discovery.requests,
        "requests": budget.used,
        "cache_hits": cache.stats.hits,
        "cache_misses": cache.stats.misses,
        "discovery_failures": len(failures),
    }
    query = {
        "home_airports": list(home),
        "depart_days": sorted(depart_days),
        "return_days": sorted(return_days),
        "start": start.isoformat(),
        "end": end.isoformat(),
        "min_nights": args.min_nights,
        "max_nights": args.max_nights,
        "region": "dest" if args.dest else args.region,
        "destinations": list(_csv_tuple(args.dest)) if args.dest else None,
        "countries": list(_csv_tuple(args.countries)) if args.countries else None,
        "settings": settings.cache_key(),
    }
    windows = {
        "departure": depart_window.label(),
        "return": return_window.label(),
    }
    payload = results_payload(
        displayed,
        query=query,
        stats=stats,
        failed=failures,
        windows=windows,
    )

    if args.output:
        import json

        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        error_console.print(f"Wrote {args.output}")

    if args.format == "json":
        dump_json(payload, console)
    else:
        render_results(
            displayed,
            console=console,
            query_lines=[
                f"{len(destinations)} airports · {len(cities)} cities · "
                f"{stats['requests']} requests · cache {stats['cache_hits']} hits",
            ],
            show_roundtrip=args.compare_roundtrip,
            verbose=args.verbose,
        )
        if args.best_per_city:
            render_best_per_city(pool, console=console)

    return 0


def _run_airports(args) -> int:
    console = Console()
    try:
        airports = load_airports(include_small=args.include_small)
    except AirportDataError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2
    max_distance = args.max_distance_km if args.region == "weekend" else None
    selected = filter_airports(
        airports,
        codes=_csv_tuple(args.dest) if args.dest else (),
        countries=frozenset(_csv_tuple(args.countries)) if args.countries else frozenset(),
        max_distance_km=max_distance,
    )
    table = Table(box=None)
    table.add_column("IATA", style="cyan")
    table.add_column("City")
    table.add_column("Country")
    table.add_column("Airport")
    table.add_column("km", justify="right")
    for airport in selected:
        table.add_row(
            airport.iata,
            airport.city,
            airport.country,
            airport.name,
            f"{distance_from_karlsruhe(airport):.0f}",
        )
    console.print(f"{len(selected)} airports")
    console.print(table)
    return 0


def _run_refresh(args) -> int:
    console = Console()
    try:
        stats = refresh_airports(url=args.url) if args.url else refresh_airports()
    except Exception as exc:  # noqa: BLE001
        console.print(f"[bold red]Error:[/bold red] {type(exc).__name__}: {exc}")
        return 2
    console.print(
        f"Wrote {stats['total']} airports "
        f"({stats['medium_large']} medium/large, {stats['small']} small)"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "weekend":
        return _run_weekend(args)
    if args.command == "airports":
        return _run_airports(args)
    if args.command == "refresh-airports":
        return _run_refresh(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
