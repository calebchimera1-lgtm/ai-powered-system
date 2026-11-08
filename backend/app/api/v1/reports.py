"""Downloadable reports: PDF, Excel and CSV."""

from datetime import date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Response
from pydantic import BaseModel

from app.api.deps import Ctx, CurrentUser, DbSession
from app.core.config import get_settings
from app.core.exceptions import RateLimited
from app.core.rate_limit import SlidingWindowLimiter
from app.reports.writers import WRITERS, Meta
from app.services import audit_service, report_service

router = APIRouter(prefix="/reports", tags=["Reports"])

# Reports run synchronously; cap how often one person can generate them.
report_limiter = SlidingWindowLimiter(limit=30, window_seconds=60)


class ReportTypeOut(BaseModel):
    key: str
    title: str
    description: str
    uses_period: bool
    formats: list[str]


@router.get("", response_model=list[ReportTypeOut])
def report_types(user: CurrentUser) -> list[ReportTypeOut]:
    """The reports this user may download."""
    return [
        ReportTypeOut(
            key=r.key,
            title=r.title,
            description=r.description,
            uses_period=r.uses_period,
            formats=list(WRITERS),
        )
        for r in report_service.available(user)
    ]


@router.get("/{key}")
def download(
    key: str,
    user: CurrentUser,
    db: DbSession,
    ctx: Ctx,
    format: Literal["pdf", "xlsx", "csv"] = "pdf",
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
) -> Response:
    if not report_limiter.hit(f"user:{user.id}"):
        raise RateLimited("Too many reports in a minute. Wait a moment and try again.")
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.store_timezone)).date()
    d2 = date_to or today
    d1 = date_from or d2 - timedelta(days=29)
    report = report_service.build(db, user, key, d1, d2, category_id)
    details = " · ".join(
        x
        for x in (
            settings.store_address,
            f"KRA PIN {settings.store_kra_pin}" if settings.store_kra_pin else "",
        )
        if x
    )
    meta = Meta(
        store_name=settings.store_name,
        store_details=details,
        generated_by=user.full_name,
        generated_at=datetime.now(ZoneInfo(settings.store_timezone)),
    )
    writer, media, ext = WRITERS[format]
    body = writer(report, meta)
    audit_service.record(
        db,
        action="report.exported",
        actor=user,
        ctx=ctx,
        entity_type="report",
        entity_id=key,
        after={
            "format": format,
            "date_from": d1.isoformat(),
            "date_to": d2.isoformat(),
            "category_id": category_id,
            "rows": len(report.rows),
        },
    )
    db.commit()
    rt = report_service.BY_KEY[key]
    period = f"{d1:%Y-%m-%d}_{d2:%Y-%m-%d}" if rt.uses_period else f"{today:%Y-%m-%d}"
    filename = f"{key}_{period}.{ext}"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
            "X-Report-Rows": str(len(report.rows)),
        },
    )
