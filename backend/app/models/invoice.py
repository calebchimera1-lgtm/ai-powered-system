"""Digitized supplier invoices, their extracted lines, and learnt product aliases."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Cost, Money, Product, Qty
from app.models.supplier import Supplier

INVOICE_STATUSES = ("QUEUED", "PROCESSING", "NEEDS_REVIEW", "APPROVED", "REJECTED", "FAILED")
MATCH_METHODS = ("CODE", "ALIAS", "FUZZY", "MANUAL", "NONE")


class Invoice(IdMixin, TimestampMixin, Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("ix_invoices_status_created", "status", "created_at"),
        # One approved invoice per supplier invoice number.
        Index(
            "uq_invoices_approved_number",
            "supplier_id",
            text("upper(invoice_number)"),
            unique=True,
            postgresql_where=text("status = 'APPROVED'"),
        ),
        CheckConstraint(f"status IN {INVOICE_STATUSES!r}", name="status_valid"),
    )

    # The uploaded document (stored privately; served only to signed-in staff).
    file_path: Mapped[str] = mapped_column(String(255), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    uploaded_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="QUEUED")

    # What the OCR did.
    ocr_engine: Mapped[str | None] = mapped_column(String(20))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    quality: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    processing_steps: Mapped[list[str] | None] = mapped_column(JSONB)
    processing_ms: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)

    # Header fields (as extracted, then as corrected by the reviewer).
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id", ondelete="RESTRICT"))
    supplier_match_score: Mapped[float | None] = mapped_column(Float)
    extracted_supplier_name: Mapped[str | None] = mapped_column(String(255))
    kra_pin: Mapped[str | None] = mapped_column(String(11))
    invoice_number: Mapped[str | None] = mapped_column(String(50))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal | None] = mapped_column(Money)
    tax_total: Mapped[Decimal | None] = mapped_column(Money)
    grand_total: Mapped[Decimal | None] = mapped_column(Money)
    prices_include_vat: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    field_confidences: Mapped[dict[str, float] | None] = mapped_column(JSONB)
    original_fields: Mapped[dict[str, Any] | None] = mapped_column(JSONB)  # OCR's own values
    flags: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)

    # Review outcome.
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_note: Mapped[str | None] = mapped_column(Text)
    purchase_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchases.id", ondelete="RESTRICT"), unique=True
    )

    supplier: Mapped[Supplier | None] = relationship(lazy="joined")
    uploaded_by: Mapped[User] = relationship(foreign_keys=[uploaded_by_id], lazy="joined")
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id], lazy="joined")
    items: Mapped[list["InvoiceItem"]] = relationship(
        back_populates="invoice",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="InvoiceItem.line_no",
    )


class InvoiceItem(IdMixin, Base):
    __tablename__ = "invoice_items"
    __table_args__ = (
        CheckConstraint(f"match_method IN {MATCH_METHODS!r}", name="match_method_valid"),
    )

    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, index=True
    )
    line_no: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str] = mapped_column(String(255), nullable=False)
    item_code: Mapped[str | None] = mapped_column(String(50))
    quantity: Mapped[Decimal | None] = mapped_column(Qty)
    unit_price: Mapped[Decimal | None] = mapped_column(Cost)  # as printed on the invoice
    line_total: Mapped[Decimal | None] = mapped_column(Money)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), index=True
    )
    match_method: Mapped[str] = mapped_column(String(8), nullable=False, default="NONE")
    match_score: Mapped[float | None] = mapped_column(Float)
    suggested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    arithmetic_ok: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    batch_number: Mapped[str | None] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    # The OCR's values before any human correction, kept to measure real-world accuracy.
    original: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    was_corrected: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    invoice: Mapped[Invoice] = relationship(back_populates="items")
    product: Mapped[Product | None] = relationship(lazy="joined")


class SupplierProductAlias(IdMixin, TimestampMixin, Base):
    """How a supplier writes a product on its invoices, learnt from approvals."""

    __tablename__ = "supplier_product_aliases"
    __table_args__ = (UniqueConstraint("supplier_id", "alias_text", name="uq_supplier_alias_text"),)

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alias_text: Mapped[str] = mapped_column(String(255), nullable=False)
    times_confirmed: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
