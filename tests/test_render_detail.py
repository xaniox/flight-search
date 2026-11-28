"""Detail view and JSON of PR 3, commit C3: segments and connections.

The ``--verbose`` block shows one line per leg with its date, flight and times,
a ``connection`` line with airport and time between two legs, marks an
overnight connection, a different operating airline and a self-transfer; the
JSON of each direction carries its segment count and its connections
(PRTHREE-CRITERION-14 to -19).

The render functions run directly on hand-built itineraries, because the fake
of ``fake_flights.py`` only makes direct flights.
"""

from __future__ import annotations

import io
import json

import pytest
from rich.console import Console
from test_cli_golden import BASE_ARGS
from test_render_connections import itinerary, option
from test_segment_data import offline_weekend  # noqa: F401  (pytest fixture)

from flight_search import cli
from flight_search.combine import LegInfo
from flight_search.render import render_results

SELF_TRANSFER = "self-transfer: separate tickets, connections at your own risk"


def leg(airline, number, origin, destination, departure, arrival, *, operating=""):
    return LegInfo(
        airline=airline,
        airline_name=airline,
        flight_number=number,
        origin=origin,
        destination=destination,
        departure=departure,
        arrival=arrival,
        duration=60,
        operating_airline=operating,
    )


def outbound(*, self_transfer=False, second_departure="2026-06-12T11:05:00"):
    """MUC→ATH→LCA on Fri 12 Jun 2026; 1h20 at ATH with the default departure."""
    return option(
        leg("A3", "901", "MUC", "ATH", "2026-06-12T06:15:00", "2026-06-12T09:45:00"),
        leg("A3", "902", "ATH", "LCA", second_departure, "2026-06-12T13:00:00"),
        price=120.0,
        self_transfer=self_transfer,
    )


def inbound(*, self_transfer=False):
    """RHO→ATH→MUC from Sun 21 Jun 2026, 13h10 overnight at ATH.

    The second leg is sold by A3 and operated by OA.
    """
    return option(
        leg("OA", "601", "RHO", "ATH", "2026-06-21T18:40:00", "2026-06-21T19:35:00"),
        leg(
            "A3",
            "603",
            "ATH",
            "MUC",
            "2026-06-22T08:45:00",
            "2026-06-22T10:20:00",
            operating="OA",
        ),
        price=95.0,
        self_transfer=self_transfer,
    )


def direct_back():
    """LCA→MUC on Sun 21 Jun 2026, a direct flight."""
    return option(
        leg("A3", "903", "LCA", "MUC", "2026-06-21T14:00:00", "2026-06-21T17:00:00"),
        price=80.0,
    )


def render_verbose(itineraries, *, width=200):
    console = Console(
        width=width,
        file=io.StringIO(),
        color_system=None,
        force_terminal=False,
        legacy_windows=False,
    )
    render_results(itineraries, console=console, query_lines=[], verbose=True)
    # A non-breaking space is as good as a space to the reader.
    return console.file.getvalue().replace(" ", " ")


