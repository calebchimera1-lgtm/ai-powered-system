"""Supplier invoice digitization: upload -> OCR (worker) -> human review -> approval.

Nothing touches stock until a person with `invoices:approve` approves the reviewed data.
Approval re-validates everything on the server and then calls the same
`procurement_service.receive_goods` used for manual deliveries, inside one transaction:
the goods-received note, stock, weighted average cost, batches, supplier prices, learnt
aliases and the audit entry all commit together or not at all.
"""

import hashlib
import io
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.ocr import engines, matcher, validator
from app.ai.ocr.pipeline import process as run_pipeline
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import (
    Invoice,
    InvoiceItem,
    Product,
    Supplier,
    SupplierProduct,
    SupplierProductAlias,
    User,
)
from app.schemas.common import PageParams
from app.schemas.invoices import InvoiceApprove, InvoiceReview
from app.schemas.procurement import GoodsReceivedCreate, GRNLine
from app.services import audit_service, job_service, procurement_service
from app.services.audit_service import RequestContext

logger = logging.getLogger(__name__)

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 40_000_000
ALLOWED = {
    b"\xff\xd8\xff": ("image/jpeg", "jpg"),
    b"\x89PNG\r\n\x1a\n": ("image/png", "png"),
    b"%PDF-": ("application/pdf", "pdf"),
}
JOB = "invoice.process"


def _now() -> datetime:
    return datetime.now(UTC)


def _folder(inv: Invoice) -> Path:
    return get_settings().storage_dir / Path(inv.file_path).parent


# --- Upload ------------------------------------------------------------------------


def sniff(data: bytes) -> tuple[str, str]:
    for magic, kind in ALLOWED.items():
        if data.startswith(magic):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ("image/webp", "webp")
    raise ValidationFailed(
        "Upload a photo (JPEG, PNG, WebP) or a PDF of the invoice.", code="UNSUPPORTED_FILE"
    )


def upload(db: Session, data: bytes, filename: str, user: User, ctx: RequestContext) -> Invoice:
    if not data:
        raise ValidationFailed("The file is empty.", code="UNSUPPORTED_FILE")
    if len(data) > MAX_BYTES:
        raise ValidationFailed("The file is larger than 10 MB.", code="FILE_TOO_LARGE")
    mime, ext = sniff(data)  # by content, never by file name
    pages = 1
    if mime == "application/pdf":
        try:
            pages = engines.pdf_page_count(data)
        except Exception as exc:
            raise ValidationFailed(
                "That PDF could not be opened.", code="UNSUPPORTED_FILE"
            ) from exc
        if pages > engines.MAX_PDF_PAGES:
            raise ValidationFailed(
                f"PDFs can have at most {engines.MAX_PDF_PAGES} pages.", code="FILE_TOO_LARGE"
            )
    else:
        try:
            Image.MAX_IMAGE_PIXELS = MAX_PIXELS
            with Image.open(io.BytesIO(data)) as img:
                img.verify()
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ValidationFailed(
                "That image could not be read.", code="UNSUPPORTED_FILE"
            ) from exc

    digest = hashlib.sha256(data).hexdigest()
    existing = db.scalar(select(Invoice).where(Invoice.file_sha256 == digest))
    if existing:
        raise ConflictError(
            f"This exact file was already uploaded on {existing.created_at:%d %b %Y}.",
            code="DUPLICATE_FILE",
            details={"invoice_id": existing.id},
        )

    folder = f"invoices/{uuid.uuid4().hex}"
    path = get_settings().storage_dir / folder
    path.mkdir(parents=True, exist_ok=True)
    (path / f"original.{ext}").write_bytes(data)
    inv = Invoice(
        file_path=f"{folder}/original.{ext}",
        original_filename=Path(filename or f"invoice.{ext}").name[:255],
        mime_type=mime,
        file_size=len(data),
        file_sha256=digest,
        page_count=pages,
        uploaded_by_id=user.id,
        status="QUEUED",
    )
    db.add(inv)
    db.flush()
    job_service.enqueue(db, JOB, {"invoice_id": inv.id}, max_attempts=1)
    audit_service.record(
        db,
        action="invoice.uploaded",
        actor=user,
        ctx=ctx,
        entity_type="invoice",
        entity_id=inv.id,
        after={"file": inv.original_filename, "bytes": len(data), "pages": pages},
    )
    db.commit()
    db.refresh(inv)
    return inv


