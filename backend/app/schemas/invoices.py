"""Invoice digitization schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any

from pydantic import BaseModel, Field, field_validator

from app.schemas.common import ORMModel
from app.schemas.stock import UserBrief

Money = Annotated[Decimal, Field(ge=0, le=Decimal("999999999.99"), decimal_places=2)]
Qty = Annotated[Decimal, Field(gt=0, le=Decimal("999999.999"), decimal_places=3)]
Cost = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.9999"), decimal_places=4)]


class ProductBrief(ORMModel):
    id: int
    name: str
    sku: str
    unit_of_measure: str
    tracks_expiry: bool
    vat_rate: Decimal
    purchase_price: Decimal | None = None


class InvoiceItemOut(ORMModel):
    id: int
    line_no: int
    raw_text: str | None
    description: str
    item_code: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal | None
    product: ProductBrief | None
    match_method: str
    match_score: float | None
    suggested: bool
    confidence: float
    arithmetic_ok: bool
    batch_number: str | None
    expiry_date: date | None
    was_corrected: bool


class SupplierRef(ORMModel):
    id: int
    name: str


class InvoiceOut(ORMModel):
    id: int
    status: str
    original_filename: str
    mime_type: str
    file_size: int
    page_count: int
    uploaded_by: UserBrief
    created_at: datetime
    ocr_engine: str | None
    processing_ms: int | None
    processing_steps: list[str] | None
    quality: dict[str, Any] | None
    error_message: str | None
    supplier: SupplierRef | None
    supplier_match_score: float | None
    extracted_supplier_name: str | None
    kra_pin: str | None
    invoice_number: str | None
    invoice_date: date | None
    subtotal: Decimal | None
    tax_total: Decimal | None
    grand_total: Decimal | None
    prices_include_vat: bool
    field_confidences: dict[str, float] | None
    flags: list[dict[str, Any]] | None
    reviewed_by: UserBrief | None
    reviewed_at: datetime | None
    review_note: str | None
    purchase_id: int | None
    items: list[InvoiceItemOut] = []


class InvoiceSummary(ORMModel):
    id: int
    status: str
    original_filename: str
    created_at: datetime
    uploaded_by: UserBrief
    supplier: SupplierRef | None
    extracted_supplier_name: str | None
    invoice_number: str | None
    invoice_date: date | None
    grand_total: Decimal | None
    purchase_id: int | None
    line_count: int = 0
    warnings: int = 0


class ReviewLine(BaseModel):
    id: int | None = None
    description: str = Field(..., min_length=1, max_length=255)
    product_id: int | None = None
    quantity: Qty | None = None
    unit_price: Cost | None = None
    line_total: Money | None = None
    batch_number: str | None = Field(None, max_length=50)
    expiry_date: date | None = None
    # Accept the matcher's suggested product for this line (default: yes, for API users
    # who send exactly what they mean; the review screen sends false until confirmed).
    confirm_product: bool = True


class InvoiceReview(BaseModel):
    supplier_id: int | None = None
    invoice_number: str | None = Field(None, max_length=50)
    invoice_date: date | None = None
    subtotal: Money | None = None
    tax_total: Money | None = None
    grand_total: Money | None = None
    prices_include_vat: bool = False
    items: list[ReviewLine] | None = Field(None, max_length=300)

    @field_validator("invoice_number")
    @classmethod
    def _no(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        return v or None


class InvoiceApprove(BaseModel):
    purchase_order_id: int | None = None
    note: str | None = Field(None, max_length=500)


class InvoiceReject(BaseModel):
    note: str | None = Field(None, max_length=500)


class InvoiceStats(BaseModel):
    by_status: dict[str, int]
    approved: int
    approved_lines: int
    lines_corrected: int
    line_correction_rate: float | None
    waiting_over_24h: int
