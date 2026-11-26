"""AI accounting assistant: conversation log and actions awaiting confirmation.

Adds three new tables; nothing existing changes.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _now() -> sa.TextClause:
    return sa.text("now()")


def upgrade() -> None:
    op.create_table(
        "assistant_conversations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "users.id", ondelete="RESTRICT", name="fk_assistant_conversations_user_id_users"
            ),
            nullable=False,
        ),
        sa.Column("title", sa.String(120), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assistant_conversations"),
    )
    op.create_index(
        "ix_assistant_conversations_user_updated",
        "assistant_conversations",
        ["user_id", "updated_at"],
    )
    op.create_table(
        "assistant_messages",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "assistant_conversations.id",
                ondelete="CASCADE",
                name="fk_assistant_messages_conversation_id_assistant_conversations",
            ),
            nullable=False,
        ),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("attachment_path", sa.String(255)),
        sa.Column("attachment_name", sa.String(255)),
        sa.Column("attachment_mime", sa.String(40)),
        sa.Column("tool_log", JSONB()),
        sa.Column("model", sa.String(60)),
        sa.Column("input_tokens", sa.Integer()),
        sa.Column("output_tokens", sa.Integer()),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assistant_messages"),
        sa.CheckConstraint(
            "role IN ('user', 'assistant')", name="ck_assistant_messages_role_valid"
        ),
    )
    op.create_index(
        "ix_assistant_messages_conversation_id", "assistant_messages", ["conversation_id"]
    )
    op.create_table(
        "assistant_proposals",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "conversation_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "assistant_conversations.id",
                ondelete="CASCADE",
                name="fk_assistant_proposals_conversation_id_assistant_conversations",
            ),
            nullable=False,
        ),
        sa.Column(
            "message_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "assistant_messages.id",
                ondelete="SET NULL",
                name="fk_assistant_proposals_message_id_assistant_messages",
            ),
        ),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("result_id", sa.BigInteger()),
        sa.Column(
            "decided_by_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "users.id", ondelete="SET NULL", name="fk_assistant_proposals_decided_by_id_users"
            ),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=_now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assistant_proposals"),
        sa.CheckConstraint(
            "kind IN ('EXPENSE', 'INVOICE')", name="ck_assistant_proposals_kind_valid"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')",
            name="ck_assistant_proposals_status_valid",
        ),
    )
    op.create_index(
        "ix_assistant_proposals_conversation_id", "assistant_proposals", ["conversation_id"]
    )


def downgrade() -> None:
    op.drop_table("assistant_proposals")
    op.drop_table("assistant_messages")
    op.drop_table("assistant_conversations")
