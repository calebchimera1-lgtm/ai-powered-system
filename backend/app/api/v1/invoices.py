"""Supplier invoice digitization: upload, review and approve.

Uploaded documents are private: page images and originals are served only to signed-in
staff with invoice permissions (fetched with the Authorization header, not public URLs).
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.config import get_settings
from app.core.permissions import P
from app.models import User
from app.schemas.common import Page
from app.schemas.invoices import (
    InvoiceApprove,
    InvoiceOut,
    InvoiceReject,
    InvoiceReview,
    InvoiceStats,
    InvoiceSummary,
)
from app.services import invoice_service

router = APIRouter(prefix="/invoices", tags=["Invoice digitization"])

Uploader = Annotated[User, Depends(require(P.INVOICES_UPLOAD))]
Approver = Annotated[User, Depends(require(P.INVOICES_APPROVE))]
Reader = Annotated[User, Depends(require(P.INVOICES_UPLOAD, P.INVOICES_APPROVE, any_of=True))]


def summary(inv) -> InvoiceSummary:  # type: ignore[no-untyped-def]
    out = InvoiceSummary.model_validate(inv)
    out.line_count = len(inv.items)
    out.warnings = sum(1 for f in inv.flags or [] if f.get("severity") in ("warning", "error"))
    return out


@router.post("", response_model=InvoiceOut, status_code=status.HTTP_202_ACCEPTED)
async def upload(
    user: Uploader,
    db: DbSession,
    ctx: Ctx,
    file: Annotated[UploadFile, File(description="Photo (JPEG/PNG/WebP) or PDF, max 10 MB")],
) -> InvoiceOut:
    """Upload a supplier invoice. It is read in the background; poll until NEEDS_REVIEW."""
    data = await file.read(invoice_service.MAX_BYTES + 1)
    inv = invoice_service.upload(db, data, file.filename or "", user, ctx)
    return InvoiceOut.model_validate(inv)


@router.get("", response_model=Page[InvoiceSummary])
def list_invoices(
    _: Reader,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[
        Literal["OPEN", "QUEUED", "PROCESSING", "NEEDS_REVIEW", "APPROVED", "REJECTED", "FAILED"]
        | None,
        Query(alias="status"),
    ] = None,
) -> Page[InvoiceSummary]:
    rows, total = invoice_service.list_invoices(db, pagination, status=status_filter)
    return Page.build([summary(r) for r in rows], total, pagination)


@router.get("/stats", response_model=InvoiceStats)
def invoice_stats(_: Reader, db: DbSession) -> InvoiceStats:
    """Counts by status and how often reviewers had to correct the OCR (real accuracy)."""
    return InvoiceStats.model_validate(invoice_service.stats(db))


@router.get("/{invoice_id}", response_model=InvoiceOut)
def get_invoice(invoice_id: int, _: Reader, db: DbSession) -> InvoiceOut:
    return InvoiceOut.model_validate(invoice_service.get(db, invoice_id))


@router.get("/{invoice_id}/pages/{page}", response_class=FileResponse)
def page_image(invoice_id: int, page: int, _: Reader, db: DbSession) -> FileResponse:
    inv = invoice_service.get(db, invoice_id)
    return FileResponse(
        invoice_service.page_path(inv, page),
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=600"},
    )


@router.get("/{invoice_id}/original", response_class=FileResponse)
def original(invoice_id: int, _: Reader, db: DbSession) -> FileResponse:
    inv = invoice_service.get(db, invoice_id)
    return FileResponse(
        get_settings().storage_dir / inv.file_path,
        media_type=inv.mime_type,
        filename=inv.original_filename,
        headers={"Cache-Control": "private, no-store"},
    )


@router.put("/{invoice_id}", response_model=InvoiceOut)
def save_review(
    invoice_id: int, body: InvoiceReview, user: Reader, db: DbSession, ctx: Ctx
) -> InvoiceOut:
    """Save the reviewer's corrections. Stock is not changed until approval."""
    inv = invoice_service.get(db, invoice_id)
    return InvoiceOut.model_validate(invoice_service.save_review(db, inv, body, user, ctx))


@router.post("/{invoice_id}/approve", response_model=InvoiceOut)
def approve(
    invoice_id: int, body: InvoiceApprove, user: Approver, db: DbSession, ctx: Ctx
) -> InvoiceOut:
    """Receive the reviewed invoice into stock (creates a goods-received note)."""
    inv = invoice_service.get(db, invoice_id)
    return InvoiceOut.model_validate(invoice_service.approve(db, inv, body, user, ctx))


@router.post("/{invoice_id}/reject", response_model=InvoiceOut)
def reject(
    invoice_id: int, body: InvoiceReject, user: Approver, db: DbSession, ctx: Ctx
) -> InvoiceOut:
    inv = invoice_service.get(db, invoice_id)
    return InvoiceOut.model_validate(invoice_service.reject(db, inv, body.note, user, ctx))


@router.post("/{invoice_id}/reprocess", response_model=InvoiceOut)
def reprocess(invoice_id: int, user: Uploader, db: DbSession, ctx: Ctx) -> InvoiceOut:
    """Read the document again (e.g. after adding the supplier or products)."""
    inv = invoice_service.get(db, invoice_id)
    return InvoiceOut.model_validate(invoice_service.reprocess(db, inv, user, ctx))
