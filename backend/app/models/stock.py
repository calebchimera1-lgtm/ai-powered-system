"""Stock ledger (append-only movements) and manual stock adjustments."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin
from app.models.catalog import Cost, Product, ProductBatch, Qty

INBOUND_TYPES = ("OPENING", "PURCHASE_IN", "RETURN_IN", "ADJUSTMENT_IN")
OUTBOUND_TYPES = ("SALE_OUT", "RETURN_TO_SUPPLIER", "DAMAGED", "EXPIRED", "ADJUSTMENT_OUT")
MOVEMENT_TYPES = INBOUND_TYPES + OUTBOUND_TYPES


class StockMovement(IdMixin, Base):
    """One change to a product's stock. Never updated or deleted (enforced by a trigger)."""

    __tablename__ = "stock_movements"
    __table_args__ = (
        Index("ix_stock_movements_product_created", "product_id", "created_at"),
        Index("ix_stock_movements_type_created", "movement_type", "created_at"),
        Index("ix_stock_movements_user_created", "user_id", "created_at"),
        Index("ix_stock_movements_reference", "reference_type", "reference_id"),
        CheckConstraint(f"movement_type IN {MOVEMENT_TYPES!r}", name="type_valid"),
        CheckConstraint("quantity <> 0", name="quantity_non_zero"),
        CheckConstraint(
            f"(movement_type IN {INBOUND_TYPES!r} AND quantity > 0) OR "
            f"(movement_type IN {OUTBOUND_TYPES!r} AND quantity < 0)",
            name="sign_matches_type",
        ),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_batches.id", ondelete="RESTRICT")
    )
    movement_type: Mapped[str] = mapped_column(String(24), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False)
    balance_after: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(32))
    reference_id: Mapped[str | None] = mapped_column(String(64))
    reason: Mapped[str | None] = mapped_column(Text)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    product: Mapped[Product] = relationship(lazy="joined")
    batch: Mapped[ProductBatch | None] = relationship(lazy="joined")
    user: Mapped[User] = relationship(lazy="joined")


ADJUSTMENT_REASONS = (
    "COUNT_CORRECTION",
    "FOUND_STOCK",
    "DATA_ENTRY_ERROR",
    "THEFT_SUSPECTED",
    "INTERNAL_USE",
    "OTHER",
)
ADJUSTMENT_STATUSES = ("PENDING", "APPROVED", "REJECTED")


class StockAdjustment(IdMixin, Base):
    """A manual correction. Large ones wait for a manager's approval before applying."""

    __tablename__ = "stock_adjustments"
    __table_args__ = (
        Index("ix_stock_adjustments_status_created", "status", "created_at"),
        Index("ix_stock_adjustments_product", "product_id"),
        CheckConstraint(f"reason_code IN {ADJUSTMENT_REASONS!r}", name="reason_valid"),
        CheckConstraint(f"status IN {ADJUSTMENT_STATUSES!r}", name="status_valid"),
        CheckConstraint("quantity_change <> 0", name="change_non_zero"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    batch_id: Mapped[int | None] = mapped_column(
        ForeignKey("product_batches.id", ondelete="RESTRICT")
    )
    reason_code: Mapped[str] = mapped_column(String(24), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    system_quantity: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    counted_quantity: Mapped[Decimal | None] = mapped_column(Qty)
    quantity_change: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    unit_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False)
    value_impact: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    allow_negative: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="PENDING")
    requested_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    decision_note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    product: Mapped[Product] = relationship(lazy="joined")
    requested_by: Mapped[User] = relationship(foreign_keys=[requested_by_id], lazy="joined")
    decided_by: Mapped[User | None] = relationship(foreign_keys=[decided_by_id], lazy="joined")
