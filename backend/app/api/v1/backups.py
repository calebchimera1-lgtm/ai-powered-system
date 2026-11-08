"""Backups (Super Admin). Creating and downloading only: restoring replaces live data and
is done from the command line (scripts/restore_backup.py), with the app stopped."""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import Ctx, DbSession, require
from app.core.permissions import P
from app.models import BackgroundJob, User
from app.schemas.analytics import JobQueued
from app.services import audit_service, backup_service, job_service

router = APIRouter(prefix="/system/backups", tags=["Backups"])

Admin = Annotated[User, Depends(require(P.BACKUPS_MANAGE))]


@router.get("")
def list_backups(_: Admin, db: DbSession) -> dict[str, Any]:
    running = db.scalar(
        select(BackgroundJob.id).where(
            BackgroundJob.job_type == "system.backup",
            BackgroundJob.status.in_(["PENDING", "RUNNING"]),
        )
    )
    last_failure = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.job_type == "system.backup")
        .order_by(BackgroundJob.id.desc())
    )
    return {
        "backups": backup_service.list_backups(),
        "running": running is not None,
        "last_error": last_failure.error
        if last_failure is not None and last_failure.status == "FAILED"
        else None,
        "policy": {
            "daily": backup_service.KEEP_DAILY,
            "weekly": backup_service.KEEP_WEEKLY,
            "manual": backup_service.KEEP_MANUAL,
        },
    }


@router.post("", response_model=JobQueued, status_code=status.HTTP_202_ACCEPTED)
def back_up_now(user: Admin, db: DbSession, ctx: Ctx) -> JobQueued:
    job = job_service.enqueue(db, "system.backup", {"kind": "manual"})
    audit_service.record(db, action="backup.requested", actor=user, ctx=ctx, entity_type="backup")
    db.commit()
    return JobQueued(job_id=job.id, message="Backup started; it appears here when finished.")


@router.get("/{name}/{file}", response_class=FileResponse)
def download(
    name: str,
    file: Literal["database.dump", "files.tar.gz", "manifest.json"],
    user: Admin,
    db: DbSession,
    ctx: Ctx,
) -> FileResponse:
    path = backup_service.path_of(name, file)
    audit_service.record(
        db,
        action="backup.downloaded",
        actor=user,
        ctx=ctx,
        entity_type="backup",
        entity_id=name,
        details=file,
    )
    db.commit()
    return FileResponse(path, filename=f"{name}-{file}", media_type="application/octet-stream")
