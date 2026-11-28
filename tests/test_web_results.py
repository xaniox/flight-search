from dataclasses import replace
from datetime import date, time, timedelta
from unittest.mock import Mock

from airport_factory import airport
from test_web import app_for, start_search, wait_for_final_state

from flight_search.airports import CityGroup
from flight_search.candidates import Candidate
from flight_search.combine import FlightOption, LegInfo
from flight_search.config import SearchSettings
from flight_search.dates import DatePair
from flight_search.search import SearchRequest, SearchResult, SearchStats
from flight_search.windows import DepartureWindow, ReturnWindow

LISBON = CityGroup("LIS", "Lisbon", "PT", (airport("LIS", "PT"),))
ROME = CityGroup("FCO", "Rome", "IT", (airport("FCO", "IT"),))
FRIDAY = date(2026, 12, 4)
SUNDAY = FRIDAY + timedelta(days=2)


def option(
    number, day, route, *, price=100, departs="18:00", arrives="20:00", operator="LH"
):
    departure = f"{day}T{departs}"
    arrival = f"{day}T{arrives}"
    origin, destination = route
    leg = LegInfo(
        "LH",
        "Lufthansa",
        number,
        origin,
        destination,
        departure,
        arrival,
        120,
        operating_airline=operator,
    )
    return FlightOption(price, "EUR", departure, arrival, 0, 120, (leg,))


def candidate(city, depart, ret):
    return Candidate(city, DatePair(depart, ret), 100, 100, 200)


def result_with(shortlist, options, *, request=None):
    if request is None:
        request = SearchRequest(
            home=("FRA",),
            destinations=LISBON.airports + ROME.airports,
            pairs=tuple(item.pair for item in shortlist),
            depart_window=DepartureWindow(after=time(17)),
            return_window=ReturnWindow(arrive_before=time(21)),
            settings=SearchSettings(),
            batch_size=1,
            concurrency=1,
            max_candidates=10,
            per_city=3,
            airlines=frozenset({"LH"}),
        )
    return SearchResult(
        request=request,
        shortlist=tuple(shortlist),
        options=options,
        stats=SearchStats(
            2, 2, len(shortlist), 1, 1, 1, len(shortlist), len(shortlist), 0
        ),
        failures=(),
    )


def choices_by_date(projection):
    return {group["date"]: group for group in projection["outbound_groups"]}


def flight_numbers(projection, ids):
    return {projection["options"][key]["legs"][0]["flight_number"] for key in ids}


def test_outbound_choices_keep_costlier_flights_and_share_return_group_ids():
    from flight_search.web_results import outbound_choices

    saturday = FRIDAY + timedelta(days=1)
    cheap = option("10", FRIDAY, ("FRA", "LIS"))
    costlier = option("11", FRIDAY, ("FRA", "LIS"), price=145)
    following = option("12", saturday, ("FRA", "LIS"))
    inbound = option("20", SUNDAY, ("LIS", "FRA"))
    result = result_with(
        [candidate(LISBON, FRIDAY, SUNDAY), candidate(LISBON, saturday, SUNDAY)],
        {
            ("LIS", FRIDAY, "out"): (cheap, costlier),
            ("LIS", saturday, "out"): (following,),
            ("LIS", SUNDAY, "ret"): (inbound,),
        },
    )
    assert {pair.out for pair in result.itineraries()} == {cheap, following}

    projection = outbound_choices(result)
    groups = choices_by_date(projection)
    friday_group = groups[FRIDAY.isoformat()]
    saturday_group = groups[saturday.isoformat()]
    assert friday_group["city"] == "Lisbon"
    assert friday_group["country"] == "PT"
    assert flight_numbers(projection, friday_group["options"]) == {"10", "11"}
    assert flight_numbers(projection, saturday_group["options"]) == {"12"}
    [return_group_id] = friday_group["return_groups"]
    assert saturday_group["return_groups"] == [return_group_id]
    assert set(projection["return_groups"]) == {return_group_id}
    shared_return = projection["return_groups"][return_group_id]
    assert shared_return["date"] == SUNDAY.isoformat()
    [return_option_id] = shared_return["options"]
    returned = projection["options"][return_option_id]
    assert returned["legs"][0]["flight_number"] == "20"
    assert returned["price"] == 100
    assert returned["currency"] == "EUR"
    assert returned["departure"] == inbound.departure
    assert returned["arrival"] == inbound.arrival
    assert returned["duration"] == 120
    assert returned["segments"] == 1
    assert returned["layovers"] == []
    assert returned["booking_url"].startswith("https://www.google.com/travel/flights")


