"""Command-line interface."""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from copy import copy
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from time import monotonic
from typing import ClassVar

from rich.console import Console
from rich.markup import escape
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

from flight_search.airports import (
    AirportDataError,
    AirportInfo,
    build_city_groups,
    display_city,
    distance_km,
    load_airports,
)
from flight_search.config import (
    DEFAULT_COUNTRY,
    DEFAULT_CURRENCY,
    DEFAULT_HOME_AIRPORTS,
    DEFAULT_LANGUAGE,
    KARLSRUHE,
    SearchSettings,
)
from flight_search.destinations import DestinationChoice, select_destinations
from flight_search.detail import add_roundtrip_comparison
from flight_search.discover import DiscoveryAborted
from flight_search.links import attach_links
from flight_search.refresh import refresh_airports
from flight_search.render import (
    dump_json,
    format_window_line,
    render_best_per_city,
    render_results,
    results_payload,
)
from flight_search.search import run_search
from flight_search.settings_file import (
    BUILT_IN_REGIONS,
    ConfigError,
    Settings,
    apply_defaults,
    load,
)
from flight_search.weekend import (
    AirlineError,
    WeekendBudgetError,
    WeekendError,
    WeekendQuery,
    prepare_weekend,
    resolve_weekend_destinations,
)

logger = logging.getLogger(__name__)


class _ConsoleLogHandler(logging.Handler):
    """Print through the console shared with Rich progress."""

    _labels: ClassVar[dict[str, str]] = {
        "flight_search.cli": "Search",
        "flight_search.search": "Search",
        "flight_search.discover": "Discovery",
        "flight_search.detail": "Confirmation",
        "flight_search.detail.roundtrip": "Round-trip",
        "flight_search.cache": "Cache",
        "fli.search._tfs": "Transport",
    }

    def __init__(self, console: Console) -> None:
        super().__init__()
        self.console = console

    def emit(self, record: logging.LogRecord) -> None:
        try:
            record = copy(record)
            record.name = self._labels.get(record.name, record.name)
            if record.threadName and record.threadName.startswith("discovery_"):
                record.name += f" [{record.threadName.removeprefix('discovery_')}]"
            self.console.print(Text(self.format(record)), soft_wrap=True)
        except Exception:  # noqa: BLE001 - report handler failures via logging
            self.handleError(record)


def _csv_tuple(value: str) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in value.split(",") if part.strip())


def _csv_lower(value: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in value.split(",") if part.strip())


def _airline_line(airlines: frozenset[str], allow_codeshare: bool) -> str:
    rule = (
        "selling airline of every leg, codeshares allowed"
        if allow_codeshare
        else "selling and operating airline of every leg"
    )
    return f"airlines {', '.join(sorted(airlines))} ({rule})"


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

    def discovered(self, failures: Sequence[str]) -> None:
        if failures:
            self.console.print(
                f"[yellow]warning:[/yellow] {len(failures)} discovery requests failed; "
                f"first: {failures[0]}"
            )


REGION_HELP = (
    "europe = Europe including Cyprus, the Greek islands and the Canaries, plus "
    "North Africa, Turkey and the Caucasus; weekend = the same within --max-distance-km."
)
EXCLUDE_COUNTRIES_HELP = (
    "Leave out whole countries by ISO code (comma-separated), e.g. RU,BY; "
    "explicit --dest codes are kept."
)
INCLUDE_SMALL_HELP = (
    "Include small scheduled airports (more requests); airports named by "
    "{named} are always used, even when small."
)
AIRLINES_HELP = (
    "Keep only itineraries where the selling and the operating airline of every "
    "leg are in this list of IATA codes (comma-separated), e.g. A3,OA; "
    "--allow-codeshare checks the selling airline only. A leg without a "
    "reported operator counts as operated by its selling airline. The price "
    "shown is the cheapest matching flight Google returned in a batch, so "
    "cheaper matching flights or whole destinations can be missing."
)
MAX_DISTANCE_HELP = "Radius used by --region weekend (default: %(default)g)."

# The options that choose the destinations; their file values give way to any
# of them on the command line (see _drop_file_selection).
SELECTION_OPTIONS = frozenset({"dest", "countries", "region"})


