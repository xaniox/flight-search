from datetime import date, timedelta
from unittest.mock import Mock

import pytest
from test_web import app_for

from flight_search import weekend


def test_browser_rejects_over_budget_dates_before_expanding_pairs(monkeypatch):
    runner = Mock()
    client = app_for(runner).test_client()
    start = date.today() + timedelta(days=7)
    start += timedelta(days=(4 - start.weekday()) % 7)
    end = start + timedelta(weeks=2, days=2)

    def unexpected_expansion(*args, **kwargs):
        pytest.fail("Over-budget search expanded date pairs before admission")

    monkeypatch.setattr(weekend, "expand_date_pairs", unexpected_expansion)
    response = client.post(
        "/api/searches",
        json={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "depart_days": ["fri"],
            "return_days": ["sun"],
            "regions": [],
            "countries": ["PT"],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"].lower()
    assert "request" in error
    assert "limit" in error or "budget" in error
    runner.assert_not_called()


def test_browser_rejects_too_many_date_pairs_before_expanding_them(monkeypatch):
    runner = Mock()
    client = app_for(runner).test_client()
    start = date.today() + timedelta(days=30)
    end = start + timedelta(days=365 * 8)

    def unexpected_expansion(*args, **kwargs):
        pytest.fail("Search with too many date pairs expanded them before admission")

    monkeypatch.setattr(weekend, "expand_date_pairs", unexpected_expansion)
    response = client.post(
        "/api/searches",
        json={
            "start": start.isoformat(),
            "end": end.isoformat(),
            "depart_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "return_days": ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
            "min_nights": 0,
            "max_nights": 3000,
            "max_requests": 1_000_000,
            "regions": [],
            "countries": ["PT"],
        },
    )

    assert response.status_code == 400
    error = response.get_json()["error"].lower()
    assert "date pairs" in error
    assert "limit" in error
    runner.assert_not_called()
