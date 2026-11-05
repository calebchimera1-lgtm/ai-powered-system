"""Audit log schemas."""

from datetime import datetime
from typing import Any

from app.schemas.common import ORMModel


class AuditUser(ORMModel):
    id: int
    username: str
    full_name: str


class AuditLogOut(ORMModel):
    id: int
    action: str
    entity_type: str | None
    entity_id: str | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    details: str | None
    ip_address: str | None
    user_agent: str | None
    created_at: datetime
    user: AuditUser | None