class _DefaultsHelpFormatter(argparse.HelpFormatter):
    """Append the default in effect, also one the config file set, to each help.

    Defaults of ``None`` or an empty string mean "not set" and stay unprinted.
    """

    def _get_help_string(self, action):
        help_text = action.help or ""
        if "%(default)" in help_text or action.default in (
            None,
            "",
            argparse.SUPPRESS,
        ):
            return help_text
        return f"{help_text} (default: %(default)s)".lstrip()


class _StoreGiven(argparse.Action):
    """Store the value and note in ``given`` that the command line set it."""

    def __call__(self, parser, namespace, values, option_string=None):
        setattr(namespace, self.dest, values)
        namespace.given = namespace.given | {self.dest}


def _build_parser(settings: Settings | None = None) -> argparse.ArgumentParser:
    """The parser; ``settings`` from the config file add regions and defaults."""
    settings = settings or Settings()
    region_choices = (*BUILT_IN_REGIONS, *settings.regions)
    region_help = REGION_HELP
    if settings.regions:
        region_help += (
            f" From the config file: {', '.join(settings.regions)}"
            " (their countries, no radius)."
        )
    parser = argparse.ArgumentParser(
        prog="flight-search",
        description="Find cheap weekend getaways and open-jaw itineraries via Google Flights.",
    )
    parser.add_argument("--version", action="version", version="flight-search 0.1.0")
    subparsers = parser.add_subparsers(dest="command", required=True)

    weekend = subparsers.add_parser(
        "weekend",
        help="Search weekend getaways across a date range.",
        formatter_class=_DefaultsHelpFormatter,
    )
    weekend.add_argument(
        "--from",
        dest="home_airports",
        default=",".join(DEFAULT_HOME_AIRPORTS),
        help="Comma-separated home airports (default: %(default)s).",
    )
    weekend.add_argument(
        "--dest",
        action=_StoreGiven,
        default=None,
        help="Explicit destination airport codes (comma-separated); overrides --region.",
    )
    weekend.add_argument(
        "--region",
        action=_StoreGiven,
        choices=region_choices,
        default="europe",
        help=region_help,
    )
    weekend.add_argument(
        "--max-distance-km",
        type=float,
        default=1200.0,
        help=MAX_DISTANCE_HELP,
    )
    weekend.add_argument(
        "--countries",
        action=_StoreGiven,
        default="",
        help=(
            "Choose destinations by ISO country code from the worldwide dataset "
            "instead of the default region, e.g. ES,IT,IL; --region weekend keeps its radius."
        ),
    )
    weekend.add_argument(
        "--exclude",
        default="",
        help="Additional destination airport codes to exclude (comma-separated).",
    )
    weekend.add_argument("--exclude-countries", default="", help=EXCLUDE_COUNTRIES_HELP)
    weekend.add_argument(
        "--include-small",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=INCLUDE_SMALL_HELP.format(named="--dest or --from"),
    )
    weekend.add_argument(
        "--depart-days",
        default="fri",
        help="Weekdays allowed for departure (default: %(default)s).",
    )
    weekend.add_argument(
        "--return-days",
        default="sun",
        help="Weekdays allowed for the return (default: %(default)s).",
    )
    weekend.add_argument(
        "--start", required=True, help="Start of the date range (YYYY-MM-DD)."
    )
    weekend.add_argument(
        "--end", required=True, help="End of the date range (YYYY-MM-DD)."
    )
    weekend.add_argument(
        "--min-nights", type=int, default=1, help="Fewest nights at the destination."
    )
    weekend.add_argument(
        "--max-nights", type=int, default=4, help="Most nights at the destination."
    )
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
        "--airlines", action=_StoreGiven, default="", help=AIRLINES_HELP
    )
    weekend.add_argument(
        "--allow-codeshare",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "With --airlines, check only the selling airline of every leg; "
            "the operating airline may differ."
        ),
    )
    weekend.add_argument(
        "--max-stops",
        default="ANY",
        help="ANY, 0/NON_STOP, 1/ONE_STOP or 2+ (default: %(default)s).",
    )
    weekend.add_argument(
        "--cabin",
        default="ECONOMY",
        help="ECONOMY, PREMIUM_ECONOMY, BUSINESS or FIRST.",
    )
    weekend.add_argument("--adults", type=int, default=1, help="Number of adults.")
    weekend.add_argument(
        "--currency", default=DEFAULT_CURRENCY, help="Currency of the prices."
    )
    weekend.add_argument(
        "--country",
        default=DEFAULT_COUNTRY,
        help="Country (market) of the Google Flights request.",
    )
    weekend.add_argument(
        "--language",
        default=DEFAULT_LANGUAGE,
        help="Language of the Google Flights request.",
    )
    weekend.add_argument(
        "--top",
        type=int,
        default=20,
        help="Number of results to display (default: %(default)s).",
    )
    weekend.add_argument(
        "--best-per-city",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Also show the cheapest confirmed itinerary per destination city.",
    )
    weekend.add_argument(
        "--compare-roundtrip",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Price conventional same-airport round-trips for comparison across "
            "all airlines, even when --airlines filters the itinerary."
        ),
    )
    weekend.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format (default: %(default)s).",
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
        help=(
            "Cache directory (default: %(default)s)."
            if "cache_dir" in settings.options
            else "Cache directory (default: ~/.cache/flight-search)."
        ),
    )
    weekend.add_argument(
        "--cache-ttl",
        default="12h",
        help="Cache lifetime, e.g. 30m, 12h, 2d or 0 to disable (default: %(default)s).",
    )
    weekend.add_argument(
        "--cache",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Use the disk cache; --no-cache neither reads nor writes it.",
    )
    weekend.add_argument(
        "--concurrency",
        type=int,
        default=6,
        help="Parallel requests (Google is limited to 10/s globally; default: %(default)s).",
    )
    weekend.add_argument(
        "--max-requests",
        type=int,
        default=6000,
        help="Search request budget before transport retries (default: %(default)s).",
    )
    weekend.add_argument(
        "--max-candidates",
        type=int,
        default=60,
        help="City/date-pair candidates confirmed in phase 2 (default: %(default)s).",
    )
    weekend.add_argument(
        "--per-city",
        type=int,
        default=3,
        help="Maximum date pairs per city among the confirmed candidates (default: %(default)s).",
    )
    weekend.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="Destination airports per discovery batch (max 10, and 14 airports total).",
    )
    weekend.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Show the plan and request estimate without searching.",
    )
    weekend.add_argument(
        "--verbose",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print full leg details.",
    )
    weekend.add_argument(
        "--debug",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Log all search phases, cache activity and transport diagnostics to stderr.",
    )
    weekend.add_argument(
        "--quiet",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Disable progress output.",
    )

    airports = subparsers.add_parser(
        "airports",
        help="List the airport dataset.",
        formatter_class=_DefaultsHelpFormatter,
    )
    airports.add_argument(
        "--countries",
        action=_StoreGiven,
        default="",
        help=(
            "Show the airports of these ISO country codes (comma-separated) "
            "instead of the default region; --region weekend keeps its radius."
        ),
    )
    airports.add_argument(
        "--exclude-countries", default="", help=EXCLUDE_COUNTRIES_HELP
    )
    airports.add_argument(
        "--include-small",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=INCLUDE_SMALL_HELP.format(named="--dest"),
    )
    airports.add_argument(
        "--region",
        action=_StoreGiven,
        choices=region_choices,
        default="europe",
        help=region_help,
    )
    airports.add_argument(
        "--max-distance-km", type=float, default=1200.0, help=MAX_DISTANCE_HELP
    )
    airports.add_argument(
        "--dest",
        action=_StoreGiven,
        default=None,
        help=(
            "Only show these codes (comma-separated); overrides --countries, "
            "the region and the radius of --region weekend."
        ),
    )

    web = subparsers.add_parser("web", help="Serve weekend search in a local browser.")
    web.add_argument(
        "--port", type=int, default=8765, help="Local port (default: %(default)s)."
    )

    refresh = subparsers.add_parser(
        "refresh-airports",
        help="Regenerate the vendored airport dataset from OurAirports.",
    )
    refresh.add_argument("--url", default=None)

    for subparser in (weekend, airports):
        subparser.set_defaults(
            center=settings.home or KARLSRUHE,
            regions=settings.regions,
            given=frozenset(),
        )
    weekend.set_defaults(airlines_config_path=settings.path)
    apply_defaults(settings, {"weekend": weekend, "airports": airports})
    return parser


