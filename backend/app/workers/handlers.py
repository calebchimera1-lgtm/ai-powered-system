"""Job type → handler function registry.

Each handler receives an open session and the job payload, and returns a small JSON-able
result. Later phases register OCR, forecasting and anomaly handlers here.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, or_
from sqlalchemy.orm import Session

from app.models import BackgroundJob, PasswordResetToken, UserSession

Handler = Callable[[Session, dict[str, Any]], dict[str, Any] | None]

HANDLERS: dict[str, Handler] = {}


def handler(job_type: str) -> Callable[[Handler], Handler]:
    def register(fn: Handler) -> Handler:
        HANDLERS[job_type] = fn
        return fn

    return register


@handler("system.ping")
def ping(_: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Diagnostic job: proves the worker is alive end-to-end."""
    return {"pong": True, "echo": payload.get("echo")}


@handler("system.cleanup")
def cleanup(db: Session, _: dict[str, Any]) -> dict[str, Any]:
    """Purge expired sessions, old reset tokens and finished jobs older than 30 days."""
    now = datetime.now(UTC)
    old = now - timedelta(days=30)
    sessions = db.execute(
        delete(UserSession).where(
            or_(UserSession.expires_at < now - timedelta(days=1), UserSession.revoked_at < old)
        )
    ).rowcount
    tokens = db.execute(
        delete(PasswordResetToken).where(PasswordResetToken.expires_at < old)
    ).rowcount
    jobs = db.execute(
        delete(BackgroundJob).where(
            BackgroundJob.status.in_(["SUCCEEDED", "FAILED"]), BackgroundJob.finished_at < old
        )
    ).rowcount
    return {"sessions_deleted": sessions, "reset_tokens_deleted": tokens, "jobs_deleted": jobs}


@handler("invoice.process")
def process_invoice(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """OCR and extraction for an uploaded supplier invoice (see invoice_service)."""
    from app.services import invoice_service

    return invoice_service.process(db, int(payload["invoice_id"]))


@handler("forecast.run")
def run_forecast(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Backtest, choose models and forecast every product (nightly, or on request)."""
    from app.models import User
    from app.services import forecast_service

    user = db.get(User, payload["user_id"]) if payload.get("user_id") else None
    run = forecast_service.run(db, triggered_by=user)
    return {"run_id": run.id, **(run.summary or {})}


@handler("anomaly.scan")
def scan_anomalies(db: Session, _: dict[str, Any]) -> dict[str, Any]:
    from app.services import anomaly_service

    return anomaly_service.scan(db)


@handler("notifications.sweep")
def sweep_notifications(db: Session, _: dict[str, Any]) -> dict[str, Any]:
    """Expiring batches and approvals waiting (low stock is notified in real time)."""
    from app.services import notification_service

    return notification_service.sweep(db)


@handler("system.backup")
def backup(db: Session, payload: dict[str, Any]) -> dict[str, Any]:
    """Nightly (or on request) database + uploaded files backup, then rotation."""
    from app.services import backup_service

    result = backup_service.create(db, kind=payload.get("kind", "daily"))
    return {
        "name": result["name"],
        "removed": result["removed"],
        "bytes": sum(f["bytes"] for f in result["files"].values()),
    }
