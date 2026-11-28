from dataclasses import replace
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from test_web_results import LISBON, candidate, option, result_with

from flight_search.web_results import outbound_choices, pair_results


def epoch(year, month, day, hour, minute=0):
    return int(datetime(year, month, day, hour, minute, tzinfo=UTC).timestamp())


def test_airport_timezones_follow_the_snapshot_including_icao_exceptions():
    from flight_search.airport_timezones import airport_timezone

    for code, expected in (
        ("FRA", "Europe/Berlin"),
        ("ATH", "Europe/Athens"),
        ("LHR", "Europe/London"),
        ("HBE", "Africa/Cairo"),
        ("RUS", "Pacific/Guadalcanal"),
        ("OUI", "Europe/Paris"),
        ("GOY", "Asia/Krasnoyarsk"),
    ):
        zone = airport_timezone(code)
        assert isinstance(zone, ZoneInfo), code
        assert zone.key == expected, code
    assert airport_timezone("ZZZ") is None


def test_stay_uses_final_arrival_and_first_return_departure_in_utc():
    from flight_search.airport_timezones import stay_minutes, utc_timestamp

    saturday = date(2027, 3, 27)
    sunday = date(2027, 3, 28)
    outbound = option("10", saturday, ("FRA", "ATH"), departs="09:00", arrives="12:00")
    inbound = option("20", sunday, ("ATH", "FRA"), departs="12:00", arrives="15:00")
    assert stay_minutes(outbound, inbound) == 23 * 60
    assert utc_timestamp("2027-03-27T12:00", "ATH") == epoch(2027, 3, 27, 10)
    assert utc_timestamp("2027-03-28T12:00", "ATH") == epoch(2027, 3, 28, 9)

    friday = date(2027, 1, 15)
    saturday = date(2027, 1, 16)
    first = option("30", friday, ("FRA", "AMS"), departs="20:00", arrives="21:00")
    last = option("31", friday, ("AMS", "LHR"), departs="23:30", arrives="23:59")
    last_leg = replace(last.legs[0], arrival="2027-01-16T00:15")
    overnight_outbound = replace(
        first, arrival=last_leg.arrival, legs=first.legs + (last_leg,)
    )
    return_first = option(
        "40", saturday, ("CDG", "AMS"), departs="10:00", arrives="11:00"
    )
    return_last = option(
        "41", saturday, ("AMS", "FRA"), departs="13:00", arrives="14:00"
    )
    open_jaw_return = replace(
        return_first,
        arrival=return_last.arrival,
        legs=return_first.legs + return_last.legs,
    )
    assert stay_minutes(overnight_outbound, open_jaw_return) == 8 * 60 + 45

    assert utc_timestamp("2027-03-28T03:30", "ATH") is None
    assert utc_timestamp("2027-10-31T03:30", "ATH") is None
    assert utc_timestamp("2027-03-28T12:00", "ZZZ") is None
    assert stay_minutes(replace(outbound, legs=()), inbound) is None
    assert stay_minutes(outbound, replace(inbound, legs=())) is None
    assert (
        stay_minutes(overnight_outbound, option("42", friday, ("CDG", "FRA"))) is None
    )


def test_both_browser_projections_include_stay_data_and_unknown_values():
    friday = date(2027, 1, 15)
    sunday = date(2027, 1, 17)
    inbound = option("20", sunday, ("LIS", "FRA"))
    for destination, arrival_utc, minutes in (
        ("LIS", epoch(2027, 1, 15, 20), 46 * 60),
        ("ZZZ", None, None),
    ):
        result = result_with(
            [candidate(LISBON, friday, sunday)],
            {
                ("LIS", friday, "out"): (option("10", friday, ("FRA", destination)),),
                ("LIS", sunday, "ret"): (inbound,),
            },
        )
        [pair] = pair_results(result, result.request.settings, top=20)["pairs"]
        assert pair["stay_minutes"] == minutes

        projection = outbound_choices(result)
        [group] = projection["outbound_groups"]
        [out_id] = group["options"]
        [return_group_id] = group["return_groups"]
        [return_id] = projection["return_groups"][return_group_id]["options"]
        assert projection["options"][out_id]["arrival_utc"] == arrival_utc
        assert projection["options"][return_id]["departure_utc"] == epoch(
            2027, 1, 17, 18
        )
