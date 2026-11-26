"""AI accounting assistant and AI invoice reading.

The Claude API is replaced by a fake HTTP transport that answers in the Messages API's
format, so the whole flow runs: request building (model, effort, fallbacks, strict tools,
images), the tool loop against the real database, permissions, proposals, confirmation
and logging. A real Claude call needs the shop's own ANTHROPIC_API_KEY.
"""

# ruff: noqa: F811  (fixtures are imported from the invoice tests)
import io
import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from app.ai import claude
from app.core.config import get_settings
from app.models import AssistantMessage, AuditLog, Expense, Invoice
from app.services import job_service
from tests.integration.test_invoices_api import docs, env, process_all, upload  # noqa: F401

Reply = Callable[[dict[str, Any]], dict[str, Any]] | dict[str, Any]


def message(content: list[dict[str, Any]], stop: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop,
        "stop_sequence": None,
        "usage": {"input_tokens": 120, "output_tokens": 30},
    }


def text(t: str) -> dict[str, Any]:
    return message([{"type": "text", "text": t}])


def tool(name: str, args: dict[str, Any], tid: str = "toolu_1") -> dict[str, Any]:
    return message([{"type": "tool_use", "id": tid, "name": name, "input": args}], "tool_use")


class FakeClaude:
    def __init__(self) -> None:
        self.replies: list[Reply] = []
        self.requests: list[dict[str, Any]] = []
        self.headers: list[httpx2.Headers] = []
        self.status: int | None = None

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/v1/messages"
        body = json.loads(request.content)
        self.requests.append(body)
        self.headers.append(request.headers)
        if self.status:
            return httpx2.Response(
                self.status,
                json={"type": "error", "error": {"type": "authentication_error", "message": "x"}},
            )
        reply = self.replies.pop(0)
        return httpx2.Response(200, json=reply(body) if callable(reply) else reply)


@pytest.fixture
def fake(monkeypatch):  # type: ignore[no-untyped-def]
    s = get_settings()
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")
    f = FakeClaude()
    claude.set_client(
        anthropic.Anthropic(
            api_key="test-key",
            max_retries=0,
            http_client=httpx2.Client(transport=httpx2.MockTransport(f.handler)),
        )
    )
    yield f
    claude.set_client(None)


def ask(client: TestClient, h: dict, q: str, conv: int | None = None, file=None):  # type: ignore[no-untyped-def]
    data: dict[str, Any] = {"text": q}
    if conv:
        data["conversation_id"] = str(conv)
    return client.post("/api/v1/assistant/messages", headers=h, data=data, files=file)


def png_receipt() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (400, 600), "white").save(buf, "PNG")
    return buf.getvalue()


# --- Not configured -----------------------------------------------------------------


def test_without_a_key_the_assistant_says_it_is_not_set_up(client: TestClient, env) -> None:
    h = env["officer"]
    st = client.get("/api/v1/assistant/status", headers=h).json()
    assert st["enabled"] is False and st["model"] is None
    r = ask(client, h, "What is low on stock?")
    assert r.status_code == 409 and r.json()["error"]["code"] == "ASSISTANT_NOT_CONFIGURED"
    assert client.get("/api/v1/store", headers=h).json()["assistant_enabled"] is False


# --- Questions answered from the records ------------------------------------------------


