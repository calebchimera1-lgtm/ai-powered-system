"""phase3 sales procurement and expenses

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06 13:04:37.341720+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Human-readable document numbers (RCPT-2026-000123) come from these sequences.
SEQUENCES = ("sale_receipt_seq", "sale_return_seq", "purchase_order_seq", "goods_received_seq")

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


def upgrade() -> None:
    for seq in SEQUENCES:
        op.execute(f"CREATE SEQUENCE IF NOT EXISTS {seq}")
    op.create_table(
        "customers",
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_customers")),
    )
    op.create_index(
        "uq_customers_phone",
        "customers",
        ["phone"],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )
    op.create_table(
        "expense_categories",
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expense_categories")),
    )
    op.create_index(
        "uq_expense_categories_name", "expense_categories", [sa.text("lower(name)")], unique=True
    )
    op.create_table(
        "expenses",
        sa.Column("category_id", sa.BigInteger(), nullable=False),
        sa.Column("expense_date", sa.Date(), nullable=False),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("payment_method", sa.String(length=10), nullable=False),
        sa.Column("reference", sa.String(length=50), nullable=True),
        sa.Column("recorded_by_id", sa.BigInteger(), nullable=False),
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
            "payment_method IN ('CASH', 'MPESA', 'CARD', 'BANK')",
            name=op.f("ck_expenses_payment_method_valid"),
        ),
        sa.CheckConstraint("amount > 0", name=op.f("ck_expenses_amount_positive")),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["expense_categories.id"],
            name=op.f("fk_expenses_category_id_expense_categories"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_id"],
            ["users.id"],
            name=op.f("fk_expenses_recorded_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_expenses")),
    )
    op.create_index(op.f("ix_expenses_category_id"), "expenses", ["category_id"], unique=False)
    op.create_index("ix_expenses_date", "expenses", ["expense_date"], unique=False)
    op.create_table(
        "purchase_orders",
        sa.Column("po_number", sa.String(length=32), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("order_date", sa.Date(), nullable=False),
        sa.Column("expected_date", sa.Date(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_by_id", sa.BigInteger(), nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
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
            "status IN ('DRAFT', 'SENT', 'PARTIAL', 'RECEIVED', 'CANCELLED')",
            name=op.f("ck_purchase_orders_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name=op.f("fk_purchase_orders_created_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_purchase_orders_supplier_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_orders")),
        sa.UniqueConstraint("po_number", name=op.f("uq_purchase_orders_po_number")),
    )
    op.create_index("ix_purchase_orders_status", "purchase_orders", ["status"], unique=False)
    op.create_index(
        op.f("ix_purchase_orders_supplier_id"), "purchase_orders", ["supplier_id"], unique=False
    )
    op.create_table(
        "sales",
        sa.Column("receipt_number", sa.String(length=32), nullable=False),
        sa.Column("client_request_id", sa.UUID(), nullable=True),
        sa.Column("cashier_id", sa.BigInteger(), nullable=False),
        sa.Column("customer_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "sold_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("discount_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("cost_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("payment_method", sa.String(length=10), nullable=False),
        sa.Column("payment_reference", sa.String(length=40), nullable=True),
        sa.Column("amount_tendered", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("change_given", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "payment_method IN ('CASH', 'MPESA', 'CARD')",
            name=op.f("ck_sales_payment_method_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('COMPLETED', 'PARTIALLY_RETURNED', 'RETURNED')",
            name=op.f("ck_sales_status_valid"),
        ),
        sa.CheckConstraint(
            "amount_tendered IS NULL OR amount_tendered >= grand_total",
            name=op.f("ck_sales_tendered_covers"),
        ),
        sa.CheckConstraint(
            "discount_total >= 0 AND discount_total <= subtotal", name=op.f("ck_sales_discount_ok")
        ),
        sa.CheckConstraint(
            "grand_total >= 0 AND subtotal >= 0", name=op.f("ck_sales_totals_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["cashier_id"],
            ["users.id"],
            name=op.f("fk_sales_cashier_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["customer_id"],
            ["customers.id"],
            name=op.f("fk_sales_customer_id_customers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales")),
        sa.UniqueConstraint("client_request_id", name=op.f("uq_sales_client_request_id")),
        sa.UniqueConstraint("receipt_number", name=op.f("uq_sales_receipt_number")),
    )
    op.create_index("ix_sales_cashier_sold_at", "sales", ["cashier_id", "sold_at"], unique=False)
    op.create_index("ix_sales_sold_at", "sales", ["sold_at"], unique=False)
    op.create_table(
        "purchase_order_items",
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity_ordered", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("quantity_received", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "quantity_ordered > 0", name=op.f("ck_purchase_order_items_ordered_positive")
        ),
        sa.CheckConstraint(
            "quantity_received >= 0", name=op.f("ck_purchase_order_items_received_non_negative")
        ),
        sa.CheckConstraint(
            "unit_cost >= 0", name=op.f("ck_purchase_order_items_cost_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_purchase_order_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=op.f("fk_purchase_order_items_purchase_order_id_purchase_orders"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_order_items")),
        sa.UniqueConstraint("purchase_order_id", "product_id", name="uq_po_items_product"),
    )
    op.create_index(
        op.f("ix_purchase_order_items_purchase_order_id"),
        "purchase_order_items",
        ["purchase_order_id"],
        unique=False,
    )
    op.create_table(
        "purchases",
        sa.Column("grn_number", sa.String(length=32), nullable=False),
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("purchase_order_id", sa.BigInteger(), nullable=True),
        sa.Column("supplier_invoice_number", sa.String(length=50), nullable=True),
        sa.Column("invoice_date", sa.Date(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("subtotal", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("grand_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("source", sa.String(length=10), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("received_by_id", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "source IN ('MANUAL', 'INVOICE')", name=op.f("ck_purchases_source_valid")
        ),
        sa.CheckConstraint("grand_total >= 0", name=op.f("ck_purchases_total_non_negative")),
        sa.ForeignKeyConstraint(
            ["purchase_order_id"],
            ["purchase_orders.id"],
            name=op.f("fk_purchases_purchase_order_id_purchase_orders"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_id"],
            ["users.id"],
            name=op.f("fk_purchases_received_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["supplier_id"],
            ["suppliers.id"],
            name=op.f("fk_purchases_supplier_id_suppliers"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
        sa.UniqueConstraint("grn_number", name=op.f("uq_purchases_grn_number")),
    )
    op.create_index(
        op.f("ix_purchases_purchase_order_id"), "purchases", ["purchase_order_id"], unique=False
    )
    op.create_index("ix_purchases_received_at", "purchases", ["received_at"], unique=False)
    op.create_index(op.f("ix_purchases_supplier_id"), "purchases", ["supplier_id"], unique=False)
    op.create_index(
        "uq_purchases_supplier_invoice",
        "purchases",
        ["supplier_id", sa.text("upper(supplier_invoice_number)")],
        unique=True,
        postgresql_where=sa.text("supplier_invoice_number IS NOT NULL"),
    )
    op.create_table(
        "sale_items",
        sa.Column("sale_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("product_name", sa.String(length=150), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("discount_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("returned_quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "discount_amount >= 0", name=op.f("ck_sale_items_discount_non_negative")
        ),
        sa.CheckConstraint("line_total >= 0", name=op.f("ck_sale_items_line_total_non_negative")),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_items_quantity_positive")),
        sa.CheckConstraint(
            "returned_quantity >= 0 AND returned_quantity <= quantity",
            name=op.f("ck_sale_items_returned_ok"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_sale_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"], ["sales.id"], name=op.f("fk_sale_items_sale_id_sales"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_items")),
    )
    op.create_index("ix_sale_items_product", "sale_items", ["product_id"], unique=False)
    op.create_index(op.f("ix_sale_items_sale_id"), "sale_items", ["sale_id"], unique=False)
    op.create_table(
        "sale_returns",
        sa.Column("return_number", sa.String(length=32), nullable=False),
        sa.Column("sale_id", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("refund_method", sa.String(length=10), nullable=False),
        sa.Column("refund_total", sa.Numeric(precision=14, scale=2), nullable=False),
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
            "refund_method IN ('CASH', 'MPESA', 'CARD')",
            name=op.f("ck_sale_returns_refund_method_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'APPROVED', 'REJECTED')",
            name=op.f("ck_sale_returns_status_valid"),
        ),
        sa.CheckConstraint("refund_total > 0", name=op.f("ck_sale_returns_refund_positive")),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name=op.f("fk_sale_returns_decided_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["requested_by_id"],
            ["users.id"],
            name=op.f("fk_sale_returns_requested_by_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["sale_id"],
            ["sales.id"],
            name=op.f("fk_sale_returns_sale_id_sales"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_returns")),
        sa.UniqueConstraint("return_number", name=op.f("uq_sale_returns_return_number")),
    )
    op.create_index(op.f("ix_sale_returns_sale_id"), "sale_returns", ["sale_id"], unique=False)
    op.create_index(
        "ix_sale_returns_status_created", "sale_returns", ["status", "created_at"], unique=False
    )
    op.create_table(
        "purchase_items",
        sa.Column("purchase_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("purchase_order_item_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("unit_cost", sa.Numeric(precision=14, scale=4), nullable=False),
        sa.Column("vat_rate", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("tax_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("line_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("previous_unit_cost", sa.Numeric(precision=14, scale=4), nullable=True),
        sa.Column("batch_number", sa.String(length=50), nullable=True),
        sa.Column("expiry_date", sa.Date(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_purchase_items_quantity_positive")),
        sa.CheckConstraint("unit_cost >= 0", name=op.f("ck_purchase_items_cost_non_negative")),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_purchase_items_product_id_products"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_id"],
            ["purchases.id"],
            name=op.f("fk_purchase_items_purchase_id_purchases"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["purchase_order_item_id"],
            ["purchase_order_items.id"],
            name=op.f("fk_purchase_items_purchase_order_item_id_purchase_order_items"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_items")),
    )
    op.create_index("ix_purchase_items_product", "purchase_items", ["product_id"], unique=False)
    op.create_index(
        op.f("ix_purchase_items_purchase_id"), "purchase_items", ["purchase_id"], unique=False
    )
    op.create_table(
        "sale_return_items",
        sa.Column("return_id", sa.BigInteger(), nullable=False),
        sa.Column("sale_item_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Numeric(precision=12, scale=3), nullable=False),
        sa.Column("refund_amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("condition", sa.String(length=12), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.CheckConstraint(
            "condition IN ('RESALEABLE', 'DAMAGED')",
            name=op.f("ck_sale_return_items_condition_valid"),
        ),
        sa.CheckConstraint("quantity > 0", name=op.f("ck_sale_return_items_quantity_positive")),
        sa.ForeignKeyConstraint(
            ["return_id"],
            ["sale_returns.id"],
            name=op.f("fk_sale_return_items_return_id_sale_returns"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["sale_item_id"],
            ["sale_items.id"],
            name=op.f("fk_sale_return_items_sale_item_id_sale_items"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sale_return_items")),
    )
    op.create_index(
        op.f("ix_sale_return_items_return_id"), "sale_return_items", ["return_id"], unique=False
    )
    op.create_index(
        op.f("ix_sale_return_items_sale_item_id"),
        "sale_return_items",
        ["sale_item_id"],
        unique=False,
    )
    categories = sa.table("expense_categories", sa.column("name"), sa.column("is_active"))
    op.bulk_insert(categories, [{"name": n, "is_active": True} for n in DEFAULT_EXPENSE_CATEGORIES])


def downgrade() -> None:
    for seq in SEQUENCES:
        op.execute(f"DROP SEQUENCE IF EXISTS {seq}")
    op.drop_index(op.f("ix_sale_return_items_sale_item_id"), table_name="sale_return_items")
    op.drop_index(op.f("ix_sale_return_items_return_id"), table_name="sale_return_items")
    op.drop_table("sale_return_items")
    op.drop_index(op.f("ix_purchase_items_purchase_id"), table_name="purchase_items")
    op.drop_index("ix_purchase_items_product", table_name="purchase_items")
    op.drop_table("purchase_items")
    op.drop_index("ix_sale_returns_status_created", table_name="sale_returns")
    op.drop_index(op.f("ix_sale_returns_sale_id"), table_name="sale_returns")
    op.drop_table("sale_returns")
    op.drop_index(op.f("ix_sale_items_sale_id"), table_name="sale_items")
    op.drop_index("ix_sale_items_product", table_name="sale_items")
    op.drop_table("sale_items")
    op.drop_index(
        "uq_purchases_supplier_invoice",
        table_name="purchases",
        postgresql_where=sa.text("supplier_invoice_number IS NOT NULL"),
    )
    op.drop_index(op.f("ix_purchases_supplier_id"), table_name="purchases")
    op.drop_index("ix_purchases_received_at", table_name="purchases")
    op.drop_index(op.f("ix_purchases_purchase_order_id"), table_name="purchases")
    op.drop_table("purchases")
    op.drop_index(
        op.f("ix_purchase_order_items_purchase_order_id"), table_name="purchase_order_items"
    )
    op.drop_table("purchase_order_items")
    op.drop_index("ix_sales_sold_at", table_name="sales")
    op.drop_index("ix_sales_cashier_sold_at", table_name="sales")
    op.drop_table("sales")
    op.drop_index(op.f("ix_purchase_orders_supplier_id"), table_name="purchase_orders")
    op.drop_index("ix_purchase_orders_status", table_name="purchase_orders")
    op.drop_table("purchase_orders")
    op.drop_index("ix_expenses_date", table_name="expenses")
    op.drop_index(op.f("ix_expenses_category_id"), table_name="expenses")
    op.drop_table("expenses")
    op.drop_index("uq_expense_categories_name", table_name="expense_categories")
    op.drop_table("expense_categories")
    op.drop_index(
        "uq_customers_phone", table_name="customers", postgresql_where=sa.text("phone IS NOT NULL")
    )
    op.drop_table("customers")
