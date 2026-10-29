from collections.abc import Iterator
from datetime import date
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from spotwise.api.main import app
from spotwise.api.routes.prices import parse_time
from spotwise.db.session import get_session
from spotwise.ingest.pipeline import upsert_prices
from tests.quality.helpers import day_rows

HEL = ZoneInfo("Europe/Helsinki")
DAY = date(2025, 11, 1)


def test_parse_time_accepts_dates_and_datetimes() -> None:
    assert parse_time("2025-11-01", HEL).isoformat() == "2025-10-31T22:00:00+00:00"
    assert parse_time("2025-11-01T10:00", HEL).isoformat() == "2025-11-01T10:00:00+02:00"
    assert parse_time("2025-11-01T10:00Z", HEL).isoformat() == "2025-11-01T10:00:00+00:00"
    with pytest.raises(HTTPException):
        parse_time("yesterday", HEL)


@pytest.fixture
def client(db_session: Session) -> Iterator[TestClient]:
    # Cheap night: 10 €/MWh from 02:00 to 05:00 Helsinki (slots 8..19), else 100 €/MWh
    rows = day_rows(DAY, lambda i: "10" if 8 <= i < 20 else "100")
    upsert_prices(db_session, rows, "FI", "entsoe")
    app.dependency_overrides[get_session] = lambda: db_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.db
def test_prices_in_c_kwh_with_vat_by_default(client: TestClient) -> None:
    body = client.get("/prices", params={"from": "2025-11-01", "to": "2025-11-02"}).json()
    assert body["count"] == 96
    assert body["vat_included"] is True
    assert body["unit"] == "c/kWh"
    first = body["prices"][0]
    assert first["start"] == "2025-11-01T00:00:00+02:00"
    assert first["end"] == "2025-11-01T00:15:00+02:00"
    assert first["price_c_kwh"] == "12.550"  # 100 €/MWh = 10 c/kWh + 25.5% VAT


@pytest.mark.db
def test_prices_without_vat_and_hourly(client: TestClient) -> None:
    params = {"from": "2025-11-01", "to": "2025-11-02", "vat": "false", "resolution": "60"}
    body = client.get("/prices", params=params).json()
    assert body["count"] == 24
    assert body["prices"][2]["price_c_kwh"] == "1.000"
    assert body["prices"][2]["resolution_minutes"] == 60


@pytest.mark.db
def test_prices_rejects_bad_ranges(client: TestClient) -> None:
    assert (
        client.get("/prices", params={"from": "2025-11-02", "to": "2025-11-01"}).status_code == 422
    )
    assert (
        client.get("/prices", params={"from": "2025-01-01", "to": "2025-12-01"}).status_code == 422
    )


@pytest.mark.db
def test_cheapest_window(client: TestClient) -> None:
    response = client.get("/prices/cheapest-window", params={"date": "2025-11-01", "hours": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["start"] == "2025-11-01T02:00:00+02:00"
    assert body["end"] == "2025-11-01T05:00:00+02:00"
    assert body["average_price_c_kwh"] == "1.255"
    assert body["vat_included"] is True
    assert body["data_complete"] is True


@pytest.mark.db
def test_cheapest_window_for_unpublished_day(client: TestClient) -> None:
    response = client.get("/prices/cheapest-window", params={"date": "2099-01-01", "hours": 3})
    assert response.status_code == 404
    assert "published around 14:00" in response.json()["detail"]


@pytest.mark.db
def test_cheapest_window_bad_length(client: TestClient) -> None:
    response = client.get("/prices/cheapest-window", params={"date": "2025-11-01", "hours": 0.1})
    assert response.status_code == 422


@pytest.mark.db
def test_prices_rejects_other_resolutions(client: TestClient) -> None:
    assert client.get("/prices", params={"resolution": "30"}).status_code == 422


@pytest.mark.db
def test_future_day_with_only_early_slots_counts_as_unpublished(
    client: TestClient, db_session: Session
) -> None:
    # porssisahko sometimes has tomorrow's first hour before the rest is published
    upsert_prices(db_session, day_rows(date(2099, 1, 2))[:4], "FI", "porssisahko")
    response = client.get("/prices/cheapest-window", params={"date": "2099-01-02", "hours": 1})
    assert response.status_code == 404
    assert "not published yet" in response.json()["detail"]


@pytest.mark.db
def test_past_day_with_gap_is_flagged_incomplete(client: TestClient, db_session: Session) -> None:
    upsert_prices(db_session, day_rows(date(2025, 11, 2))[:50], "FI", "entsoe")
    response = client.get("/prices/cheapest-window", params={"date": "2025-11-02", "hours": 1})
    assert response.status_code == 200
    assert response.json()["data_complete"] is False
