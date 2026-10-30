"""Unit and VAT conversion (PRICE-01). The ONLY place VAT is applied.

Money math uses Decimal, not float: 0.1 + 0.2 must be exactly 0.3 when we add up costs.
Values keep full precision here; rounding happens only when we show them (API, agent).
"""

from collections.abc import Iterable
from decimal import Decimal

from spotwise.prices.slot import PriceSlot


def eur_mwh_to_c_kwh(price_eur_mwh: Decimal) -> Decimal:
    """€/MWh → c/kWh. 1 €/MWh = 100 c / 1000 kWh = 0.1 c/kWh."""
    return price_eur_mwh / 10


def apply_vat(price: Decimal, vat_rate: Decimal) -> Decimal:
    """Add VAT to a positive price. Negative prices get no VAT (Finnish practice:
    a credit to the customer is not taxed), and zero stays zero."""
    return price * (1 + vat_rate) if price > 0 else price


def consumer_price_c_kwh(price_eur_mwh: Decimal, include_vat: bool, vat_rate: Decimal) -> Decimal:
    """€/MWh excl. VAT → c/kWh, with or without VAT."""
    c_kwh = eur_mwh_to_c_kwh(price_eur_mwh)
    return apply_vat(c_kwh, vat_rate) if include_vat else c_kwh


def round_price(value: Decimal, places: int = 3) -> Decimal:
    """Round for display (default 3 decimals, like the sources)."""
    return value.quantize(Decimal(1).scaleb(-places))


def to_consumer_slots(
    slots: Iterable[PriceSlot], include_vat: bool, vat_rate: Decimal
) -> list[PriceSlot]:
    """Same slots with the price converted to consumer c/kWh (with or without VAT).

    The window and stats functions don't care about units, so running them on these
    slots ranks by what the customer actually pays. Note: the field is still called
    `price_eur_mwh`, but after this conversion it holds c/kWh.
    """
    return [
        PriceSlot(
            s.ts_start,
            s.resolution_minutes,
            consumer_price_c_kwh(s.price_eur_mwh, include_vat, vat_rate),
        )
        for s in slots
    ]
