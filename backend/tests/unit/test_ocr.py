"""OCR pipeline stages, each tested on its own, plus an accuracy regression check."""

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.ai.ocr import matcher, patterns, preprocessing, validator
from app.ai.ocr.layout import group_lines
from app.ai.ocr.parser import extract
from app.ai.ocr.types import Line, Word

D = Decimal
FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def lines_from(rows: list[str]) -> list[Line]:
    """Build OCR lines as if read from a clean page (each word on its own position)."""
    out = []
    for y, row in enumerate(rows):
        x, words = 50, []
        for tok in row.split():
            words.append(Word(tok, 95.0, x, 40 + y * 50, 20 * len(tok), 30))
            x += 20 * len(tok) + 18
        out.append(Line(words))
    return out


# --- Patterns ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("token", "value"),
    [
        ("1,250.00", D("1250.00")),
        ("KES1,250", D("1250")),
        ("Ksh250.50", D("250.50")),
        ("1250/=", D("1250")),
        ("146,92", D("146.92")),
        ("12O.5O", D("120.50")),
        ("2,94O.00", D("2940.00")),
        ("-15.00", D("-15.00")),
    ],
)
def test_parse_money(token: str, value: Decimal) -> None:
    assert patterns.parse_money(token) == value


@pytest.mark.parametrize("token", ["SOAP", "2KG", "INV-001", "12/10/2026", "abc"])
def test_parse_money_rejects_words(token: str) -> None:
    assert patterns.parse_money(token) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Date: 31/10/2026", date(2026, 10, 31)),
        ("Date 2026-10-05", date(2026, 10, 5)),
        ("Invoice date: 5 Nov 2026", date(2026, 11, 5)),
        ("29.10.2026", date(2026, 10, 29)),
        ("Date: 18-Oct-2026", date(2026, 10, 18)),
        ("Nov 3, 2026", date(2026, 11, 3)),
    ],
)
def test_parse_date_day_first(text: str, expected: date) -> None:
    assert patterns.parse_date(text, today=date(2026, 11, 7)) == expected


def test_parse_date_ignores_implausible_years() -> None:
    assert patterns.parse_date("Est. 01/01/1998", today=date(2026, 11, 7)) is None


# --- Parser ----------------------------------------------------------------------------


CLASSIC = [
    "NAIROBI WHOLESALE DISTRIBUTORS (DEMO)",
    "Enterprise Rd, Industrial Area, Kenya",
    "PIN: PO51111111A",
    "TAX INVOICE",
    "Invoice No: INV-2026-00412 Date: 31/10/2026",
    "Bill To: Smart Supermarket (Demo)",
    "Customer PIN: P051999999Z",
    "Description Qty Unit Price Amount",
    "WHT SUGAR 2KG 24 201.50 4,836.00",
    "MAIZE FLR 2 KG 30 145.12 4,353.60",
    "VEG COOKING OIL 1LT",
    "(CARTON OF 12) 12 290.00 3,480.00",
    "Subtotal 12,669.60",
    "VAT 16% 1,330.56",
    "TOTAL KES 14,000.16",
]


def test_parser_classic_invoice() -> None:
    ext = extract(lines_from(CLASSIC))
    assert ext.invoice_number.value == "INV-2026-00412"
    assert ext.invoice_date.value == date(2026, 10, 31)
    assert ext.kra_pin.value == "P051111111A"  # O read as 0, buyer PIN ignored
    assert (ext.subtotal.value, ext.tax_total.value, ext.grand_total.value) == (
        D("12669.60"),
        D("1330.56"),
        D("14000.16"),
    )
    assert [(i.description, i.quantity, i.unit_price, i.line_total) for i in ext.items] == [
        ("WHT SUGAR 2KG", D(24), D("201.50"), D("4836.00")),
        ("MAIZE FLR 2 KG", D(30), D("145.12"), D("4353.60")),
        ("VEG COOKING OIL 1LT (CARTON OF 12)", D(12), D("290.00"), D("3480.00")),
    ]
    assert all(i.arithmetic_ok for i in ext.items)
    assert ext.prices_include_vat is False


def test_parser_quantity_first_vat_inclusive() -> None:
    ext = extract(
        lines_from(
            [
                "RIFT VALLEY DAIRY CO-OP (DEMO)",
                "INVOICE",
                "Invoice Number: SI/4650 Date: 22 Oct 2026",
                "Qty Description Rate Amount",
                "24 MILK FRESH 500 ML 55.68 1,336.32",
                "20 BREAD WHT 400 G 60.32 1,206.40",
                "Total (incl. VAT) 2,542.72",
                "VAT included 0.00",
            ]
        )
    )
    assert [(i.description, i.quantity, i.unit_price) for i in ext.items] == [
        ("MILK FRESH 500 ML", D(24), D("55.68")),
        ("BREAD WHT 400 G", D(20), D("60.32")),
    ]


