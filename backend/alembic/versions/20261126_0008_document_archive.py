"""Filing approved invoices in the document archive (Paperless-ngx).

Adds five nullable columns to invoices; existing rows are untouched.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("invoices", sa.Column("archive_status", sa.String(10), nullable=True))
    op.add_column("invoices", sa.Column("archive_task_id", sa.String(64), nullable=True))
    op.add_column("invoices", sa.Column("archive_document_id", sa.Integer(), nullable=True))
    op.add_column("invoices", sa.Column("archive_error", sa.String(255), nullable=True))
    op.add_column("invoices", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in (
        "archived_at",
        "archive_error",
        "archive_document_id",
        "archive_task_id",
        "archive_status",
    ):
        op.drop_column("invoices", col)
