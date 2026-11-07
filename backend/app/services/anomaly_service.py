"""Run anomaly detection on the store's records, store alerts and handle their review."""

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.anomaly import detector
from app.core.exceptions import NotFoundError, PermissionDenied, ValidationFailed
from app.core.permissions import P
from app.models import AnomalyAlert, User
from app.services import analytics_data, audit_service, notification_service
from app.services.audit_service import RequestContext
from app.services.forecast_service import today

LOOKBACK_DAYS = 180  # history used to learn what is normal
ALERT_DAYS = 14  # only findings this recent become alerts
CONTAMINATION = 0.01
REVIEW_STATUSES = ("INVESTIGATING", "RESOLVED_ISSUE_FOUND", "RESOLVED_NO_ISSUE")


def scan(db: Session, *, alert_days: int = ALERT_DAYS) -> dict[str, int]:
    end = today()
    start = end - timedelta(days=LOOKBACK_DAYS)
    pdays = analytics_data.product_days(db, start, end)
    udays = analytics_data.user_days(db, start, end)
    findings = detector.detect(pdays, udays, contamination=CONTAMINATION)
    recent = [f for f in findings if f.day >= end - timedelta(days=alert_days)]
    created = extended = 0
    for f in sorted(recent, key=lambda f: f.day):
        outcome = _upsert(db, f)
        created += outcome == "created"
        extended += outcome == "extended"
    db.commit()
    return {
        "findings": len(findings),
        "recent": len(recent),
        "created": created,
        "extended": extended,
    }


def _entity_filter(f: detector.Finding) -> Any:
    if f.entity == "product":
        return AnomalyAlert.product_id == f.entity_id
    return AnomalyAlert.subject_user_id == f.entity_id


def _evidence(f: detector.Finding) -> dict[str, Any]:
    return {
        "day": f.day.isoformat(),
        "detector": f.detector,
        "score": round(f.score, 3),
        "explanation": f.explanation,
        "figures": f.evidence,
    }


def _upsert(db: Session, f: detector.Finding) -> str:
    same = select(AnomalyAlert).where(
        AnomalyAlert.entity_type == f.entity, _entity_filter(f), AnomalyAlert.kind == f.kind
    )
    if db.scalar(same.where(AnomalyAlert.period_start <= f.day, AnomalyAlert.period_end >= f.day)):
        return "seen"
    running = db.scalar(
        same.where(
            AnomalyAlert.period_end == f.day - timedelta(days=1),
            AnomalyAlert.status.in_(["OPEN", "INVESTIGATING"]),
        )
    )
    if running is not None:  # the same irregularity continues: one alert covering the days
        running.period_end = f.day
        running.quantity += f.quantity
        running.value_kes += Decimal(str(f.value_kes))
        running.score = max(running.score, f.score)
        if f.detector != running.detector:
            running.detector = "BOTH"
        running.evidence = [*(running.evidence or []), _evidence(f)]
        running.explanation += f" It continued on {f.day:%d %b}."
        running.severity = _max_sev(running.severity, detector.severity(f), running.value_kes)
        return "extended"
    alert = AnomalyAlert(
        entity_type=f.entity,
        product_id=f.entity_id if f.entity == "product" else None,
        subject_user_id=f.entity_id if f.entity == "user" else None,
        kind=f.kind,
        period_start=f.day,
        period_end=f.day,
        quantity=f.quantity,
        value_kes=Decimal(str(f.value_kes)).quantize(Decimal("0.01")),
        severity=detector.severity(f),
        score=round(f.score, 4),
        detector=f.detector,
        explanation=f.explanation,
        recommended_action=f.action,
        evidence=[_evidence(f)],
        status="OPEN",
        dedupe_key=f"{f.entity}:{f.entity_id}:{f.kind}:{f.day.isoformat()}",
    )
    db.add(alert)
    db.flush()
    if alert.severity in ("MEDIUM", "HIGH"):
        # Alerts about a person go only to those allowed to review them (wording policy).
        perms = [P.ANOMALIES_REVIEW] if f.entity == "user" else [P.ANOMALIES_READ]
        notification_service.notify(
            db,
            perms=perms,
            type="ANOMALY",
            severity="critical" if alert.severity == "HIGH" else "warning",
            title=f"Irregularity to review: {detector.KIND_LABELS[f.kind]}",
            message=f.explanation,
            link=f"/anomalies/{alert.id}",
            dedupe_key=f"anomaly:{alert.id}",
        )
    return "created"


