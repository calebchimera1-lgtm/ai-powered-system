"""Turn OCR lines into invoice fields and line items.

Rule-based and geometry-aware (explainable, CPU-cheap, good on regular supplier layouts):

* Header fields come from keyword anchors ("Invoice No", "Date", "PIN") plus patterns.
* The item table starts after a header row (a line with words like Qty/Description/
  Price/Amount) and ends at the first totals line.
* An item line is text followed by numbers. Which number is the quantity, the unit price
  and the line total is decided by the column positions under the header row when there
  is one, and checked with arithmetic (quantity x price = total), trying every order.
* "2 x 245.00" style receipt lines are recognised, and description lines that wrap onto
  the next line are joined.

Every field carries a 0..1 confidence: OCR word confidence, lowered when the arithmetic
does not agree, so the review screen can highlight doubtful values.
"""

import itertools
import re
from decimal import ROUND_HALF_UP, Decimal

from app.ai.ocr import patterns as pt
from app.ai.ocr.types import ExtractedItem, Extraction, Field, Line

CENT = Decimal("0.01")
NOT_SUPPLIER = re.compile(
    r"(invoice|receipt|tel|phone|mobile|p\.?\s?o\.?\s?box|pin|vat|date|email|@|www\.|"
    r"bill\s+to|customer|buyer|page|no\.|cash\s+sale|delivery|road|street|avenue|nairobi|"
    r"mombasa|kisumu|nakuru|kenya)",
    re.I,
)
BUYER_CONTEXT = re.compile(r"(customer|buyer|bill\s*to|sold\s*to|client|ship\s*to)", re.I)
TOTALS_STOP = re.compile(
    r"\b(sub\s*-?\s*total|total|vat|tax|amount\s+due|balance|"
    r"discount|paid|change|cash|tendered)\b",
    re.I,
)
SEPARATOR_RE = re.compile(r"^\s*[-=_*.~]{5,}\s*$")
QTY_X_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX@*]\s*([\d,]+(?:\.\d{1,2})?)")
CODE_RE = re.compile(r"^[A-Z]{0,4}\d?[-/]?[A-Z0-9]*\d[A-Z0-9\-/]*$")


def _conf(line: Line) -> float:
    return round(line.conf / 100, 3)


def _close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal("1.00"), b * Decimal("0.005"))


# --- Header ---------------------------------------------------------------------


def find_invoice_number(lines: list[Line]) -> Field:
    for regex in (pt.INVOICE_NO_RE, pt.LOOSE_NO_RE):
        for ln in lines[:25]:
            m = regex.search(ln.text)
            if m:
                value = m.group(1).strip(".:-").upper()
                if len(value) >= 3 and any(c.isdigit() for c in value):
                    return Field(value, _conf(ln), ln.text)
    return Field(None, 0.0)


def find_date(lines: list[Line]) -> Field:
    labelled = [ln for ln in lines if re.search(r"\bdate\b", ln.text, re.I)]
    for ln in labelled + lines:
        d = pt.parse_date(ln.text)
        if d:
            return Field(d, _conf(ln) * (1.0 if ln in labelled else 0.8), ln.text)
    return Field(None, 0.0)


def find_pin(lines: list[Line]) -> Field:
    """The supplier's KRA PIN: the first PIN not on a 'customer/buyer' line. Letters that
    OCR confuses with digits (O for 0, I for 1...) are corrected inside the 9 digits."""
    for ln in lines[:30]:
        if BUYER_CONTEXT.search(ln.text):
            continue
        m = pt.LOOSE_PIN_RE.search(ln.text)
        if m:
            pin = m.group(1).upper() + pt.fix_digits(m.group(2)).upper() + m.group(3).upper()
            if pt.KRA_PIN_RE.fullmatch(pin):
                return Field(pin, _conf(ln), ln.text)
    return Field(None, 0.0)


def find_supplier_name(lines: list[Line]) -> tuple[Field, list[str]]:
    """Best guess at the business name: an early, mostly-letter line that is not an
    address/contact line. Matching against registered suppliers happens later."""
    header = [ln.text for ln in lines[:8]]
    for ln in lines[:8]:
        text = ln.text.strip()
        letters = sum(c.isalpha() for c in text)
        if len(text) < 4 or letters < len(text) * 0.6 or NOT_SUPPLIER.search(text):
            continue
        return Field(text, _conf(ln) * 0.8, text), header
    return Field(None, 0.0), header


# --- Totals ------------------------------------------------------------------------


