"""Operating expenses (rent, salaries, electricity...) for net-profit estimates."""

from datetime import date
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Money
from app.models.sales import PAYMENT_METHODS

EXPENSE_PAYMENT_METHODS = PAYMENT_METHODS + ("BANK",)


class ExpenseCategory(IdMixin, Base):
    __tablename__ = "expense_categories"
    __table_args__ = (Index("uq_expense_categories_name", text("lower(name)"), unique=True),)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Expense(IdMixin, TimestampMixin, Base):
    __tablename__ = "expenses"
    __table_args__ = (
        Index("ix_expenses_date", "expense_date"),
        CheckConstraint("amount > 0", name="amount_positive"),
        CheckConstraint(
            f"payment_method IN {EXPENSE_PAYMENT_METHODS!r}", name="payment_method_valid"
        ),
    )

    category_id: Mapped[int] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    expense_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(10), nullable=False, default="CASH")
    reference: Mapped[str | None] = mapped_column(String(50))
    recorded_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )

    category: Mapped[ExpenseCategory] = relationship(lazy="joined")
    recorded_by: Mapped[User] = relationship(lazy="joined")


DEFAULT_EXPENSE_CATEGORIES = (
    "Rent",
    "Salaries and wages",
    "Electricity",
    "Water",
    "Transport and delivery",
    "Security",
    "Repairs and maintenance",
    "Licences and permits",
    "Bank and M-Pesa charges",
    "Other",
)
