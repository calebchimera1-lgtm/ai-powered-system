"""AI accounting assistant: conversations, messages and actions waiting for confirmation.

Everything said to and by the assistant is kept (who asked, what, which records the AI
looked at, what it proposed and who confirmed it), so the shop has a complete log.
"""

from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin, TimestampMixin

PROPOSAL_KINDS = ("EXPENSE", "INVOICE")
PROPOSAL_STATUSES = ("PENDING", "CONFIRMED", "CANCELLED")


class AssistantConversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "assistant_conversations"
    __table_args__ = (Index("ix_assistant_conversations_user_updated", "user_id", "updated_at"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)

    user: Mapped[User] = relationship(lazy="joined")
    messages: Mapped[list["AssistantMessage"]] = relationship(
        back_populates="conversation", order_by="AssistantMessage.id", lazy="selectin"
    )


class AssistantMessage(IdMixin, Base):
    __tablename__ = "assistant_messages"
    __table_args__ = (CheckConstraint("role IN ('user', 'assistant')", name="role_valid"),)

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(10), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attachment_path: Mapped[str | None] = mapped_column(String(255))
    attachment_name: Mapped[str | None] = mapped_column(String(255))
    attachment_mime: Mapped[str | None] = mapped_column(String(40))
    # Each record lookup the AI made: [{"tool", "input", "ok", "summary"}]
    tool_log: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    model: Mapped[str | None] = mapped_column(String(60))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    conversation: Mapped[AssistantConversation] = relationship(back_populates="messages")


class AssistantProposal(IdMixin, TimestampMixin, Base):
    """Something the AI suggests recording. Nothing is saved until a person confirms."""

    __tablename__ = "assistant_proposals"
    __table_args__ = (
        CheckConstraint(f"kind IN {PROPOSAL_KINDS!r}", name="kind_valid"),
        CheckConstraint(f"status IN {PROPOSAL_STATUSES!r}", name="status_valid"),
    )

    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("assistant_conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("assistant_messages.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="PENDING")
    result_id: Mapped[int | None] = mapped_column(BigInteger)  # expense or invoice id
    decided_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
