import json
from datetime import UTC, date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
import pytest
import respx

from spotwise.ingest.sources.base import SourceError
from spotwise.ingest.sources.porssisahko import (
    BASE_URL,
    PorssisahkoSource,
    parse_latest_prices,
    to_eur_mwh_excl_vat,
    vat_rate_on,
)
from tests.conftest import FIXTURES_DIR

HEL = ZoneInfo("Europe/Helsinki")
LATEST = json.loads((FIXTURES_DIR / "porssisahko_v2_latest_prices.json").read_text())


def no_sleep(_: float) -> None:
    pass


def test_parses_real_latest_prices_sample() -> None:
    slots = parse_latest_prices(LATEST, HEL)
    assert len(slots) == len(LATEST["prices"])
    assert {s.resolution_minutes for s in slots} == {15}
    assert all(
        s.ts_start.tzinfo is not None and s.ts_start.utcoffset() == UTC.utcoffset(None)
        for s in slots
    )
    assert slots == sorted(slots, key=lambda s: s.ts_start)


def test_vat_history() -> None:
    assert vat_rate_on(date(2022, 11, 30)) == Decimal("0.24")
    assert vat_rate_on(date(2022, 12, 1)) == Decimal("0.10")
    assert vat_rate_on(date(2023, 5, 1)) == Decimal("0.24")
    assert vat_rate_on(date(2024, 8, 31)) == Decimal("0.24")
    assert vat_rate_on(date(2024, 9, 1)) == Decimal("0.255")


@pytest.mark.parametrize(
    ("c_kwh_incl_vat", "ts", "expected_eur_mwh"),
    [
        ("1.255", datetime(2025, 1, 1, 12, tzinfo=UTC), "10.000"),  # 25.5% VAT
        ("1.24", datetime(2024, 1, 1, 12, tzinfo=UTC), "10.000"),  # 24% VAT
        ("1.1", datetime(2023, 1, 1, 12, tzinfo=UTC), "10.000"),  # 10% VAT
        ("-0.5", datetime(2025, 1, 1, 12, tzinfo=UTC), "-5.000"),  # negative: no VAT
        ("0", datetime(2025, 1, 1, 12, tzinfo=UTC), "0.000"),
    ],
)
def test_converts_to_eur_mwh_excluding_vat(
    c_kwh_incl_vat: str, ts: datetime, expected_eur_mwh: str
) -> None:
    assert to_eur_mwh_excl_vat(Decimal(c_kwh_incl_vat), ts, HEL) == Decimal(expected_eur_mwh)


def test_vat_day_is_the_helsinki_day() -> None:
    # 2024-08-31 21:30 UTC is already 1 Sept in Helsinki, when VAT became 25.5%
    ts = datetime(2024, 8, 31, 21, 30, tzinfo=UTC)
    assert to_eur_mwh_excl_vat(Decimal("1.255"), ts, HEL) == Decimal("10.000")


def test_unexpected_format_is_a_source_error() -> None:
    with pytest.raises(SourceError):
        parse_latest_prices({"oops": []}, HEL)


@respx.mock
def test_fetch_uses_latest_and_fetches_older_slots_one_by_one() -> None:
    latest = {
        "prices": [
            {
                "price": 2.51,
                "startDate": "2025-10-01T00:00:00.000Z",
                "endDate": "2025-10-01T00:14:59.999Z",
            }
        ]
    }
    respx.get(f"{BASE_URL}/latest-prices.json").mock(return_value=httpx.Response(200, json=latest))
    single = respx.get(f"{BASE_URL}/price.json").mock(
        return_value=httpx.Response(200, json={"price": 1.255})
    )
    # 2025-09-30 21:00Z .. 2025-10-01 00:15Z: 12 quarters before the latest window, then 1 from it
    start = datetime(2025, 9, 30, 21, tzinfo=UTC)
    end = datetime(2025, 10, 1, 0, 15, tzinfo=UTC)
    with httpx.Client() as client:
        slots = PorssisahkoSource(client, HEL, sleep=no_sleep).fetch(start, end)
    assert single.call_count == 12
    assert single.calls[0].request.url.params["date"] == "2025-09-30T21:00:00Z"
    assert len(slots) == 13
    assert slots[-1].price_eur_mwh == Decimal("20.000")


@respx.mock
def test_history_before_switch_is_hourly() -> None:
    respx.get(f"{BASE_URL}/latest-prices.json").mock(
        return_value=httpx.Response(200, json={"prices": []})
    )
    respx.get(f"{BASE_URL}/price.json").mock(return_value=httpx.Response(200, json={"price": 1.24}))
    start = datetime(2024, 6, 1, 21, tzinfo=UTC)  # 2024-06-02 00:00 Helsinki
    end = datetime(2024, 6, 2, 21, tzinfo=UTC)
    with httpx.Client() as client:
        slots = PorssisahkoSource(client, HEL, sleep=no_sleep).fetch(start, end)
    assert len(slots) == 24
    assert {s.resolution_minutes for s in slots} == {60}
