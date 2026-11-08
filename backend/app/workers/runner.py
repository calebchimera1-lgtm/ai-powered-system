"""Background worker process.

Run with:  python -m app.workers.runner

Loop: claim one due job, run its handler in its own transaction, record the outcome.
Also enqueues periodic maintenance. Stops cleanly on SIGTERM (docker stop).
"""

import logging
import signal
import time
import traceback
from datetime import UTC, datetime
from types import FrameType

from sqlalchemy import select

from app.core.config import get_settings
from app.core.database import SessionLocal
from app.core.logging import configure_logging
from app.models import BackgroundJob
from app.services import job_service
from app.workers.handlers import HANDLERS

logger = logging.getLogger("worker")

# job_type -> interval in seconds
# Job type -> interval in seconds. Each also runs once when the worker starts.
PERIODIC_JOBS: dict[str, int] = {
    "system.cleanup": 6 * 3600,
    "notifications.sweep": 15 * 60,
    "anomaly.scan": 3 * 3600,
    "forecast.run": 24 * 3600,
    "system.backup": 24 * 3600,
}


class Worker:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.running = True
        self._last_periodic: dict[str, float] = {}

    def stop(self, signum: int, _frame: FrameType | None) -> None:
        logger.info("Received signal %s, finishing current job then stopping", signum)
        self.running = False

    def run_once(self) -> bool:
        """Process at most one job. Returns True if a job was processed."""
        with SessionLocal() as db:
            job = job_service.claim_next(db)
            if job is None:
                db.commit()
                return False
            db.commit()  # persist RUNNING state before doing the work
            job_id, job_type, payload = job.id, job.job_type, dict(job.payload)

        logger.info("Running job %s (%s), attempt %s", job_id, job_type, job.attempts)
        started = time.monotonic()
        with SessionLocal() as db:
            try:
                fn = HANDLERS.get(job_type)
                if fn is None:
                    raise LookupError(f"No handler registered for job type '{job_type}'")
                result = fn(db, payload)
                db.commit()
                outcome: tuple[bool, object] = (True, result)
            except Exception:
                db.rollback()
                outcome = (False, traceback.format_exc())
                logger.exception("Job %s failed", job_id)

        with SessionLocal() as db:
            job = db.get(BackgroundJob, job_id)
            if job is not None:
                if outcome[0]:
                    job_service.mark_succeeded(job, outcome[1])  # type: ignore[arg-type]
                else:
                    job_service.mark_failed(job, str(outcome[1]))
                db.commit()
        logger.info("Job %s finished in %.2fs", job_id, time.monotonic() - started)
        return True

    def schedule_periodic(self) -> None:
        now = time.monotonic()
        for job_type, interval in PERIODIC_JOBS.items():
            last = self._last_periodic.get(job_type)
            if last is not None and now - last < interval:
                continue
            self._last_periodic[job_type] = now
            with SessionLocal() as db:
                pending = db.scalar(
                    select(BackgroundJob.id).where(
                        BackgroundJob.job_type == job_type,
                        BackgroundJob.status.in_(["PENDING", "RUNNING"]),
                    )
                )
                if pending is None:
                    job_service.enqueue(db, job_type)
                job_service.requeue_stale(db)
                db.commit()

    def run_forever(self) -> None:
        logger.info("Worker started at %s", datetime.now(UTC).isoformat())
        while self.running:
            try:
                self.schedule_periodic()
                if not self.run_once():
                    time.sleep(self.settings.worker_poll_seconds)
            except Exception:
                logger.exception("Worker loop error; retrying shortly")
                time.sleep(5)
        logger.info("Worker stopped")


def main() -> None:
    configure_logging(get_settings().log_level)
    worker = Worker()
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run_forever()


if __name__ == "__main__":
    main()
