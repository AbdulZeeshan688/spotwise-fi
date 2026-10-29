"""ENTSO-E Transparency Platform: day-ahead prices (documentType A44) as XML.

Docs: https://transparency.entsoe.eu (RESTful API user guide). Prices are €/MWh excl. VAT.
"""

import logging
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from xml.etree.ElementTree import Element

import defusedxml.ElementTree as SafeET
import httpx

from spotwise.ingest.sources.base import PriceSlot, SourceError, get_with_retry

logger = logging.getLogger(__name__)

API_URL = "https://web-api.tp.entsoe.eu/api"
AREA_EIC_CODES = {"FI": "10YFI-1--------U"}
RESOLUTIONS = {"PT15M": 15, "PT60M": 60}


class EntsoeSource:
    """Fetches day-ahead prices from ENTSO-E (needs a security token)."""

    name = "entsoe"

    def __init__(
        self,
        token: str,
        area: str,
        client: httpx.Client,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if area not in AREA_EIC_CODES:
            raise ValueError(f"No ENTSO-E EIC code known for area {area!r}")
        self._token = token
        self._eic = AREA_EIC_CODES[area]
        self._client = client
        self._sleep = sleep

    def fetch(self, start: datetime, end: datetime) -> list[PriceSlot]:
        """Fetch slots in [start, end). One request may cover at most one year."""
        params = {
            "securityToken": self._token,
            "documentType": "A44",
            "in_Domain": self._eic,
            "out_Domain": self._eic,
            "contract_MarketAgreement.type": "A01",  # A01 = day-ahead
            "periodStart": _format_period(start),
            "periodEnd": _format_period(end),
        }
        response = get_with_retry(
            self._client, API_URL, params=params, source_name=self.name, sleep=self._sleep
        )
        if response.status_code == 401:
            raise SourceError("entsoe: unauthorised, check ENTSOE_TOKEN")
        # ENTSO-E answers "no data" with an Acknowledgement document, sometimes with
        # HTTP 200 and sometimes 400, so parse the body before looking at the status.
        try:
            slots = parse_entsoe_xml(response.content)
        except SourceError:
            if response.status_code >= 400:
                raise SourceError(f"entsoe: HTTP {response.status_code}") from None
            raise
        return [slot for slot in slots if start <= slot.ts_start < end]


def parse_entsoe_xml(content: bytes) -> list[PriceSlot]:
    """Parse an A44 Publication_MarketDocument into price slots, sorted by time.

    Returns [] for a "No matching data found" acknowledgement. Reads the resolution
    from every Period (PT15M or PT60M) and fills positions omitted by curve type A03,
    which means "same price as the previous position".
    """
    try:
        root = SafeET.fromstring(content)
    except SafeET.ParseError as exc:
        raise SourceError(f"entsoe: response is not valid XML ({exc})") from None

    kind = _local_name(root.tag)
    if kind == "Acknowledgement_MarketDocument":
        reason = " ".join(
            el.text.strip() for el in root.iter() if _local_name(el.tag) == "text" and el.text
        )
        if "no matching data" in reason.lower():
            return []
        raise SourceError(f"entsoe: request rejected: {reason or 'no reason given'}")
    if kind != "Publication_MarketDocument":
        raise SourceError(f"entsoe: unexpected document type {kind}")

    # Keyed by (start, resolution) so a slot repeated in two TimeSeries appears once.
    slots: dict[tuple[datetime, int], PriceSlot] = {}
    for series in _children(root, "TimeSeries"):
        curve = _child(series, "curveType")
        curve_type = curve.text.strip() if curve is not None and curve.text else "A01"
        for period in _children(series, "Period"):
            for slot in _parse_period(period, curve_type):
                slots[(slot.ts_start, slot.resolution_minutes)] = slot
    return sorted(slots.values(), key=lambda s: (s.ts_start, s.resolution_minutes))


def _parse_period(period: Element, curve_type: str) -> list[PriceSlot]:
    interval = _child(period, "timeInterval")
    if interval is None:
        raise SourceError("entsoe: Period without timeInterval")
    start = _parse_utc(_text(interval, "start"))
    end = _parse_utc(_text(interval, "end"))

    resolution_text = _text(period, "resolution")
    if resolution_text not in RESOLUTIONS:
        raise SourceError(f"entsoe: unsupported resolution {resolution_text}")
    resolution = RESOLUTIONS[resolution_text]
    step = timedelta(minutes=resolution)

    prices: dict[int, Decimal] = {}
    for point in _children(period, "Point"):
        try:
            prices[int(_text(point, "position"))] = Decimal(_text(point, "price.amount"))
        except (ValueError, InvalidOperation):
            raise SourceError("entsoe: bad position or price.amount in Point") from None
    if 1 not in prices:
        raise SourceError("entsoe: Period has no position 1")

    slots = []
    price = prices[1]
    for position in range(1, (end - start) // step + 1):
        if position in prices:
            price = prices[position]
        elif curve_type != "A03":
            raise SourceError(f"entsoe: position {position} missing in curve {curve_type}")
        # A03: an omitted position keeps the previous price.
        slots.append(PriceSlot(start + (position - 1) * step, resolution, price))
    return slots


def _format_period(ts: datetime) -> str:
    """ENTSO-E wants UTC as yyyyMMddHHmm."""
    return ts.astimezone(UTC).strftime("%Y%m%d%H%M")


def _parse_utc(text: str) -> datetime:
    """Parse ENTSO-E times like 2025-10-31T22:00Z."""
    return datetime.fromisoformat(text).astimezone(UTC)


def _local_name(tag: str) -> str:
    """Tag name without the XML namespace (ENTSO-E changes namespace versions)."""
    return tag.rsplit("}", 1)[-1]


def _children(element: Element, name: str) -> Iterator[Element]:
    return (child for child in element if _local_name(child.tag) == name)


def _child(element: Element, name: str) -> Element | None:
    return next(_children(element, name), None)


def _text(element: Element, name: str) -> str:
    child = _child(element, name)
    if child is None or child.text is None:
        raise SourceError(f"entsoe: missing <{name}>")
    return child.text.strip()
