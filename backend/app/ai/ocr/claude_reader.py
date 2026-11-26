"""Read a supplier invoice or receipt with Claude vision instead of Tesseract.

Used when ANTHROPIC_API_KEY is set (and AI_INVOICE_READING is not false). Phone photos
that Tesseract finds hard (shadows, folds, curved paper, small print, handwriting) are
usually read correctly. The result has the same shape as the Tesseract pipeline's, so the
rest of the flow is unchanged: product and supplier matching, arithmetic and VAT checks,
and the human review before anything touches stock.

Confidences: Claude does not return calibrated probabilities. The model marks each value
it is unsure of; we turn that into 0.9 (sure) or 0.5 (unsure) so the review screen
highlights the unsure ones. These numbers are flags, not a measured accuracy.
"""

import base64
import json
import time
from datetime import date
from decimal import Decimal, InvalidOperation

import cv2
import numpy as np

from app.ai import claude
from app.ai.ocr import engines, preprocessing
from app.ai.ocr.pipeline import DocumentRead, _png
from app.ai.ocr.types import ExtractedItem, Extraction, Field, Line, Quality, Word

SURE, UNSURE = 0.9, 0.5
MAX_SIDE = 2000  # long side sent to the model, in pixels

_NUM = {"type": ["string", "null"], "description": "Amount as digits, e.g. 1250.00; null if absent"}
_TXT = {"type": ["string", "null"]}
SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "document_kind",
        "supplier_name",
        "supplier_kra_pin",
        "invoice_number",
        "invoice_date",
        "prices_include_vat",
        "vat_rate_percent",
        "subtotal",
        "tax_total",
        "grand_total",
        "items",
        "uncertain_fields",
        "transcript",
    ],
    "properties": {
        "document_kind": {
            "type": "string",
            "enum": ["supplier_invoice", "receipt", "delivery_note", "other"],
        },
        "supplier_name": _TXT,
        "supplier_kra_pin": {**_TXT, "description": "KRA PIN such as P051234567X"},
        "invoice_number": _TXT,
        "invoice_date": {**_TXT, "description": "YYYY-MM-DD"},
        "prices_include_vat": {"type": "boolean"},
        "vat_rate_percent": {"type": ["number", "null"]},
        "subtotal": _NUM,
        "tax_total": _NUM,
        "grand_total": _NUM,
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "description",
                    "item_code",
                    "quantity",
                    "unit_price",
                    "line_total",
                    "source_text",
                    "unsure",
                ],
                "properties": {
                    "description": {"type": "string"},
                    "item_code": _TXT,
                    "quantity": _NUM,
                    "unit_price": _NUM,
                    "line_total": _NUM,
                    "source_text": {"type": "string", "description": "The row as printed"},
                    "unsure": {"type": "boolean"},
                },
            },
        },
        "uncertain_fields": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": [
                    "supplier_name",
                    "supplier_kra_pin",
                    "invoice_number",
                    "invoice_date",
                    "subtotal",
                    "tax_total",
                    "grand_total",
                ],
            },
        },
        "transcript": {"type": "string", "description": "All printed text, line by line"},
    },
}

PROMPT = """You are reading a document photographed or scanned at a Kenyan supermarket's \
receiving desk, usually a supplier invoice, delivery note or till receipt. Extract exactly \
what is printed. Never guess or invent a value: use null when something is not on the \
document or cannot be read. Write amounts as plain digits with a dot for decimals (no \
commas, no currency). Dates as YYYY-MM-DD (Kenyan documents usually print day/month/year). \
One entry in items per product row; skip rows that are totals, VAT, discounts or notes. \
Set prices_include_vat to true when the item prices already include VAT. List in \
uncertain_fields every header value you are not sure you read correctly, and set unsure \
on any item row that is hard to read. transcript is the full printed text, line by line."""


def _decimal(v: object) -> Decimal | None:
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(",", "").replace("KES", "").replace("KSh", "").strip())
    except InvalidOperation:
        return None
    return d if d.is_finite() else None


def _date(v: object) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def _jpeg(img: np.ndarray) -> bytes:
    h, w = img.shape[:2]
    if max(h, w) > MAX_SIDE:
        s = MAX_SIDE / max(h, w)
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    if not ok:
        raise ValueError("could not encode image")
    return buf.tobytes()


