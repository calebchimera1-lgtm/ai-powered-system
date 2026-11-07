"""Generate SYNTHETIC supplier invoices with exact ground truth, for testing and evaluating
the OCR pipeline honestly (every value the pipeline should find is known).

    python -m scripts.generate_synthetic_invoices --out ../sample-data/invoices --count 12
    python -m scripts.generate_synthetic_invoices --out /tmp/ocr-eval --count 60

Five layouts (classic A4, item-code table, thermal receipt, VAT-inclusive with quantity
first, and a text-layer PDF) x three conditions:

* clean  - a perfect digital render
* scan   - slight tilt, noise and JPEG compression, like a flatbed scan
* phone  - the paper photographed on a desk: perspective, tilt, uneven light, blur,
           noise and stronger compression

All suppliers, numbers and prices are invented. Files are deterministic for a seed.
Each image comes with <name>.truth.json.
"""

import argparse
import io
import json
import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FONTS = {
    "sans": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "sans_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "lib": "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    "lib_bold": "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "mono": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "mono_bold": "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
}

SUPPLIERS = [
    ("Nairobi Wholesale Distributors (Demo)", "P051111111A", "Enterprise Rd, Industrial Area"),
    ("Rift Valley Dairy Co-op (Demo)", "P052222222B", "Kenyatta Ave, Nakuru"),
    ("Coast Household Supplies (Demo)", "P053333333C", "Moi Ave, Mombasa"),
]
BUYER = ("Smart Supermarket (Demo)", "P051999999Z")

# catalogue name -> (supplier index, base cost excl. VAT, VAT rate, supplier-style names)
PRODUCTS = {
    "White Sugar 2kg": (0, 198, 16, ["WHT SUGAR 2KG", "SUGAR WHITE 2 KG", "WHITE SUGAR 2KG"]),
    "Pishori Rice 2kg": (0, 305, 16, ["PISHORI RICE 2KG", "RICE PISHORI 2 KG", "PISH RICE 2KG"]),
    "Vegetable Cooking Oil 1L": (
        0,
        281,
        16,
        ["VEG COOKING OIL 1LT", "COOKING OIL VEG 1 LTR", "VEGETABLE OIL 1L"],
    ),
    "Maize Flour 2kg": (0, 142, 0, ["MAIZE FLOUR 2KG", "MAIZE FLR 2 KG", "FLOUR MAIZE 2KG"]),
    "Loose Sugar (per kg)": (0, 98, 16, ["SUGAR LOOSE PER KG", "LOOSE SUGAR KG"]),
    "Fresh Milk 500ml": (1, 48, 0, ["FRESH MILK 500ML", "MILK FRESH 500 ML", "MILK 500ML FRESH"]),
    "White Bread 400g": (1, 52, 0, ["WHITE BREAD 400G", "BREAD WHT 400 G", "BREAD WHITE 400GM"]),
    "Natural Yoghurt 500ml": (1, 112, 16, ["NATURAL YOGHURT 500ML", "YOGHURT NAT 500 ML"]),
    "Bar Soap 800g": (2, 139, 16, ["BAR SOAP 800G", "SOAP BAR 800 GM", "BAR SOAP 800 G"]),
    "Bottled Water 1L": (2, 38, 16, ["BOTTLED WATER 1L", "WATER BTL 1 LTR", "DRINKING WATER 1L"]),
}
LAYOUTS = ["classic", "coded", "receipt", "inclusive", "pdf"]
CONDITIONS = ["clean", "scan", "phone"]

D = Decimal
CENT = D("0.01")


def money(v: D) -> D:
    return v.quantize(CENT, ROUND_HALF_UP)


def fmt(v: D) -> str:
    return f"{v:,.2f}"


@dataclass
class Doc:
    supplier: tuple[str, str, str]
    number: str
    when: date
    date_text: str
    items: list[dict]
    subtotal: D
    vat: D
    total: D
    inclusive: bool


