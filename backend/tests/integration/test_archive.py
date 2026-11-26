"""Filing approved invoices in the document archive (Paperless-ngx).

Paperless is replaced by a fake that follows the API of Paperless-ngx 3.5.1 as observed
against the real server (post_document returns a task id; /api/tasks/ is paginated and
reports result_data.document_id). The same flow was also run against a real Paperless-ngx
3.5.1 container by hand (see docs/installation.md, section 6b).
"""

# ruff: noqa: F811  (fixtures are imported from the invoice tests)
import json
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.config import get_settings
from app.models import Invoice
from app.services import archive_service
from tests.integration.test_invoices_api import docs, env, process_all, upload  # noqa: F401


class FakePaperless:
    def __init__(self) -> None:
        self.objects: dict[str, list[dict]] = {
            "correspondents": [],
            "tags": [],
            "document_types": [],
        }
        self.uploads: list[dict] = []
        self.tasks: dict[str, dict] = {}
        self.pending_polls = 0  # how many polls a task stays "started"
        self.fail_with: str | None = None
        self.status_code: int | None = None

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.status_code:
            return httpx.Response(self.status_code, json={"detail": "Invalid token."})
        assert request.headers["Authorization"] == "Token pl-token"
        path = request.url.path
        kind = path.strip("/").split("/")[1]
        if kind in self.objects:
            rows = self.objects[kind]
            if request.method == "GET":
                name = request.url.params.get("name__iexact", "").lower()
                hits = [r for r in rows if r["name"].lower() == name]
                return httpx.Response(200, json={"count": len(hits), "results": hits})
            body = json.loads(request.content)
            row = {"id": len(rows) + 1, "name": body["name"]}
            rows.append(row)
            return httpx.Response(201, json=row)
        if path == "/api/documents/post_document/":
            fields: dict[str, list[str]] = {}
            for part in request.content.split(b"--")[1:]:
                head, _, value = part.partition(b"\r\n\r\n")
                if b'name="' not in head:
                    continue
                name = head.split(b'name="')[1].split(b'"')[0].decode()
                fields.setdefault(name, []).append(
                    value.rsplit(b"\r\n", 1)[0].decode("utf-8", "replace")
                )
            self.uploads.append(fields)
            tid = str(uuid.uuid4())
            self.tasks[tid] = {"polls": 0, "doc": 100 + len(self.uploads)}
            return httpx.Response(200, json=tid)
        if path == "/api/tasks/":
            t = self.tasks[request.url.params["task_id"]]
            t["polls"] += 1
            if t["polls"] <= self.pending_polls:
                row = {"status": "started", "result_data": None, "related_document_ids": []}
            elif self.fail_with:
                row = {"status": "failure", "result": self.fail_with, "result_data": None}
            else:
                row = {
                    "status": "success",
                    "result_data": {"document_id": t["doc"]},
                    "related_document_ids": [t["doc"]],
                }
            return httpx.Response(200, json={"count": 1, "results": [row]})
        return httpx.Response(404, json={})


@pytest.fixture
def paperless(monkeypatch):  # type: ignore[no-untyped-def]
    s = get_settings()
    monkeypatch.setattr(s, "paperless_url", "http://archive:8000")
    monkeypatch.setattr(s, "paperless_token", "pl-token")
    monkeypatch.setattr(s, "paperless_public_url", "http://localhost:8090")
    fake = FakePaperless()
    archive_service.set_client(
        archive_service.PaperlessClient(s, transport=httpx.MockTransport(fake.handler))
    )
    yield fake
    archive_service.set_client(None)


def approved_invoice(client: TestClient, env, docs) -> dict:  # type: ignore[no-untyped-def]
    h = env["officer"]
    data, _ = docs["pdf"]
    inv = upload(client, h, data, "invoice.pdf").json()
    process_all()
    r = client.post(f"/api/v1/invoices/{inv['id']}/approve", headers=h, json={})
    assert r.status_code == 200, r.text
    return r.json()