def _drop_file_selection(args) -> None:
    """Let a destination choice on the command line beat the file's.

    ``--dest`` and ``--countries`` take precedence over ``--region`` whatever
    their source, so a ``countries`` or ``dest`` from the config file would
    beat a ``--region`` on the command line. Once the command line names any
    of the three, the file's ``countries`` and ``dest`` are dropped.
    """
    if args.given & SELECTION_OPTIONS:
        if "countries" not in args.given:
            args.countries = ""
        if "dest" not in args.given:
            args.dest = None


def _countries(args) -> frozenset[str]:
    """``--countries``, else the countries of a named region from the config file."""
    return frozenset(_csv_tuple(args.countries)) or args.regions.get(
        args.region, frozenset()
    )


def _destination_choice(args, **extra) -> DestinationChoice:
    """The destination options of ``weekend`` and ``airports`` as one choice."""
    return DestinationChoice(
        codes=_csv_tuple(args.dest) if args.dest else (),
        countries=_countries(args),
        region=args.region,
        max_distance_km=args.max_distance_km,
        include_small=args.include_small,
        exclude_countries=frozenset(_csv_tuple(args.exclude_countries)),
        **extra,
    )


def _select_airports(args) -> tuple[tuple[AirportInfo, ...], list[str]]:
    return resolve_weekend_destinations(
        _csv_tuple(args.home_airports),
        _destination_choice(args, exclude_codes=frozenset(_csv_tuple(args.exclude))),
        center=args.center,
        airport_loader=load_airports,
        warn_missing_home=True,
    )


