"""Irregularities found in stock, refunds and adjustments, and their review.

Alerts are prompts to investigate, not findings of wrongdoing. Alerts about a member of
staff are visible only to those who may review them (Store Manager, Super Admin), and
nobody can review an alert about their own activity.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, status

from app.ai.anomaly.detector import KIND_LABELS
from app.api.deps import Ctx, DbSession, Pagination, limit_per_user, require
from app.core.permissions import P
from app.models import AnomalyAlert, BackgroundJob, User
from app.schemas.analytics import AnomalyAlertOut, AnomalyReview, AnomalyStats, JobQueued
from app.schemas.common import Page
from app.services import anomaly_service, job_service

router = APIRouter(prefix="/anomalies", tags=["Anomaly detection"])

Reader = Annotated[User, Depends(require(P.ANOMALIES_READ))]
Reviewer = Annotated[User, Depends(require(P.ANOMALIES_REVIEW))]


def _out(a: AnomalyAlert) -> AnomalyAlertOut:
    out = AnomalyAlertOut.model_validate(a)
    out.kind_label = KIND_LABELS.get(a.kind, a.kind)
    return out


@router.get("", response_model=Page[AnomalyAlertOut])
def list_alerts(
    user: Reader,
    db: DbSession,
    pagination: Pagination,
    status_filter: Annotated[
        Literal[
            "OPEN_ALL",
            "OPEN",
            "INVESTIGATING",
            "RESOLVED",
            "RESOLVED_ISSUE_FOUND",
            "RESOLVED_NO_ISSUE",
        ]
        | None,
        Query(alias="status"),
    ] = None,
    severity: Literal["LOW", "MEDIUM", "HIGH"] | None = None,
) -> Page[AnomalyAlertOut]:
    rows, total = anomaly_service.list_alerts(
        db,
        user,
        status=status_filter,
        severity=severity,
        limit=pagination.page_size,
        offset=pagination.offset,
    )
    return Page.build([_out(a) for a in rows], total, pagination)


@router.get("/stats", response_model=AnomalyStats)
def alert_stats(user: Reader, db: DbSession) -> AnomalyStats:
    """Open alerts by severity and the real-world precision of reviewed alerts."""
    return AnomalyStats.model_validate(anomaly_service.stats(db, user))


@router.post(
    "/scan",
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_per_user(5, 60, "Too many scans. Wait a minute."))],
)
def scan_now(_: Reviewer, db: DbSession) -> JobQueued:
    from sqlalchemy import select

    pending = db.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == "anomaly.scan",
            BackgroundJob.status.in_(["PENDING", "RUNNING"]),
        )
    )
    if pending:
        return JobQueued(job_id=pending, message="A scan is already running.")
    job = job_service.enqueue(db, "anomaly.scan")
    db.commit()
    return JobQueued(job_id=job.id, message="Scan queued.")


@router.get("/{alert_id}", response_model=AnomalyAlertOut)
def get_alert(alert_id: int, user: Reader, db: DbSession) -> AnomalyAlertOut:
    return _out(anomaly_service.get(db, user, alert_id))


@router.post("/{alert_id}/review", response_model=AnomalyAlertOut)
def review_alert(
    alert_id: int, body: AnomalyReview, user: Reviewer, db: DbSession, ctx: Ctx
) -> AnomalyAlertOut:
    """Record what the investigation found. Resolving needs a note."""
    alert = anomaly_service.get(db, user, alert_id)
    return _out(anomaly_service.review(db, user, alert, body.status, body.notes, ctx))