# --- Processing (runs in the worker) -----------------------------------------------


def _catalog(db: Session) -> tuple[list[matcher.ProductRef], list[matcher.SupplierRef]]:
    products = [
        matcher.ProductRef(p.id, p.name, p.sku, p.barcode)
        for p in db.scalars(select(Product).where(Product.is_active))
    ]
    suppliers = [
        matcher.SupplierRef(s.id, s.name, s.kra_pin)
        for s in db.scalars(select(Supplier).where(Supplier.is_active))
    ]
    return products, suppliers


def _supplier_knowledge(
    db: Session, supplier_id: int | None
) -> tuple[dict[str, int], dict[str, int]]:
    if supplier_id is None:
        return {}, {}
    aliases = {
        a.alias_text: a.product_id
        for a in db.scalars(
            select(SupplierProductAlias).where(SupplierProductAlias.supplier_id == supplier_id)
        )
    }
    codes = {
        sp.supplier_sku.upper(): sp.product_id
        for sp in db.scalars(
            select(SupplierProduct).where(SupplierProduct.supplier_id == supplier_id)
        )
        if sp.supplier_sku
    }
    return aliases, codes


def _jsonable(v: Any) -> Any:
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def process(db: Session, invoice_id: int) -> dict[str, Any]:
    """OCR + extraction + matching + checks. Never raises for a bad document: the invoice
    is marked FAILED with a reason so a person can enter it by hand."""
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        return {"skipped": "invoice deleted"}
    inv.status = "PROCESSING"
    db.commit()
    try:
        data = (get_settings().storage_dir / inv.file_path).read_bytes()
        doc, ext = run_pipeline(data, inv.mime_type)
    except Exception as exc:
        logger.exception("Invoice %s could not be processed", invoice_id)
        inv.status = "FAILED"
        inv.error_message = f"The document could not be read ({exc.__class__.__name__})."
        db.commit()
        return {"status": "FAILED"}

    folder = _folder(inv)
    for i, png in enumerate(doc.pages, 1):
        (folder / f"page-{i}.png").write_bytes(png)
    inv.page_count = len(doc.pages)
    inv.ocr_engine = doc.engine
    inv.ocr_text = doc.raw_text[:200_000]
    inv.processing_steps = doc.steps
    inv.processing_ms = doc.milliseconds
    inv.quality = {
        "blur": round(doc.quality.blur, 1),
        "brightness": round(doc.quality.brightness, 1),
        "contrast": round(doc.quality.contrast, 1),
        "skew_degrees": doc.quality.skew_degrees,
        "document_detected": doc.quality.document_detected,
        "score": doc.quality.score,
        "problems": doc.quality.problems,
    }

    products, suppliers = _catalog(db)
    sup_id, sup_score, _ = matcher.match_supplier(
        ext.kra_pin.value, ext.supplier_name.value, ext.header_lines, suppliers
    )
    inv.supplier_id = sup_id
    inv.supplier_match_score = sup_score
    inv.extracted_supplier_name = (ext.supplier_name.value or None) and str(
        ext.supplier_name.value
    )[:255]
    inv.kra_pin = ext.kra_pin.value
    inv.invoice_number = str(ext.invoice_number.value)[:50] if ext.invoice_number.value else None
    inv.invoice_date = ext.invoice_date.value
    inv.subtotal, inv.tax_total, inv.grand_total = (
        ext.subtotal.value,
        ext.tax_total.value,
        ext.grand_total.value,
    )
    inv.prices_include_vat = ext.prices_include_vat
    inv.field_confidences = {
        "supplier": round(sup_score / 100, 3),
        "invoice_number": ext.invoice_number.confidence,
        "invoice_date": ext.invoice_date.confidence,
        "subtotal": ext.subtotal.confidence,
        "tax_total": ext.tax_total.confidence,
        "grand_total": ext.grand_total.confidence,
    }
    inv.original_fields = {
        "supplier_id": sup_id,
        "invoice_number": inv.invoice_number,
        "invoice_date": _jsonable(inv.invoice_date),
        "subtotal": _jsonable(inv.subtotal),
        "tax_total": _jsonable(inv.tax_total),
        "grand_total": _jsonable(inv.grand_total),
    }

    aliases, codes = _supplier_knowledge(db, sup_id)
    inv.items.clear()
    db.flush()
    for n, it in enumerate(ext.items, 1):
        m = matcher.match_product(
            it.description,
            it.item_code,
            it.raw_text,
            products,
            aliases=aliases,
            supplier_codes=codes,
        )
        inv.items.append(
            InvoiceItem(
                line_no=n,
                raw_text=it.raw_text[:2000],
                description=it.description[:255],
                item_code=it.item_code,
                quantity=it.quantity,
                unit_price=it.unit_price,
                line_total=it.line_total,
                product_id=m.product_id,
                match_method=m.method,
                match_score=m.score,
                suggested=m.suggestion_only,
                confidence=it.confidence,
                arithmetic_ok=it.arithmetic_ok,
                original={
                    "description": it.description,
                    "quantity": _jsonable(it.quantity),
                    "unit_price": _jsonable(it.unit_price),
                    "line_total": _jsonable(it.line_total),
                    "product_id": m.product_id,
                },
            )
        )
    inv.status = "NEEDS_REVIEW"
    inv.error_message = None
    _refresh_flags(db, inv)
    db.commit()
    return {"status": inv.status, "items": len(inv.items), "ms": doc.milliseconds}


