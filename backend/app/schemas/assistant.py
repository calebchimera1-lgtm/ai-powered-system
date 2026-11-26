"""AI assistant schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, computed_field

from app.schemas.common import ORMModel, Page
from app.schemas.stock import UserBrief


class ToolCall(BaseModel):
    tool: str
    input: Any = None
    ok: bool
    summary: str


class MessageOut(ORMModel):
    id: int
    role: str
    content: str
    attachment_name: str | None
    attachment_mime: str | None
    tool_log: list[ToolCall] | None
    model: str | None
    input_tokens: int | None
    output_tokens: int | None
    error: str | None
    created_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def has_attachment(self) -> bool:
        return self.attachment_name is not None


class ProposalOut(ORMModel):
    id: int
    message_id: int | None
    kind: str
    payload: dict[str, Any]
    status: str
    result_id: int | None
    decided_at: datetime | None
    created_at: datetime


class ConversationSummary(BaseModel):
    id: int
    title: str
    user: UserBrief
    created_at: datetime
    updated_at: datetime
    messages: int = 0


class ConversationOut(BaseModel):
    id: int
    title: str
    user: UserBrief
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]
    proposals: list[ProposalOut]


class AssistantStatus(BaseModel):
    enabled: bool
    model: str | None
    ai_invoice_reading: bool
    tools: list[str]
    can_see_all: bool


class ConversationPage(Page[ConversationSummary]):
    pass
