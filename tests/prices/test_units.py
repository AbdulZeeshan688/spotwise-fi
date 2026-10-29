from decimal import Decimal

from hypothesis import given

from spotwise.prices.units import apply_vat, consumer_price_c_kwh, eur_mwh_to_c_kwh, round_price
from tests.prices.strategies import prices

VAT = Decimal("0.255")


def test_eur_mwh_to_c_kwh() -> None:
    assert eur_mwh_to_c_kwh(Decimal("100")) == Decimal("10")


def test_vat_added_to_positive_prices() -> None:
    assert consumer_price_c_kwh(Decimal("100"), True, VAT) == Decimal("12.55")
    assert consumer_price_c_kwh(Decimal("100"), False, VAT) == Decimal("10")


def test_no_vat_on_negative_or_zero_prices() -> None:
    assert consumer_price_c_kwh(Decimal("-20"), True, VAT) == Decimal("-2")
    assert apply_vat(Decimal("0"), VAT) == Decimal("0")


def test_round_price() -> None:
    assert round_price(Decimal("1.23456")) == Decimal("1.235")
    assert round_price(Decimal("1.23456"), 2) == Decimal("1.23")


@given(prices)
def test_vat_never_lowers_a_price(price: Decimal) -> None:
    assert apply_vat(price, VAT) >= price


@given(prices)
def test_without_vat_is_exactly_a_tenth(price: Decimal) -> None:
    assert consumer_price_c_kwh(price, False, VAT) * 10 == price