def detail_block(text, rank=1):
    """The lines of the ``--verbose`` block of itinerary ``rank``, header first."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{rank}. "))
    block = []
    for line in lines[start:]:
        if not line.strip():
            break
        block.append(line)
    return block


def line_with(block, *parts):
    """The one line of ``block`` that holds every one of ``parts``."""
    matches = [line for line in block if all(part in line for part in parts)]
    assert len(matches) == 1, (parts, "\n".join(block))
    return matches[0]


def index_of(block, line):
    return block.index(line)


def assert_in_order(line, *parts):
    positions = [line.index(part) for part in parts]
    assert positions == sorted(positions), (parts, line)


# --- PRTHREE-CRITERION-14 ---------------------------------------------------


def test_verbose_shows_one_line_per_leg_with_date_flight_and_times():
    block = detail_block(render_verbose([itinerary(outbound(), inbound())]))

    first = line_with(block, "A3 901")
    second = line_with(block, "A3 902")
    assert_in_order(first, "Fri 12 Jun", "A3 901", "MUC 06:15 → ATH 09:45")
    assert_in_order(second, "Fri 12 Jun", "A3 902", "ATH 11:05 → LCA 13:00")
    assert first.split()[0] == "out"
    assert line_with(block, "OA 601").split()[0] == "ret"
    # The legs all on one line under ``out:`` and ``ret:`` are gone.
    assert not [line for line in block if line.strip().startswith(("out:", "ret:"))]


def test_following_legs_are_indented_to_the_column_of_the_first():
    block = detail_block(render_verbose([itinerary(outbound(), inbound())]))

    for first_flight, next_flight, date in (
        ("A3 901", "A3 902", "Fri 12 Jun"),
        ("OA 601", "A3 603", "Mon 22 Jun"),
    ):
        first = line_with(block, first_flight)
        following = line_with(block, next_flight)
        column = following.index(date)
        assert following[:column].strip() == "", following
        assert first.split()[0] in ("out", "ret")
        start_of_first = first.index(first.split()[1])
        assert column == start_of_first, (first, following)


def test_a_leg_arriving_on_a_later_day_is_marked_plus_n():
    late = option(
        leg("A3", "911", "MUC", "ATH", "2026-06-12T22:00:00", "2026-06-13T01:30:00"),
        leg("A3", "912", "ATH", "LCA", "2026-06-13T05:20:00", "2026-06-13T07:05:00"),
    )
    block = detail_block(render_verbose([itinerary(late, direct_back())]))

    assert line_with(block, "A3 911").rstrip().endswith("MUC 22:00 → ATH 01:30 +1")
    assert line_with(block, "A3 912").rstrip().endswith("ATH 05:20 → LCA 07:05")
    assert "Sat 13 Jun" in line_with(block, "A3 912")


def test_the_other_lines_of_the_verbose_block_stay():
    trip = itinerary(outbound(), inbound(), roundtrip_price=200.0)
    trip = type(trip)(
        **{
            **{name: getattr(trip, name) for name in trip.__dataclass_fields__},
            "booking_url": "https://example.test/book",
            "outbound_url": "https://example.test/out",
            "return_url": "https://example.test/ret",
        }
    )
    block = detail_block(render_verbose([trip]))

    assert block[0] == "1. Larnaca (2026-06-12 → 2026-06-21)"
    # Four leg lines and two connection lines, then the lines that stay.
    assert len(block) == 1 + 6 + 4, "\n".join(block)
    assert block[-4:] == [
        "   conventional round-trip: €200",
        "   google flights: https://example.test/book",
        "   outbound link:  https://example.test/out",
        "   return link:    https://example.test/ret",
    ]


# --- PRTHREE-CRITERION-15 ---------------------------------------------------


def test_a_connection_line_stands_between_two_legs():
    block = detail_block(render_verbose([itinerary(outbound(), direct_back())]))

    first = index_of(block, line_with(block, "A3 901"))
    connection = index_of(block, line_with(block, "connection"))
    second = index_of(block, line_with(block, "A3 902"))
    assert (first, second) == (connection - 1, connection + 1)
    assert block[connection].strip() == "connection ATH 1h20"


@pytest.mark.parametrize(
    ("departure", "written"),
    [
        ("2026-06-12T10:30:00", "45m"),
        ("2026-06-12T11:45:00", "2h"),
        ("2026-06-12T11:05:00", "1h20"),
    ],
)
def test_the_connection_time_is_written_like_fmt_duration(departure, written):
    out = outbound(second_departure=departure)
    block = detail_block(render_verbose([itinerary(out, direct_back())]))

    assert line_with(block, "connection").strip() == f"connection ATH {written}"


def test_a_direct_flight_has_no_connection_line():
    direct = option(
        leg("LH", "1", "FRA", "PMI", "2026-06-12T18:40:00", "2026-06-12T20:42:00")
    )
    back = option(
        leg("LH", "2", "PMI", "FRA", "2026-06-14T20:05:00", "2026-06-14T22:07:00")
    )
    block = detail_block(render_verbose([itinerary(direct, back, city="Palma")]))

    assert not [line for line in block if "connection" in line]
    assert "LH 1" in line_with(block, "FRA 18:40 → PMI 20:42")
    assert "LH 2" in line_with(block, "PMI 20:05 → FRA 22:07")


# --- PRTHREE-CRITERION-16 ---------------------------------------------------


def test_an_overnight_connection_is_marked():
    block = detail_block(render_verbose([itinerary(outbound(), inbound())]))

    connections = [line.strip() for line in block if "connection" in line]
    assert connections == [
        "connection ATH 1h20",
        "connection ATH 13h10 · overnight",
    ]


# --- PRTHREE-CRITERION-17 ---------------------------------------------------


def test_a_different_operating_airline_is_named_at_its_leg():
    block = detail_block(render_verbose([itinerary(outbound(), inbound())]))

    operated = line_with(block, "A3 603")
    assert operated.rstrip().endswith("operated by OA")
    assert_in_order(operated, "ATH 08:45 → MUC 10:20", "operated by OA")
    others = [line for line in block if "operated by" in line]
    assert others == [operated]


# --- PRTHREE-CRITERION-18 ---------------------------------------------------


@pytest.mark.parametrize("direction", ["out", "ret"])
def test_a_self_transfer_ends_its_direction_in_the_detail_view(direction):
    out = outbound(self_transfer=direction == "out")
    ret = inbound(self_transfer=direction == "ret")
    block = detail_block(render_verbose([itinerary(out, ret)]))

    notes = [line for line in block if SELF_TRANSFER in line]
    assert len(notes) == 1, "\n".join(block)
    note = index_of(block, notes[0])
    last_flight = "A3 902" if direction == "out" else "A3 603"
    first_flight = "A3 901" if direction == "out" else "OA 601"
    assert note == index_of(block, line_with(block, last_flight)) + 1
    assert notes[0].strip() == SELF_TRANSFER
    # Indented like the leg lines that follow the first one.
    first = line_with(block, first_flight)
    column = first.index(first.split()[1])
    assert notes[0].index(SELF_TRANSFER) == column


def test_no_self_transfer_adds_no_note():
    text = render_verbose([itinerary(outbound(), inbound())])

    assert "self-transfer" not in text
    assert line_with(detail_block(text), "A3 902", "ATH 11:05 → LCA 13:00")


# --- PRTHREE-CRITERION-19 ---------------------------------------------------


def test_itinerary_dict_carries_segments_and_layovers_per_direction():
    data = itinerary(outbound(), inbound()).to_dict()

    assert data["outbound"]["segments"] == 2
    assert data["outbound"]["layovers"] == [{"airport": "ATH", "minutes": 80}]
    assert data["return"]["segments"] == 2
    assert data["return"]["layovers"] == [{"airport": "ATH", "minutes": 790}]


def test_a_direct_direction_has_one_segment_and_no_layovers():
    data = itinerary(outbound(), direct_back()).to_dict()

    assert data["return"]["segments"] == 1
    assert data["return"]["layovers"] == []


def test_segments_and_layovers_keep_every_existing_key():
    out = outbound()
    ret = inbound(self_transfer=True)
    data = itinerary(out, ret).to_dict()

    for key, option_ in (("outbound", out), ("return", ret)):
        direction = data[key]
        assert {"segments", "layovers"} <= set(direction)
        rest = {
            name: value
            for name, value in direction.items()
            if name not in ("segments", "layovers")
        }
        assert rest == option_.to_dict()


def test_option_dict_carries_no_segments_or_layovers():
    """Both are derived from the legs, so the cache payload does not carry them."""
    for option_ in (outbound(), inbound(self_transfer=True), direct_back()):
        data = option_.to_dict()
        assert "segments" not in data
        assert "layovers" not in data


def test_weekend_json_carries_segments_and_layovers(offline_weekend, capsys):  # noqa: F811
    code = cli.main(
        [*BASE_ARGS, "--cache-dir", str(offline_weekend), "--format", "json"]
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert payload["results"]
    for result in [*payload["results"], *payload["best_per_city"]]:
        for direction in ("outbound", "return"):
            data = result[direction]
            # The fake only makes direct flights.
            assert data["segments"] == len(data["legs"]) == 1
            assert data["layovers"] == []


def test_detail_shows_the_airport_change_and_keeps_the_json_layover():
    out = option(
        leg("LH", "901", "MUC", "LGW", "2026-06-12T06:15:00", "2026-06-12T08:00:00"),
        leg("FR", "902", "STN", "ATH", "2026-06-12T11:00:00", "2026-06-12T14:30:00"),
    )
    back = option(
        leg("LH", "903", "ATH", "MUC", "2026-06-21T14:00:00", "2026-06-21T17:00:00"),
    )
    trip = itinerary(out, back, city="Athens", country="GR")
    block = detail_block(render_verbose([trip]))
    data = trip.to_dict()["outbound"]

    assert data["layovers"] == [{"airport": "LGW", "minutes": 180}]
    assert [
        (segment["origin"], segment["destination"]) for segment in data["legs"]
    ] == [("MUC", "LGW"), ("STN", "ATH")]
    assert (
        line_with(block, "connection").strip()
        == "connection LGW→STN 3h · airport change"
    )
