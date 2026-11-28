"""Distances are measured from a home coordinate (PRTWO-CRITERION-08).

The new names are imported inside each test, so each test fails on its own
until ``flight_search.config.Coordinate`` and ``airports.distance_km`` exist.
"""

from __future__ import annotations

import dataclasses

import pytest
from airport_factory import airport

MUC_LAT, MUC_LON = 48.354, 11.786


def test_coordinate_is_a_frozen_dataclass():
    from flight_search.config import Coordinate

    point = Coordinate(1.0, 2.0)
    assert dataclasses.is_dataclass(point)
    assert (point.lat, point.lon) == (1.0, 2.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        point.lat = 3.0


def test_karlsruhe_is_the_default_home_coordinate():
    from flight_search.config import KARLSRUHE, Coordinate

    assert KARLSRUHE == Coordinate(49.013, 8.404)


def test_distance_km_defaults_to_karlsruhe():
    from flight_search.airports import distance_km, load_airports

    fra = {a.iata: a for a in load_airports()}["FRA"]
    assert distance_km(fra) < 200


def test_distance_km_measures_from_a_given_center():
    from flight_search.airports import distance_km
    from flight_search.config import Coordinate

    muc_like = airport("MUC", "DE", "EU", lat=MUC_LAT, lon=MUC_LON)
    assert distance_km(muc_like, center=Coordinate(MUC_LAT, MUC_LON)) < 5
    assert distance_km(muc_like) > 200


def test_filter_airports_measures_from_a_given_center():
    from flight_search.airports import filter_airports
    from flight_search.config import Coordinate

    muc_like = airport("MUC", "DE", "EU", lat=MUC_LAT, lon=MUC_LON)
    stuttgart_like = airport("STR", "DE", "EU", lat=48.69, lon=9.22)
    airports = (muc_like, stuttgart_like)
    centre = Coordinate(MUC_LAT, MUC_LON)

    near_muc = filter_airports(airports, max_distance_km=50, center=centre)
    assert {a.iata for a in near_muc} == {"MUC"}
    near_home = filter_airports(airports, max_distance_km=100)
    assert {a.iata for a in near_home} == {"STR"}