def build_doc(rng: random.Random, layout: str, today: date) -> Doc:
    sup_idx = rng.randrange(len(SUPPLIERS))
    names = [n for n, v in PRODUCTS.items() if v[0] == sup_idx]
    chosen = rng.sample(names, k=min(len(names), rng.randint(2, len(names))))
    inclusive = layout in ("receipt", "inclusive")
    items = []
    for name in chosen:
        _, cost, rate, styles = PRODUCTS[name]
        unit = D(cost) * D(str(round(rng.uniform(0.97, 1.06), 3)))
        if inclusive:
            unit = unit * (1 + D(rate) / 100)
        unit = money(unit)
        qty = (
            D(rng.choice([6, 10, 12, 20, 24, 30, 36, 48]))
            if "per kg" not in name
            else D(rng.choice([25, 50]))
        )
        items.append(
            {
                "product": name,
                "description": rng.choice(styles),
                "quantity": qty,
                "unit_price": unit,
                "line_total": money(qty * unit),
                "vat_rate": D(rate),
            }
        )
    lines_sum = sum((i["line_total"] for i in items), D(0))
    if inclusive:
        vat = sum(
            (money(i["line_total"] * i["vat_rate"] / (100 + i["vat_rate"])) for i in items), D(0)
        )
        subtotal, total = lines_sum - vat, lines_sum
    else:
        vat = sum((money(i["line_total"] * i["vat_rate"] / 100) for i in items), D(0))
        subtotal, total = lines_sum, lines_sum + vat
    when = today - timedelta(days=rng.randint(0, 20))
    date_text = rng.choice(
        [
            when.strftime("%d/%m/%Y"),
            when.strftime("%d-%m-%Y"),
            when.strftime("%d %b %Y"),
            when.strftime("%d-%b-%Y"),
            when.strftime("%d.%m.%Y"),
        ]
    )
    number = rng.choice(
        [
            f"INV-{when:%Y}-{rng.randint(100, 99999):05d}",
            f"{rng.randint(10000, 999999)}",
            f"SI/{rng.randint(1000, 9999)}",
            f"TI{rng.randint(100000, 999999)}",
        ]
    )
    return Doc(SUPPLIERS[sup_idx], number, when, date_text, items, subtotal, vat, total, inclusive)


class Canvas:
    def __init__(self, width: int, height: int) -> None:
        self.img = Image.new("RGB", (width, height), "white")
        self.draw = ImageDraw.Draw(self.img)
        self.lines: list[str] = []

    def font(self, key: str, size: int) -> ImageFont.FreeTypeFont:
        return ImageFont.truetype(FONTS[key], size)

    def text(self, xy: tuple[int, int], s: str, font, anchor: str = "la") -> None:
        self.draw.text(xy, s, font=font, fill=(20, 20, 20), anchor=anchor)

    def row(self, y: int, cells: list[tuple[int, str, str]], font) -> None:
        """cells: (x, text, 'l'|'r'); also records the reading-order text line."""
        for x, s, align in cells:
            self.text((x, y), s, font, "ra" if align == "r" else "la")
        self.lines.append(" ".join(s for _, s, _ in cells if s))

    def rule(self, y: int, x0: int, x1: int) -> None:
        self.draw.line((x0, y, x1, y), fill=(60, 60, 60), width=2)