# --- Review ------------------------------------------------------------------------


def _unit_cost_excl_vat(inv: Invoice, item: InvoiceItem) -> Decimal | None:
    if item.unit_price is None:
        return None
    if inv.prices_include_vat and item.product is not None:
        rate = item.product.vat_rate
        return (item.unit_price * 100 / (100 + rate)).quantize(Decimal("0.0001"), ROUND_HALF_UP)
    return item.unit_price


def _refresh_flags(db: Session, inv: Invoice) -> None:
    db.flush()
    for item in inv.items:
        if item.product_id:  # make sure a newly chosen product is loaded
            db.refresh(item, ["product"])
    flags = validator.check(
        supplier_id=inv.supplier_id,
        invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        subtotal=inv.subtotal,
        tax_total=inv.tax_total,
        grand_total=inv.grand_total,
        prices_include_vat=inv.prices_include_vat,
        items=[
            {
                "quantity": i.quantity,
                "unit_price": i.unit_price,
                "line_total": i.line_total,
                "product_id": None if i.suggested else i.product_id,
                "previous_cost": i.product.purchase_price if i.product else None,
                "unit_cost_excl_vat": _unit_cost_excl_vat(inv, i),
            }
            for i in inv.items
        ],
        quality_problems=(inv.quality or {}).get("problems", []),
        price_alert_percent=get_settings().price_change_alert_percent,
    )
    out = [f.as_dict() for f in flags]
    for i in inv.items:
        if i.suggested and i.product_id:
            out.append(
                {
                    "code": "CHECK_PRODUCT",
                    "severity": "warning",
                    "item": i.line_no - 1,
                    "message": f"Line {i.line_no}: confirm the suggested product "
                    f"({i.product.name if i.product else ''}).",
                }
            )
    dup = _duplicate(db, inv)
    if dup is not None:
        out.insert(
            0,
            {
                "code": "DUPLICATE_INVOICE",
                "severity": "error",
                "item": None,
                "message": f"Invoice {inv.invoice_number} from this supplier was already "
                f"approved (invoice #{dup.id}). It cannot be received twice.",
            },
        )
    elif inv.supplier_id and inv.invoice_date and inv.grand_total is not None:
        similar = db.scalar(
            select(Invoice).where(
                Invoice.id != inv.id,
                Invoice.status == "APPROVED",
                Invoice.supplier_id == inv.supplier_id,
                Invoice.invoice_date == inv.invoice_date,
                Invoice.grand_total == inv.grand_total,
            )
        )
        if similar:
            out.insert(
                0,
                {
                    "code": "POSSIBLE_DUPLICATE",
                    "severity": "warning",
                    "item": None,
                    "message": f"An approved invoice from this supplier has the same date "
                    f"and total (invoice #{similar.id}). Check it is not the same one.",
                },
            )
    inv.flags = out