def find_totals(lines: list[Line]) -> tuple[Field, Field, Field, int | None, Decimal | None]:
    """(subtotal, VAT, grand total, index of the first totals line, VAT rate if printed)."""
    subtotal = tax = grand = Field(None, 0.0)
    first = None
    rate: Decimal | None = None
    for i, ln in enumerate(lines):
        text = ln.text
        amount = pt.last_amount(text)
        if amount is None:
            continue
        if pt.SUBTOTAL_RE.search(text):
            subtotal = Field(amount, _conf(ln), text)
        elif pt.VAT_RE.search(text) and not pt.GRAND_RE.search(text) and "PIN" not in text.upper():
            tax = Field(amount, _conf(ln), text)
            m = re.search(r"(\d{1,2}(?:\.\d+)?)\s*%", text)
            if m:
                rate = Decimal(m.group(1))
        elif pt.GRAND_RE.search(text):
            grand = Field(amount, _conf(ln), text)  # the last "total" line wins
        else:
            continue
        first = i if first is None else min(first, i)
    return subtotal, tax, grand, first, rate


# --- Items -------------------------------------------------------------------------


def _header_row(lines: list[Line], stop: int) -> tuple[int | None, dict[str, float]]:
    """Index of the table header row and the x-centres of its numeric columns."""
    for i, ln in enumerate(lines[:stop]):
        found = pt.HEADER_WORDS.findall(ln.text)
        if len({f.lower() for f in found}) >= 2 and len(pt.numeric_tokens(ln.text)) == 0:
            cols: dict[str, float] = {}
            for w in ln.words:
                t = w.text.lower().strip(".:")
                if t in ("qty", "quantity", "qnty"):
                    cols["qty"] = w.cx
                elif t in ("price", "rate", "unit", "cost") and "price" not in cols:
                    cols["price"] = w.cx
                elif t in ("amount", "total", "value", "amt"):
                    cols["total"] = w.cx
                elif t in ("vat", "tax", "vat%"):
                    cols["vat"] = w.cx
            return i, cols
    return None, {}


def _assign(values: list[Decimal]) -> tuple[Decimal | None, Decimal | None, Decimal | None, bool]:
    """Pick (qty, unit, total) from trailing numbers using arithmetic."""
    vals = values[-4:]
    best = None
    for qi, ui, ti in itertools.permutations(range(len(vals)), 3):
        q, u, t = vals[qi], vals[ui], vals[ti]
        if q <= 0 or q > 10000 or ti != len(vals) - 1 and ti < max(qi, ui):
            continue
        if _close(q * u, t):
            # Prefer quantities printed without decimals ("12", not "139.00"), then
            # whole-number ones, then the conventional left-to-right order.
            whole = 3 if q.as_tuple().exponent == 0 else 2 if q == q.to_integral_value() else 0
            score = whole * 2 + (qi < ui < ti) + (ti == len(vals) - 1)
            if best is None or score > best[0]:
                best = (score, q, u, t)
    if best:
        return best[1], best[2], best[3], True
    if len(vals) >= 3:
        q, u, t = vals[-3], vals[-2], vals[-1]
        return q, u, t, False
    if len(vals) == 2:
        a, b = vals
        if a == a.to_integral_value() and 0 < a <= 999 and b > a:
            unit = (b / a).quantize(CENT, ROUND_HALF_UP)
            return a, unit, b, False
        return Decimal(1), b, b, False
    return None, None, None, False


def _by_columns(line: Line, cols: dict[str, float]) -> dict[str, Decimal]:
    """Assign numeric words to the nearest numeric column of the header row."""
    out: dict[str, Decimal] = {}
    for w in line.words:
        value = pt.parse_money(w.text)
        if value is None:
            continue
        name = min(cols, key=lambda k: abs(cols[k] - w.cx))
        if abs(cols[name] - w.cx) < 260:  # pixels at ~300 dpi
            out[name] = value
    return out


