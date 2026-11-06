"""Supplier tables."""

from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, IdMixin, TimestampMixin


class Supplier(IdMixin, TimestampMixin, Base):
    __tablename__ = "suppliers"
    __table_args__ = (
        Index("uq_suppliers_name", text("lower(name)"), unique=True),
        Index(
            "uq_suppliers_kra_pin",
            "kra_pin",
            unique=True,
            postgresql_where=text("kra_pin IS NOT NULL"),
        ),
        CheckConstraint("payment_terms_days >= 0", name="terms_non_negative"),
    )

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    kra_pin: Mapped[str | None] = mapped_column(String(11))
    contact_person: Mapped[str | None] = mapped_column(String(150))
    phone: Mapped[str | None] = mapped_column(String(30))
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(Text)
    payment_terms_days: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class SupplierProduct(TimestampMixin, Base):
    """What a supplier sells us, their code for it and the last price they charged."""

    __tablename__ = "supplier_products"
    __table_args__ = (
        CheckConstraint("last_unit_price IS NULL OR last_unit_price >= 0", name="price_ok"),
        CheckConstraint("lead_time_days IS NULL OR lead_time_days >= 0", name="lead_time_ok"),
    )

    supplier_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("suppliers.id", ondelete="CASCADE"), primary_key=True
    )
    product_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("products.id", ondelete="CASCADE"), primary_key=True
    )
    supplier_sku: Mapped[str | None] = mapped_column(String(50))
    last_unit_price: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)

    supplier: Mapped[Supplier] = relationship(lazy="joined")
    product: Mapped["Product"] = relationship(lazy="joined")  # noqa: F821