def _arithmetic_ok(q: Decimal | None, p: Decimal | None, t: Decimal | None) -> bool:
    if q is None or p is None or t is None:
        return False
    return abs(q * p - t) <= max(Decimal("0.05"), abs(t) * Decimal("0.005"))


def to_extraction(data: dict) -> Extraction:
    unsure = set(data.get("uncertain_fields") or [])

    def field(name: str, value: object) -> Field:
        if value is None:
            return Field(None, 0.0, "")
        return Field(value, UNSURE if name in unsure else SURE, "AI reading")  # type: ignore[arg-type]

    items = []
    for it in data.get("items") or []:
        q, p, t = (
            _decimal(it.get("quantity")),
            _decimal(it.get("unit_price")),
            _decimal(it.get("line_total")),
        )
        if t is None and q is not None and p is not None:
            t = (q * p).quantize(Decimal("0.01"))
        items.append(
            ExtractedItem(
                raw_text=str(it.get("source_text") or it.get("description") or ""),
                description=str(it.get("description") or "").strip(),
                quantity=q,
                unit_price=p,
                line_total=t,
                item_code=(str(it["item_code"])[:50] if it.get("item_code") else None),
                confidence=UNSURE if it.get("unsure") else SURE,
                arithmetic_ok=_arithmetic_ok(q, p, t),
            )
        )
    rate = data.get("vat_rate_percent")
    transcript = str(data.get("transcript") or "")
    return Extraction(
        supplier_name=field("supplier_name", data.get("supplier_name")),
        kra_pin=field(
            "supplier_kra_pin",
            str(data["supplier_kra_pin"]).upper().replace(" ", "")
            if data.get("supplier_kra_pin")
            else None,
        ),
        invoice_number=field("invoice_number", data.get("invoice_number")),
        invoice_date=field("invoice_date", _date(data.get("invoice_date"))),
        subtotal=field("subtotal", _decimal(data.get("subtotal"))),
        tax_total=field("tax_total", _decimal(data.get("tax_total"))),
        grand_total=field("grand_total", _decimal(data.get("grand_total"))),
        items=[i for i in items if i.description],
        vat_rate=_decimal(rate) if rate is not None else None,
        prices_include_vat=bool(data.get("prices_include_vat")),
        header_lines=[ln for ln in transcript.splitlines() if ln.strip()][:8],
    )


def read(data: bytes, mime: str) -> tuple[DocumentRead, Extraction]:
    """Raises claude.AIUnavailable (or ValueError for an unreadable answer)."""
    started = time.perf_counter()
    steps: list[str] = []
    quality = Quality(score=1.0)
    if mime == "application/pdf":
        rendered = engines.render_pdf(data)
        pages = [_png(img) for img in rendered]
        block = {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(data).decode(),
            },
        }
    else:
        img = preprocessing.decode(data)
        prepared = preprocessing.prepare(img)
        quality = prepared.quality
        steps.extend(s for s in prepared.steps if "binarised" not in s)
        pages = [_png(prepared.display)]
        block = {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/jpeg",
                "data": base64.b64encode(_jpeg(img)).decode(),
            },
        }
    response = claude.create(
        max_tokens=16000,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": [block, {"type": "text", "text": PROMPT}]}],
    )
    if response.stop_reason == "max_tokens":
        raise ValueError("the AI answer was cut off (document too long)")
    parsed = json.loads(claude.text_of(response))
    extraction = to_extraction(parsed)
    model = getattr(response, "model", None) or "claude"
    steps.append(f"read by the AI model {model} (Claude vision)")
    if parsed.get("document_kind") not in ("supplier_invoice", "delivery_note"):
        steps.append(f"the AI says this looks like: {parsed.get('document_kind')}")
    lines = [
        Line(words=[Word(text=t, conf=0.0, left=0, top=i * 10, width=1, height=1)])
        for i, t in enumerate(str(parsed.get("transcript") or "").splitlines())
        if t.strip()
    ]
    doc = DocumentRead(
        lines=lines,
        pages=pages,
        quality=quality,
        engine="claude-vision",
        steps=steps,
        milliseconds=int((time.perf_counter() - started) * 1000),
    )
    return doc, extraction
