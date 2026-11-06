"""phase2 catalogue, suppliers and stock ledger

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06 02:43:16.140166+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


LEDGER_GUARD = """
CREATE OR REPLACE FUNCTION stock_movements_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'stock_movements is an append-only ledger; % is not allowed', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER stock_movements_no_update_delete
    BEFORE UPDATE OR DELETE ON stock_movements
    FOR EACH ROW EXECUTE FUNCTION stock_movements_append_only();
"""


def upgrade() -> None:
    # Trigram index support for fuzzy product-name search.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.create_table(
        "categories",
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            "parent_id IS NULL OR parent_id <> id", name=op.f("ck_categories_not_own_parent")
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"],
            ["categories.id"],
            name=op.f("fk_categories_parent_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_categories")),
    )
    op.create_index(op.f("ix_categories_parent_id"), "categories", ["parent_id"], unique=False)
    op.create_index(
        "uq_categories_parent_name",
        "categories",
        [sa.text("coalesce(parent_id, 0)"), sa.text("lower(name)")],
        unique=True,
    )
    op.create_table(
        "suppliers",
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("kra_pin", sa.String(length=11), nullable=True),
        sa.Column("contact_person", sa.String(length=150), nullable=True),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("payment_terms_days", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
        sa.CheckConstraint("payment_terms_days >= 0", name=op.f("ck_suppliers_terms_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
    )
    op.create_index(
        "uq_suppliers_kra_pin",
        "suppliers",
        ["kra_pin"],
        unique=True,
        postgresql_where=sa.text("kra_pin IS NOT NULL"),
    )
    op.create_index("uq_suppliers_name", "suppliers", [sa.text("lower(name)")], unique=True)
    op.create_table(
        "products",
        sa.Column("sku", sa.String(length=40), nullable=False),
        sa.Column("barcode", sa.String(length=32), nullable=True),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column("default_supplier_id", sa.BigInteger(), nullable=True),
        sa.Column("unit_of_measure", sa.String(length=10), nullable=False),
        sa.Column("image_path", sa.String(length=255), nullable=True),
        sa.Column("selling_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("purchase_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("avg_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("quantity_on_hand", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("min_stock_level", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("max_stock_level", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("reorder_lead_time_days", sa.Integer(), nullable=False),
        sa.Column("tracks_expiry", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
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
            "unit_of_measure IN ('pcs', 'pack', 'box', 'dozen', 'bottle', 'carton', 'bag', 'kg', 'g', 'l', 'ml')",
            name=op.f("ck_products_unit_valid"),
        ),
        sa.CheckConstraint("avg_cost >= 0", name=op.f("ck_products_avg_cost_non_negative")),
        sa.CheckConstraint(
            "max_stock_level IS NULL OR max_stock_level >= min_stock_level",
            name=op.f("ck_products_max_not_below_min"),
        ),
        sa.CheckConstraint("min_stock_level >= 0", name=op.f("ck_products_min_stock_non_negative")),
        sa.CheckConstraint(
            "purchase_price >= 0", name=op.f("ck_products_purchase_price_non_negative")
        ),
        sa.CheckConstraint(
            "reorder_lead_time_days >= 0", name=op.f("ck_products_lead_time_non_negative")
        ),
        sa.CheckConstraint(
            "selling_price >= 0", name=op.f("ck_products_selling_price_non_negative")
        ),
        sa.CheckConstraint(
            "vat_rate >= 0 AND vat_rate <= 100", name=op.f("ck_products_vat_rate_range")
        ),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["categories.id"],
            name=op.f("fk_products_category_id_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["default_supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_products_default_supplier_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
    )
    op.create_index(op.f("ix_products_category_id"), "products", ["category_id"], unique=False)
    op.create_index(
        op.f("ix_products_default_supplier_id"), "products", ["default_supplier_id"], unique=False
    )
    op.create_index(
        "ix_products_name_trgm",
        "products",
        ["name"],
        unique=False,
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.create_index(
        "uq_products_barcode",
        "products",
        ["barcode"],
        unique=True,
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.create_index("uq_products_sku", "products", [sa.text("upper(sku)")], unique=True)
    op.create_table(
        "product_batches",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_number", sa.String(length=50), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("quantity_received", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("quantity_remaining", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "quantity_received > 0", name=op.f("ck_product_batches_received_positive")
        ),
        sa.CheckConstraint(
            "quantity_remaining <= quantity_received",
            name=op.f("ck_product_batches_remaining_le_received"),
        ),
        sa.CheckConstraint(
            "quantity_remaining >= 0", name=op.f("ck_product_batches_remaining_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_product_batches_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_product_batches")),
    )
    op.create_index(
        "ix_product_batches_product_expiry",
        "product_batches",
        ["product_id", "expiry_date"],
        unique=False,
    )
    op.create_table(
        "supplier_products",
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_sku", sa.String(length=50), nullable=True),
        sa.Column("last_unit_price", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("lead_time_days", sa.Integer(), nullable=True),
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
            "last_unit_price IS NULL OR last_unit_price >= 0",
            name=op.f("ck_supplier_products_price_ok"),
        ),
        sa.CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name=op.f("ck_supplier_products_lead_time_ok"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_supplier_products_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_supplier_products_supplier_id_suppliers"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("supplier_id", "product_id", name=op.f("pk_supplier_products")),
    )
    op.create_table(
        "stock_adjustments",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=True),
        sa.Column("reason_code", sa.String(length=24), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("system_quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("counted_quantity", sa.Numeric(precision=12, scale=3), nullable=True),
        sa.Column("quantity_change", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("value_impact", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("allow_negative", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("requested_by_id", sa.BigInteger(), nullable=False),
        sa.Column("decided_by_id", sa.BigInteger(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "reason_code IN ('COUNT_CORRECTION', 'FOUND_STOCK', 'DATA_ENTRY_ERROR', 'THEFT_SUSPECTED', 'INTERNAL_USE', 'OTHER')",
            name=op.f("ck_stock_adjustments_reason_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name=op.f("ck_stock_adjustments_status_valid"),
        ),
        sa.CheckConstraint(
            "quantity_change <> 0", name=op.f("ck_stock_adjustments_change_non_zero")
        ),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["product_batches.id"],
            name=op.f("fk_stock_adjustments_batch_id_product_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_stock_adjustments_decided_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_adjustments_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_stock_adjustments_requested_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_adjustments")),
    )
    op.create_index(
        "ix_stock_adjustments_product", "stock_adjustments", ["product_id"], unique=False
    )
    op.create_index(
        "ix_stock_adjustments_status_created",
        "stock_adjustments",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "stock_movements",
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("batch_id", sa.BigInteger(), nullable=True),
        sa.Column("movement_type", sa.String(length=24), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("reference_type", sa.String(length=32), nullable=True),
        sa.Column("reference_id", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "(movement_type IN ('OPENING', 'PURCHASE_IN', 'RETURN_IN', 'ADJUSTMENT_IN') AND quantity > 0) OR (movement_type IN ('SALE_OUT', 'RETURN_TO_SUPPLIER', 'DAMAGED', 'EXPIRED', 'ADJUSTMENT_OUT') AND quantity < 0)",
            name=op.f("ck_stock_movements_sign_matches_type"),
        ),
        sa.CheckConstraint(
            "movement_type IN ('OPENING', 'PURCHASE_IN', 'RETURN_IN', 'ADJUSTMENT_IN', 'SALE_OUT', 'RETURN_TO_SUPPLIER', 'DAMAGED', 'EXPIRED', 'ADJUSTMENT_OUT')",
            name=op.f("ck_stock_movements_type_valid"),
        ),
        sa.CheckConstraint("quantity <> 0", name=op.f("ck_stock_movements_quantity_non_zero")),
        sa.ForeignKeyConstraint(
            ["batch_id"],
            ["product_batches.id"],
            name=op.f("fk_stock_movements_batch_id_product_batches"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_stock_movements_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_stock_movements_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stock_movements")),
    )
    op.create_index(
        "ix_stock_movements_product_created",
        "stock_movements",
        ["product_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_stock_movements_reference",
        "stock_movements",
        ["reference_type", "reference_id"],
        unique=False,
    )
    op.create_index(
        "ix_stock_movements_type_created",
        "stock_movements",
        ["movement_type", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_stock_movements_user_created",
        "stock_movements",
        ["user_id", "created_at"],
        unique=False,
    )
    op.execute(LEDGER_GUARD)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS stock_movements_no_update_delete ON stock_movements")
    op.execute("DROP FUNCTION IF EXISTS stock_movements_append_only()")
    op.drop_index("ix_stock_movements_user_created", table_name="stock_movements")
    op.drop_index("ix_stock_movements_type_created", table_name="stock_movements")
    op.drop_index("ix_stock_movements_reference", table_name="stock_movements")
    op.drop_index("ix_stock_movements_product_created", table_name="stock_movements")
    op.drop_table("stock_movements")
    op.drop_index("ix_stock_adjustments_status_created", table_name="stock_adjustments")
    op.drop_index("ix_stock_adjustments_product", table_name="stock_adjustments")
    op.drop_table("stock_adjustments")
    op.drop_table("supplier_products")
    op.drop_index("ix_product_batches_product_expiry", table_name="product_batches")
    op.drop_table("product_batches")
    op.drop_index("uq_products_sku", table_name="products")
    op.drop_index(
        "uq_products_barcode",
        table_name="products",
        postgresql_where=sa.text("barcode IS NOT NULL"),
    )
    op.drop_index(
        "ix_products_name_trgm",
        table_name="products",
        postgresql_using="gin",
        postgresql_ops={"name": "gin_trgm_ops"},
    )
    op.drop_index(op.f("ix_products_default_supplier_id"), table_name="products")
    op.drop_index(op.f("ix_products_category_id"), table_name="products")
    op.drop_table("products")
    op.drop_index("uq_suppliers_name", table_name="suppliers")
    op.drop_index(
        "uq_suppliers_kra_pin",
        table_name="suppliers",
        postgresql_where=sa.text("kra_pin IS NOT NULL"),
    )
    op.drop_table("suppliers")
    op.drop_index("uq_categories_parent_name", table_name="categories")
    op.drop_index(op.f("ix_categories_parent_id"), table_name="categories")
    op.drop_table("categories")
