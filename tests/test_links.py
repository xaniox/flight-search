import base64
from datetime import date

from flight_search.combine import FlightOption, Itinerary, LegInfo
from flight_search.config import SearchSettings
from flight_search.links import attach_links, itinerary_url, leg_url
from flight_search.render import link_cell, results_payload


def make_option(
    origin: str,
    destination: str,
    depart: str,
    arrive: str,
    *,
    price: float = 100.0,
    airline: str = "LH",
    number: str = "123",
) -> FlightOption:
    leg = LegInfo(
        airline=airline,
        airline_name="Lufthansa",
        flight_number=number,
        origin=origin,
        destination=destination,
        departure=depart,
        arrival=arrive,
        duration=120,
    )
    return FlightOption(
        price=price,
        currency="EUR",
        departure=depart,
        arrival=arrive,
        stops=0,
        duration=120,
        legs=(leg,),
    )


def make_itinerary() -> Itinerary:
    return Itinerary(
        city_key="city:al:tirana",
        city="Tirana",
        country="AL",
        city_codes=("TIA",),
        depart_date=date(2026, 11, 13),
        return_date=date(2026, 11, 16),
        out=make_option(
            "FKB", "TIA", "2026-11-13T17:20:00", "2026-11-13T19:30:00", price=35.0
        ),
        ret=make_option(
            "TIA", "STR", "2026-11-16T09:45:00", "2026-11-16T11:55:00",
            price=34.0, airline="W4", number="5119",
        ),
    )


def tfs_of(url: str) -> str:
    return url.split("tfs=", 1)[1].split("&", 1)[0]


def decode(tfs: str) -> bytes:
    padded = tfs + "=" * (-len(tfs) % 4)
    return base64.urlsafe_b64decode(padded)


def test_attach_links_builds_booking_urls():
    itinerary = make_itinerary()
    attach_links([itinerary], SearchSettings())

    for url in (
        itinerary.booking_url,
        itinerary.outbound_url,
        itinerary.return_url,
    ):
        assert url is not None
        assert url.startswith("https://www.google.com/travel/flights/booking?tfs=")
        assert "curr=EUR" in url
        assert "hl=de-DE" in url
        assert "gl=DE" in url

    assert itinerary.booking_url != itinerary.outbound_url
    assert itinerary.outbound_url != itinerary.return_url


def test_combined_token_encodes_both_segments_and_flights():
    itinerary = make_itinerary()
    attach_links([itinerary], SearchSettings())
    payload = decode(tfs_of(itinerary.booking_url))

    # Dates and airport codes are length-delimited ASCII inside the token.
    assert b"2026-11-13" in payload
    assert b"2026-11-16" in payload
    assert b"FKB" in payload
    assert b"TIA" in payload
    assert b"STR" in payload
    # Airline + flight number of both legs.
    assert b"LH" in payload and b"123" in payload
    assert b"W4" in payload and b"5119" in payload


def test_one_way_token_differs_from_combined():
    itinerary = make_itinerary()
    attach_links([itinerary], SearchSettings())
    combined = tfs_of(itinerary.booking_url)
    outbound = tfs_of(itinerary.outbound_url)
    assert len(combined) > len(outbound)
    assert b"2026-11-16" not in decode(outbound)


def test_token_uses_requested_cabin():
    economy = make_itinerary()
    business = make_itinerary()
    attach_links([economy], SearchSettings(cabin="ECONOMY"))
    attach_links([business], SearchSettings(cabin="BUSINESS"))
    assert tfs_of(economy.booking_url) != tfs_of(business.booking_url)


def test_leg_url_falls_back_to_search_without_flight_number():
    option = make_option(
        "FKB", "TIA", "2026-11-13T17:20:00", "2026-11-13T19:30:00", number=""
    )
    url = leg_url(option, SearchSettings())
    assert url.startswith("https://www.google.com/travel/flights?q=")
    assert "FKB" in url and "TIA" in url
    assert "2026-11-13" in url


def test_itinerary_url_falls_back_without_leg_data():
    empty = FlightOption(
        price=10.0,
        currency="EUR",
        departure="2026-11-13T00:00:00",
        arrival="2026-11-13T02:00:00",
        stops=0,
        duration=120,
        legs=(),
    )
    url = itinerary_url(empty, empty, SearchSettings())
    assert url.startswith("https://www.google.com/travel/flights?q=")


def test_attach_links_never_raises_for_incomplete_data():
    itinerary = make_itinerary()
    itinerary.out = FlightOption(
        price=10.0,
        currency="EUR",
        departure="2026-11-13T00:00:00",
        arrival="2026-11-13T02:00:00",
        stops=0,
        duration=120,
        legs=(),
    )
    attach_links([itinerary], SearchSettings())  # must not raise


def test_payload_includes_links_for_results_and_best_per_city():
    itinerary = make_itinerary()
    attach_links([itinerary], SearchSettings())
    payload = results_payload(
        [itinerary], query={}, stats={}, failed=[], windows={}
    )
    result = payload["results"][0]
    assert result["booking_url"] == itinerary.booking_url
    assert result["outbound_url"] == itinerary.outbound_url
    assert result["return_url"] == itinerary.return_url
    assert payload["best_per_city"][0]["booking_url"] == itinerary.booking_url


def test_link_cell_markup():
    assert link_cell("https://example.com/x") == "[link=https://example.com/x][cyan]open[/cyan][/link]"
    assert link_cell(None) == "—"
