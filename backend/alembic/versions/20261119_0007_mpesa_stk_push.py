"""M-Pesa STK push payment requests.

Adds one new table; existing data is untouched.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "mpesa_payments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("checkout_request_id", sa.String(64), nullable=True),
        sa.Column("merchant_request_id", sa.String(64), nullable=True),
        sa.Column("phone", sa.String(12), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("sale_total", sa.Numeric(14, 2), nullable=False),
        sa.Column("account_reference", sa.String(12), nullable=False),
        sa.Column("status", sa.String(10), nullable=False, server_default="PENDING"),
        sa.Column("result_code", sa.String(20), nullable=True),
        sa.Column("result_desc", sa.String(255), nullable=True),
        sa.Column("mpesa_receipt_number", sa.String(20), nullable=True),
        sa.Column("paid_phone", sa.String(15), nullable=True),
        sa.Column(
            "initiated_by_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "users.id",
                ondelete="RESTRICT",
                name=op.f("fk_mpesa_payments_initiated_by_id_users"),
            ),
            nullable=False,
        ),
        sa.Column(
            "sale_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "sales.id", ondelete="RESTRICT", name=op.f("fk_mpesa_payments_sale_id_sales")
            ),
            nullable=True,
        ),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("callback_payload", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'SUCCESS', 'FAILED', 'CANCELLED', 'TIMEOUT')",
            name=op.f("ck_mpesa_payments_status_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_mpesa_payments_amount_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mpesa_payments")),
        sa.UniqueConstraint(
            "checkout_request_id", name=op.f("uq_mpesa_payments_checkout_request_id")
        ),
        sa.UniqueConstraint(
            "mpesa_receipt_number", name=op.f("uq_mpesa_payments_mpesa_receipt_number")
        ),
        sa.UniqueConstraint("sale_id", name=op.f("uq_mpesa_payments_sale_id")),
    )
    op.create_index(
        op.f("ix_mpesa_payments_initiated_by_created"),
        "mpesa_payments",
        ["initiated_by_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_mpesa_payments_initiated_by_created"), table_name="mpesa_payments")
    op.drop_table("mpesa_payments")