def _max_sev(a: str, b: str, value: Decimal) -> str:
    order = ["LOW", "MEDIUM", "HIGH"]
    sev = max(a, b, key=order.index)
    if value >= 5000:
        sev = "HIGH"
    return sev


# --- Reading and review --------------------------------------------------------------------


def _visible(user: User) -> Any:
    """People-related alerts are visible only to reviewers (managers and admins)."""
    if P.ANOMALIES_REVIEW.value in user.permission_codes:
        return True
    return AnomalyAlert.entity_type == "product"


def list_alerts(
    db: Session, user: User, *, status: str | None, severity: str | None, limit: int, offset: int
) -> tuple[list[AnomalyAlert], int]:
    stmt = select(AnomalyAlert).where(_visible(user))
    if status == "OPEN_ALL":
        stmt = stmt.where(AnomalyAlert.status.in_(["OPEN", "INVESTIGATING"]))
    elif status == "RESOLVED":
        stmt = stmt.where(AnomalyAlert.status.like("RESOLVED_%"))
    elif status:
        stmt = stmt.where(AnomalyAlert.status == status)
    if severity:
        stmt = stmt.where(AnomalyAlert.severity == severity)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    order = func.array_position(["HIGH", "MEDIUM", "LOW"], AnomalyAlert.severity)
    rows = (
        db.scalars(
            stmt.order_by(AnomalyAlert.period_end.desc(), order, AnomalyAlert.id.desc())
            .offset(offset)
            .limit(limit)
        )
        .unique()
        .all()
    )
    return list(rows), total


def get(db: Session, user: User, alert_id: int) -> AnomalyAlert:
    alert = db.get(AnomalyAlert, alert_id)
    if alert is None or (
        alert.entity_type == "user" and P.ANOMALIES_REVIEW.value not in user.permission_codes
    ):
        raise NotFoundError("Alert not found")
    return alert


def review(
    db: Session,
    user: User,
    alert: AnomalyAlert,
    status: str,
    notes: str | None,
    ctx: RequestContext,
) -> AnomalyAlert:
    if status not in REVIEW_STATUSES:
        raise ValidationFailed("Choose investigating, issue found or no issue")
    if alert.entity_type == "user" and alert.subject_user_id == user.id:
        raise PermissionDenied("Someone else must review an alert about your own activity.")
    if status.startswith("RESOLVED") and not (notes or "").strip():
        raise ValidationFailed(
            "Add a short note on what was found",
            details=[{"field": "notes", "message": "required"}],
        )
    before = alert.status
    alert.status = status
    alert.review_notes = (notes or "").strip() or alert.review_notes
    alert.reviewed_by_id = user.id
    alert.reviewed_at = datetime.now(UTC)
    audit_service.record(
        db,
        action="anomaly.reviewed",
        actor=user,
        ctx=ctx,
        entity_type="anomaly_alert",
        entity_id=alert.id,
        before={"status": before},
        after={"status": status},
        details=alert.review_notes,
    )
    db.commit()
    db.refresh(alert)
    return alert


def stats(db: Session, user: User) -> dict[str, Any]:
    base = select(AnomalyAlert).where(_visible(user)).subquery()
    counts = dict(db.execute(select(base.c.status, func.count()).group_by(base.c.status)).all())
    open_by_sev = dict(
        db.execute(
            select(base.c.severity, func.count())
            .where(base.c.status.in_(["OPEN", "INVESTIGATING"]))
            .group_by(base.c.severity)
        ).all()
    )
    found, none = counts.get("RESOLVED_ISSUE_FOUND", 0), counts.get("RESOLVED_NO_ISSUE", 0)
    value_open = db.scalar(
        select(func.coalesce(func.sum(base.c.value_kes), 0)).where(
            base.c.status.in_(["OPEN", "INVESTIGATING"])
        )
    )
    return {
        "by_status": counts,
        "open_by_severity": open_by_sev,
        "open_value_kes": Decimal(value_open or 0),
        "reviewed": found + none,
        # Real-world precision: of the alerts people checked, how many were real issues.
        "precision": round(found / (found + none), 3) if found + none else None,
    }


def period_label(start: date, end: date) -> str:
    return f"{start:%d %b}" if start == end else f"{start:%d %b} to {end:%d %b}"
