"""Background job queue backed by PostgreSQL.

Jobs are claimed with `SELECT ... FOR UPDATE SKIP LOCKED`, so several worker processes
can run safely without double-processing and without Redis.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import BackgroundJob


def enqueue(
    db: Session,
    job_type: str,
    payload: dict[str, Any] | None = None,
    *,
    delay_seconds: int = 0,
    max_attempts: int | None = None,
) -> BackgroundJob:
    """Add a job to the caller's transaction (it becomes visible to workers on commit)."""
    job = BackgroundJob(
        job_type=job_type,
        payload=payload or {},
        status="PENDING",
        max_attempts=max_attempts or get_settings().worker_max_attempts,
        run_after=datetime.now(UTC) + timedelta(seconds=delay_seconds),
    )
    db.add(job)
    db.flush()
    return job


def claim_next(db: Session, job_types: list[str] | None = None) -> BackgroundJob | None:
    """Lock and mark the next due job as RUNNING. Caller must commit."""
    now = datetime.now(UTC)
    stmt = (
        select(BackgroundJob)
        .where(BackgroundJob.status == "PENDING", BackgroundJob.run_after <= now)
        .order_by(BackgroundJob.run_after, BackgroundJob.id)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job_types:
        stmt = stmt.where(BackgroundJob.job_type.in_(job_types))
    job = db.scalar(stmt)
    if job is None:
        return None
    job.status = "RUNNING"
    job.attempts += 1
    job.locked_at = now
    return job


def mark_succeeded(job: BackgroundJob, result: dict[str, Any] | None = None) -> None:
    job.status = "SUCCEEDED"
    job.result = result
    job.error = None
    job.finished_at = datetime.now(UTC)


def mark_failed(job: BackgroundJob, error: str) -> None:
    """Retry with exponential backoff (30s, 60s, 120s...) until max_attempts is reached."""
    job.error = error[:4000]
    if job.attempts >= job.max_attempts:
        job.status = "FAILED"
        job.finished_at = datetime.now(UTC)
    else:
        job.status = "PENDING"
        job.run_after = datetime.now(UTC) + timedelta(seconds=30 * 2 ** (job.attempts - 1))
        job.locked_at = None


def requeue_stale(db: Session, older_than_minutes: int = 15) -> int:
    """Return RUNNING jobs whose worker died (e.g. container restart) to the queue."""
    cutoff = datetime.now(UTC) - timedelta(minutes=older_than_minutes)
    jobs = db.scalars(
        select(BackgroundJob)
        .where(BackgroundJob.status == "RUNNING", BackgroundJob.locked_at < cutoff)
        .with_for_update(skip_locked=True)
    ).all()
    for job in jobs:
        mark_failed(job, "worker stopped before finishing (requeued)")
    return len(jobs)