def test_without_an_archive_nothing_is_queued(client: TestClient, env, docs) -> None:
    inv = approved_invoice(client, env, docs)
    assert inv["archive_status"] is None and inv["archive_url"] is None
    assert (
        client.get("/api/v1/store", headers=env["officer"]).json()["document_archive_url"] is None
    )
    r = client.post(f"/api/v1/invoices/{inv['id']}/archive", headers=env["officer"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "ARCHIVE_NOT_CONFIGURED"


def test_approved_invoice_is_filed_with_supplier_type_tags_and_date(
    client: TestClient, env, docs, paperless, db
) -> None:
    store = client.get("/api/v1/store", headers=env["officer"]).json()
    assert store["document_archive_url"] == "http://localhost:8090"
    inv = approved_invoice(client, env, docs)
    assert inv["archive_status"] == "QUEUED"
    process_all()
    out = client.get(f"/api/v1/invoices/{inv['id']}", headers=env["officer"]).json()
    assert out["archive_status"] == "ARCHIVED" and out["archive_document_id"] == 101
    assert out["archive_url"] == "http://localhost:8090/documents/101/details"

    sent = paperless.uploads[0]
    row = db.get(Invoice, inv["id"])
    assert sent["title"] == [f"Invoice {out['invoice_number']} · {_grn(db, row)}"]
    assert sent["created"] == [out["invoice_date"]]
    supplier = next(o for o in paperless.objects["correspondents"])
    assert supplier["name"] == out["supplier"]["name"] and sent["correspondent"] == [
        str(supplier["id"])
    ]
    assert [t["name"] for t in paperless.objects["tags"]] == list(archive_service.TAGS)
    assert sorted(sent["tags"]) == ["1", "2"] and sent["document_type"] == ["1"]
    assert paperless.objects["document_types"][0]["name"] == "Supplier invoice"


def _grn(db, inv: Invoice) -> str:  # type: ignore[no-untyped-def]
    from app.models import Purchase

    return db.get(Purchase, inv.purchase_id).grn_number


def test_the_original_file_is_sent_unchanged(client: TestClient, env, docs, paperless, db) -> None:
    inv = approved_invoice(client, env, docs)
    process_all()
    row = db.get(Invoice, inv["id"])
    original = (get_settings().storage_dir / row.file_path).read_bytes()
    assert docs["pdf"][0] == original  # what was uploaded is what is stored
    assert len(paperless.uploads) == 1


def test_still_processing_is_retried_without_a_second_upload(
    client: TestClient, env, docs, paperless, db
) -> None:
    inv = approved_invoice(client, env, docs)
    paperless.pending_polls = 1
    with pytest.raises(archive_service.ArchiveError):
        archive_service.archive_invoice(db, inv["id"], wait_seconds=0)
    db.expire_all()
    assert db.get(Invoice, inv["id"]).archive_status == "QUEUED"
    result = archive_service.archive_invoice(db, inv["id"], wait_seconds=0)
    assert result == {"document_id": 101} and len(paperless.uploads) == 1


def test_already_archived_is_never_uploaded_again(
    client: TestClient, env, docs, paperless, db
) -> None:
    inv = approved_invoice(client, env, docs)
    process_all()
    assert archive_service.archive_invoice(db, inv["id"])["skipped"] == "already archived"
    r = client.post(f"/api/v1/invoices/{inv['id']}/archive", headers=env["officer"])
    assert r.json()["archive_status"] == "ARCHIVED" and len(paperless.uploads) == 1


def test_archive_failure_is_shown_and_can_be_retried(
    client: TestClient, env, docs, paperless
) -> None:
    paperless.fail_with = "Error while consuming document: unsupported file"
    inv = approved_invoice(client, env, docs)
    process_all()
    out = client.get(f"/api/v1/invoices/{inv['id']}", headers=env["officer"]).json()
    assert out["archive_status"] == "FAILED" and "unsupported file" in out["archive_error"]
    paperless.fail_with = None
    r = client.post(f"/api/v1/invoices/{inv['id']}/archive", headers=env["officer"])
    assert r.status_code == 200 and r.json()["archive_status"] == "QUEUED"
    process_all()
    out = client.get(f"/api/v1/invoices/{inv['id']}", headers=env["officer"]).json()
    assert out["archive_status"] == "ARCHIVED" and len(paperless.uploads) == 2


def test_refused_token_is_explained(client: TestClient, env, docs, paperless, db) -> None:
    paperless.status_code = 401
    inv = approved_invoice(client, env, docs)
    with pytest.raises(archive_service.ArchiveError):
        archive_service.archive_invoice(db, inv["id"])
    db.expire_all()
    row = db.get(Invoice, inv["id"])
    assert row.archive_status == "FAILED" and "PAPERLESS_TOKEN" in row.archive_error


def test_back_fill_queues_only_unfiled_approved_invoices(
    client: TestClient, env, docs, paperless, db
) -> None:
    inv = approved_invoice(client, env, docs)
    process_all()
    assert archive_service.queue_all_approved(db) == 0  # already filed
    row = db.get(Invoice, inv["id"])
    row.archive_status, row.archive_document_id = None, None
    db.commit()
    assert archive_service.queue_all_approved(db) == 1
    assert db.scalar(select(Invoice.archive_status).where(Invoice.id == inv["id"])) == "QUEUED"


def test_only_approvers_can_trigger_filing(client: TestClient, env, docs, paperless) -> None:
    inv = approved_invoice(client, env, docs)
    assert (
        client.post(f"/api/v1/invoices/{inv['id']}/archive", headers=env["cashier"]).status_code
        == 403
    )
