"""Consistency checks on extracted invoices. Flags warn the reviewer; only a duplicate
invoice blocks approval (checked again on the server at approval time)."""

from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal

TOLERANCE = Decimal("1.00")


@dataclass
class Flag:
    code: str
    severity: str  # info | warning | error
    message: str
    item: int | None = None  # index of the line item, if the flag is about one

    def as_dict(self) -> dict:
        return asdict(self)


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(TOLERANCE, abs(b) * Decimal("0.005"))


def check(
    *,
    supplier_id: int | None,
    invoice_number: str | None,
    invoice_date: date | None,
    subtotal: Decimal | None,
    tax_total: Decimal | None,
    grand_total: Decimal | None,
    prices_include_vat: bool,
    items: list[dict],  # quantity, unit_price, line_total, product_id, previous_cost
    quality_problems: list[str],
    price_alert_percent: Decimal = Decimal("10"),
    today: date | None = None,
) -> list[Flag]:
    today = today or date.today()
    flags: list[Flag] = []
    if supplier_id is None:
        flags.append(Flag("MISSING_SUPPLIER", "warning", "Supplier not recognised: choose it."))
    if not invoice_number:
        flags.append(Flag("MISSING_INVOICE_NUMBER", "warning", "Invoice number not found."))
    if invoice_date is None:
        flags.append(Flag("MISSING_DATE", "warning", "Invoice date not found."))
    elif invoice_date > today + timedelta(days=1):
        flags.append(Flag("DATE_IN_FUTURE", "warning", "The invoice date is in the future."))
    if grand_total is None:
        flags.append(Flag("MISSING_TOTAL", "warning", "Invoice total not found."))
    if not items:
        flags.append(Flag("NO_ITEMS", "error", "No product lines could be read."))
    for p in quality_problems:
        flags.append(Flag("LOW_IMAGE_QUALITY", "warning", p))

    line_sum = Decimal(0)
    for i, it in enumerate(items):
        q, u, t = it.get("quantity"), it.get("unit_price"), it.get("line_total")
        if q is not None and u is not None and t is not None:
            line_sum += t
            if not _close(q * u, t):
                flags.append(
                    Flag("LINE_ARITHMETIC", "warning", f"Line {i + 1}: {q} x {u} is not {t}.", i)
                )
        else:
            flags.append(
                Flag(
                    "LINE_INCOMPLETE",
                    "warning",
                    f"Line {i + 1}: quantity, price or total missing.",
                    i,
                )
            )
        if it.get("product_id") is None:
            flags.append(
                Flag(
                    "UNMATCHED_PRODUCT",
                    "warning",
                    f"Line {i + 1}: choose the product or add it as new.",
                    i,
                )
            )
        prev = it.get("previous_cost")
        cost = it.get("unit_cost_excl_vat")
        if prev and cost is not None and prev > 0:
            pct = (cost - prev) / prev * 100
            if abs(pct) >= price_alert_percent:
                flags.append(
                    Flag(
                        "PRICE_CHANGE",
                        "info",
                        f"Line {i + 1}: cost {prev:.2f} -> {cost:.2f} ({pct:+.1f}%).",
                        i,
                    )
                )

    if items and line_sum:
        target = grand_total if prices_include_vat else subtotal
        if target is not None and not _close(line_sum, target):
            label = "total" if prices_include_vat else "subtotal"
            flags.append(
                Flag(
                    "SUBTOTAL_MISMATCH",
                    "warning",
                    f"Lines add up to {line_sum:.2f} but the {label} says {target:.2f}.",
                )
            )
    if subtotal is not None and tax_total is not None and grand_total is not None:
        if not prices_include_vat and not _close(subtotal + tax_total, grand_total):
            flags.append(
                Flag(
                    "TOTAL_MISMATCH",
                    "warning",
                    f"Subtotal {subtotal:.2f} + VAT {tax_total:.2f} is not the total "
                    f"{grand_total:.2f}.",
                )
            )
        if subtotal > 0 and tax_total > 0:
            base = subtotal if not prices_include_vat else grand_total - tax_total
            if base > 0:
                rate = tax_total / base * 100
                if not any(abs(rate - r) <= 1 for r in (Decimal(16), Decimal(8))):
                    flags.append(
                        Flag(
                            "VAT_RATE_UNUSUAL",
                            "info",
                            f"VAT works out at {rate:.1f}% (expected 16% or 8%); some "
                            "items may be zero-rated.",
                        )
                    )
    return flags
