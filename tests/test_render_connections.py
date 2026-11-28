"""Compact weekend output for direct flights and connections."""

from __future__ import annotations

import io
from datetime import date

from rich.console import Console

from flight_search.combine import FlightOption, Itinerary, LegInfo
from flight_search.render import render_best_per_city, render_results

RET_LINE = "in   Sun 21.06.  RHO → ATH [11:25 h] → MUC  18:40 – 10:20 +1  OA/A3"


def leg(airline, origin, destination, departure, arrival, *, operating=""):
    return LegInfo(
        airline=airline,
        airline_name=airline,
        flight_number="100",
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        duration=60,
        operating_airline=operating,
    )


def option(*legs, price=100.0, self_transfer=False):
    return FlightOption(
        price=price,
        currency="EUR",
        departure=legs[0].departure,
        arrival=legs[-1].arrival,
        stops=len(legs) - 1,
        duration=60 * len(legs),
        legs=tuple(legs),
        self_transfer=self_transfer,
    )


def outbound(*, self_transfer=False, price=120.0):
    """MUC→ATH→LCA on Fri 12 Jun 2026, 06:15–13:00 the same day."""
    return option(
        leg("A3", "MUC", "ATH", "2026-06-12T06:15:00", "2026-06-12T09:45:00"),
        leg("A3", "ATH", "LCA", "2026-06-12T11:20:00", "2026-06-12T13:00:00"),
        price=price,
        self_transfer=self_transfer,
    )


def inbound(*, self_transfer=False, price=95.0):
    """RHO→ATH→MUC on Sun 21 Jun 2026, 18:40–10:20 the next day.

    The second leg is sold by A3 but operated by OA, so the airline list shows
    the selling code.
    """
    return option(
        leg("OA", "RHO", "ATH", "2026-06-21T18:40:00", "2026-06-21T19:35:00"),
        leg(
            "A3",
            "ATH",
            "MUC",
            "2026-06-22T07:00:00",
            "2026-06-22T10:20:00",
            operating="OA",
        ),
        price=price,
        self_transfer=self_transfer,
    )


def itinerary(out, ret, *, city="Larnaca", country="CY", roundtrip_price=None):
    return Itinerary(
        city_key=city.lower(),
        city=city,
        country=country,
        city_codes=("LCA",),
        depart_date=date.fromisoformat(out.departure[:10]),
        return_date=date.fromisoformat(ret.departure[:10]),
        out=out,
        ret=ret,
        roundtrip_price=roundtrip_price,
    )


def render(itineraries, *, width=200, show_roundtrip=False):
    console = Console(
        width=width,
        file=io.StringIO(),
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
    )
    render_results(
        itineraries,
        console=console,
        query_lines=[],
        show_roundtrip=show_roundtrip,
    )
    # A non-breaking space is as good as a space to the reader.
    return console.file.getvalue().replace(" ", " ")


def test_compact_results_align_directions_and_show_layovers_at_80_columns():
    trip = itinerary(outbound(), inbound(), roundtrip_price=200.0)
    head, out, ret = render([trip], width=80, show_roundtrip=True).strip().splitlines()

    assert (
        head
        == "1  €215  Larnaca (CY) · 9 nights · 4 segments · Open jaw: dest · vs RT +€15"
    )
    indent = " " * head.index("Larnaca")
    assert (
        out
        == f"{indent}out  Fri 12.06.  MUC → ATH [1:35 h] → LCA   06:15 – 13:00     A3"
    )
    assert ret == f"{indent}{RET_LINE}"


def test_direct_trip_has_no_layover_and_keeps_price_nights_and_segment_count():
    out = option(
        leg("LH", "FRA", "PMI", "2026-06-12T18:40", "2026-06-12T20:42"), price=60.5
    )
    ret = option(
        leg("LH", "PMI", "FRA", "2026-06-13T20:05", "2026-06-13T22:07"), price=55.25
    )
    head, out_line, ret_line = (
        render([itinerary(out, ret, city="Palma", country="ES")]).strip().splitlines()
    )

    assert head == "1  €115.75  Palma (ES) · 1 night · 2 segments"
    indent = " " * head.index("Palma")
    assert out_line == f"{indent}out  Fri 12.06.  FRA → PMI  18:40 – 20:42  LH"
    assert ret_line == f"{indent}in   Sat 13.06.  PMI → FRA  20:05 – 22:07  LH"


