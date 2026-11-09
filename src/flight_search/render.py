"""Text and JSON rendering of search results."""

from __future__ import annotations

import json
from typing import Any, Iterable

from rich.console import Console
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
    from datetime import datetime

    return datetime.fromisoformat(value).strftime(fmt)


def _route(option: FlightOption) -> str:
    return f"{option.origin}→{option.destination}"


def _timing(option: FlightOption) -> str:
    return (
        f"{_stamp(option.departure, '%H:%M')}–{_stamp(option.arrival, '%H:%M')}"
    )


def _leg_detail(option: FlightOption) -> str:
    parts = []
    for leg in option.legs:
        parts.append(
            f"{leg.airline} {leg.flight_number} {leg.origin}→{leg.destination} "
            f"{_stamp(leg.departure, '%H:%M')}–{_stamp(leg.arrival, '%H:%M')}"
        )
    return " · ".join(parts)


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
    rows = [(i, it.booking_url) for i, it in enumerate(itineraries, 1) if it.booking_url]
    if not rows:
        return
    console.print()
    console.print(f"[dim]{title}[/dim]")
    for index, url in rows:
        console.print(f"{index}. {url}", soft_wrap=True)


def format_window_line(
    depart_label: str, return_label: str
) -> str:
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
    table.add_column("Outbound")
    table.add_column("Return")
    table.add_column("Nights", justify="right")
    table.add_column("Stops", justify="right")
    table.add_column("Open jaw", justify="center")
    if show_roundtrip:
        table.add_column("vs RT", justify="right")
    table.add_column("Link", justify="center")

    for rank, itinerary in enumerate(itineraries, 1):
        out = itinerary.out
        ret = itinerary.ret
        outbound = (
            f"{_stamp(out.departure, '%a %d %b')} · {_route(out)} · {_timing(out)}"
        )
        inbound = (
            f"{_stamp(ret.departure, '%a %d %b')} · {_route(ret)} · {_timing(ret)}"
        )
        row: list[Any] = [
            str(rank),
            fmt_money(itinerary.total, out.currency),
            f"{itinerary.city} ({itinerary.country})",
            outbound,
            inbound,
            str(itinerary.nights),
            f"{out.stops}/{ret.stops}",
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
            console.print(f"   out: {_leg_detail(itinerary.out)}")
            console.print(f"   ret: {_leg_detail(itinerary.ret)}")
            if itinerary.roundtrip_price is not None:
                console.print(
                    f"   conventional round-trip: "
                    f"{fmt_money(itinerary.roundtrip_price, itinerary.out.currency)}"
                )
            if itinerary.booking_url:
                console.print(f"   google flights: {itinerary.booking_url}", soft_wrap=True)
            if itinerary.outbound_url:
                console.print(f"   outbound link:  {itinerary.outbound_url}", soft_wrap=True)
            if itinerary.return_url:
                console.print(f"   return link:    {itinerary.return_url}", soft_wrap=True)
            console.print()
    else:
        render_links(itineraries, console=console)


def render_best_per_city(
    itineraries: Iterable[Itinerary], *, console: Console
) -> None:
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
