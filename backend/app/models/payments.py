"""M-Pesa STK push ("Lipa Na M-Pesa Online") payment requests.

A row is created when the till sends a payment prompt to a customer's phone. Safaricom then
reports the outcome by callback, or the app asks for it (STK query). A successful payment
can be attached to exactly one sale.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import BigInteger, CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin
from app.models.catalog import Money

MPESA_STATUSES = ("PENDING", "SUCCESS", "FAILED", "CANCELLED", "TIMEOUT")


class MpesaPayment(IdMixin, TimestampMixin, Base):
    __tablename__ = "mpesa_payments"
    __table_args__ = (
        CheckConstraint(f"status IN {MPESA_STATUSES!r}", name="status_valid"),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index("ix_mpesa_payments_initiated_by_created", "initiated_by_id", "created_at"),
    )

    # Safaricom's ids for the request; checkout_request_id is how callbacks find the row.
    checkout_request_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    merchant_request_id: Mapped[str | None] = mapped_column(String(64))
    phone: Mapped[str] = mapped_column(String(12), nullable=False)  # 2547XXXXXXXX
    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # whole shillings (M-Pesa rule)
    sale_total: Mapped[Decimal] = mapped_column(Money, nullable=False)
    account_reference: Mapped[str] = mapped_column(String(12), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    result_code: Mapped[str | None] = mapped_column(String(20))
    result_desc: Mapped[str | None] = mapped_column(String(255))
    mpesa_receipt_number: Mapped[str | None] = mapped_column(String(20), unique=True)
    paid_phone: Mapped[str | None] = mapped_column(String(15))
    initiated_by_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    sale_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("sales.id", ondelete="RESTRICT"), unique=True
    )
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    callback_payload: Mapped[dict | None] = mapped_column(JSONB)

    initiated_by: Mapped[User] = relationship(lazy="joined")