def _build_settings(args) -> SearchSettings:
    return SearchSettings(
        cabin=args.cabin.upper(),
        max_stops=args.max_stops.upper(),
        adults=args.adults,
        currency=args.currency.upper(),
        country=args.country.upper() if args.country else None,
        language=args.language or None,
    )


def _weekend_query(args) -> WeekendQuery:
    return WeekendQuery(
        start=args.start,
        end=args.end,
        depart_days=(args.depart_days,),
        return_days=(args.return_days,),
        min_nights=args.min_nights,
        max_nights=args.max_nights,
        home=_csv_tuple(args.home_airports),
        destination=_destination_choice(
            args, exclude_codes=frozenset(_csv_tuple(args.exclude))
        ),
        center=args.center,
        settings=_build_settings(args),
        max_requests=args.max_requests,
        depart_after=args.depart_after,
        depart_before=args.depart_before,
        return_depart_after=args.return_depart_after,
        return_arrive_before=args.return_arrive_before,
        airline_codes=tuple(args.airlines.split(",")),
        allow_codeshare=args.allow_codeshare,
        batch_size=args.batch_size,
        max_candidates=args.max_candidates,
        concurrency=args.concurrency,
        per_city=args.per_city,
    )


def _run_weekend(args, *, error_console: Console | None = None) -> int:
    started = monotonic()
    console = Console()
    error_console = error_console or Console(stderr=True)
    reporter = Reporter(console=error_console, quiet=args.quiet)

    airline_source = (
        f"{args.airlines_config_path}: 'airlines'"
        if args.airlines_config_path is not None and "airlines" not in args.given
        else "--airlines"
    )
    query = _weekend_query(args)
    try:
        plan = prepare_weekend(
            query,
            today=date.today(),
            destination_resolver=lambda: _select_airports(args),
            airline_source=airline_source,
        )
    except WeekendError as exc:
        for warning in exc.warnings:
            error_console.print(f"[yellow]warning:[/yellow] {warning}")
        error_console.print(
            f"[bold red]Error:[/bold red] {escape(str(exc))}",
            soft_wrap=isinstance(exc, AirlineError),
        )
        return 2
    except (AirportDataError, ValueError) as exc:
        error_console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2

    for warning in plan.warnings:
        error_console.print(f"[yellow]warning:[/yellow] {warning}")

    request = plan.request
    home = request.home
    destinations = request.destinations
    pairs = request.pairs
    start, end = plan.start, plan.end
    depart_days, return_days = plan.depart_days, plan.return_days
    depart_dates, return_dates = plan.depart_dates, plan.return_dates
    depart_window, return_window = request.depart_window, request.return_window
    settings = request.settings
    airlines = request.airlines
    batch_size = request.batch_size
    estimated = plan.estimated_requests
    cities = build_city_groups(destinations)
    carrier_label = ", ".join(sorted(airlines)) or "any airline"
    if airlines and args.allow_codeshare:
        carrier_label += " (codeshares allowed)"
    logger.debug(
        "%s: %s · %s to %s · %d date pairs, %d destinations · %d per batch · %s "
        "· estimated requests: %d (budget: %d)",
        "Dry run" if args.dry_run else "Plan",
        ", ".join(home),
        start,
        end,
        len(pairs),
        len(destinations),
        batch_size,
        carrier_label,
        estimated,
        args.max_requests,
    )

    if args.format == "text":
        console.print()
        console.print(f"[bold]Weekend getaways from {', '.join(home)}[/bold]")
        console.print(
            f"{_date_label(start)} – {_date_label(end)} · depart {_weekday_label(depart_days)}"
            f" · return {_weekday_label(return_days)} · {args.min_nights}–{args.max_nights} nights"
        )
        console.print(format_window_line(depart_window.label(), return_window.label()))
        if airlines:
            console.print(_airline_line(airlines, args.allow_codeshare))
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

    try:
        cache, budget = plan.create_resources(
            cache_dir=args.cache_dir, cache_ttl=args.cache_ttl, cache_enabled=args.cache
        )
    except WeekendBudgetError as exc:
        error_console.print(
            f"[bold red]Error:[/bold red] this run needs ~{exc.estimated_requests} requests, "
            f"above --max-requests {exc.max_requests}. Narrow the region or raise the limit."
        )
        return 2
    logger.debug(
        "Cache: %s", f"enabled (TTL {args.cache_ttl})" if cache.active else "disabled"
    )

    try:
        result = run_search(request, cache=cache, budget=budget, progress=reporter)
    except DiscoveryAborted as exc:
        error_console.print(f"[bold red]Error:[/bold red] {escape(str(exc))}")
        return 2
    except Exception as exc:
        logger.debug("Search failed", exc_info=True)
        error_console.print(f"[bold red]Error:[/bold red] {type(exc).__name__}: {exc}")
        return 2

    airline_filter = f"--airlines {','.join(sorted(airlines))}" if airlines else ""
    if not result.stats.candidates:
        explanation = (
            f"No priced flights matched the search with {airline_filter}. "
            "Try adjusting the airline filter or widening the date range or region."
            if airlines
            else "Google returned no rows for the selected airports/dates. "
            "Try a wider date range or region."
        )
        error_console.print(f"[bold red]No priced candidates.[/bold red] {explanation}")
        return 1

    pool_size = max(args.top, 100) if args.best_per_city else args.top
    itineraries = result.itineraries()
    pool = itineraries[:pool_size]
    logger.debug(
        "Ranked %d itineraries (kept %d for display)", len(itineraries), len(pool)
    )
    if not pool:
        explanation = (
            f"No detailed results matched the search with {airline_filter}. "
            "Try adjusting the airline filter or choosing another date range."
            if airlines
            else "Calendar prices did not reproduce in detailed searches; try another date range."
        )
        error_console.print(
            f"[bold red]No itineraries confirmed.[/bold red] {explanation}"
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

    found = result.stats
    failures = list(result.failures)
    stats = {
        "destination_airports": found.destination_airports,
        "cities": found.cities,
        "date_pairs": found.date_pairs,
        "distinct_departure_dates": found.distinct_departure_dates,
        "distinct_return_dates": found.distinct_return_dates,
        "batch_size": found.batch_size,
        "candidates": found.candidates,
        "shortlisted": found.shortlisted,
        "confirmed_pool": len(pool),
        "discovery_requests": found.discovery_requests,
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
        "airlines": sorted(airlines),
        "allow_codeshare": bool(airlines) and args.allow_codeshare,
        "settings": settings.cache_key(),
    }
    compare_across_airlines = args.compare_roundtrip and bool(airlines)
    if compare_across_airlines:
        query["roundtrip_airlines"] = []
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
        query_lines = [
            (
                f"{len(destinations)} airports · {len(cities)} cities · "
                f"{stats['requests']} requests · cache {stats['cache_hits']} hits"
            ),
        ]
        if compare_across_airlines:
            query_lines.append(
                "vs RT uses a conventional round-trip across all airlines."
            )
        render_results(
            displayed,
            console=console,
            query_lines=query_lines,
            show_roundtrip=args.compare_roundtrip,
            verbose=args.verbose,
        )
        if args.best_per_city:
            render_best_per_city(pool, console=console)

    logger.debug(
        "Finished in %.0f ms · results shown: %d · requests: %d · cache: %d hits, "
        "%d misses, %d writes · discovery failures: %d",
        (monotonic() - started) * 1000,
        len(displayed),
        budget.used,
        cache.stats.hits,
        cache.stats.misses,
        cache.stats.writes,
        len(failures),
    )
    return 0


def _run_airports(args) -> int:
    console = Console()
    try:
        airports = load_airports(include_small=True)
    except AirportDataError as exc:
        console.print(f"[bold red]Error:[/bold red] {exc}")
        return 2
    # The listing leaves unknown codes out without a warning.
    selected, _ = select_destinations(
        _destination_choice(args),
        airports=airports,
        center=args.center,
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
            display_city(airport),
            airport.country,
            airport.name,
            f"{distance_km(airport, args.center):.0f}",
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


CONFIGURED_COMMANDS = ("weekend", "airports", "web")


def _run_web(parser: argparse.ArgumentParser, port: int) -> int:
    from waitress import serve

    from flight_search.web import create_app

    if not 1 <= port <= 65535:
        parser.error("--port must be between 1 and 65535")

    today = date.today()
    defaults = parser.parse_args(
        [
            "weekend",
            "--start",
            today.isoformat(),
            "--end",
            (today + timedelta(days=13)).isoformat(),
        ]
    )
    app = create_app(
        _weekend_query(defaults),
        configured_regions=defaults.regions,
        cache_dir=defaults.cache_dir,
        cache_ttl=defaults.cache_ttl,
        cache_enabled=defaults.cache,
        rolling_dates=True,
    )
    Console().print(f"Open http://127.0.0.1:{port} in your browser.")
    serve(app, host="127.0.0.1", port=port)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # The subcommand is the first word that is not an option; the config file
    # is read only for the commands it configures (LOG-DECISION-41), so
    # --help, --version and refresh-airports work with a broken file.
    command = next((arg for arg in argv if not arg.startswith("-")), None)
    try:
        settings = load() if command in CONFIGURED_COMMANDS else Settings()
        parser = _build_parser(settings)
    except ConfigError as exc:
        _build_parser().error(str(exc))
    args = parser.parse_args(argv)
    if args.command == "web":
        return _run_web(parser, args.port)
    if args.command in CONFIGURED_COMMANDS:
        _drop_file_selection(args)
    if args.command == "weekend":
        if not args.debug:
            return _run_weekend(args)
        error_console = Console(stderr=True)
        handler = _ConsoleLogHandler(error_console)
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s.%(msecs)03d %(levelname)-7s %(name)-13s | %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
        loggers = (
            logging.getLogger("flight_search"),
            logging.getLogger("fli.search._tfs"),
        )
        states = [(target, target.level, target.propagate) for target in loggers]
        for target in loggers:
            target.addHandler(handler)
            target.setLevel(logging.DEBUG)
            target.propagate = False
        try:
            return _run_weekend(args, error_console=error_console)
        finally:
            for target, level, propagate in states:
                target.removeHandler(handler)
                target.setLevel(level)
                target.propagate = propagate
    if args.command == "airports":
        return _run_airports(args)
    if args.command == "refresh-airports":
        return _run_refresh(args)
    parser.error(f"Unknown command {args.command!r}")
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