def test_question_is_answered_from_the_books_and_logged(
    client: TestClient, env, fake, auth_headers, db
) -> None:
    _, h = auth_headers("store_manager", username="mgr")

    def answer(body: dict[str, Any]) -> dict[str, Any]:
        result = json.loads(body["messages"][-1]["content"][0]["content"])
        return text(
            f"Revenue was KES {result['revenue']} and net profit {result['net_profit_estimate']}."
        )

    fake.replies = [
        tool("financial_summary", {"date_from": "2026-11-01", "date_to": "2026-11-26"}),
        answer,
    ]
    r = ask(client, h, "How much profit did we make this month?")
    assert r.status_code == 200, r.text
    conv = r.json()
    user_msg, reply = conv["messages"]
    assert user_msg["content"] == "How much profit did we make this month?"
    assert reply["content"].startswith("Revenue was KES 0") and reply["error"] is None
    assert reply["tool_log"][0]["tool"] == "financial_summary" and reply["tool_log"][0]["ok"]
    assert reply["input_tokens"] == 240 and reply["model"] == "claude-opus-5-5"

    first = fake.requests[0]
    assert first["model"] == "claude-opus-5-5"
    assert first["fallbacks"] == "default"
    assert "server-side-fallback-2026-07-01" in fake.headers[0]["anthropic-beta"]
    assert first["output_config"]["effort"] == "medium"
    assert all(t["strict"] is True for t in first["tools"])
    assert "financial_summary" in {t["name"] for t in first["tools"]}
    assert "Store Manager" in first["system"]
    assert "x-api-key" in fake.headers[0] and fake.headers[0]["x-api-key"] == "test-key"
    # The tool result went back to Claude paired with its tool_use id.
    assert fake.requests[1]["messages"][-1]["content"][0]["tool_use_id"] == "toolu_1"

    # A follow-up question carries the earlier exchange.
    fake.replies = [text("Yes.")]
    r = ask(client, h, "Is that good?", conv=conv["id"])
    msgs = fake.requests[-1]["messages"]
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assert msgs[1]["content"].startswith("Revenue was")
    assert len(r.json()["messages"]) == 4


def test_tools_follow_the_users_permissions(client: TestClient, env, fake) -> None:
    h = env["cashier"]
    st = client.get("/api/v1/assistant/status", headers=h).json()
    assert st["enabled"] and "financial_summary" not in st["tools"]
    assert st["tools"] == ["search_products"]
    # Even if the model asks for a tool it was not given, nothing is read.
    fake.replies = [
        tool("financial_summary", {"date_from": "2026-11-01", "date_to": "2026-11-26"}),
        text("Sorry, your account cannot see profit figures."),
    ]
    r = ask(client, h, "What was the profit?")
    log = r.json()["messages"][1]["tool_log"][0]
    assert not log["ok"] and "does not have access" in log["summary"]
    assert {t["name"] for t in fake.requests[0]["tools"]} == {"search_products"}


def test_product_search_reads_real_stock(client: TestClient, env, fake) -> None:
    fake.replies = [
        tool("search_products", {"query": "milk", "stock": None}),
        lambda body: text(body["messages"][-1]["content"][0]["content"]),
    ]
    r = ask(client, env["officer"], "How much milk do we have?")
    found = json.loads(r.json()["messages"][1]["content"])
    assert found["matches"] >= 1 and "on_hand" in found["products"][0]


# --- Receipts: read, propose, confirm --------------------------------------------------


