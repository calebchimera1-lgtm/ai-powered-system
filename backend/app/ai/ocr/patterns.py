"""Regular expressions and normalisers for Kenyan supplier invoices and receipts."""

import re
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

# OCR often confuses these characters inside numbers. Only applied to tokens that are
# already mostly digits, so words like "SOAP" are never changed.
_DIGIT_FIX = str.maketrans(
    {
        "O": "0",
        "o": "0",
        "D": "0",
        "Q": "0",
        "l": "1",
        "I": "1",
        "|": "1",
        "i": "1",
        "S": "5",
        "s": "5",
        "B": "8",
        "Z": "2",
        "z": "2",
        "g": "9",
    }
)

CURRENCY_RE = re.compile(r"^(?:KES|KSH|KSHS|K\.SH|SH|SHS)\.?", re.I)
MONEY_RE = re.compile(r"^-?(?:\d{1,3}(?:[,\s]\d{3})+|\d+)(?:\.\d{1,2})?$")

KRA_PIN_RE = re.compile(r"\b([AP]\s?\d{9}\s?[A-Z])\b", re.I)
# The same shape, tolerating OCR look-alikes inside the digits (fixed by fix_digits).
LOOSE_PIN_RE = re.compile(r"\b([AP])\s?([0-9OoQDIl|SBZ]{9})\s?([A-Z])\b", re.I)

INVOICE_NO_RE = re.compile(
    r"(?:tax\s+)?(?:invoice|inv|receipt|bill|delivery\s+note|cu\s+invoice)\s*"
    r"(?:no|number|num|#)\.?\s*[:#.\-]?\s*([A-Z0-9][A-Z0-9\-/]{2,24})",
    re.I,
)
LOOSE_NO_RE = re.compile(r"\b(?:no|number|ref)\.?\s*[:#]\s*([A-Z0-9][A-Z0-9\-/]{2,24})", re.I)

MONTHS = {
    m: i
    for i, m in enumerate(
        ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1
    )
}
DATE_NUMERIC_RE = re.compile(r"\b(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})\b")
DATE_TEXT_RE = re.compile(
    r"\b(\d{1,2})(?:st|nd|rd|th)?[\s\-]+([A-Za-z]{3,9})[\s\-,]+(\d{2,4})\b"
    r"|\b([A-Za-z]{3,9})[\s\-]+(\d{1,2})(?:st|nd|rd|th)?,?[\s\-]+(\d{2,4})\b"
)

SUBTOTAL_RE = re.compile(
    r"\b(sub\s*-?\s*total|total\s+excl|net\s+(amount|total)|"
    r"amount\s+excl|taxable\s+(amount|value)|total\s+before)",
    re.I,
)
VAT_RE = re.compile(r"\b(v\.?\s?a\.?\s?t\.?|tax)\b", re.I)
GRAND_RE = re.compile(
    r"\b(grand\s+total|total\s+amount|amount\s+due|total\s+incl|"
    r"total\s+payable|balance\s+due|total\s+due|^\s*total\b)",
    re.I,
)
HEADER_WORDS = re.compile(
    r"\b(qty|quantity|description|item|items|particulars|"
    r"unit|price|rate|amount|total|cost|code)\b",
    re.I,
)

DECIMAL_COMMA_RE = re.compile(r"^(-?\d{1,3}(?:[.,]?\d{3})*|-?\d+),(\d{2})$")


def fix_digits(token: str) -> str:
    """Correct look-alike letters in a token that is mostly digits."""
    digits = sum(ch.isdigit() for ch in token)
    if digits and digits >= (len(token) - token.count(",") - token.count(".")) * 0.6:
        return token.translate(_DIGIT_FIX)
    return token


def parse_money(token: str) -> Decimal | None:
    """'1,250.00' / 'KES1250' / '1 250' / '1250/=' -> Decimal; None if not an amount."""
    t = token.strip().rstrip("/=").rstrip("=").strip()
    t = CURRENCY_RE.sub("", t).strip(":").strip()
    t = fix_digits(t)
    # A comma before exactly two final digits is a misread decimal point ("146,92"):
    # thousands groups always have three digits, so this cannot be a thousands separator.
    t = DECIMAL_COMMA_RE.sub(r"\1.\2", t)
    if not MONEY_RE.match(t):
        return None
    t = t.replace(",", "").replace(" ", "")
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numeric_tokens(text: str) -> list[tuple[int, Decimal]]:
    """(token index, value) for every token that reads as a number."""
    out: list[tuple[int, Decimal]] = []
    for i, token in enumerate(text.split()):
        value = parse_money(token)
        if value is not None:
            out.append((i, value))
    return out


def last_amount(text: str) -> Decimal | None:
    nums = numeric_tokens(text)
    return nums[-1][1] if nums else None


def _year(y: int) -> int:
    return y + 2000 if y < 100 else y


def parse_date(text: str, today: date | None = None) -> date | None:
    """First plausible date in the text (day-first, as used in Kenya)."""
    today = today or date.today()
    candidates: list[date] = []
    for m in DATE_NUMERIC_RE.finditer(text):
        a, b, c = (fix_digits(x) for x in m.groups())
        try:
            a_i, b_i, c_i = int(a), int(b), int(c)
        except ValueError:
            continue
        try:
            if len(a) == 4:  # ISO yyyy-mm-dd
                candidates.append(date(a_i, b_i, c_i))
            else:
                candidates.append(date(_year(c_i), b_i, a_i))  # dd/mm/yyyy
        except ValueError:
            try:  # some printers use mm/dd/yyyy
                candidates.append(date(_year(c_i), a_i, b_i))
            except ValueError:
                continue
    for m in DATE_TEXT_RE.finditer(text):
        if m.group(1):
            day, mon, year = m.group(1), m.group(2), m.group(3)
        else:
            mon, day, year = m.group(4), m.group(5), m.group(6)
        month = MONTHS.get(mon[:3].lower())
        if not month:
            continue
        try:
            candidates.append(date(_year(int(year)), month, int(day)))
        except ValueError:
            continue
    for d in candidates:
        if today - timedelta(days=400) <= d <= today + timedelta(days=31):
            return d
    return None


def normalise_pin(raw: str) -> str:
    return re.sub(r"\s", "", raw).upper()