def parse_items(
    lines: list[Line], start: int, stop: int, cols: dict[str, float]
) -> list[ExtractedItem]:
    items: list[ExtractedItem] = []
    pending_desc: list[str] = []
    for ln in lines[start:stop]:
        text = ln.text.strip()
        if not text or TOTALS_STOP.match(text):
            continue
        tokens = text.split()
        nums = pt.numeric_tokens(text)
        num_at = {idx for idx, _ in nums}
        qx = QTY_X_RE.search(text)

        # Split the line into: leading numbers (a quantity column printed first),
        # the description, and trailing numbers (prices). Numbers inside the description,
        # such as "500" in "MILK 500 ML", stay part of the description.
        lead = 0
        while lead < len(tokens) and lead in num_at:
            lead += 1
        end = len(tokens)
        while end > lead and (end - 1) in num_at:
            end -= 1
        value = {idx: v for idx, v in nums}
        leading = [value[i] for i in range(lead)]
        trailing = [value[i] for i in range(end, len(tokens))]
        desc_tokens = tokens[lead:end]

        if not trailing and not qx:
            # A text-only line (or one ending in a word): a description that wraps, or the
            # name line of a receipt item whose numbers are on the next line.
            if sum(c.isalpha() for c in text) >= 3:
                pending_desc.append(text)
            continue

        # Treat a leading code like "S1-004" as the item code, not part of the name.
        code = None
        first = desc_tokens[0].replace("$", "S") if desc_tokens else ""  # OCR: S read as $
        if desc_tokens and CODE_RE.match(first) and len(desc_tokens) > 1:
            code = first
            desc_tokens = desc_tokens[1:]
        if qx:  # "20 x 52.16  1,043.20": the description is on the line(s) above
            desc_tokens = []
        description = " ".join(pending_desc + desc_tokens).strip()
        pending_desc = []
        trailing = leading + trailing if not qx else trailing

        qty = unit = total = None
        ok = False
        if qx:
            qty = pt.parse_money(qx.group(1))
            unit = pt.parse_money(qx.group(2))
            total = trailing[-1] if trailing else None
            if qty and unit and total is not None:
                ok = _close(qty * unit, total)
            if description == "" and items and items[-1].quantity is None:
                description = items.pop().description
        elif cols and {"qty", "total"} <= cols.keys():
            got = _by_columns(ln, cols)
            qty, unit, total = got.get("qty"), got.get("price"), got.get("total")
            if qty and unit and total is not None:
                ok = _close(qty * unit, total)
            if not ok and len(trailing) >= 2:
                qty, unit, total, ok = _assign(trailing)
        elif len(trailing) >= 2:
            qty, unit, total, ok = _assign(trailing)
        elif len(trailing) == 1 and description:
            # Only one amount (e.g. "Delivery charge 500"): read as 1 x amount, flagged for
            # review by the low confidence and failed arithmetic check.
            qty, unit, total, ok = Decimal(1), trailing[0], trailing[0], False
        else:
            continue

        if not description or sum(c.isalpha() for c in description) < 2:
            continue
        items.append(
            ExtractedItem(
                raw_text=text,
                description=description,
                quantity=qty,
                unit_price=unit,
                line_total=total,
                item_code=code,
                confidence=round(_conf(ln) * (1.0 if ok else 0.6), 3),
                arithmetic_ok=ok,
            )
        )
    # Items that never got a quantity: assume 1 x total.
    for it in items:
        if it.quantity is None and it.line_total is not None:
            it.quantity, it.unit_price = Decimal(1), it.line_total
    return items


def extract(lines: list[Line]) -> Extraction:
    subtotal, tax, grand, totals_at, rate = find_totals(lines)
    stop = totals_at if totals_at is not None else len(lines)
    header_idx, cols = _header_row(lines, stop)
    if header_idx is not None:
        start = header_idx + 1
    else:
        # No column headings (typical of till receipts): items start after the first
        # separator line, or after the first few header lines.
        sep = next((i for i, ln in enumerate(lines[:stop]) if SEPARATOR_RE.match(ln.text)), None)
        start = sep + 1 if sep is not None and sep < 15 else min(6, stop)
    items = parse_items(lines, start, stop, cols)
    supplier, header_lines = find_supplier_name(lines)

    # Are the line prices VAT-inclusive? If the items add up to the grand total and VAT
    # is shown separately as a part of it, they include VAT; if they add up to the
    # subtotal, they exclude it.
    item_sum = sum((i.line_total or Decimal(0) for i in items), Decimal(0))
    includes = False
    if grand.value is not None and _close(item_sum, grand.value):
        if subtotal.value is None or not _close(item_sum, subtotal.value):
            includes = tax.value is not None and tax.value > 0
    if rate is None and tax.value and subtotal.value and subtotal.value > 0:
        implied = (tax.value / subtotal.value * 100).quantize(Decimal("0.1"))
        if abs(implied - 16) <= Decimal("0.6"):
            rate = Decimal(16)
        elif abs(implied - 8) <= Decimal("0.6"):
            rate = Decimal(8)

    # Invoices with VAT-inclusive prices often print no subtotal: derive it.
    if subtotal.value is None and includes and grand.value is not None and tax.value is not None:
        subtotal = Field(
            grand.value - tax.value,
            min(grand.confidence, tax.confidence) * 0.9,
            "derived: total - VAT",
        )

    return Extraction(
        supplier_name=supplier,
        kra_pin=find_pin(lines),
        invoice_number=find_invoice_number(lines),
        invoice_date=find_date(lines),
        subtotal=subtotal,
        tax_total=tax,
        grand_total=grand,
        items=items,
        vat_rate=rate,
        prices_include_vat=includes,
        header_lines=header_lines,
    )
