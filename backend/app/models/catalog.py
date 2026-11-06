"""Catalogue tables: categories, products and product batches (expiry tracking)."""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin

# Units sold in whole numbers vs. loose goods that can be weighed/measured.
COUNT_UNITS = ("pcs", "pack", "box", "dozen", "bottle", "carton", "bag")
MEASURE_UNITS = ("kg", "g", "l", "ml")
UNITS = COUNT_UNITS + MEASURE_UNITS

Money = Numeric(14, 2)
Cost = Numeric(14, 4)  # weighted average cost keeps extra precision
Qty = Numeric(12, 3)


class Category(IdMixin, TimestampMixin, Base):
    __tablename__ = "categories"
    __table_args__ = (
        # Names are unique (case-insensitive) among siblings, including top level.
        Index(
            "uq_categories_parent_name",
            text("coalesce(parent_id, 0)"),
            text("lower(name)"),
            unique=True,
        ),
        CheckConstraint("parent_id IS NULL OR parent_id <> id", name="not_own_parent"),
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    parent: Mapped["Category | None"] = relationship(remote_side="Category.id", lazy="joined")


class Product(IdMixin, TimestampMixin, Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("uq_products_sku", text("upper(sku)"), unique=True),
        Index(
            "uq_products_barcode",
            "barcode",
            unique=True,
            postgresql_where=text("barcode IS NOT NULL"),
        ),
        Index(
            "ix_products_name_trgm",
            "name",
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
        ),
        CheckConstraint("selling_price >= 0", name="selling_price_non_negative"),
        CheckConstraint("purchase_price >= 0", name="purchase_price_non_negative"),
        CheckConstraint("avg_cost >= 0", name="avg_cost_non_negative"),
        CheckConstraint("vat_rate >= 0 AND vat_rate <= 100", name="vat_rate_range"),
        CheckConstraint("min_stock_level >= 0", name="min_stock_non_negative"),
        CheckConstraint(
            "max_stock_level IS NULL OR max_stock_level >= min_stock_level",
            name="max_not_below_min",
        ),
        CheckConstraint("reorder_lead_time_days >= 0", name="lead_time_non_negative"),
        CheckConstraint(f"unit_of_measure IN {UNITS!r}", name="unit_valid"),
    )

    sku: Mapped[str] = mapped_column(String(40), nullable=False)
    barcode: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("categories.id", ondelete="RESTRICT"), index=True
    )
    default_supplier_id: Mapped[int | None] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), index=True
    )
    unit_of_measure: Mapped[str] = mapped_column(String(10), nullable=False, default="pcs")
    image_path: Mapped[str | None] = mapped_column(String(255))

    # Prices are VAT-inclusive, as on Kenyan shelf labels.
    selling_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    purchase_price: Mapped[Decimal] = mapped_column(Money, nullable=False, default=Decimal("0"))
    avg_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False, default=Decimal("0"))
    vat_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("16"))

    # Cached running balance; the stock_movements ledger is the source of truth.
    quantity_on_hand: Mapped[Decimal] = mapped_column(Qty, nullable=False, default=Decimal("0"))
    min_stock_level: Mapped[Decimal] = mapped_column(Qty, nullable=False, default=Decimal("0"))
    max_stock_level: Mapped[Decimal | None] = mapped_column(Qty)
    reorder_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    tracks_expiry: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    category: Mapped[Category | None] = relationship(lazy="joined")
    default_supplier: Mapped["Supplier | None"] = relationship(lazy="joined")  # noqa: F821


class ProductBatch(IdMixin, Base):
    """A received lot of a product, used for expiry tracking and FEFO deduction."""

    __tablename__ = "product_batches"
    __table_args__ = (
        Index("ix_product_batches_product_expiry", "product_id", "expiry_date"),
        CheckConstraint("quantity_remaining >= 0", name="remaining_non_negative"),
        CheckConstraint("quantity_received > 0", name="received_positive"),
        CheckConstraint("quantity_remaining <= quantity_received", name="remaining_le_received"),
    )

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    batch_number: Mapped[str | None] = mapped_column(String(50))
    expiry_date: Mapped[date | None] = mapped_column(Date)
    quantity_received: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    quantity_remaining: Mapped[Decimal] = mapped_column(Qty, nullable=False)
    unit_cost: Mapped[Decimal] = mapped_column(Cost, nullable=False)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
