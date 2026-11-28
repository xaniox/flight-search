from unittest.mock import Mock

from test_web import app_for, start_search, wait_for_final_state
from test_web_results import LISBON, candidate, option, result_with


def test_browser_pairs_and_booking_reject_return_before_arrival():
    def run(request, **_):
        pair = request.pairs[0]
        assert pair.depart == pair.ret
        outbound = option("10", pair.depart, ("FRA", "LIS"))
        too_early = option("20", pair.ret, ("LIS", "FRA"), price=70)
        valid = option(
            "21", pair.ret, ("LIS", "FRA"), price=110, departs="22:00", arrives="23:50"
        )
        result = result_with(
            [candidate(LISBON, pair.depart, pair.ret)],
            {
                ("LIS", pair.depart, "out"): (outbound,),
                ("LIS", pair.ret, "ret"): (too_early, valid),
            },
            request=request,
        )
        assert [item.ret for item in result.itineraries()] == [too_early]
        return result

    runner = Mock(side_effect=run)
    client = app_for(runner).test_client()
    start = client.get("/api/catalogs").get_json()["defaults"]["start"]
    path = start_search(
        client,
        end=start,
        return_days=["fri"],
        min_nights=0,
        max_nights=0,
        regions=["europe"],
    )
    state = wait_for_final_state(client, path)
    assert state["status"] == "done", state
    result = state["result"]
    options = result["outbound_choices"]["options"]
    ids = {flight["legs"][0]["flight_number"]: key for key, flight in options.items()}
    assert (
        options[ids["20"]]["departure_utc"]
        < options[ids["10"]]["arrival_utc"]
        < options[ids["21"]]["departure_utc"]
    )

    bad = client.get(
        f"{path}/booking", query_string={"outbound": ids["10"], "return": ids["20"]}
    )
    good = client.get(
        f"{path}/booking", query_string={"outbound": ids["10"], "return": ids["21"]}
    )
    assert 300 <= good.status_code < 400
    assert good.location.startswith("https://www.google.com/travel/flights")

    returns = [pair["return"]["legs"][0]["flight_number"] for pair in result["pairs"]]
    assert (returns, bad.status_code) == (["21"], 404)
    runner.assert_called_once()
