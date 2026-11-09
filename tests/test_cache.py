from datetime import timedelta

from flight_search.cache import Cache, parse_duration


def test_parse_duration():
    assert parse_duration("12h") == timedelta(hours=12)
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("45s") == timedelta(seconds=45)
    assert parse_duration("0") == timedelta(0)


def test_cache_roundtrip(tmp_path):
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1))
    key = {"phase": "calendar", "destination": "BCN"}
    assert cache.get(key) is None
    cache.put(key, {"2026-11-13": 44.0})
    assert cache.get(key) == {"2026-11-13": 44.0}
    assert cache.stats.hits == 1


def test_cache_expiry(tmp_path):
    cache = Cache(directory=tmp_path, ttl=timedelta(seconds=-1))
    key = {"a": 1}
    cache.put(key, "value")
    assert cache.get(key) is None


def test_cache_disabled(tmp_path):
    cache = Cache(directory=tmp_path, ttl=timedelta(hours=1), enabled=False)
    cache.put({"a": 1}, "value")
    assert cache.get({"a": 1}) is None
    assert not list(tmp_path.glob("*.json"))
