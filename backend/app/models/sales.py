"""Sales: customers, sales (receipts), sale lines and customer returns."""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Cost, Money, Product, Qty

PAYMENT_METHODS = ("CASH", "MPESA", "CARD")
SALE_STATUSES = ("COMPLETED", "PARTIALLY_RETURNED", "RETURNED")
RETURN_STATUSES = ("PENDING", "APPROVED", "REJECTED")
RETURN_CONDITIONS = ("RESALEABLE", "DAMAGED")


class Customer(IdMixin, TimestampMixin, Base):
    """Optional customer details (for receipts sent by phone, returns, loyalty later)."""

    __tablename__ = "customers"
    __table_args__ = (
        Index(
            "uq_customers_phone", "phone", unique=True, postgresql_where=text("phone IS NOT NULL")
        ),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255))
    notes: Mapped[str | None] = mapped_column(Text)


class Sale(IdMixin, Base):
    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_sold_at", "sold_at"),
        Index("ix_sales_cashier_sold_at", "cashier_id", "sold_at"),
        CheckConstraint(f"payment_method IN {PAYMENT_METHODS!r}", name="payment_method_valid"),
        CheckConstraint(f"status IN {SALE_STATUSES!r}", name="status_valid"),
        CheckConstraint("grand_total >= 0 AND subtotal >= 0", name="totals_non_negative"),
        CheckConstraint("discount_total >= 0 AND discount_total <= subtotal", name="discount_ok"),
        CheckConstraint(
            "amount_tendered IS NULL OR amount_tendered >= grand_total", name="tendered_covers"
        ),
    )

    receipt_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    # Sent by the till with each checkout so a double-click or network retry
    # cannot record the same sale twice.
    client_request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), unique=True)
    cashier_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id", ondelete="RESTRICT"))
    sold_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="COMPLETED")
    # All amounts in KES. Prices are VAT-inclusive.
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)  # before discounts
    discount_total: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal(0))
    tax_total: Mapped[Decimal] = mapped_column(Money, nullable=False)  # VAT included in total
    grand_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    cost_total: Mapped[Decimal] = mapped_column(Money, nullable=False)  # COGS at sale time
    payment_method: Mapped[str] = mapped_column(String(10), nullable=False)
    payment_reference: Mapped[str | None] = mapped_column(String(40))
    amount_tendered: Mapped[Decimal | None] = mapped_column(Money)
    change_given: Mapped[Decimal | None] = mapped_column(Money)
    notes: Mapped[str | None] = mapped_column(Text)

    cashier: Mapped[User] = relationship(lazy="joined")
    customer: Mapped[Customer | None] = relationship(lazy="joined")
    items: Mapped[list["SaleItem"]] = relationship(
        back_populates="sale", lazy="selectin", order_by="SaleItem.id", cascade="all, delete-orphan"
    )


class SaleItem(IdMixin, Base):
    __tablename__ = "sale_items"
    __table_args__ = (
        Index("ix_sale_items_product", "product_id"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(
            "returned_quantity >= 0 AND returned_quantity <= quantity", name="returned_ok"
        ),
        CheckConstraint("discount_amount >= 0", name="discount_non_negative"),
        CheckConstraint("line_total >= 0", name="line_total_non_negative"),
    )

    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    product_name: Mapped[str] = mapped_column(String(150), nullable=False)  # as printed
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)  # VAT-inclusive
    discount_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal(0))
    vat_rate: Mapped[Decimal] = mapped_column(Money, nullable=False)
    tax_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Money, nullable=False)  # after discounts
    unit_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False)  # WAC snapshot -> COGS
    returned_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False, default=Decimal(0))

    sale: Mapped[Sale] = relationship(back_populates="items")
    product: Mapped[Product] = relationship(lazy="joined")


class SaleReturn(IdMixin, Base):
    __tablename__ = "sale_returns"
    __table_args__ = (
        Index("ix_sale_returns_status_created", "status", "created_at"),
        CheckConstraint(f"status IN {RETURN_STATUSES!r}", name="status_valid"),
        CheckConstraint(f"refund_method IN {PAYMENT_METHODS!r}", name="refund_method_valid"),
        CheckConstraint("refund_total > 0", name="refund_positive"),
    )

    return_number: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    sale_id: Mapped[int] = mapped_column(
        ForeignKey("sales.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="PENDING")
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    refund_method: Mapped[str] = mapped_column(String(10), nullable=False)
    refund_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    requested_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    sale: Mapped[Sale] = relationship(lazy="joined")
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")
    items: Mapped[list["SaleReturnItem"]] = relationship(
        back_populates="sale_return",
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="SaleReturnItem.id",
    )


class SaleReturnItem(IdMixin, Base):
    __tablename__ = "sale_return_items"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint(f"condition IN {RETURN_CONDITIONS!r}", name="condition_valid"),
    )

    return_id: Mapped[int] = mapped_column(
        ForeignKey("sale_returns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sale_item_id: Mapped[int] = mapped_column(
        ForeignKey("sale_items.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    condition: Mapped[str] = mapped_column(String(12), nullable=False)

    sale_return: Mapped[SaleReturn] = relationship(back_populates="items")
    sale_item: Mapped[SaleItem] = relationship(lazy="joined")
