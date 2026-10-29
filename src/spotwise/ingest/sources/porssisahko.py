"""porssisahko.net: free, no key. Fallback source and quick start before ENTSO-E.

Facts from https://porssisahko.net/api (checked 2026-10-29):
- `v2/latest-prices.json` returns about 48 h of 15-minute prices in one request.
- `v2/price.json?date=<ISO UTC>` returns the price of a single moment. There is no
  date-range endpoint, so history needs one request per slot (slow).
- Prices are c/kWh INCLUDING the VAT valid on that day. Negative prices have 0% VAT.
- Rate limit: 30 requests per 10 seconds per IP address.
"""

import logging
import time
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from spotwise.ingest.sources.base import PriceSlot, SourceError, get_with_retry
from spotwise.timeutils import iter_market_slots, local_tz

logger = logging.getLogger(__name__)

BASE_URL = "https://api.porssisahko.net/v2"

# Finnish VAT on electricity, newest first. Only used to REMOVE the VAT that
# porssisahko.net adds, so we can store €/MWh excl. VAT like ENTSO-E. (The VAT we
# show to users comes from config VAT_RATE.)
VAT_HISTORY: list[tuple[date, Decimal]] = [
    (date(2024, 9, 1), Decimal("0.255")),
    (date(2023, 5, 1), Decimal("0.24")),
    (date(2022, 12, 1), Decimal("0.10")),
    (date.min, Decimal("0.24")),
]

# Stay under the 30 requests / 10 s limit, with some margin.
MIN_REQUEST_INTERVAL_S = 0.4


def vat_rate_on(day: date) -> Decimal:
    """Finnish electricity VAT rate on a given day."""
    for start, rate in VAT_HISTORY:
        if day >= start:
            return rate
    raise AssertionError("unreachable: VAT_HISTORY ends with date.min")


def to_eur_mwh_excl_vat(price_c_kwh: Decimal, ts_start: datetime, tz: ZoneInfo) -> Decimal:
    """Convert porssisahko's c/kWh incl. VAT to €/MWh excl. VAT (3 decimals).

    porssisahko rounds to 0.001 c/kWh including VAT, so the result can differ from the
    exact ENTSO-E value by about 0.01 €/MWh.
    """
    if price_c_kwh > 0:
        price_c_kwh = price_c_kwh / (1 + vat_rate_on(ts_start.astimezone(tz).date()))
    return (price_c_kwh * 10).quantize(Decimal("0.001"))


def parse_latest_prices(payload: dict[str, Any], tz: ZoneInfo) -> list[PriceSlot]:
    """Parse a `latest-prices.json` payload into slots sorted by time."""
    slots = []
    try:
        for item in payload["prices"]:
            start = _parse_utc(item["startDate"])
            # endDate is like ...:14:59.999Z, so round the slot length to whole minutes
            minutes = round((_parse_utc(item["endDate"]) - start) / timedelta(minutes=1))
            if minutes not in (15, 60):
                raise SourceError(f"porssisahko: unexpected slot length {minutes} min")
            price = to_eur_mwh_excl_vat(Decimal(str(item["price"])), start, tz)
            slots.append(PriceSlot(start, minutes, price))
    except (KeyError, TypeError, ValueError) as exc:
        raise SourceError(f"porssisahko: unexpected response format ({exc!r})") from None
    return sorted(slots, key=lambda s: s.ts_start)


class PorssisahkoSource:
    """Fetches prices from porssisahko.net, converted to €/MWh excl. VAT."""

    name = "porssisahko"

    def __init__(
        self,
        client: httpx.Client,
        tz: ZoneInfo | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._client = client
        self._tz = tz or local_tz()
        self._sleep = sleep

    def fetch_latest(self) -> list[PriceSlot]:
        """All prices from `latest-prices.json` (about 48 h around today)."""
        response = get_with_retry(
            self._client, f"{BASE_URL}/latest-prices.json", source_name=self.name, sleep=self._sleep
        )
        if response.status_code != 200:
            raise SourceError(f"porssisahko: HTTP {response.status_code} from latest-prices")
        return parse_latest_prices(response.json(), self._tz)

    def fetch(self, start: datetime, end: datetime) -> list[PriceSlot]:
        """Slots in [start, end): recent ones in one request, older ones one by one."""
        latest = self.fetch_latest()
        found = {s.ts_start: s for s in latest if start <= s.ts_start < end}

        # Anything before the latest window is history; anything after isn't published.
        history_end = min(end, latest[0].ts_start if latest else datetime.now(UTC))
        missing = [
            (ts, res)
            for ts, res in iter_market_slots(start, history_end, self._tz)
            if ts not in found
        ]
        if len(missing) > 100:
            logger.warning(
                "porssisahko has no range endpoint: fetching %d slots one by one, about %.0f min. "
                "Set ENTSOE_TOKEN for fast backfills.",
                len(missing),
                len(missing) * MIN_REQUEST_INTERVAL_S / 60,
            )
        for i, (ts, resolution) in enumerate(missing, start=1):
            slot = self._fetch_one(ts, resolution)
            if slot is not None:
                found[ts] = slot
            if i % 500 == 0:
                logger.info("porssisahko: fetched %d/%d historical slots", i, len(missing))
            self._sleep(MIN_REQUEST_INTERVAL_S)
        return sorted(found.values(), key=lambda s: s.ts_start)

    def _fetch_one(self, ts: datetime, resolution: int) -> PriceSlot | None:
        response = get_with_retry(
            self._client,
            f"{BASE_URL}/price.json",
            params={"date": ts.strftime("%Y-%m-%dT%H:%M:%SZ")},
            source_name=self.name,
            sleep=self._sleep,
        )
        if response.status_code == 404:  # not published (yet)
            return None
        if response.status_code != 200:
            raise SourceError(f"porssisahko: HTTP {response.status_code} from price.json")
        try:
            price = Decimal(str(response.json()["price"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise SourceError(f"porssisahko: unexpected price.json format ({exc!r})") from None
        return PriceSlot(ts, resolution, to_eur_mwh_excl_vat(price, ts, self._tz))


def _parse_utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)