def test_receipt_photo_becomes_an_expense_only_after_confirmation(
    client: TestClient, env, fake, db
) -> None:
    h = env["admin"]
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    power = next(c for c in cats if c["name"] == "Electricity")

    def propose(body: dict[str, Any]) -> dict[str, Any]:
        return tool(
            "propose_expense",
            {
                "category_id": power["id"],
                "expense_date": "2026-11-20",
                "amount": "4520.00",
                "description": "Kenya Power token, November",
                "payment_method": "MPESA",
                "reference": "QK7Y2LM9PA",
                "from_attached_receipt": True,
            },
            "toolu_2",
        )

    fake.replies = [
        tool("expense_categories", {}),
        propose,
        text("This is a KPLC receipt for KES 4,520.00. Press Confirm to record it."),
    ]
    r = ask(
        client,
        h,
        "Record this receipt",
        file={"file": ("kplc.png", png_receipt(), "image/png")},
    )
    assert r.status_code == 200, r.text
    conv = r.json()
    sent = fake.requests[0]["messages"][0]["content"]
    assert sent[0]["type"] == "image" and sent[0]["source"]["media_type"] == "image/jpeg"
    assert (
        conv["messages"][0]["has_attachment"]
        and conv["messages"][0]["attachment_name"] == "kplc.png"
    )
    (p,) = conv["proposals"]
    assert p["kind"] == "EXPENSE" and p["status"] == "PENDING"
    assert p["payload"]["category_name"] == "Electricity"
    assert db.scalar(select(Expense).where(Expense.reference == "QK7Y2LM9PA")) is None

    a = client.get(f"/api/v1/assistant/messages/{conv['messages'][0]['id']}/attachment", headers=h)
    assert a.status_code == 200 and a.content[:4] == b"\x89PNG"

    r = client.post(f"/api/v1/assistant/proposals/{p['id']}/confirm", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED"
    exp = db.scalar(select(Expense).where(Expense.reference == "QK7Y2LM9PA"))
    assert exp is not None and str(exp.amount) == "4520.00"
    assert r.json()["result_id"] == exp.id
    again = client.post(f"/api/v1/assistant/proposals/{p['id']}/confirm", headers=h)
    assert again.status_code == 409
    actions = set(db.scalars(select(AuditLog.action)).all())
    assert {"assistant.proposed", "assistant.confirmed", "expense.create"} <= actions


def test_a_cancelled_proposal_records_nothing(client: TestClient, env, fake, db) -> None:
    h = env["admin"]
    cats = client.get("/api/v1/expense-categories", headers=h).json()
    fake.replies = [
        tool(
            "propose_expense",
            {
                "category_id": cats[0]["id"],
                "expense_date": "2026-11-20",
                "amount": "1000",
                "description": "Rent deposit",
                "payment_method": "BANK",
                "reference": None,
                "from_attached_receipt": False,
            },
        ),
        text("Ready to confirm."),
    ]
    p = ask(client, h, "Record rent 1000").json()["proposals"][0]
    r = client.post(f"/api/v1/assistant/proposals/{p['id']}/cancel", headers=h)
    assert r.json()["status"] == "CANCELLED"
    assert db.scalar(select(Expense)) is None


def test_invalid_figures_from_the_model_are_rejected(client: TestClient, env, fake) -> None:
    fake.replies = [
        tool(
            "propose_expense",
            {
                "category_id": 999999,
                "expense_date": "2026-11-20",
                "amount": "-5",
                "description": "x",
                "payment_method": "CASH",
                "reference": None,
                "from_attached_receipt": False,
            },
        ),
        text("I could not prepare that."),
    ]
    conv = ask(client, env["admin"], "record -5").json()
    assert conv["proposals"] == [] and not conv["messages"][1]["tool_log"][0]["ok"]


def test_attached_supplier_invoice_goes_to_invoice_review(
    client: TestClient, env, fake, docs, db
) -> None:
    h = env["officer"]
    data, _ = docs["pdf"]
    fake.replies = [
        tool(
            "propose_supplier_invoice",
            {"supplier_name": "Dairy Ltd", "invoice_number": "SI/1", "grand_total": "100"},
        ),
        text("Press Confirm to send it to the invoice review."),
    ]
    conv = ask(
        client, h, "Here is today's delivery", file={"file": ("inv.pdf", data, "application/pdf")}
    ).json()
    assert fake.requests[0]["messages"][0]["content"][0]["type"] == "document"
    p = conv["proposals"][0]
    r = client.post(f"/api/v1/assistant/proposals/{p['id']}/confirm", headers=h)
    assert r.status_code == 200, r.text
    inv = db.get(Invoice, r.json()["result_id"])
    assert inv.status == "QUEUED" and inv.original_filename == "inv.pdf"
    get_settings().anthropic_api_key = ""  # read this one with the normal OCR
    process_all()
    db.expire_all()
    assert db.get(Invoice, inv.id).status == "NEEDS_REVIEW"


# --- Errors and privacy ----------------------------------------------------------------


def test_api_failure_is_explained_and_the_question_kept(client: TestClient, env, fake, db) -> None:
    fake.status = 401
    r = ask(client, env["officer"], "hello")
    assert r.status_code == 200
    reply = r.json()["messages"][1]
    assert "refused the API key" in reply["error"]
    assert db.scalar(select(AssistantMessage).where(AssistantMessage.content == "hello"))


def test_conversations_are_private_but_visible_to_auditors(client: TestClient, env, fake) -> None:
    fake.replies = [text("Hi")]
    conv = ask(client, env["officer"], "hello").json()
    other = client.get(f"/api/v1/assistant/conversations/{conv['id']}", headers=env["cashier"])
    assert other.status_code == 404
    mine = client.get("/api/v1/assistant/conversations", headers=env["cashier"]).json()
    assert mine["total"] == 0
    everyone = client.get(
        "/api/v1/assistant/conversations?everyone=true", headers=env["admin"]
    ).json()
    assert everyone["items"][0]["id"] == conv["id"] and everyone["items"][0]["messages"] == 2
    fake.replies = [text("x")]
    r = ask(client, env["cashier"], "hijack", conv=conv["id"])
    assert r.status_code == 404


# --- AI invoice reading ----------------------------------------------------------------

READ = {
    "document_kind": "supplier_invoice",
    "supplier_name": "Fresh Dairy Ltd",
    "supplier_kra_pin": "P051234567X",
    "invoice_number": "FD-2201",
    "invoice_date": "2026-11-24",
    "prices_include_vat": False,
    "vat_rate_percent": 16,
    "subtotal": "1,000.00",
    "tax_total": "160.00",
    "grand_total": "1160.00",
    "items": [
        {
            "description": "Fresh Milk 500ml",
            "item_code": None,
            "quantity": "20",
            "unit_price": "50.00",
            "line_total": "1000.00",
            "source_text": "Fresh Milk 500ml 20 50.00 1000.00",
            "unsure": False,
        }
    ],
    "uncertain_fields": ["invoice_date"],
    "transcript": "FRESH DAIRY LTD\nPIN P051234567X\nInvoice FD-2201",
}


def test_scanned_invoice_is_read_by_the_ai(client: TestClient, env, fake, docs, db) -> None:
    fake.replies = [message([{"type": "text", "text": json.dumps(READ)}])]
    data, _ = docs["classic"]
    inv = upload(client, env["officer"], data, "photo.jpg").json()
    process_all()
    out = client.get(f"/api/v1/invoices/{inv['id']}", headers=env["officer"]).json()
    assert out["status"] == "NEEDS_REVIEW", out
    assert out["invoice_number"] == "FD-2201" and out["grand_total"] == "1160.00"
    assert out["subtotal"] == "1000.00"
    assert out["items"][0]["description"] == "Fresh Milk 500ml"
    assert out["items"][0]["arithmetic_ok"] is True
    assert out["field_confidences"]["invoice_date"] == 0.5
    assert out["field_confidences"]["invoice_number"] == 0.9
    req = fake.requests[0]
    assert req["output_config"]["format"]["type"] == "json_schema"
    assert req["messages"][0]["content"][0]["type"] == "image"
    row = db.get(Invoice, inv["id"])
    assert row.ocr_engine == "claude-vision"


def test_if_the_ai_cannot_read_it_tesseract_does(client: TestClient, env, fake, docs, db) -> None:
    fake.status = 401
    data, truth = docs["classic"]
    inv = upload(client, env["officer"], data, "photo.jpg").json()
    process_all()
    row = db.get(Invoice, inv["id"])
    assert row.status == "NEEDS_REVIEW" and row.ocr_engine != "claude-vision"
    assert "AI reading was not available" in row.processing_steps[0]
    assert row.invoice_number == truth["invoice_number"]


# --- Scanning without a running worker ---------------------------------------------------


def test_upload_is_read_even_when_no_worker_is_running(
    client: TestClient, env, docs, monkeypatch, db
) -> None:
    s = get_settings()
    monkeypatch.setattr(s, "worker_inline_fallback", True)
    hb = s.storage_dir / job_service.HEARTBEAT_FILE
    hb.unlink(missing_ok=True)
    data, _ = docs["classic"]
    r = upload(client, env["officer"], data, "photo.jpg")
    assert r.status_code == 202
    db.expire_all()
    assert db.get(Invoice, r.json()["id"]).status == "NEEDS_REVIEW"  # read by the API itself

    job_service.touch_heartbeat()  # a worker is alive: leave it to the worker
    data2, _ = docs["pdf"]
    r = upload(client, env["officer"], data2, "b.pdf")
    db.expire_all()
    assert db.get(Invoice, r.json()["id"]).status == "QUEUED"
    hb.unlink(missing_ok=True)
