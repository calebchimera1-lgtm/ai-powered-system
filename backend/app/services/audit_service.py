"""Audit logging helpers.

`record()` adds an audit row to the caller's session, so the audit entry commits or rolls
back with the business change it describes. Login failures commit on their own because
there is no business change to attach them to.
"""

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models import AuditLog, User


@dataclass(frozen=True)
class RequestContext:
    ip_address: str | None = None
    user_agent: str | None = None

    @classmethod
    def from_request(cls, request: Request) -> "RequestContext":
        ip = request.client.host if request.client else None
        ua = request.headers.get("user-agent")
        return cls(ip_address=ip, user_agent=ua[:255] if ua else None)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    return value


def record(
    db: Session,
    *,
    action: str,
    actor: User | None,
    ctx: RequestContext | None = None,
    entity_type: str | None = None,
    entity_id: Any = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: str | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=actor.id if actor else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        before=_jsonable(before) if before is not None else None,
        after=_jsonable(after) if after is not None else None,
        details=details,
        ip_address=ctx.ip_address if ctx else None,
        user_agent=ctx.user_agent if ctx else None,
    )
    db.add(entry)
    return entry


def diff(before: dict[str, Any], after: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Reduce two snapshots to only the fields that changed."""
    changed = {k for k in before.keys() | after.keys() if before.get(k) != after.get(k)}
    return ({k: before.get(k) for k in changed}, {k: after.get(k) for k in changed})
