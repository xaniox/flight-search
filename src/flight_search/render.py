"""Text and JSON rendering of search results."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from rich.cells import cell_len
from rich.console import Console
from rich.style import Style
from rich.table import Table
from rich.text import Text

from flight_search.combine import FlightOption, Itinerary

_WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_AMBER = "#aa6d19"
_COLUMN_GAP = "  "
_LABEL_WIDTH = 3

FlightColumns = tuple[Text, Text, Text, Text]

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}


def fmt_money(price: float, currency: str) -> str:
    symbol = SYMBOLS.get(currency.upper())
    if price == int(price):
        amount = f"{int(price):,}"
    else:
        amount = f"{price:,.2f}"
    return f"{symbol}{amount}" if symbol else f"{amount} {currency}"


def _layover_time(minutes: int) -> str:
    hours, mins = divmod(minutes, 60)
    return f"[{hours}:{mins:02d} h]"


def _days_between(earlier: str, later: str) -> int:
    return (
        datetime.fromisoformat(later).date() - datetime.fromisoformat(earlier).date()
    ).days


def _arrival_day_marker(departure: str, arrival: str) -> str:
    days = _days_between(departure, arrival)
    return f" +{days}" if days > 0 else ""


def _route(option: FlightOption) -> str:
    """Show flight legs and mark any ground transfer between airports."""
    if not option.legs:
        return "→"
    route = [option.origin]
    for leg in option.legs:
        if route[-1] != leg.origin:
            route.extend((" ⇢ ", leg.origin))
        route.extend(("→", leg.destination))
    return "".join(route)


def _flight_date(departure: datetime) -> str:
    return f"{_WEEKDAYS[departure.weekday()]} {departure:%d.%m.}"


def _flight_columns(
    label: str, departure: str, arrival: str, route: Text, airline: str
) -> FlightColumns:
    depart_at = datetime.fromisoformat(departure)
    arrive_at = datetime.fromisoformat(arrival)
    when = Text(
        f"{label:{_LABEL_WIDTH}}{_COLUMN_GAP}{_flight_date(depart_at)}", style="dim"
    )
    marker = _arrival_day_marker(departure, arrival)
    times = Text(f"{depart_at:%H:%M} – {arrive_at:%H:%M}{marker}")
    return when, route, times, Text.assemble((airline, _AMBER))


def _direction_columns(label: str, option: FlightOption) -> FlightColumns:
    route = Text(option.origin)
    layovers = option.layovers
    for index, leg in enumerate(option.legs):
        if index:
            airport, minutes = layovers[index - 1]
            route.append(f" {_layover_time(minutes)}", style="dim")
            if airport != leg.origin:
                route.append(f" ⇢ {leg.origin}")
        route.append(f" → {leg.destination}")

    airlines = [leg.airline for leg in option.legs]
    codes = airlines[0] if len(set(airlines)) == 1 else "/".join(airlines)
    columns = _flight_columns(label, option.departure, option.arrival, route, codes)
    if option.self_transfer:
        columns[-1].append(f"{_COLUMN_GAP}self-transfer", style="dim")
    return columns


def _flight_line(
    columns: tuple[Text, ...], widths: tuple[int, ...], indent: int, width: int
) -> Text:
    required = indent + len(_COLUMN_GAP) * (len(columns) - 1)
    required += sum(
        max(column.cell_len, preferred)
        for column, preferred in zip(columns, widths, strict=True)
    )
    line = Text(" " * indent)
    for index, column in enumerate(columns):
        if index:
            line.append(_COLUMN_GAP)
        line.append(column)
        if required <= width:
            line.append(" " * max(0, widths[index] - column.cell_len))
    return line


def _detail_rows(label: str, option: FlightOption) -> list[FlightColumns | Text]:
    """One row per leg, with connection notes between legs."""
    layovers = option.layovers
    rows: list[FlightColumns | Text] = []
    continuation = " " * (_LABEL_WIDTH + len(_COLUMN_GAP))
    for index, leg in enumerate(option.legs):
        columns = _flight_columns(
            "" if index else label,
            leg.departure,
            leg.arrival,
            Text(f"{leg.origin} → {leg.destination}"),
            f"{leg.airline} {leg.flight_number}",
        )
        if leg.operating_airline != leg.airline:
            columns[-1].append("  operated by ", style="dim")
            columns[-1].append(leg.operating_airline, style=_AMBER)
        rows.append(columns)
        if index < len(layovers):
            airport, minutes = layovers[index]
            following = option.legs[index + 1]
            airport_change = airport != following.origin
            connection = (
                f"{airport} ⇢ {following.origin}" if airport_change else airport
            )
            note = f"{continuation}connection {connection} {_layover_time(minutes)}"
            if airport_change:
                note += " · airport change"
            if _days_between(leg.arrival, following.departure) > 0:
                note += " · overnight"
            rows.append(Text(note, style="dim"))
    if option.self_transfer:
        rows.append(
            Text(
                f"{continuation}self-transfer: separate tickets, connections at your own risk",
                style="dim",
            )
        )
    return rows


def _detail_links(itinerary: Itinerary, console: Console, indent: int) -> None:
    links = [
        (label, url)
        for label, url in (
            ("trip", itinerary.booking_url),
            ("outbound", itinerary.outbound_url),
            ("return", itinerary.return_url),
        )
        if url
    ]
    if not links:
        return
    if console.is_terminal:
        line = Text(" " * indent)
        line.append("Google Flights", style="dim")
        for label, url in links:
            line.append(" · ", style="dim")
            line.append(label, style=Style(color="cyan", link=url))
        console.print(line)
    else:
        for label, url in links:
            console.print(
                Text.assemble((" " * indent + f"{label} link: ", "dim"), url),
                soft_wrap=True,
            )


def link_cell(url: str | None) -> str:
    """Rich markup for a clickable Google Flights link."""
    if not url:
        return "—"
    return f"[link={url}][cyan]open[/cyan][/link]"


def render_links(
    itineraries: list[Itinerary],
    *,
    console: Console,
    title: str = "Google Flights links:",
) -> None:
    """Print raw URLs when the terminal cannot render OSC-8 hyperlinks."""
    if console.is_terminal:
        return
    rows = [
        (i, it.booking_url) for i, it in enumerate(itineraries, 1) if it.booking_url
    ]
    if not rows:
        return
    console.print()
    console.print(f"[dim]{title}[/dim]")
    for index, url in rows:
        console.print(f"{index}. {url}", soft_wrap=True)


def format_window_line(depart_label: str, return_label: str) -> str:
    parts = []
    if depart_label != "any time":
        parts.append(f"depart {depart_label}")
    if return_label != "any time":
        parts.append(f"return {return_label}")
    if not parts:
        return "Any departure / arrival time"
    return " · ".join(parts) + " (local times)"


def render_results(
    itineraries: list[Itinerary],
    *,
    console: Console,
    query_lines: list[str],
    show_roundtrip: bool = False,
    verbose: bool = False,
) -> None:
    console.print()
    for line in query_lines:
        console.print(Text(line, style="dim"))
    console.print()

    if not itineraries:
        console.print(Text("No itineraries matched.", style="bold red"))
        return

    rank_width = len(str(len(itineraries)))
    prices = [fmt_money(it.total, it.out.currency) for it in itineraries]
    price_width = max(map(cell_len, prices))
    place_width = max(cell_len(f"{it.city} ({it.country})") for it in itineraries)
    indent = rank_width + price_width + 2 * len(_COLUMN_GAP)
    result_rows = [
        [*_detail_rows("out", it.out), *_detail_rows("in", it.ret)]
        if verbose
        else [_direction_columns("out", it.out), _direction_columns("in", it.ret)]
        for it in itineraries
    ]
    available = console.width - indent - 3 * len(_COLUMN_GAP)
    fitting = [
        columns
        for rows in result_rows
        for columns in rows
        if isinstance(columns, tuple)
        and sum(column.cell_len for column in columns) <= available
    ]
    widths = (
        tuple(max(column.cell_len for column in group) for group in zip(*fitting))
        if fitting
        else (0, 0, 0, 0)
    )
    # The final column has no trailing padding.
    widths = (*widths[:-1], 0)

    for rank, (itinerary, price, rows) in enumerate(
        zip(itineraries, prices, result_rows, strict=True), 1
    ):
        if rank > 1:
            console.print()
        segments = len(itinerary.out.legs) + len(itinerary.ret.legs)
        nights = "night" if itinerary.nights == 1 else "nights"
        segment_label = "segment" if segments == 1 else "segments"
        head = Text.assemble(
            (f"{rank:>{rank_width}}", "dim"),
            _COLUMN_GAP + " " * (price_width - cell_len(price)),
            (price, "bold green"),
            _COLUMN_GAP,
        )
        head.append(itinerary.city, style="cyan")
        country = f" ({itinerary.country})"
        padding = place_width - cell_len(itinerary.city + country)
        head.append(
            f"{country}{' ' * padding} · {itinerary.nights} {nights}"
            f" · {segments} {segment_label}",
            style="dim",
        )
        if itinerary.open_jaw_label:
            head.append(f" · Open jaw: {itinerary.open_jaw_label}", style="dim")
        if show_roundtrip:
            delta = itinerary.roundtrip_delta
            comparison = "n/a"
            if delta is not None:
                sign = "+" if delta >= 0 else "−"
                comparison = f"{sign}{fmt_money(abs(delta), itinerary.out.currency)}"
            head.append(f" · vs RT {comparison}", style="dim")
        if not verbose and console.is_terminal and itinerary.booking_url:
            head.append(" · ", style="dim")
            head.append("open", style=Style(color="cyan", link=itinerary.booking_url))

        console.print(head)
        for row in rows:
            if isinstance(row, Text):
                console.print(Text(" " * indent).append(row))
            else:
                console.print(_flight_line(row, widths, indent, console.width))
        if verbose:
            if itinerary.roundtrip_price is not None:
                price = fmt_money(itinerary.roundtrip_price, itinerary.out.currency)
                console.print(
                    Text(f"{' ' * indent}conventional round-trip: {price}", style="dim")
                )
            _detail_links(itinerary, console, indent)

    if not verbose:
        render_links(itineraries, console=console)


def render_best_per_city(itineraries: Iterable[Itinerary], *, console: Console) -> None:
    best: dict[str, Itinerary] = {}
    for itinerary in itineraries:
        current = best.get(itinerary.city_key)
        if current is None or itinerary.total < current.total:
            best[itinerary.city_key] = itinerary
    if not best:
        return

    rows = sorted(best.values(), key=lambda item: item.total)
    table = Table(title="Best per city", box=None, pad_edge=False, show_edge=False)
    table.add_column("Total", justify="right", style="bold green")
    table.add_column("City", style="cyan")
    table.add_column("Dates")
    table.add_column("Route")
    table.add_column("Nights", justify="right")
    table.add_column("Link", justify="center")

    for itinerary in rows:
        table.add_row(
            fmt_money(itinerary.total, itinerary.out.currency),
            f"{itinerary.city} ({itinerary.country})",
            f"{itinerary.depart_date} → {itinerary.return_date}",
            f"{_route(itinerary.out)} / {_route(itinerary.ret)}",
            str(itinerary.nights),
            link_cell(itinerary.booking_url),
        )
    console.print()
    console.print(table)
    render_links(rows, console=console, title="Best per city links:")


def results_payload(
    itineraries: list[Itinerary],
    *,
    query: dict[str, Any],
    stats: dict[str, Any],
    failed: list[str],
    windows: dict[str, str],
) -> dict[str, Any]:
    best: dict[str, Itinerary] = {}
    for itinerary in itineraries:
        current = best.get(itinerary.city_key)
        if current is None or itinerary.total < current.total:
            best[itinerary.city_key] = itinerary

    return {
        "query": query,
        "windows": windows,
        "stats": stats,
        "count": len(itineraries),
        "results": [itinerary.to_dict() for itinerary in itineraries],
        "best_per_city": [
            itinerary.to_dict()
            for itinerary in sorted(best.values(), key=lambda item: item.total)
        ],
        "failed": failed,
    }


def dump_json(payload: dict[str, Any], console: Console) -> None:
    console.print_json(json.dumps(payload, ensure_ascii=False))
