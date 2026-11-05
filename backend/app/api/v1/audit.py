"""Audit log browsing (Super Administrator only)."""

from datetime import date, datetime, time, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select

from app.api.deps import DbSession, Pagination, require
from app.core.config import get_settings
from app.core.permissions import P
from app.models import AuditLog, User
from app.schemas.audit import AuditLogOut
from app.schemas.common import Page

router = APIRouter(prefix="/audit-logs", tags=["Audit"])


@router.get("", response_model=Page[AuditLogOut])
def list_audit_logs(
    _: Annotated[User, Depends(require(P.AUDIT_READ))],
    db: DbSession,
    pagination: Pagination,
    user_id: int | None = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    entity_type: Annotated[str | None, Query(max_length=64)] = None,
    entity_id: Annotated[str | None, Query(max_length=64)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> Page[AuditLogOut]:
    """Newest first. Dates are interpreted in the store's timezone (Africa/Nairobi)."""
    tz = ZoneInfo(get_settings().store_timezone)
    stmt = select(AuditLog)
    if user_id is not None:
        stmt = stmt.where(AuditLog.user_id == user_id)
    if action:
        # "auth" matches auth.login, auth.logout, ...; "auth.login" matches exactly.
        stmt = stmt.where(
            (AuditLog.action == action) | AuditLog.action.like(f"{action.rstrip('.')}.%")
        )
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if date_from:
        stmt = stmt.where(AuditLog.created_at >= datetime.combine(date_from, time.min, tz))
    if date_to:
        end = datetime.combine(date_to + timedelta(days=1), time.min, tz)
        stmt = stmt.where(AuditLog.created_at < end)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        .offset(pagination.offset)
        .limit(pagination.page_size)
    ).all()
    return Page.build([AuditLogOut.model_validate(r) for r in rows], total, pagination)
