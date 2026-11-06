"""Barcode validation and generation.

Retail barcodes (EAN-8, UPC-A, EAN-13, GTIN-14) carry a check digit, which we verify
so a mistyped code is caught at entry. Products without a manufacturer barcode (loose
goods, in-store packs) get an internal EAN-13 starting with "20"; GS1 reserves the
20-29 prefixes for in-store use, so these never collide with real product codes.
"""

import io
import re

import barcode
from barcode.writer import SVGWriter

GTIN_LENGTHS = (8, 12, 13, 14)
ALNUM_RE = re.compile(r"^[A-Z0-9-]{4,32}$")
INTERNAL_PREFIX = "20"


def gtin_check_digit(body: str) -> int:
    """GS1 mod-10 check digit for the digits before the check digit."""
    total = 0
    for i, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if i % 2 == 0 else 1)
    return (10 - total % 10) % 10


def is_valid_gtin(code: str) -> bool:
    if not code.isdigit() or len(code) not in GTIN_LENGTHS:
        return False
    return gtin_check_digit(code[:-1]) == int(code[-1])


def normalize_barcode(raw: str) -> str:
    """Clean a scanned/typed code and validate it. Raises ValueError with a reason."""
    code = raw.strip().upper().replace(" ", "")
    if code.isdigit():
        if len(code) in GTIN_LENGTHS:
            if not is_valid_gtin(code):
                raise ValueError("check digit is wrong; re-scan or re-type the barcode")
            return code
        if len(code) < 4 or len(code) > 32:
            raise ValueError("must be 4-32 characters")
        return code
    if not ALNUM_RE.match(code):
        raise ValueError("use digits, capital letters or dashes (4-32 characters)")
    return code


def internal_ean13(product_id: int) -> str:
    body = f"{INTERNAL_PREFIX}{product_id:010d}"
    if len(body) != 12:
        raise ValueError("product id too large for an internal EAN-13")
    return body + str(gtin_check_digit(body))


def render_svg(code: str) -> bytes:
    """Render a printable SVG: EAN-13/EAN-8 when valid, otherwise Code 128."""
    if code.isdigit() and len(code) == 13 and is_valid_gtin(code):
        cls = barcode.get_barcode_class("ean13")
        obj = cls(code[:12], writer=SVGWriter())
    elif code.isdigit() and len(code) == 8 and is_valid_gtin(code):
        cls = barcode.get_barcode_class("ean8")
        obj = cls(code[:7], writer=SVGWriter())
    else:
        cls = barcode.get_barcode_class("code128")
        obj = cls(code, writer=SVGWriter())
    buf = io.BytesIO()
    obj.write(buf, options={"module_height": 15.0, "font_size": 10, "text_distance": 5.0})
    return buf.getvalue()