def _duplicate(db: Session, inv: Invoice) -> Invoice | None:
    if not inv.supplier_id or not inv.invoice_number:
        return None
    return db.scalar(
        select(Invoice).where(
            Invoice.id != inv.id,
            Invoice.status == "APPROVED",
            Invoice.supplier_id == inv.supplier_id,
            func.upper(Invoice.invoice_number) == inv.invoice_number.upper(),
        )
    )


def get(db: Session, invoice_id: int) -> Invoice:
    inv = db.get(Invoice, invoice_id)
    if inv is None:
        raise NotFoundError("Invoice not found")
    return inv


def _editable(inv: Invoice) -> None:
    if inv.status not in ("NEEDS_REVIEW", "FAILED"):
        raise ValidationFailed(
            f"This invoice is {inv.status.lower().replace('_', ' ')} and can no "
            "longer be edited."
        )


def save_review(
    db: Session, inv: Invoice, data: InvoiceReview, user: User, ctx: RequestContext
) -> Invoice:
    """Store the reviewer's corrections (header and lines). Does not touch stock."""
    _editable(inv)
    if data.supplier_id is not None and db.get(Supplier, data.supplier_id) is None:
        raise ValidationFailed("Supplier not found")
    for name in (
        "supplier_id",
        "invoice_number",
        "invoice_date",
        "subtotal",
        "tax_total",
        "grand_total",
        "prices_include_vat",
    ):
        if name in data.model_fields_set:
            setattr(inv, name, getattr(data, name))
    if data.items is not None:
        product_ids = {i.product_id for i in data.items if i.product_id}
        found = (
            set(db.scalars(select(Product.id).where(Product.id.in_(product_ids))))
            if product_ids
            else set()
        )
        if product_ids - found:
            raise ValidationFailed("One of the chosen products does not exist")
        existing = {i.id: i for i in inv.items}
        keep: list[InvoiceItem] = []
        for n, line in enumerate(data.items, 1):
            item = existing.get(line.id) if line.id else None
            if item is None:
                item = InvoiceItem(
                    raw_text=None,
                    original=None,
                    match_method="MANUAL",
                    confidence=1.0,
                    arithmetic_ok=False,
                )
            before = (
                item.description,
                item.quantity,
                item.unit_price,
                item.line_total,
                item.product_id,
            )
            item.line_no = n
            item.description = line.description
            item.quantity, item.unit_price, item.line_total = (
                line.quantity,
                line.unit_price,
                line.line_total,
            )
            if line.product_id != item.product_id:
                item.match_method = "MANUAL" if line.product_id else "NONE"
                item.match_score = None
            item.product_id = line.product_id
            item.suggested = False if line.product_id else item.suggested
            item.batch_number = line.batch_number
            item.expiry_date = line.expiry_date
            if item.original is not None and before != (
                item.description,
                item.quantity,
                item.unit_price,
                item.line_total,
                item.product_id,
            ):
                item.was_corrected = True
            if (
                item.quantity is not None
                and item.unit_price is not None
                and item.line_total is not None
            ):
                item.arithmetic_ok = abs(
                    item.quantity * item.unit_price - item.line_total
                ) <= Decimal("1")
            keep.append(item)
        inv.items[:] = keep
    if inv.status == "FAILED":
        inv.status = "NEEDS_REVIEW"  # entered by hand instead
    _refresh_flags(db, inv)
    audit_service.record(
        db, action="invoice.reviewed", actor=user, ctx=ctx, entity_type="invoice", entity_id=inv.id
    )
    db.commit()
    db.refresh(inv)
    return inv


