"""Files approved supplier invoices in the document archive.

On approval an "archive.invoice" job is queued. The worker uploads the original file with
its title, date, supplier (as the archive's "correspondent"), document type and tags, then
follows the archive's consume task until the document exists, and stores its id so the
invoice page can link to it. The archive OCRs the file again for full-text search.

Each invoice is uploaded at most once: once an archive task id is stored, retries only
follow that task.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.exceptions import ConflictError, ValidationFailed
from app.models import Invoice, Purchase
from app.services import job_service

logger = logging.getLogger(__name__)

JOB = "archive.invoice"
DOCUMENT_TYPE = "Supplier invoice"
TAGS = ("supplier invoice", "smart inventory")
TASK_WAIT_SECONDS = 120


class ArchiveError(Exception):
    """A problem talking to the archive; the message is safe to show to staff."""


class ArchiveClient:
    def __init__(
        self, settings: Settings | None = None, transport: httpx.BaseTransport | None = None
    ):
        self.settings = settings or get_settings()
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.settings.paperless_url.rstrip("/"),
            headers={
                "Authorization": f"Token {self.settings.paperless_token}",
                "Accept": "application/json",
            },
            timeout=60.0,
            transport=self._transport,
        )

    def _call(self, method: str, path: str, **kw: Any) -> Any:
        try:
            with self._client() as c:
                r = c.request(method, path, **kw)
        except httpx.HTTPError as exc:
            raise ArchiveError("The document archive could not be reached.") from exc
        if r.status_code in (401, 403):
            raise ArchiveError("The document archive refused the API token (PAPERLESS_TOKEN).")
        if r.status_code == 400 and "text/html" in r.headers.get("content-type", ""):
            # Django's "Bad Request (400)" page: the host name is not allowed.
            raise ArchiveError(
                "The document archive refused the address PAPERLESS_URL; add its host name to "
                "PAPERLESS_ALLOWED_HOSTS on the archive."
            )
        if r.status_code >= 400:
            is_json = "json" in r.headers.get("content-type", "")
            detail = r.text[:120].replace("\n", " ") if is_json else ""
            message = f"The document archive answered HTTP {r.status_code}. {detail}"
            raise ArchiveError(message.strip())
        return r.json()

    def get_or_create(self, kind: str, name: str) -> int:
        """kind: correspondents, document_types or tags. Matching is left to us (algorithm 0)."""
        found = self._call("GET", f"/api/{kind}/", params={"name__iexact": name})
        results = found.get("results", found) if isinstance(found, dict) else found
        if results:
            return int(results[0]["id"])
        created = self._call("POST", f"/api/{kind}/", json={"name": name, "matching_algorithm": 0})
        return int(created["id"])

    def upload(self, *, content: bytes, filename: str, mime: str, fields: dict[str, Any]) -> str:
        # Repeated fields (tags) are sent as lists; httpx needs a dict alongside files.
        data: dict[str, str | list[str]] = {}
        for k, v in fields.items():
            if v is None:
                continue
            data[k] = [str(i) for i in v] if isinstance(v, list | tuple) else str(v)
        task = self._call(
            "POST",
            "/api/documents/post_document/",
            data=data,
            files={"document": (filename, content, mime)},
        )
        if not isinstance(task, str) or not task:
            raise ArchiveError("The document archive did not return a task id.")
        return task

    def task(self, task_id: str) -> tuple[str, int | None, str | None]:
        """(state, document id, message). Works with both the 2.x and 3.x task formats."""
        res = self._call("GET", "/api/tasks/", params={"task_id": task_id})
        rows = res.get("results", []) if isinstance(res, dict) else res
        if not rows:
            return "pending", None, None
        t = rows[0]
        status = str(t.get("status", "")).lower()
        doc = (t.get("result_data") or {}).get("document_id") or t.get("related_document")
        if doc is None and t.get("related_document_ids"):
            doc = t["related_document_ids"][0]
        message = t.get("result") or (t.get("result_data") or {}).get("message")
        if status == "success":
            return "success", int(doc) if doc is not None else None, message
        if status in ("failure", "revoked"):
            return "failure", None, str(message or "The archive could not read the file.")[:250]
        return "pending", None, None


_client: ArchiveClient | None = None


def get_client() -> ArchiveClient:
    global _client
    if _client is None:
        _client = ArchiveClient()
    return _client


def set_client(client: ArchiveClient | None) -> None:
    """Used by tests to plug in a client with a fake archive transport."""
    global _client
    _client = client


# --- application side --------------------------------------------------------------------


def queue_invoice(db: Session, inv: Invoice) -> bool:
    """Called in the approval transaction: file the invoice once it is committed."""
    if not get_settings().archive_enabled or inv.archive_status == "ARCHIVED":
        return False
    inv.archive_status, inv.archive_error = "QUEUED", None
    job_service.enqueue(db, JOB, {"invoice_id": inv.id}, max_attempts=5)
    return True


def retry(db: Session, inv: Invoice) -> Invoice:
    if not get_settings().archive_enabled:
        raise ConflictError("The document archive is not set up.", code="ARCHIVE_NOT_CONFIGURED")
    if inv.status != "APPROVED":
        raise ValidationFailed("Only approved invoices are filed in the archive.")
    if inv.archive_status in ("QUEUED", "ARCHIVED"):
        return inv
    queue_invoice(db, inv)
    db.commit()
    db.refresh(inv)
    return inv


def queue_all_approved(db: Session) -> int:
    """Back-fill: queue every approved invoice that is not filed yet."""
    if not get_settings().archive_enabled:
        raise ConflictError("The document archive is not set up.", code="ARCHIVE_NOT_CONFIGURED")
    rows = db.scalars(
        select(Invoice).where(
            Invoice.status == "APPROVED",
            (Invoice.archive_status.is_(None)) | (Invoice.archive_status == "FAILED"),
        )
    ).all()
    for inv in rows:
        queue_invoice(db, inv)
    db.commit()
    return len(rows)


def archive_invoice(
    db: Session, invoice_id: int, *, wait_seconds: int = TASK_WAIT_SECONDS
) -> dict[str, Any]:
    """Worker job. Raises on transient problems so the job is retried."""
    inv = db.get(Invoice, invoice_id)
    if inv is None or inv.status != "APPROVED":
        return {"skipped": "not an approved invoice"}
    if inv.archive_status == "ARCHIVED":
        return {"skipped": "already archived", "document_id": inv.archive_document_id}
    client = get_client()
    s = get_settings()
    try:
        if not inv.archive_task_id:
            supplier = inv.supplier.name if inv.supplier else None
            fields: dict[str, Any] = {
                "title": _title(db, inv),
                "created": inv.invoice_date.isoformat() if inv.invoice_date else None,
                "document_type": client.get_or_create("document_types", DOCUMENT_TYPE),
                "tags": [client.get_or_create("tags", t) for t in TAGS],
            }
            if supplier:
                fields["correspondent"] = client.get_or_create("correspondents", supplier)
            content = (s.storage_dir / inv.file_path).read_bytes()
            inv.archive_task_id = client.upload(
                content=content, filename=inv.original_filename, mime=inv.mime_type, fields=fields
            )
            db.commit()  # never upload the same invoice twice, even if the next step fails
        deadline = time.monotonic() + wait_seconds
        while True:
            state, doc_id, message = client.task(inv.archive_task_id)
            if state != "pending" or time.monotonic() >= deadline:
                break
            time.sleep(2)
    except ArchiveError as exc:
        # Shown on the invoice with a Retry button; the job also retries by itself.
        inv.archive_status, inv.archive_error = "FAILED", str(exc)[:255]
        db.commit()
        raise

    if state == "success":
        inv.archive_status, inv.archive_document_id = "ARCHIVED", doc_id
        inv.archived_at, inv.archive_error = datetime.now(UTC), None
        db.commit()
        return {"document_id": doc_id}
    if state == "failure":
        inv.archive_status, inv.archive_error = "FAILED", message
        inv.archive_task_id = None  # a fresh upload is allowed after a definite failure
        db.commit()
        return {"failed": message}
    inv.archive_error = "Still being processed by the archive; will check again."
    db.commit()
    raise ArchiveError("The archive is still processing the file.")


def document_url(inv: Invoice) -> str | None:
    base = get_settings().paperless_public_url.rstrip("/")
    if not base or not inv.archive_document_id:
        return None
    return f"{base}/documents/{inv.archive_document_id}/details"


def _title(db: Session, inv: Invoice) -> str:
    parts = [f"Invoice {inv.invoice_number}" if inv.invoice_number else "Supplier invoice"]
    purchase = db.get(Purchase, inv.purchase_id) if inv.purchase_id else None
    if purchase is not None:
        parts.append(purchase.grn_number)
    return " · ".join(parts)[:128]
