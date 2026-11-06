"""Procurement: purchase orders and goods received (purchases)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Cost, Money, Product, Qty
from app.models.supplier import Supplier

PO_STATUSES = ("DRAFT", "SENT", "PARTIAL", "RECEIVED", "CANCELLED")
PURCHASE_SOURCES = ("MANUAL", "INVOICE")


class PurchaseOrder(IdMixin, TimestampMixin, Base):
    __tablename__ = "purchase_orders"
    __table_args__ = (
        Index("ix_purchase_orders_status", "status"),
        CheckConstraint(f"status IN {PO_STATUSES!r}", name="status_valid"),
    )

    po_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="DRAFT")
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    expected_date: Mapped[date | None] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    created_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    created_by: Mapped[User] = relationship(lazy="joined")
    items: Mapped[list["PurchaseOrderItem"]] = relationship(
        back_populates="order",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="PurchaseOrderItem.id",
    )


class PurchaseOrderItem(IdMixin, Base):
    __tablename__ = "purchase_order_items"
    __table_args__ = (
        UniqueConstraint("purchase_order_id", "product_id", name="uq_po_items_product"),
        CheckConstraint("quantity_ordered > 0", name="ordered_positive"),
        CheckConstraint("quantity_received >= 0", name="received_non_negative"),
        CheckConstraint("unit_cost >= 0", name="cost_non_negative"),
    )

    purchase_order_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantity_ordered: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    quantity_received: Mapped[Decimal] = mapped_column(Qty, nullable=False, default=Decimal(0))
    unit_cost: Mapped[Decimal] = mapped_column(Money, nullable=False)  # expected, excl. VAT

    order: Mapped[PurchaseOrder] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")


class Purchase(IdMixin, Base):
    """Goods received note (GRN): stock that actually arrived, usually with an invoice."""

    __tablename__ = "purchases"
    __table_args__ = (
        Index("ix_purchases_received_at", "received_at"),
        # The same supplier invoice can only be received once.
        Index(
            "uq_purchases_supplier_invoice",
            "supplier_id",
            text("upper(supplier_invoice_number)"),
            unique=True,
            postgresql_where=text("supplier_invoice_number IS NOT NULL"),
        ),
        CheckConstraint(f"source IN {PURCHASE_SOURCES!r}", name="source_valid"),
        CheckConstraint("grand_total >= 0", name="total_non_negative"),
    )

    grn_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    purchase_order_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_orders.id", ondelete="RESTRICT"), index=True
    )
    supplier_invoice_number: Mapped[str | None] = mapped_column(String(50))
    invoice_date: Mapped[date | None] = mapped_column(Date)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    # Costs are VAT-exclusive (input VAT is reclaimable); VAT is recorded separately.
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="MANUAL")
    notes: Mapped[str | None] = mapped_column(Text)
    received_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    purchase_order: Mapped[PurchaseOrder | None] = relationship(lazy="joined")
    received_by: Mapped[User] = relationship(lazy="joined")
    items: Mapped[list["PurchaseItem"]] = relationship(
        back_populates="purchase",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="PurchaseItem.id",
    )


class PurchaseItem(IdMixin, Base):
    __tablename__ = "purchase_items"
    __table_args__ = (
        Index("ix_purchase_items_product", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_cost >= 0", name="cost_non_negative"),
    )

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    purchase_order_item_id: Mapped[int | None] = mapped_column(
        ForeignKey("purchase_order_items.id", ondelete="SET NULL")
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False)  # excl. VAT
    vat_rate: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)  # incl. VAT
    previous_unit_cost: Mapped[Decimal | None] = mapped_column(Cost)  # for price-change alerts
    batch_number: Mapped[str | None] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date)

    purchase: Mapped[Purchase] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")