def approve(
    db: Session, inv: Invoice, data: InvoiceApprove, user: User, ctx: RequestContext
) -> Invoice:
    """Turn a reviewed invoice into a goods-received note and stock, in one transaction."""
    if inv.status != "NEEDS_REVIEW":
        raise ValidationFailed(
            f"Only invoices waiting for review can be approved (this one is "
            f"{inv.status.lower().replace('_', ' ')})."
        )
    problems: list[str] = []
    if inv.supplier_id is None:
        problems.append("choose the supplier")
    if not inv.invoice_number:
        problems.append("enter the invoice number")
    if not inv.items:
        problems.append("add at least one line")
    for item in inv.items:
        label = f"line {item.line_no} ({item.description})"
        if item.product_id is None or item.suggested:
            problems.append(f"{label}: confirm the product")
        if item.quantity is None or item.quantity <= 0:
            problems.append(f"{label}: enter the quantity")
        if item.unit_price is None or item.unit_price < 0:
            problems.append(f"{label}: enter the unit price")
        if item.product and item.product.tracks_expiry and not item.expiry_date:
            problems.append(f"{label}: enter the expiry date")
    if problems:
        raise ValidationFailed(
            "Before approving: " + "; ".join(problems) + ".",
            code="REVIEW_INCOMPLETE",
            details=[{"field": "items", "message": p} for p in problems],
        )
    dup = _duplicate(db, inv)
    if dup is not None:
        raise ConflictError(
            f"Invoice {inv.invoice_number} from this supplier was already "
            f"approved (invoice #{dup.id}).",
            code="DUPLICATE_INVOICE",
        )

    grn = GoodsReceivedCreate(
        supplier_id=inv.supplier_id,
        purchase_order_id=data.purchase_order_id,
        supplier_invoice_number=inv.invoice_number,
        invoice_date=inv.invoice_date,
        notes=f"From scanned invoice #{inv.id}" + (f": {data.note}" if data.note else ""),
        items=[
            GRNLine(
                product_id=i.product_id,
                quantity=i.quantity,
                unit_cost=_unit_cost_excl_vat(inv, i),
                vat_rate=None,
                batch_number=i.batch_number,
                expiry_date=i.expiry_date,
            )
            for i in inv.items
        ],
    )
    purchase, _ = procurement_service.receive_goods(
        db, grn, user, ctx, source="INVOICE", commit=False
    )
    inv.purchase_id = purchase.id
    inv.status = "APPROVED"
    inv.reviewed_by_id = user.id
    inv.reviewed_at = _now()
    inv.review_note = data.note

    # Learn this supplier's wording and codes for next time.
    for item in inv.items:
        alias = matcher.normalise(item.description)
        if alias:
            row = db.scalar(
                select(SupplierProductAlias).where(
                    SupplierProductAlias.supplier_id == inv.supplier_id,
                    SupplierProductAlias.alias_text == alias,
                )
            )
            if row is None:
                db.add(
                    SupplierProductAlias(
                        supplier_id=inv.supplier_id, product_id=item.product_id, alias_text=alias
                    )
                )
            else:
                row.product_id = item.product_id
                row.times_confirmed += 1
                row.last_seen_at = _now()
        if item.item_code:
            link = db.get(SupplierProduct, (inv.supplier_id, item.product_id))
            if link is not None and not link.supplier_sku:
                link.supplier_sku = item.item_code[:50]

    corrected_fields = sum(
        1
        for k, v in (inv.original_fields or {}).items()
        if str(_jsonable(getattr(inv, k))) != str(v)
    )
    audit_service.record(
        db,
        action="invoice.approved",
        actor=user,
        ctx=ctx,
        entity_type="invoice",
        entity_id=inv.id,
        after={
            "grn": purchase.grn_number,
            "total_kes": purchase.grand_total,
            "lines": len(inv.items),
            "lines_corrected": sum(i.was_corrected for i in inv.items),
            "header_fields_corrected": corrected_fields,
        },
    )
    db.commit()
    db.refresh(inv)
    return inv


