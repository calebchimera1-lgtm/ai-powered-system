"""phase4 invoice digitization

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-07 09:32:04.150673+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "supplier_product_aliases",
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("alias_text", sa.String(length=255), nullable=False),
        sa.Column("times_confirmed", sa.Integer(), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_supplier_product_aliases_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_supplier_product_aliases_supplier_id_suppliers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_supplier_product_aliases")),
        sa.UniqueConstraint("supplier_id", "alias_text", name="uq_supplier_alias_text"),
    )
    op.create_index(
        op.f("ix_supplier_product_aliases_product_id"),
        "supplier_product_aliases",
        ["product_id"],
        unique=False,
    )
    op.create_table(
        "invoices",
        sa.Column("file_path", sa.String(length=255), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("mime_type", sa.String(length=50), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("ocr_engine", sa.String(length=20), nullable=True),
        sa.Column("ocr_text", sa.Text(), nullable=True),
        sa.Column("quality", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processing_steps", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("processing_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("supplier_id", sa.BigInteger(), nullable=True),
        sa.Column("supplier_match_score", sa.Float(), nullable=True),
        sa.Column("extracted_supplier_name", sa.String(length=255), nullable=True),
        sa.Column("kra_pin", sa.String(length=11), nullable=True),
        sa.Column("invoice_number", sa.String(length=50), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("grand_total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("prices_include_vat", sa.Boolean(), nullable=False),
        sa.Column("field_confidences", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("original_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("reviewed_by_id", sa.BigInteger(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.Column("purchase_id", sa.BigInteger(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'NEEDS_REVIEW', 'APPROVED', 'REJECTED', 'FAILED')",
            name=op.f("ck_invoices_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            name=op.f("fk_invoices_purchase_id_purchases"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_id"],
            ["users.id"],
            name=op.f("fk_invoices_reviewed_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_invoices_supplier_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_id"],
            ["users.id"],
            name=op.f("fk_invoices_uploaded_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoices")),
        sa.UniqueConstraint("file_sha256", name=op.f("uq_invoices_file_sha256")),
        sa.UniqueConstraint("purchase_id", name=op.f("uq_invoices_purchase_id")),
    )
    op.create_index(
        "ix_invoices_status_created", "invoices", ["status", "created_at"], unique=False
    )
    op.create_index(
        "uq_invoices_approved_number",
        "invoices",
        ["supplier_id", sa.text("upper(invoice_number)")],
        unique=True,
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.create_table(
        "invoice_items",
        sa.Column("invoice_id", sa.BigInteger(), nullable=False),
        sa.Column("line_no", sa.Integer(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=True),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("item_code", sa.String(length=50), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("match_method", sa.String(length=8), nullable=False),
        sa.Column("match_score", sa.Float(), nullable=True),
        sa.Column("suggested", sa.Boolean(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("arithmetic_ok", sa.Boolean(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("original", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("was_corrected", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "match_method IN ('CODE', 'ALIAS', 'FUZZY', 'MANUAL', 'NONE')",
            name=op.f("ck_invoice_items_match_method_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["invoice_id"],
            ["invoices.id"],
            name=op.f("fk_invoice_items_invoice_id_invoices"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_invoice_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_invoice_items")),
    )
    op.create_index(
        op.f("ix_invoice_items_invoice_id"), "invoice_items", ["invoice_id"], unique=False
    )
    op.create_index(
        op.f("ix_invoice_items_product_id"), "invoice_items", ["product_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_invoice_items_product_id"), table_name="invoice_items")
    op.drop_index(op.f("ix_invoice_items_invoice_id"), table_name="invoice_items")
    op.drop_table("invoice_items")
    op.drop_index(
        "uq_invoices_approved_number",
        table_name="invoices",
        postgresql_where=sa.text("status = 'APPROVED'"),
    )
    op.drop_index("ix_invoices_status_created", table_name="invoices")
    op.drop_table("invoices")
    op.drop_index(
        op.f("ix_supplier_product_aliases_product_id"), table_name="supplier_product_aliases"
    )
    op.drop_table("supplier_product_aliases")
