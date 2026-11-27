"""The refresh keeps scheduled airports worldwide (PRONE-CRITERION-07)."""

from flight_search.refresh import build_rows

HEADER = (
    "iata_code,name,municipality,iso_country,type,continent,"
    "latitude_deg,longitude_deg,scheduled_service"
)


def _csv(*rows: str) -> str:
    return "\n".join([HEADER, *rows]) + "\n"


TLV = "TLV,Ben Gurion,Tel Aviv,IL,large_airport,AS,32.0114,34.8867,yes"
JFK = "JFK,John F Kennedy,New York,US,large_airport,NA,40.6398,-73.7789,yes"
RHO = "RHO,Diagoras,Rodes,GR,medium_airport,EU,36.4054,28.0862,yes"


def test_build_rows_keeps_scheduled_airports_on_any_continent():
    rows = build_rows(_csv(TLV, JFK, RHO))
    assert [r["iata"] for r in rows] == ["JFK", "RHO", "TLV"]


def test_build_rows_keeps_continent_and_country_of_worldwide_rows():
    rows = {r["iata"]: r for r in build_rows(_csv(TLV, JFK))}
    assert (rows["TLV"]["iso_country"], rows["TLV"]["continent"]) == ("IL", "AS")
    assert (rows["JFK"]["iso_country"], rows["JFK"]["continent"]) == ("US", "NA")


def test_build_rows_still_drops_non_scheduled_rows():
    unscheduled = TLV.replace(",yes", ",no")
    rows = build_rows(_csv(unscheduled, JFK))
    assert [r["iata"] for r in rows] == ["JFK"]


def test_build_rows_still_drops_unknown_iata_codes():
    unknown = "ZZZ,Nowhere,Nowhere,US,large_airport,NA,1.0,1.0,yes"
    rows = build_rows(_csv(unknown, JFK))
    assert [r["iata"] for r in rows] == ["JFK"]


def test_build_rows_drops_rows_of_other_types_such_as_heliports():
    heliport = "TLV,Ben Gurion Heliport,Tel Aviv,IL,heliport,AS,32.0,34.8,yes"
    rows = build_rows(_csv(heliport, JFK))
    assert [r["iata"] for r in rows] == ["JFK"]


def test_build_rows_drops_rows_with_empty_iata_code():
    empty = ",No Code Field,Nowhere,US,large_airport,NA,1.0,1.0,yes"
    rows = build_rows(_csv(empty, JFK))
    assert [r["iata"] for r in rows] == ["JFK"]


def test_build_rows_keeps_only_first_row_of_duplicate_iata_code():
    duplicate = "JFK,Second JFK,Elsewhere,US,medium_airport,NA,1.0,1.0,yes"
    rows = build_rows(_csv(JFK, duplicate))
    assert [(r["iata"], r["name"]) for r in rows] == [("JFK", "John F Kennedy")]