def reject(db: Session, inv: Invoice, note: str | None, user: User, ctx: RequestContext) -> Invoice:
    if inv.status in ("APPROVED", "REJECTED"):
        raise ValidationFailed(f"This invoice is already {inv.status.lower()}.")
    if not (note or "").strip():
        raise ValidationFailed(
            "Please give a reason for rejecting", details=[{"field": "note", "message": "required"}]
        )
    inv.status = "REJECTED"
    inv.reviewed_by_id = user.id
    inv.reviewed_at = _now()
    inv.review_note = note.strip()  # type: ignore[union-attr]
    audit_service.record(
        db,
        action="invoice.rejected",
        actor=user,
        ctx=ctx,
        entity_type="invoice",
        entity_id=inv.id,
        details=inv.review_note,
    )
    db.commit()
    db.refresh(inv)
    return inv


def reprocess(db: Session, inv: Invoice, user: User, ctx: RequestContext) -> Invoice:
    if inv.status not in ("NEEDS_REVIEW", "FAILED"):
        raise ValidationFailed("Only invoices waiting for review can be read again.")
    inv.status = "QUEUED"
    job_service.enqueue(db, JOB, {"invoice_id": inv.id}, max_attempts=1)
    audit_service.record(
        db, action="invoice.reprocess", actor=user, ctx=ctx, entity_type="invoice", entity_id=inv.id
    )
    db.commit()
    db.refresh(inv)
    return inv


def list_invoices(
    db: Session, params: PageParams, *, status: str | None
) -> tuple[list[Invoice], int]:
    stmt = select(Invoice)
    if status == "OPEN":
        stmt = stmt.where(Invoice.status.in_(["QUEUED", "PROCESSING", "NEEDS_REVIEW", "FAILED"]))
    elif status:
        stmt = stmt.where(Invoice.status == status)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(Invoice.created_at.desc(), Invoice.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    return list(rows), total


def stats(db: Session) -> dict[str, Any]:
    """Counts by status and the real-world correction rate on approved invoices."""
    counts = dict(db.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
    approved = db.scalars(select(Invoice).where(Invoice.status == "APPROVED")).all()
    lines = sum(len(i.items) for i in approved)
    corrected = sum(sum(it.was_corrected for it in i.items) for i in approved)
    stale = (
        db.scalar(
            select(func.count())
            .select_from(Invoice)
            .where(
                Invoice.status == "NEEDS_REVIEW", Invoice.created_at < _now() - timedelta(hours=24)
            )
        )
        or 0
    )
    return {
        "by_status": counts,
        "approved": len(approved),
        "approved_lines": lines,
        "lines_corrected": corrected,
        "line_correction_rate": round(corrected / lines, 4) if lines else None,
        "waiting_over_24h": stale,
    }


def page_path(inv: Invoice, page: int) -> Path:
    if page < 1 or page > max(inv.page_count, 1):
        raise NotFoundError("Page not found")
    path = _folder(inv) / f"page-{page}.png"
    if not path.is_file():
        raise NotFoundError("This page is not ready yet")
    return path