def render_a4(doc: Doc, layout: str, rng: random.Random) -> Canvas:
    W, H = 1700, 2200
    c = Canvas(W, H)
    regular, bold = ("lib", "lib_bold") if rng.random() < 0.5 else ("sans", "sans_bold")
    f, fb, fh = c.font(regular, 30), c.font(bold, 30), c.font(bold, 46)
    m = 110
    y = 110
    name, pin, addr = doc.supplier
    c.row(y, [(m, name.upper(), "l")], fh)
    y += 70
    c.row(y, [(m, addr + ", Kenya", "l")], f)
    y += 44
    c.row(
        y,
        [
            (
                m,
                f"Tel: +254 7{rng.randint(10, 99)} {rng.randint(100, 999)} {rng.randint(100, 999)}",
                "l",
            )
        ],
        f,
    )
    y += 44
    c.row(y, [(m, f"PIN: {pin}", "l")], f)
    y += 80
    title = "TAX INVOICE" if layout != "inclusive" else "INVOICE"
    c.row(y, [(m, title, "l")], fh)
    y += 80
    label = rng.choice(["Invoice No:", "Invoice Number:", "INV #", "Invoice No."])
    c.row(y, [(m, f"{label} {doc.number}", "l"), (W - m, f"Date: {doc.date_text}", "r")], fb)
    y += 54
    c.row(y, [(m, f"Bill To: {BUYER[0]}", "l")], f)
    y += 44
    c.row(y, [(m, f"Customer PIN: {BUYER[1]}", "l")], f)
    y += 80

    if layout == "coded":
        cols = [
            (m, "Code", "l"),
            (m + 200, "Description", "l"),
            (W - 610, "Qty", "r"),
            (W - 360, "Price", "r"),
            (W - m, "Total", "r"),
        ]
    elif layout == "inclusive":
        cols = [
            (m + 60, "Qty", "r"),
            (m + 140, "Description", "l"),
            (W - 400, "Rate", "r"),
            (W - m, "Amount", "r"),
        ]
    else:
        cols = [
            (m, "Description", "l"),
            (W - 640, "Qty", "r"),
            (W - 380, "Unit Price", "r"),
            (W - m, "Amount", "r"),
        ]
    c.rule(y - 14, m, W - m)
    c.row(y, cols, fb)
    y += 50
    c.rule(y - 6, m, W - m)
    y += 16
    for i, it in enumerate(doc.items):
        q = (
            f"{it['quantity']:g}"
            if it["quantity"] == it["quantity"].to_integral_value()
            else f"{it['quantity']}"
        )
        if layout == "coded":
            code = f"S{rng.randint(1, 3)}-{i + 1:03d}"
            it["item_code"] = code
            cells = [
                (m, code, "l"),
                (m + 200, it["description"], "l"),
                (W - 610, q, "r"),
                (W - 360, fmt(it["unit_price"]), "r"),
                (W - m, fmt(it["line_total"]), "r"),
            ]
        elif layout == "inclusive":
            cells = [
                (m + 60, q, "r"),
                (m + 140, it["description"], "l"),
                (W - 400, fmt(it["unit_price"]), "r"),
                (W - m, fmt(it["line_total"]), "r"),
            ]
        else:
            cells = [
                (m, it["description"], "l"),
                (W - 640, q, "r"),
                (W - 380, fmt(it["unit_price"]), "r"),
                (W - m, fmt(it["line_total"]), "r"),
            ]
        c.row(y, cells, f)
        y += 52
    c.rule(y + 4, m, W - m)
    y += 40
    if doc.inclusive:
        c.row(y, [(W - 640, "Total (incl. VAT)", "l"), (W - m, fmt(doc.total), "r")], fb)
        y += 50
        c.row(y, [(W - 640, "VAT included", "l"), (W - m, fmt(doc.vat), "r")], f)
        y += 50
    else:
        c.row(y, [(W - 640, "Subtotal", "l"), (W - m, fmt(doc.subtotal), "r")], f)
        y += 50
        c.row(y, [(W - 640, "VAT 16%", "l"), (W - m, fmt(doc.vat), "r")], f)
        y += 50
        c.row(y, [(W - 640, "TOTAL KES", "l"), (W - m, fmt(doc.total), "r")], fb)
        y += 50
    y += 60
    c.row(y, [(m, "Goods received in good order. Thank you for your business.", "l")], f)
    c.img = c.img.crop((0, 0, W, min(H, y + 140)))
    return c