def test_parser_receipt_qty_x_price() -> None:
    ext = extract(
        lines_from(
            [
                "COAST HOUSEHOLD SUPPLIES (DEMO)",
                "CASH SALE RECEIPT",
                "Receipt No: 448812",
                "Date: 03/11/2026",
                "-------------------",
                "BAR SOAP 800G",
                "10 x 161.24 1,612.40",
                "WATER BTL 1 LTR",
                "24 x 44.08 1,057.92",
                "-------------------",
                "TOTAL KES 2,670.32",
                "VAT 16% (incl) 368.32",
            ]
        )
    )
    assert [(i.description, i.quantity, i.line_total) for i in ext.items] == [
        ("BAR SOAP 800G", D(10), D("1612.40")),
        ("WATER BTL 1 LTR", D(24), D("1057.92")),
    ]
    assert ext.prices_include_vat is True
    assert ext.subtotal.value == D("2302.00")  # derived: total - VAT


def test_parser_assigns_columns_by_arithmetic_when_order_differs() -> None:
    ext = extract(
        lines_from(["Item Price Qty Total", "BAR SOAP 800G 139.00 12 1,668.00", "Total 1,668.00"])
    )
    [item] = ext.items
    assert (item.quantity, item.unit_price, item.arithmetic_ok) == (D(12), D("139.00"), True)


def test_layout_groups_words_into_lines() -> None:
    words = [
        Word("TOTAL", 90, 900, 502, 80, 30),
        Word("SUBTOTAL", 90, 100, 400, 120, 30),
        Word("1,000", 90, 1400, 404, 70, 30),
        Word("1,160", 90, 1400, 499, 70, 30),
    ]
    assert [ln.text for ln in group_lines(words)] == ["SUBTOTAL 1,000", "TOTAL 1,160"]


# --- Matcher ---------------------------------------------------------------------------

CATALOG = [
    matcher.ProductRef(1, "White Sugar 2kg", "SKU-1", "2000000000015"),
    matcher.ProductRef(2, "White Sugar 1kg", "SKU-2", None),
    matcher.ProductRef(3, "Maize Flour 2kg", "SKU-3", None),
    matcher.ProductRef(4, "Bottled Water 1L", "SKU-4", None),
]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("WHT SUGAR 2KG", 1),
        ("SUGAR WHITE 2 KG", 1),
        ("SUGAR WHITE 1 KG", 2),
        ("MAIZE FLR 2 KG", 3),
        ("WATER BTL 1 LTR", 4),
    ],
)
def test_product_matching_handles_abbreviations_and_sizes(text: str, expected: int) -> None:
    m = matcher.match_product(text, None, text, CATALOG)
    assert m.product_id == expected


def test_pack_size_must_agree() -> None:
    assert matcher.score_product("SUGAR 5KG", "White Sugar 2kg") == 0.0


def test_codes_and_aliases_win() -> None:
    assert (
        matcher.match_product("ANYTHING", None, "2000000000015 ANYTHING 2 50.00", CATALOG).method
        == "CODE"
    )
    assert (
        matcher.match_product(
            "XYZ", "S1-004", "S1-004 XYZ", CATALOG, supplier_codes={"S1-004": 3}
        ).product_id
        == 3
    )
    m = matcher.match_product(
        "Mumias white 2", None, "x", CATALOG, aliases={matcher.normalise("Mumias white 2"): 1}
    )
    assert (m.product_id, m.method) == (1, "ALIAS")


def test_unknown_product_is_not_forced() -> None:
    m = matcher.match_product("TOOTHPASTE 100ML", None, "TOOTHPASTE 100ML", CATALOG)
    assert m.product_id is None and m.method == "NONE"


def test_supplier_matching_by_pin_then_name() -> None:
    sups = [
        matcher.SupplierRef(1, "Nairobi Wholesale Distributors (Demo)", "P051111111A"),
        matcher.SupplierRef(2, "Coast Household Supplies (Demo)", None),
    ]
    assert matcher.match_supplier("P051111111A", None, [], sups)[:2] == (1, 100.0)
    sid, score, method = matcher.match_supplier(None, "COAST HOUSEHOLD SUPPLIES", [], sups)
    assert (sid, method) == (2, "NAME") and score >= 85
    assert matcher.match_supplier(None, "Unknown Traders", [], sups)[0] is None


