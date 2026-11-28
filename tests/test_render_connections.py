"""Compact results table of PR 3, commit C2: connections per direction.

One column ``Flights`` holds the outbound and the return as two lines, each
with date, route through every stop, the selling airline of every segment and
the times with a ``+N`` day marker and a self-transfer flag; ``Seg`` replaces
``Stops``, the best-per-city table shows the stops in its routes, and the table
stays readable at 120 and 80 columns (PRTHREE-CRITERION-06 to -12).

The render functions run directly on hand-built itineraries, because the fake
of ``fake_flights.py`` only makes direct flights.
"""

from __future__ import annotations

import io
from datetime import date

from rich.console import Console

from flight_search.combine import FlightOption, Itinerary, LegInfo
from flight_search.render import render_best_per_city, render_results

OUT_LINE = "out  Fri 12 Jun  MUC→ATH→LCA  A3/A3  06:15–13:00"
RET_LINE = "ret  Sun 21 Jun  RHO→ATH→MUC  OA/A3  18:40–10:20 +1"


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


def table_lines(text, rows):
    """The header line and the two lines (out, ret) of each of ``rows`` rows."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.lstrip().startswith("#"))
    body = []
    for line in lines[start:]:
        if not line.strip():
            break
        body.append(line)
    assert len(body) == 1 + 2 * rows, f"expected two lines per row:\n{text}"
    return body


def cell_under(header, row, title):
    """The value of a right-justified column: the last word ending under it."""
    end = header.index(title) + len(title)
    return row[:end].split()[-1]


def test_each_direction_is_one_line_in_one_flights_column():
    text = render([itinerary(outbound(), inbound())])
    header, first, second = table_lines(text, 1)

    assert "Flights" in header
    assert "Outbound" not in header
    assert "Return" not in header
    assert OUT_LINE in first
    assert RET_LINE in second
    # The other columns stand on the first line of the row only.
    assert first.split()[:4] == ["1", "€215", "Larnaca", "(CY)"]
    assert cell_under(header, first, "Nights") == "9"
    # Open jaw at the destination: out to LCA, back from RHO.
    assert first[header.index("Open jaw") :].split()[0] == "dest"
    assert second.split()[:1] == ["ret"]


def test_every_column_but_the_flights_keeps_its_content():
    roundtrip = itinerary(outbound(), inbound(), roundtrip_price=200.0)
    text = render([roundtrip], show_roundtrip=True)
    header, first, second = table_lines(text, 1)

    titles = ["#", "Total", "City", "Flights", "Nights", "Seg", "Open jaw", "vs RT"]
    positions = [header.index(title) for title in titles]
    assert positions == sorted(positions)
    assert header.rstrip().endswith("Link")
    assert cell_under(header, first, "vs RT") == "+€15"
    # Open jaw at the destination: out to LCA, back from RHO.
    assert first[header.index("Open jaw") :].split()[0] == "dest"
    assert first.rstrip().endswith("—")
    assert second.strip().startswith("ret")
    assert second.rstrip().endswith("+1")


def test_route_lists_every_stop_and_airlines_every_segment():
    direct = option(
        leg("LH", "FRA", "PMI", "2026-06-12T18:40:00", "2026-06-12T20:42:00"),
        price=60.0,
    )
    back = option(
        leg("LH", "PMI", "FRA", "2026-06-14T20:05:00", "2026-06-14T22:07:00"),
        price=55.0,
    )
    text = render(
        [
            itinerary(outbound(), inbound()),
            itinerary(direct, back, city="Palma", country="ES"),
        ]
    )
    lines = table_lines(text, 2)

    assert "MUC→ATH→LCA  A3/A3" in lines[1]
    # Selling codes in leg order, not the operator OA of ATH→MUC.
    assert "RHO→ATH→MUC  OA/A3" in lines[2]
    assert "out  Fri 12 Jun  FRA→PMI  LH  18:40–20:42" in lines[3]
    assert "ret  Sun 14 Jun  PMI→FRA  LH  20:05–22:07" in lines[4]


def test_total_and_nights_are_unchanged_for_connections():
    text = render([itinerary(outbound(price=120.5), inbound(price=95.25))])
    header, first, _ = table_lines(text, 1)

    assert OUT_LINE in first
    assert cell_under(header, first, "Total") == "€215.75"
    assert cell_under(header, first, "Nights") == "9"


def test_a_later_arrival_day_is_marked_plus_n():
    overnight = option(
        leg("A3", "MUC", "ATH", "2026-06-12T22:00:00", "2026-06-13T01:30:00"),
        leg("A3", "ATH", "LCA", "2026-06-14T05:20:00", "2026-06-14T07:05:00"),
    )
    text = render([itinerary(overnight, inbound())])
    lines = table_lines(text, 1)

    assert "MUC→ATH→LCA  A3/A3  22:00–07:05 +2" in lines[1]
    assert "RHO→ATH→MUC  OA/A3  18:40–10:20 +1" in lines[2]


def test_a_same_day_arrival_gets_no_marker():
    text = render([itinerary(outbound(), inbound())])
    first = table_lines(text, 1)[1]

    assert OUT_LINE in first
    assert "06:15–13:00 +" not in first


def test_a_self_transfer_is_marked_at_the_end_of_its_line():
    text = render([itinerary(outbound(self_transfer=True), inbound())])
    lines = table_lines(text, 1)

    assert f"{OUT_LINE}  self-transfer" in lines[1]
    assert "self-transfer" not in lines[2]


def test_a_self_transfer_return_line_ends_with_the_marker():
    text = render([itinerary(outbound(), inbound(self_transfer=True))])
    lines = table_lines(text, 1)

    assert lines[2].rstrip().endswith(f"{RET_LINE}  self-transfer")
    assert "self-transfer" not in lines[1]


def test_no_self_transfer_appends_nothing():
    text = render([itinerary(outbound(), inbound())])

    assert "self-transfer" not in text
    assert table_lines(text, 1)[2].rstrip().endswith(RET_LINE)


def test_seg_counts_the_legs_of_both_directions():
    direct = option(
        leg("LH", "FRA", "PMI", "2026-06-12T18:40:00", "2026-06-12T20:42:00")
    )
    back = option(leg("LH", "PMI", "FRA", "2026-06-14T20:05:00", "2026-06-14T22:07:00"))
    text = render(
        [
            itinerary(outbound(), inbound()),
            itinerary(direct, back, city="Palma", country="ES"),
            itinerary(outbound(), back, city="Mixed", country="XX"),
        ]
    )
    lines = table_lines(text, 3)
    header = lines[0]

    assert "Seg" in header
    assert "Stops" not in header
    assert cell_under(header, lines[1], "Seg") == "4"
    assert cell_under(header, lines[3], "Seg") == "2"
    assert cell_under(header, lines[5], "Seg") == "3"
    assert "1/1" not in text
    assert "0/0" not in text


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


def test_each_direction_with_one_stop_fits_one_line_at_120_columns():
    rows = [
        itinerary(outbound(), inbound(), roundtrip_price=200.0),
        itinerary(
            outbound(),
            inbound(),
            city="Thessaloniki",
            country="GR",
            roundtrip_price=180.0,
        ),
    ]
    text = render(rows, width=120, show_roundtrip=True)
    # Header plus exactly two lines per row: out and ret, nothing wrapped.
    lines = table_lines(text, len(rows))
    for first, second in zip(lines[1::2], lines[2::2], strict=True):
        assert OUT_LINE in first
        assert RET_LINE in second
    assert all(len(line.rstrip()) <= 120 for line in lines)


def test_no_token_is_split_at_80_columns():
    rows = [
        itinerary(outbound(self_transfer=True), inbound(), roundtrip_price=200.0),
        itinerary(
            outbound(),
            inbound(self_transfer=True),
            city="Thessaloniki",
            country="GR",
            roundtrip_price=180.0,
        ),
    ]
    text = render(rows, width=80, show_roundtrip=True)
    lines = text.splitlines()

    assert all(len(line.rstrip()) <= 80 for line in lines)
    for token in (
        "MUC→ATH→LCA",
        "RHO→ATH→MUC",
        "A3/A3",
        "OA/A3",
        "06:15–13:00",
        "18:40–10:20 +1",
        "Fri 12 Jun",
        "Sun 21 Jun",
    ):
        holding = [line for line in lines if token in line]
        assert len(holding) == len(rows), (token, text)


def test_an_oversized_route_is_visibly_shortened_at_61_columns():
    row = itinerary(outbound(), inbound(), roundtrip_price=200.0)
    text = render([row], width=61, show_roundtrip=True)

    route = "MUC→ATH→LCA"
    shortened_routes = {
        route[:length] + ellipsis
        for length in range(3, len(route))
        for ellipsis in ("…", "...")
    }
    assert {route, *shortened_routes}.intersection(text.split()), text


def test_compact_tables_show_both_airports_of_a_transfer():
    airport_change = option(
        leg("LH", "MUC", "LGW", "2026-06-12T06:15:00", "2026-06-12T08:00:00"),
        leg("FR", "STN", "ATH", "2026-06-12T11:00:00", "2026-06-12T14:30:00"),
    )
    rows = [itinerary(airport_change, inbound(), city="Athens", country="GR")]
    _, out, ret = table_lines(render(rows), 1)
    best = next(
        line for line in render_best(rows).splitlines() if "Athens (GR)" in line
    )

    assert "RHO→ATH→MUC" in ret
    assert "RHO→ATH→MUC" in best
    route = "MUC→LGW ⇢ STN→ATH"
    assert [route in out, route in best] == [True, True], (out, best)
