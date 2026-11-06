"""Till arithmetic, checked against hand calculations."""

from decimal import Decimal

import pytest

from app.services.pricing import (
    LineInput,
    PricingError,
    price_cart,
    proportional_refund,
    vat_included,
    vat_on_top,
)

D = Decimal


def test_vat_extracted_from_inclusive_price() -> None:
    # 116 incl. 16% VAT = 100 net + 16 VAT
    assert vat_included(D("116"), D("16")) == D("16.00")
    # 245 incl. 16%: 245 x 16/116 = 33.793... -> 33.79
    assert vat_included(D("245"), D("16")) == D("33.79")
    assert vat_included(D("245"), D("0")) == D("0.00")


def test_vat_on_top_of_supplier_cost() -> None:
    assert vat_on_top(D("1980"), D("16")) == D("316.80")


def test_simple_cart_no_discount() -> None:
    # 2 x sugar 245 + 1 x bread 70 (VAT 16% on both)
    cart = price_cart([LineInput(D("2"), D("245"), D("16")), LineInput(D("1"), D("70"), D("16"))])
    assert cart.subtotal == D("560.00")
    assert cart.grand_total == D("560.00")
    assert cart.discount_total == D("0.00")
    # 490 x 16/116 = 67.59, 70 x 16/116 = 9.66
    assert [line.tax for line in cart.lines] == [D("67.59"), D("9.66")]
    assert cart.tax_total == D("77.25")
    assert cart.lines[0].net == D("422.41")


def test_zero_rated_items_have_no_vat() -> None:
    cart = price_cart([LineInput(D("3"), D("65"), D("0"))])
    assert cart.tax_total == D("0.00") and cart.grand_total == D("195.00")


def test_line_and_cart_discounts_add_up_exactly() -> None:
    # Lines: 2 x 245 = 490 (10 off -> 480), 1 x 70 = 70. Cart discount 55 spread 480:70.
    cart = price_cart(
        [LineInput(D("2"), D("245"), D("16"), D("10")), LineInput(D("1"), D("70"), D("16"))],
        cart_discount=D("55"),
    )
    shares = [cart.lines[0].discount - D("10"), cart.lines[1].discount]
    assert shares == [D("48.00"), D("7.00")]  # 55 x 480/550 = 48, 55 x 70/550 = 7
    assert cart.grand_total == D("560") - D("10") - D("55") == D("495.00")
    assert sum(line.total for line in cart.lines) == cart.grand_total
    assert cart.discount_total == D("65.00")
    assert cart.discount_percent == D("11.61")  # 65 / 560


def test_rounding_remainder_goes_to_largest_line() -> None:
    # 10 KES off three equal lines cannot split evenly: 3.33 + 3.33 + 3.34
    lines = [LineInput(D("1"), D("100"), D("16")) for _ in range(3)]
    cart = price_cart(lines, cart_discount=D("10"))
    assert sorted(line.discount for line in cart.lines) == [D("3.33"), D("3.33"), D("3.34")]
    assert cart.grand_total == D("290.00")


def test_weighed_goods() -> None:
    # 1.250 kg of loose sugar at 125/kg = 156.25
    cart = price_cart([LineInput(D("1.250"), D("125"), D("16"))])
    assert cart.grand_total == D("156.25")


@pytest.mark.parametrize(
    ("lines", "cart_discount", "message"),
    [
        ([], D("0"), "empty"),
        ([LineInput(D("1"), D("50"), D("16"), D("60"))], D("0"), "more than the line"),
        ([LineInput(D("1"), D("50"), D("16"))], D("51"), "more than the sale"),
        ([LineInput(D("1"), D("50"), D("16"))], D("-1"), "negative"),
    ],
)
def test_invalid_discounts(lines, cart_discount, message) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(PricingError, match=message):
        price_cart(lines, cart_discount)


def test_partial_refunds_never_exceed_what_was_paid() -> None:
    # 3 units paid 100.00 in total (after discount): 33.33 + 33.33 + the remaining 33.34
    first = proportional_refund(D("100.00"), D("3"), D("0"), D("0"), D("1"))
    second = proportional_refund(D("100.00"), D("3"), D("1"), first, D("1"))
    last = proportional_refund(D("100.00"), D("3"), D("2"), first + second, D("1"))
    assert (first, second, last) == (D("33.33"), D("33.33"), D("33.34"))
    assert first + second + last == D("100.00")
    with pytest.raises(PricingError):
        proportional_refund(D("100.00"), D("3"), D("3"), D("100"), D("1"))