# --- Validator ---------------------------------------------------------------------------


def test_validator_flags_arithmetic_and_totals() -> None:
    flags = validator.check(
        supplier_id=1,
        invoice_number="X1",
        invoice_date=date(2026, 11, 1),
        subtotal=D("100"),
        tax_total=D("16"),
        grand_total=D("120"),
        prices_include_vat=False,
        items=[
            {
                "quantity": D(2),
                "unit_price": D(40),
                "line_total": D(90),
                "product_id": 1,
                "previous_cost": D(30),
                "unit_cost_excl_vat": D(40),
            }
        ],
        quality_problems=[],
        today=date(2026, 11, 7),
    )
    codes = {f.code for f in flags}
    assert {"LINE_ARITHMETIC", "SUBTOTAL_MISMATCH", "TOTAL_MISMATCH", "PRICE_CHANGE"} <= codes


def test_validator_quiet_on_consistent_invoice() -> None:
    flags = validator.check(
        supplier_id=1,
        invoice_number="X1",
        invoice_date=date(2026, 11, 1),
        subtotal=D("100"),
        tax_total=D("16"),
        grand_total=D("116"),
        prices_include_vat=False,
        items=[
            {
                "quantity": D(2),
                "unit_price": D(50),
                "line_total": D(100),
                "product_id": 1,
                "previous_cost": D(50),
                "unit_cost_excl_vat": D(50),
            }
        ],
        quality_problems=[],
        today=date(2026, 11, 7),
    )
    assert flags == []


# --- Preprocessing --------------------------------------------------------------------------


def text_page(color: int = 20) -> np.ndarray:
    im = Image.new("L", (1600, 1000), 255)
    d = ImageDraw.Draw(im)
    f = ImageFont.truetype(FONT, 34)
    for i in range(12):
        d.text(
            (60, 50 + i * 75), f"WHITE SUGAR 2KG   {i + 1}   245.00   2,940.00", font=f, fill=color
        )
    return np.asarray(im)


@pytest.mark.parametrize("angle", [-6.0, -2.0, 0.0, 1.5, 4.0])
def test_skew_is_measured_in_both_directions(angle: float) -> None:
    rotated = preprocessing.rotate(text_page(), angle)
    assert preprocessing.estimate_skew(rotated) == pytest.approx(-angle, abs=0.4)


def test_paper_outline_is_found_and_flattened() -> None:
    page = cv2.cvtColor(text_page(), cv2.COLOR_GRAY2BGR)
    desk = np.full((1600, 2200, 3), 70, np.uint8)
    src = np.float32([[0, 0], [1600, 0], [1600, 1000], [0, 1000]])
    dst = np.float32([[300, 250], [1850, 330], [1800, 1350], [250, 1250]])
    m = cv2.getPerspectiveTransform(src, dst)
    photo = cv2.warpPerspective(
        page, m, (2200, 1600), dst=desk.copy(), borderMode=cv2.BORDER_TRANSPARENT
    )
    corners = preprocessing.find_document(photo)
    assert corners is not None
    assert np.abs(corners - dst).max() < 25


def test_quality_warnings() -> None:
    assert preprocessing.measure(text_page()).problems == []
    assert "over-exposed" in preprocessing.measure(text_page(200)).problems[0]
    assert "blurry" in preprocessing.measure(cv2.GaussianBlur(text_page(), (0, 0), 4)).problems[0]
    assert "too dark" in preprocessing.measure((text_page() * 0.2).astype(np.uint8)).problems[0]


# --- End-to-end accuracy regression ----------------------------------------------------------


def test_ocr_accuracy_on_synthetic_invoices(tmp_path: Path) -> None:
    """Guards against regressions: 10 synthetic invoices (all layouts, clean/scan/phone).
    The full evaluation lives in scripts/evaluate_ocr.py and docs/ai/ocr-evaluation.md."""
    from scripts.evaluate_ocr import evaluate_one, summarise
    from scripts.generate_synthetic_invoices import generate

    files = generate(tmp_path, 10, seed=99, today=date.today())
    rows = [evaluate_one(f) for f in files]
    s = summarise(rows)
    assert s["item_f1"] >= 0.9, s
    assert s["fields"]["grand_total"] >= 0.9, s
    assert s["fields"]["invoice_date"] >= 0.9, s
    assert s["cer"] <= 0.05, s
    assert json.dumps(s)  # serialisable for the report
