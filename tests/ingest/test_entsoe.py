from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from spotwise.ingest.sources.base import SourceError
from spotwise.ingest.sources.entsoe import API_URL, EntsoeSource, parse_entsoe_xml
from tests.conftest import FIXTURES_DIR

QUARTERS = (FIXTURES_DIR / "entsoe_a44_synthetic_15min_2025-11-01.xml").read_bytes()
DST_HOURLY = (FIXTURES_DIR / "entsoe_a44_synthetic_hourly_dst_2025-10-26.xml").read_bytes()
NO_DATA = (FIXTURES_DIR / "entsoe_ack_no_data.xml").read_bytes()

DAY_START = datetime(2025, 10, 31, 22, tzinfo=UTC)
DAY_END = datetime(2025, 11, 1, 22, tzinfo=UTC)


def no_sleep(_: float) -> None:
    pass


def test_parses_quarter_hour_day_with_resolution_from_xml() -> None:
    slots = parse_entsoe_xml(QUARTERS)
    assert len(slots) == 96
    assert {s.resolution_minutes for s in slots} == {15}
    assert slots[0].ts_start == DAY_START
    assert slots[-1].ts_start == datetime(2025, 11, 1, 21, 45, tzinfo=UTC)


def test_a03_omitted_positions_repeat_previous_price() -> None:
    slots = parse_entsoe_xml(QUARTERS)
    # positions 2 and 3 are omitted in the XML, so they keep position 1's price
    assert [s.price_eur_mwh for s in slots[:4]] == [Decimal("1.50")] * 3 + [Decimal("4.50")]
    assert slots[49].price_eur_mwh == slots[48].price_eur_mwh  # position 50 omitted


def test_negative_prices_are_kept() -> None:
    slots = parse_entsoe_xml(QUARTERS)
    assert slots[59].price_eur_mwh == Decimal("-3.25")


def test_parses_25_hour_dst_day() -> None:
    slots = parse_entsoe_xml(DST_HOURLY)
    assert len(slots) == 25
    assert {s.resolution_minutes for s in slots} == {60}
    assert slots[0].ts_start == datetime(2025, 10, 25, 21, tzinfo=UTC)


def test_no_matching_data_acknowledgement_means_empty() -> None:
    assert parse_entsoe_xml(NO_DATA) == []


def test_other_acknowledgement_is_an_error() -> None:
    xml = NO_DATA.replace(b"No matching data found", b"Invalid parameter")
    with pytest.raises(SourceError, match="rejected"):
        parse_entsoe_xml(xml)


def test_missing_position_in_a01_curve_is_an_error() -> None:
    xml = DST_HOURLY.replace(b"<position>5</position>", b"<position>99</position>")
    with pytest.raises(SourceError, match="position 5 missing"):
        parse_entsoe_xml(xml)


def test_invalid_xml_is_an_error() -> None:
    with pytest.raises(SourceError, match="not valid XML"):
        parse_entsoe_xml(b"<html>oops")


@respx.mock
def test_fetch_sends_a44_query_in_utc() -> None:
    route = respx.get(API_URL).mock(return_value=httpx.Response(200, content=QUARTERS))
    with httpx.Client() as client:
        slots = EntsoeSource("secret-token", "FI", client, sleep=no_sleep).fetch(DAY_START, DAY_END)
    assert len(slots) == 96
    params = route.calls.last.request.url.params
    assert params["documentType"] == "A44"
    assert params["in_Domain"] == params["out_Domain"] == "10YFI-1--------U"
    assert params["periodStart"] == "202510312200"
    assert params["periodEnd"] == "202511012200"


@respx.mock
def test_fetch_filters_to_requested_range() -> None:
    respx.get(API_URL).mock(return_value=httpx.Response(200, content=QUARTERS))
    with httpx.Client() as client:
        slots = EntsoeSource("t", "FI", client, sleep=no_sleep).fetch(
            DAY_START, datetime(2025, 10, 31, 23, tzinfo=UTC)
        )
    assert len(slots) == 4


@respx.mock
def test_no_data_with_http_400_returns_empty() -> None:
    respx.get(API_URL).mock(return_value=httpx.Response(400, content=NO_DATA))
    with httpx.Client() as client:
        assert EntsoeSource("t", "FI", client, sleep=no_sleep).fetch(DAY_START, DAY_END) == []


@respx.mock
def test_retries_server_errors_then_succeeds() -> None:
    route = respx.get(API_URL).mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(503),
            httpx.Response(200, content=QUARTERS),
        ]
    )
    with httpx.Client() as client:
        slots = EntsoeSource("t", "FI", client, sleep=no_sleep).fetch(DAY_START, DAY_END)
    assert route.call_count == 3
    assert len(slots) == 96


@respx.mock
def test_gives_up_after_three_retries_without_leaking_token() -> None:
    route = respx.get(API_URL).mock(return_value=httpx.Response(503))
    with httpx.Client() as client, pytest.raises(SourceError) as excinfo:
        EntsoeSource("secret-token", "FI", client, sleep=no_sleep).fetch(DAY_START, DAY_END)
    assert route.call_count == 4  # first try + 3 retries
    assert "secret-token" not in str(excinfo.value)


@respx.mock
def test_bad_token_is_a_clear_error() -> None:
    respx.get(API_URL).mock(return_value=httpx.Response(401, content=b"Unauthorized"))
    with httpx.Client() as client, pytest.raises(SourceError, match="ENTSOE_TOKEN"):
        EntsoeSource("t", "FI", client, sleep=no_sleep).fetch(DAY_START, DAY_END)