def test_outbound_choices_apply_shortlist_windows_and_codeshare_filter():
    from flight_search.web_results import outbound_choices

    saturday = FRIDAY + timedelta(days=1)
    monday = SUNDAY + timedelta(days=1)
    result = result_with(
        [
            candidate(LISBON, FRIDAY, SUNDAY),
            candidate(LISBON, saturday, monday),
            candidate(ROME, FRIDAY, SUNDAY),
        ],
        {
            ("LIS", FRIDAY, "out"): (
                option("10", FRIDAY, ("FRA", "LIS")),
                option("11", FRIDAY, ("FRA", "LIS"), departs="16:00"),
                option("12", FRIDAY, ("FRA", "LIS"), operator="TP"),
            ),
            ("LIS", saturday, "out"): (option("13", saturday, ("FRA", "LIS")),),
            ("LIS", SUNDAY, "ret"): (
                option("20", SUNDAY, ("LIS", "FRA")),
                option("21", SUNDAY, ("LIS", "FRA"), arrives="22:00"),
                option("22", SUNDAY, ("LIS", "FRA"), operator="TP"),
            ),
            ("LIS", monday, "ret"): (option("23", monday, ("LIS", "FRA")),),
            ("FCO", FRIDAY, "out"): (option("30", FRIDAY, ("FRA", "FCO")),),
            ("FCO", SUNDAY, "ret"): (
                option("31", SUNDAY, ("FCO", "FRA"), arrives="22:00"),
            ),
        },
    )

    for allow_codeshare, outbound, inbound in (
        (False, {"10"}, {"20"}),
        (True, {"10", "12"}, {"20", "22"}),
    ):
        request = replace(result.request, allow_codeshare=allow_codeshare)
        projection = outbound_choices(replace(result, request=request))
        assert {group["city"] for group in projection["outbound_groups"]} == {"Lisbon"}
        groups = choices_by_date(projection)
        assert set(groups) == {FRIDAY.isoformat(), saturday.isoformat()}
        friday_group = groups[FRIDAY.isoformat()]
        assert flight_numbers(projection, friday_group["options"]) == outbound
        [sunday_id] = friday_group["return_groups"]
        assert (
            flight_numbers(
                projection, projection["return_groups"][sunday_id]["options"]
            )
            == inbound
        )
        assert projection["return_groups"][sunday_id]["date"] == SUNDAY.isoformat()
        [monday_id] = groups[saturday.isoformat()]["return_groups"]
        assert projection["return_groups"][monday_id]["date"] == monday.isoformat()


def test_search_status_and_booking_reuse_confirmed_options():
    def run(request, **_):
        pair = request.pairs[0]
        return result_with(
            [candidate(LISBON, pair.depart, pair.ret)],
            {
                ("LIS", pair.depart, "out"): (
                    option("10", pair.depart, ("FRA", "LIS")),
                ),
                ("LIS", pair.ret, "ret"): (option("20", pair.ret, ("LIS", "FRA")),),
            },
            request=request,
        )

    runner = Mock(side_effect=run)
    client = app_for(runner).test_client()
    path = start_search(client, regions=["europe"])
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    assert client.get(path).get_json() == state
    [pair] = state["result"]["pairs"]
    assert pair["city"] == "Lisbon"
    choices = state["result"]["outbound_choices"]
    [group] = choices["outbound_groups"]
    [outbound_id] = group["options"]
    [return_group_id] = group["return_groups"]
    [return_id] = choices["return_groups"][return_group_id]["options"]

    url = f"{path}/booking"
    booking = client.get(
        url, query_string={"outbound": outbound_id, "return": return_id}
    )
    assert 300 <= booking.status_code < 400
    assert booking.location.startswith("https://www.google.com/travel/flights")
    invalid = client.get(
        url, query_string={"outbound": outbound_id, "return": outbound_id}
    )
    assert invalid.status_code == 404
    unknown = client.get(
        url, query_string={"outbound": outbound_id, "return": "unknown"}
    )
    assert unknown.status_code == 404
    runner.assert_called_once()
