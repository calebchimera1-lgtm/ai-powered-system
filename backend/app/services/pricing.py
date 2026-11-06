"""Till arithmetic: line totals, discounts and VAT on VAT-inclusive prices.

Kenyan shelf prices include VAT, so VAT is *extracted*: tax = gross x rate / (100 + rate).
A whole-cart discount is spread across lines in proportion to their value, so each line's
VAT and revenue stay correct for reports. Rounding differences go to the largest line, so
the line amounts always add up exactly to the receipt total.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

CENT = Decimal("0.01")
ZERO = Decimal("0")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def vat_included(gross: Decimal, rate: Decimal) -> Decimal:
    """VAT contained in a VAT-inclusive amount."""
    if rate <= 0:
        return ZERO.quantize(CENT)
    return money(gross * rate / (Decimal(100) + rate))


def vat_on_top(net: Decimal, rate: Decimal) -> Decimal:
    """VAT added to a VAT-exclusive amount (supplier invoices)."""
    return money(net * rate / Decimal(100))


@dataclass(frozen=True)
class LineInput:
    quantity: Decimal
    unit_price: Decimal  # VAT-inclusive
    vat_rate: Decimal
    line_discount: Decimal = ZERO  # KES off this line


@dataclass(frozen=True)
class LineResult:
    gross: Decimal  # quantity x unit price
    discount: Decimal  # line discount + share of the cart discount
    total: Decimal  # gross - discount (what the customer pays for the line)
    tax: Decimal  # VAT contained in total
    net: Decimal  # total - tax (revenue excl. VAT)


@dataclass(frozen=True)
class CartResult:
    lines: list[LineResult]
    subtotal: Decimal
    discount_total: Decimal
    tax_total: Decimal
    grand_total: Decimal

    @property
    def discount_percent(self) -> Decimal:
        if self.subtotal == 0:
            return ZERO
        return (self.discount_total / self.subtotal * 100).quantize(CENT, ROUND_HALF_UP)


class PricingError(ValueError):
    pass


def price_cart(lines: list[LineInput], cart_discount: Decimal = ZERO) -> CartResult:
    if not lines:
        raise PricingError("The cart is empty")
    cart_discount = money(cart_discount)
    if cart_discount < 0:
        raise PricingError("A discount cannot be negative")

    grosses: list[Decimal] = []
    after_line: list[Decimal] = []
    for i, line in enumerate(lines, 1):
        gross = money(line.quantity * line.unit_price)
        disc = money(line.line_discount)
        if disc < 0:
            raise PricingError(f"Line {i}: a discount cannot be negative")
        if disc > gross:
            raise PricingError(f"Line {i}: the discount is more than the line value")
        grosses.append(gross)
        after_line.append(gross - disc)

    base = sum(after_line, ZERO)
    if cart_discount > base:
        raise PricingError("The discount is more than the sale value")

    # Spread the cart discount proportionally; fix rounding on the largest line.
    shares = [money(cart_discount * value / base) if base > 0 else ZERO for value in after_line]
    remainder = cart_discount - sum(shares, ZERO)
    if remainder and base > 0:
        largest = max(range(len(after_line)), key=lambda i: after_line[i])
        shares[largest] += remainder

    results = []
    for line, gross, value, share in zip(lines, grosses, after_line, shares, strict=True):
        total = value - share
        tax = vat_included(total, line.vat_rate)
        results.append(
            LineResult(
                gross=gross,
                discount=money(line.line_discount) + share,
                total=total,
                tax=tax,
                net=total - tax,
            )
        )
    subtotal = sum(grosses, ZERO)
    grand = sum((r.total for r in results), ZERO)
    return CartResult(
        lines=results,
        subtotal=subtotal,
        discount_total=subtotal - grand,
        tax_total=sum((r.tax for r in results), ZERO),
        grand_total=grand,
    )


def proportional_refund(
    line_total: Decimal,
    quantity: Decimal,
    returned_before: Decimal,
    refunded_before: Decimal,
    returning: Decimal,
) -> Decimal:
    """Refund for returning `returning` units of a sale line.

    Uses the discounted line price. Returning the last units refunds exactly what is left,
    so a line refunded in several parts never refunds more (or less) than was paid.
    """
    remaining_qty = quantity - returned_before
    if returning <= 0 or returning > remaining_qty:
        raise PricingError("Cannot return more than was sold")
    if returning == remaining_qty:
        return line_total - refunded_before
    return money(line_total * returning / quantity)
