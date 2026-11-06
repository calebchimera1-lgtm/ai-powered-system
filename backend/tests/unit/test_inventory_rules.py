"""Pure calculations: weighted average cost, margins, barcodes, image checks."""

import io
from decimal import Decimal

import pytest
from PIL import Image

from app.models import Product
from app.services.inventory_service import fmt, weighted_average_cost
from app.services.product_service import margin_percent, stock_status
from app.utils import barcodes, images

D = Decimal


# --- Weighted average cost (hand-computed expectations) -----------------------------


def test_wac_blends_old_and_new_stock() -> None:
    # 10 bags at 200 + 30 bags at 220 = 8600 / 40 = 215
    assert weighted_average_cost(D("10"), D("200"), D("30"), D("220")) == D("215.0000")


def test_wac_uneven_split_rounds_to_four_places() -> None:
    # (7*199.99 + 5*205.50) / 12 = 202.2858...
    assert weighted_average_cost(D("7"), D("199.99"), D("5"), D("205.50")) == D("202.2858")


def test_wac_from_empty_or_negative_stock_is_new_cost() -> None:
    assert weighted_average_cost(D("0"), D("180"), D("12"), D("190")) == D("190.0000")
    assert weighted_average_cost(D("-3"), D("180"), D("12"), D("190")) == D("190.0000")


def test_wac_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError):
        weighted_average_cost(D("5"), D("100"), D("0"), D("120"))


# --- Margin and stock status -------------------------------------------------------


def make(**kw: object) -> Product:
    base = {
        "name": "x",
        "sku": "X",
        "selling_price": D("232.00"),
        "vat_rate": D("16"),
        "avg_cost": D("150"),
        "quantity_on_hand": D("10"),
        "min_stock_level": D("5"),
        "max_stock_level": None,
    }
    base.update(kw)
    return Product(**base)


def test_margin_uses_vat_exclusive_price() -> None:
    # 232 incl. 16% VAT = 200 net; (200 - 150) / 200 = 25%
    assert margin_percent(make()) == D("25.00")
    assert margin_percent(make(vat_rate=D("0"), selling_price=D("200"))) == D("25.00")


def test_margin_unknown_without_cost() -> None:
    assert margin_percent(make(avg_cost=D("0"))) is None


@pytest.mark.parametrize(
    ("qty", "minimum", "maximum", "expected"),
    [
        ("0", "5", None, "out"),
        ("-1", "5", None, "out"),
        ("5", "5", None, "low"),
        ("6", "5", None, "ok"),
        ("3", "0", None, "ok"),
        ("51", "5", "50", "over"),
    ],
)
def test_stock_status(qty: str, minimum: str, maximum: str | None, expected: str) -> None:
    p = make(
        quantity_on_hand=D(qty),
        min_stock_level=D(minimum),
        max_stock_level=D(maximum) if maximum else None,
    )
    assert stock_status(p) == expected


def test_fmt_trims_trailing_zeros() -> None:
    assert fmt(D("12.000")) == "12" and fmt(D("1.250")) == "1.25" and fmt(D("-3.000")) == "-3"


# --- Barcodes --------------------------------------------------------------------


@pytest.mark.parametrize("code", ["5000159407236", "96385074", "036000291452", "4006381333931"])
def test_valid_gtins(code: str) -> None:
    assert barcodes.is_valid_gtin(code)
    assert barcodes.normalize_barcode(f" {code} ") == code


def test_wrong_check_digit_is_rejected() -> None:
    with pytest.raises(ValueError, match="check digit"):
        barcodes.normalize_barcode("5000159407237")


def test_alphanumeric_store_codes_allowed() -> None:
    assert barcodes.normalize_barcode("loose-tom-01") == "LOOSE-TOM-01"
    with pytest.raises(ValueError):
        barcodes.normalize_barcode("bad code!")


def test_internal_ean13_is_valid_and_in_store_range() -> None:
    code = barcodes.internal_ean13(42)
    assert code.startswith("20") and len(code) == 13 and barcodes.is_valid_gtin(code)


def test_render_svg() -> None:
    svg = barcodes.render_svg("5000159407236")
    assert svg.lstrip().startswith(b"<?xml") and b"<svg" in svg
    assert b"<svg" in barcodes.render_svg("LOOSE-TOM-01")  # Code 128 fallback


# --- Images ----------------------------------------------------------------------


def png_bytes(size: tuple[int, int] = (1600, 1200)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size, (3, 152, 85))
    exif = Image.Exif()
    exif[0x010F] = "SecretCam"  # camera make, should be stripped
    img.save(buf, format="PNG", exif=exif)
    return buf.getvalue()


def test_image_is_resized_reencoded_and_stripped() -> None:
    out = images.process_product_image(png_bytes(), max_bytes=5 * 1024 * 1024)
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert max(img.size) == 800
        assert not img.getexif()
    assert b"SecretCam" not in out


@pytest.mark.parametrize(
    ("data", "reason"),
    [
        (b"", "empty"),
        (b"%PDF-1.7 not an image", "Only JPEG"),
        (b"\x89PNG\r\n\x1a\n" + b"garbage" * 10, "could not be read"),
        (b"MZ\x90\x00 fake exe renamed .jpg", "Only JPEG"),
    ],
)
def test_bad_images_rejected(data: bytes, reason: str) -> None:
    with pytest.raises(images.ImageRejected, match=reason):
        images.process_product_image(data, max_bytes=1024 * 1024)


def test_oversized_image_rejected() -> None:
    with pytest.raises(images.ImageRejected, match="larger than"):
        images.process_product_image(png_bytes(), max_bytes=1024)
