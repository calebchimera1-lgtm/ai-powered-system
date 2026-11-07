"""The signed-in user's own notifications."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.api.deps import CurrentUser, DbSession
from app.schemas.analytics import MarkRead, NotificationOut, NotificationPage
from app.services import notification_service

router = APIRouter(prefix="/notifications", tags=["Notifications"])


@router.get("", response_model=NotificationPage)
def my_notifications(
    user: CurrentUser,
    db: DbSession,
    unread: bool = False,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> NotificationPage:
    rows, total, unread_count = notification_service.list_for(
        db, user, unread_only=unread, limit=limit, offset=offset
    )
    return NotificationPage(
        items=[NotificationOut.model_validate(n) for n in rows], total=total, unread=unread_count
    )


@router.get("/unread-count")
def unread_count(user: CurrentUser, db: DbSession) -> dict[str, int]:
    return {"unread": notification_service.unread_count(db, user)}


@router.post("/read")
def mark_read(body: MarkRead, user: CurrentUser, db: DbSession) -> dict[str, int]:
    """Mark the given notifications (or, with no ids, all of them) as read."""
    return {"updated": notification_service.mark_read(db, user, body.ids)}