def test_later_arrival_and_self_transfer_are_marked_on_the_affected_direction():
    overnight = option(
        leg("A3", "MUC", "ATH", "2026-06-12T22:00:00", "2026-06-13T01:30:00"),
        leg("A3", "ATH", "LCA", "2026-06-14T05:20:00", "2026-06-14T07:05:00"),
        self_transfer=True,
    )
    _, out, ret = render([itinerary(overnight, inbound())]).strip().splitlines()
    assert out.rstrip().endswith("22:00 – 07:05 +2  A3  self-transfer")
    assert ret.rstrip().endswith(RET_LINE)


def cell_under(header, row, title):
    """The value of a right-justified column: the last word ending under it."""
    end = header.index(title) + len(title)
    return row[:end].split()[-1]


def render_best(itineraries, *, width=200):
    console = Console(
        width=width,
        file=io.StringIO(),
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
    )
    render_best_per_city(itineraries, console=console)
    return console.file.getvalue().replace(" ", " ")


def test_best_per_city_route_shows_every_stop():
    direct = option(
        leg("LH", "FRA", "PMI", "2026-06-12T18:40:00", "2026-06-12T20:42:00"),
        price=60.0,
    )
    back = option(
        leg("LH", "PMI", "FRA", "2026-06-14T20:05:00", "2026-06-14T22:07:00"),
        price=55.0,
    )
    text = render_best(
        [
            itinerary(outbound(), inbound()),
            itinerary(direct, back, city="Palma", country="ES"),
        ]
    )
    lines = text.splitlines()
    larnaca = next(line for line in lines if "Larnaca (CY)" in line)
    palma = next(line for line in lines if "Palma (ES)" in line)
    header = next(line for line in lines if "Route" in line and "Total" in line)

    assert "MUC→ATH→LCA / RHO→ATH→MUC" in larnaca
    assert "FRA→PMI / PMI→FRA" in palma
    # Its other columns are unchanged.
    assert header.split() == ["Total", "City", "Dates", "Route", "Nights", "Link"]
    assert larnaca.split()[0] == "€215"
    assert "2026-06-12 → 2026-06-21" in larnaca
    assert cell_under(header, larnaca, "Nights") == "9"
    assert palma.split()[0] == "€115"


def test_long_result_fits_narrow_terminal_without_losing_data():
    row = itinerary(outbound(self_transfer=True), inbound(), roundtrip_price=200.0)
    lines = render([row], width=61, show_roundtrip=True).splitlines()

    assert all(len(line) <= 61 for line in lines)
    text = " ".join(" ".join(lines).split())
    assert "MUC → ATH [1:35 h] → LCA" in text
    assert "RHO → ATH [11:25 h] → MUC" in text
    assert "self-transfer" in text
    assert "vs RT +€15" in text


def test_compact_tables_show_both_airports_of_a_transfer():
    airport_change = option(
        leg("LH", "MUC", "LGW", "2026-06-12T06:15:00", "2026-06-12T08:00:00"),
        leg("FR", "STN", "ATH", "2026-06-12T11:00:00", "2026-06-12T14:30:00"),
    )
    rows = [itinerary(airport_change, inbound(), city="Athens", country="GR")]
    _, out, ret = render(rows).strip().splitlines()
    best = next(
        line for line in render_best(rows).splitlines() if "Athens (GR)" in line
    )

    assert "RHO → ATH [11:25 h] → MUC" in ret
    assert "RHO→ATH→MUC" in best
    assert "MUC → LGW [3:00 h] ⇢ STN → ATH" in out
    assert "MUC→LGW ⇢ STN→ATH" in best


def test_results_align_columns_across_rank_price_city_and_route_widths():
    outbound_direct = option(
        leg("A3", "MUC", "ATH", "2026-06-12T06:15", "2026-06-12T09:45"),
        price=15,
    )
    cheap = itinerary(outbound_direct, inbound(), city="Athens")
    expensive = itinerary(outbound(price=1200), inbound(), city="Thessaloniki")
    rows = [cheap] * 9 + [expensive]
    lines = [line for line in render(rows, width=80).splitlines() if line.strip()]
    first, direct, direct_return = lines[:3]
    tenth, connection, connection_return = lines[-3:]

    assert first.startswith(" 1") and tenth.startswith("10")
    assert first.index("  Athens") == tenth.index("  Thessaloniki")
    assert first.index("·") == tenth.index("·")
    assert direct.index("out") == connection.index("out") == first.index("Athens")
    assert direct.index("06:15") == connection.index("06:15")
    assert direct.rindex("A3") == connection.rindex("A3")
    assert direct_return.index("in") == connection_return.index("in")
    assert all(len(line) <= 80 for line in lines)
