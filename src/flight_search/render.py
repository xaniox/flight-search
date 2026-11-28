"""Text and JSON rendering of search results."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from rich.table import Table
from rich.text import Text

from flight_search.combine import FlightOption, Itinerary

SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF ", "JPY": "¥"}


def fmt_money(price: float, currency: str) -> str:
    symbol = SYMBOLS.get(currency.upper())
    if price == int(price):
        amount = f"{int(price):,}"
    else:
        amount = f"{price:,.2f}"
    return f"{symbol}{amount}" if symbol else f"{amount} {currency}"


def fmt_duration(minutes: int) -> str:
    hours, mins = divmod(int(minutes), 60)
    if hours and mins:
        return f"{hours}h{mins:02d}"
    if hours:
        return f"{hours}h"
    return f"{mins}m"


def _stamp(value: str, fmt: str = "%a %d %b") -> str:
    return datetime.fromisoformat(value).strftime(fmt)


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


def _airlines(option: FlightOption) -> str:
    return "/".join(leg.airline for leg in option.legs)


def _timing(option: FlightOption) -> str:
    timing = f"{_stamp(option.departure, '%H:%M')}–{_stamp(option.arrival, '%H:%M')}"
    return timing + _arrival_day_marker(option.departure, option.arrival)


def _flight_tokens(label: str, option: FlightOption) -> list[str]:
    """The words of one direction's line; none of them may be split."""
    tokens = [
        label,
        _stamp(option.departure, "%a %d %b"),
        _route(option),
        _airlines(option),
        _timing(option),
    ]
    if option.self_transfer:
        tokens.append("self-transfer")
    return tokens


class _FlightsCell:
    """One line per direction, wrapped only between its tokens.

    Rich would break a narrow cell at any space, also inside ``Fri 12 Jun`` or
    ``18:40–10:20 +1``, so this renderable packs whole tokens per line itself.
    A wrapped line continues indented under the date, as far as it fits.
    A token wider than the column ends with an ellipsis.
    """

    SEP = "  "
    INDENT = len("out  ")

    def __init__(self, *lines: list[str]) -> None:
        self.lines = lines

    def __rich_measure__(
        self, console: Console, options: ConsoleOptions
    ) -> Measurement:
        tokens = [token for line in self.lines for token in line]
        widest = max(cell_len(self.SEP.join(line)) for line in self.lines)
        return Measurement(max(cell_len(token) for token in tokens), widest)

    def __rich_console__(
        self, console: Console, options: ConsoleOptions
    ) -> RenderResult:
        width = options.max_width
        rows: list[str] = []
        for tokens in self.lines:
            current = tokens[0]
            for token in tokens[1:]:
                joined = current + self.SEP + token
                if cell_len(joined) <= width:
                    current = joined
                    continue
                rows.append(current)
                indent = min(self.INDENT, max(0, width - cell_len(token)))
                current = " " * indent + token
            rows.append(current)
        yield Text("\n".join(rows), no_wrap=True, overflow="ellipsis")


def _detail_lines(label: str, option: FlightOption) -> list[str]:
    """One line per leg of a direction, a connection line between two legs."""
    layovers = option.layovers
    lines = []
    for index, leg in enumerate(option.legs):
        line = (
            f"{_stamp(leg.departure)}  {leg.airline} {leg.flight_number}  "
            f"{leg.origin} {_stamp(leg.departure, '%H:%M')} → "
            f"{leg.destination} {_stamp(leg.arrival, '%H:%M')}"
        )
        line += _arrival_day_marker(leg.departure, leg.arrival)
        if leg.operating_airline != leg.airline:
            line += f"  operated by {leg.operating_airline}"
        lines.append(line)
        if index < len(layovers):
            airport, minutes = layovers[index]
            following = option.legs[index + 1]
            airport_change = airport != following.origin
            connection = f"{airport}→{following.origin}" if airport_change else airport
            line = f"connection {connection} {fmt_duration(minutes)}"
            if airport_change:
                line += " · airport change"
            if _days_between(leg.arrival, following.departure) > 0:
                line += " · overnight"
            lines.append(line)
    if option.self_transfer:
        lines.append("self-transfer: separate tickets, connections at your own risk")
    indent = " " * len(label)
    return [
        f"{indent if number else label} {line}" for number, line in enumerate(lines)
    ]


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

    table = Table(box=None, pad_edge=False, show_edge=False)
    table.add_column("#", justify="right", style="dim")
    table.add_column("Total", justify="right", style="bold green")
    table.add_column("City", style="cyan")
    table.add_column("Flights")
    table.add_column("Nights", justify="right")
    table.add_column("Seg", justify="right")
    table.add_column("Open jaw", justify="center")
    if show_roundtrip:
        table.add_column("vs RT", justify="right")
    table.add_column("Link", justify="center")

    for rank, itinerary in enumerate(itineraries, 1):
        out = itinerary.out
        ret = itinerary.ret
        row: list[Any] = [
            str(rank),
            fmt_money(itinerary.total, out.currency),
            f"{itinerary.city} ({itinerary.country})",
            _FlightsCell(_flight_tokens("out", out), _flight_tokens("ret", ret)),
            str(itinerary.nights),
            str(len(out.legs) + len(ret.legs)),
            itinerary.open_jaw_label or "—",
        ]
        if show_roundtrip:
            if itinerary.roundtrip_delta is None:
                row.append("n/a")
            else:
                delta = itinerary.roundtrip_delta
                sign = "+" if delta >= 0 else "−"
                row.append(f"{sign}{fmt_money(abs(delta), out.currency)}")
        row.append(link_cell(itinerary.booking_url))
        table.add_row(*row)

    console.print(table)

    if verbose:
        console.print()
        for rank, itinerary in enumerate(itineraries, 1):
            console.print(
                f"[bold]{rank}. {itinerary.city}[/bold] "
                f"({itinerary.depart_date} → {itinerary.return_date})"
            )
            for label, option in (("out", itinerary.out), ("ret", itinerary.ret)):
                for line in _detail_lines(label, option):
                    console.print(Text(f"   {line}"))
            if itinerary.roundtrip_price is not None:
                console.print(
                    f"   conventional round-trip: "
                    f"{fmt_money(itinerary.roundtrip_price, itinerary.out.currency)}"
                )
            if itinerary.booking_url:
                console.print(
                    f"   google flights: {itinerary.booking_url}", soft_wrap=True
                )
            if itinerary.outbound_url:
                console.print(
                    f"   outbound link:  {itinerary.outbound_url}", soft_wrap=True
                )
            if itinerary.return_url:
                console.print(
                    f"   return link:    {itinerary.return_url}", soft_wrap=True
                )
            console.print()
    else:
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