def render_receipt(doc: Doc, rng: random.Random) -> Canvas:
    W = 760
    c = Canvas(W, 2400)
    f, fb = c.font("mono", 26), c.font("mono_bold", 30)
    y = 50
    name, pin, addr = doc.supplier
    for s, font in ((name.upper(), fb), (addr, f), (f"PIN: {pin}", f), ("CASH SALE RECEIPT", fb)):
        c.text((W // 2, y), s, font, "ma")
        c.lines.append(s)
        y += 44
    y += 10
    c.row(y, [(30, f"Receipt No: {doc.number}", "l")], f)
    y += 40
    c.row(y, [(30, f"Date: {doc.date_text}", "l")], f)
    y += 40
    c.row(y, [(30, "-" * 44, "l")], f)
    y += 40
    for it in doc.items:
        q = f"{it['quantity']:g}"
        c.row(y, [(30, it["description"], "l")], f)
        y += 36
        c.row(
            y,
            [(60, f"{q} x {fmt(it['unit_price'])}", "l"), (W - 30, fmt(it["line_total"]), "r")],
            f,
        )
        y += 44
    c.row(y, [(30, "-" * 44, "l")], f)
    y += 40
    c.row(y, [(30, "TOTAL KES", "l"), (W - 30, fmt(doc.total), "r")], fb)
    y += 46
    c.row(y, [(30, "VAT 16% (incl)", "l"), (W - 30, fmt(doc.vat), "r")], f)
    y += 60
    c.text((W // 2, y), "THANK YOU", f, "ma")
    c.lines.append("THANK YOU")
    c.img = c.img.crop((0, 0, W, y + 80))
    return c


def render_pdf(doc: Doc) -> tuple[bytes, list[str]]:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as rl

    buf = io.BytesIO()
    pdf = rl.Canvas(buf, pagesize=A4)
    W, H = A4
    lines: list[str] = []
    y = H - 60

    def put(x: float, s: str, size: int = 10, bold: bool = False, right: bool = False) -> None:
        pdf.setFont("Helvetica-Bold" if bold else "Helvetica", size)
        (pdf.drawRightString if right else pdf.drawString)(x, y, s)

    name, pin, addr = doc.supplier
    for s, size, bold in (
        (name.upper(), 16, True),
        (addr + ", Kenya", 10, False),
        (f"PIN: {pin}", 10, False),
        ("TAX INVOICE", 14, True),
    ):
        put(50, s, size, bold)
        lines.append(s)
        y -= 22
    put(50, f"Invoice No: {doc.number}", bold=True)
    put(W - 50, f"Date: {doc.date_text}", right=True)
    lines.append(f"Invoice No: {doc.number} Date: {doc.date_text}")
    y -= 18
    put(50, f"Bill To: {BUYER[0]}")
    lines.append(f"Bill To: {BUYER[0]}")
    y -= 30
    for x, s, r in (
        (50, "Description", False),
        (W - 260, "Qty", True),
        (W - 160, "Unit Price", True),
        (W - 50, "Amount", True),
    ):
        put(x, s, bold=True, right=r)
    lines.append("Description Qty Unit Price Amount")
    y -= 18
    for it in doc.items:
        q = f"{it['quantity']:g}"
        put(50, it["description"])
        put(W - 260, q, right=True)
        put(W - 160, fmt(it["unit_price"]), right=True)
        put(W - 50, fmt(it["line_total"]), right=True)
        lines.append(f"{it['description']} {q} {fmt(it['unit_price'])} {fmt(it['line_total'])}")
        y -= 16
    y -= 14
    for label, v, bold in (
        ("Subtotal", doc.subtotal, False),
        ("VAT 16%", doc.vat, False),
        ("TOTAL KES", doc.total, True),
    ):
        put(W - 260, label, bold=bold)
        put(W - 50, fmt(v), bold=bold, right=True)
        lines.append(f"{label} {fmt(v)}")
        y -= 16
    pdf.showPage()
    pdf.save()
    return buf.getvalue(), lines


def degrade(img: Image.Image, condition: str, rng: random.Random) -> np.ndarray:
    arr = cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)
    if condition == "clean":
        return arr
    h, w = arr.shape[:2]
    if condition == "scan":
        angle = rng.uniform(-1.5, 1.5)
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        arr = cv2.warpAffine(arr, m, (w, h), borderValue=(250, 250, 250))
        noise = np.random.default_rng(rng.randint(0, 10**6)).normal(0, 6, arr.shape)
        return np.clip(arr + noise, 0, 255).astype(np.uint8)
    # phone: paper on a darker desk, photographed at an angle
    pad = int(max(h, w) * 0.12)
    desk = np.full((h + 2 * pad, w + 2 * pad, 3), (rng.randint(60, 110),) * 3, np.uint8)
    desk[pad : pad + h, pad : pad + w] = arr
    H2, W2 = desk.shape[:2]
    j = lambda: rng.uniform(-0.05, 0.05) * W2  # noqa: E731
    src = np.float32([[pad, pad], [pad + w, pad], [pad + w, pad + h], [pad, pad + h]])
    dst = np.float32(
        [
            [pad + j(), pad + j()],
            [pad + w + j(), pad + j()],
            [pad + w + j(), pad + h + j()],
            [pad + j(), pad + h + j()],
        ]
    )
    arr = cv2.warpPerspective(
        desk, cv2.getPerspectiveTransform(src, dst), (W2, H2), borderValue=(80, 80, 80)
    )
    m = cv2.getRotationMatrix2D((W2 / 2, H2 / 2), rng.uniform(-5, 5), 1.0)
    arr = cv2.warpAffine(arr, m, (W2, H2), borderValue=(80, 80, 80))
    # uneven light: brighter on one side
    grad = np.tile(np.linspace(rng.uniform(0.75, 0.9), 1.05, W2), (H2, 1))[..., None]
    arr = np.clip(arr * grad, 0, 255).astype(np.uint8)
    arr = cv2.GaussianBlur(arr, (0, 0), rng.uniform(0.6, 1.1))
    noise = np.random.default_rng(rng.randint(0, 10**6)).normal(0, 8, arr.shape)
    return np.clip(arr + noise, 0, 255).astype(np.uint8)


def generate(out: Path, count: int, seed: int = 7, today: date | None = None) -> list[Path]:
    rng = random.Random(seed)  # noqa: S311 - reproducible test data
    today = today or date.today()
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for n in range(count):
        layout = LAYOUTS[n % len(LAYOUTS)]
        condition = (
            "clean" if layout == "pdf" else CONDITIONS[(n // len(LAYOUTS)) % len(CONDITIONS)]
        )
        doc = build_doc(rng, layout, today)
        stem = f"invoice-{n + 1:03d}-{layout}-{condition}"
        if layout == "pdf":
            data, text_lines = render_pdf(doc)
            path = out / f"{stem}.pdf"
            path.write_bytes(data)
        else:
            canvas = (
                render_receipt(doc, rng) if layout == "receipt" else render_a4(doc, layout, rng)
            )
            text_lines = canvas.lines
            arr = degrade(canvas.img, condition, rng)
            quality = {"clean": 95, "scan": 85, "phone": 72}[condition]
            path = out / f"{stem}.jpg"
            cv2.imwrite(str(path), arr, [cv2.IMWRITE_JPEG_QUALITY, quality])
        truth = {
            "file": path.name,
            "layout": layout,
            "condition": condition,
            "supplier_name": doc.supplier[0],
            "kra_pin": doc.supplier[1],
            "invoice_number": doc.number,
            "invoice_date": doc.when.isoformat(),
            "subtotal": str(doc.subtotal),
            "tax_total": str(doc.vat),
            "grand_total": str(doc.total),
            "prices_include_vat": doc.inclusive,
            "items": [
                {k: str(v) if isinstance(v, D) else v for k, v in it.items()} for it in doc.items
            ],
            "text_lines": text_lines,
            "synthetic": True,
        }
        (out / f"{stem}.truth.json").write_text(json.dumps(truth, indent=2))
        written.append(path)
    return written


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--count", type=int, default=15)
    p.add_argument("--seed", type=int, default=7)
    args = p.parse_args()
    files = generate(args.out, args.count, args.seed)
    print(f"Wrote {len(files)} synthetic invoices (+ .truth.json) to {args.out}")


if __name__ == "__main__":
    main()
