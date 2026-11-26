"""AI accounting assistant (Claude API + tool use).

Staff ask questions in plain language ("What was our profit last week?", "Ni bidhaa gani
zinakaribia kuisha?") or attach a photo of a receipt or invoice. Claude answers by calling
tools that read the shop's own records. Each tool is offered only to users who hold the
permission the matching page needs, so the assistant can never show a cashier the profit
figures. The assistant does not write to the books by itself: it *proposes* an expense,
or sending a supplier invoice to the invoice review, and a person confirms it.

Everything is logged: every question, answer, attached file, record lookup (tool call),
proposal and confirmation, in the assistant tables, plus audit-log entries for proposals
and decisions.

Architecture note: the loop runs here, on the shop's own server, with the Messages API
(Claude Managed Agents would be the hosted alternative; it keeps session history on
Anthropic's side, while this keeps the shop's financial records in its own database).
"""

import base64
import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai import claude
from app.ai.ocr import claude_reader, preprocessing
from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, PermissionDenied, ValidationFailed
from app.core.permissions import P
from app.models import (
    AssistantConversation,
    AssistantMessage,
    AssistantProposal,
    AuditLog,
    ExpenseCategory,
    User,
)
from app.schemas.common import PageParams
from app.schemas.finance import ExpenseIn
from app.services import audit_service, finance_service, invoice_service, product_service
from app.services.audit_service import RequestContext

logger = logging.getLogger(__name__)

MAX_ROUNDS = 8  # tool-use rounds per question
HISTORY_MESSAGES = 20
ATTACHMENTS_IN_CONTEXT = 2  # older attached files are mentioned by name only
MAX_TOKENS = 8000


def _today() -> date:
    from app.services.dashboard_service import today

    return today()


def _j(v: Any) -> Any:
    """JSON-safe copy (Decimal -> str, dates -> ISO)."""
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, dict):
        return {k: _j(x) for k, x in v.items()}
    if isinstance(v, list | tuple):
        return [_j(x) for x in v]
    return v


# --- Tools -----------------------------------------------------------------------------


@dataclass
class Turn:
    """What a tool may use: the session, the asking user, and this conversation."""

    db: Session
    user: User
    conversation: AssistantConversation
    ctx: RequestContext | None
    proposals: list[AssistantProposal]


@dataclass
class Tool:
    name: str
    description: str
    properties: dict[str, Any]
    required: list[str]
    needs: tuple[P, ...]  # user must hold at least one
    run: Callable[[Turn, dict[str, Any]], Any]

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": self.properties,
                "required": self.required,
                "additionalProperties": False,
            },
        }


DATE = {"type": "string", "description": "YYYY-MM-DD"}
PERIOD = {"date_from": DATE, "date_to": DATE}


def _period(args: dict[str, Any]) -> tuple[date, date]:
    try:
        end = date.fromisoformat(args["date_to"]) if args.get("date_to") else _today()
        start = (
            date.fromisoformat(args["date_from"]) if args.get("date_from") else end - timedelta(29)
        )
    except ValueError as exc:
        raise ValidationFailed("Dates must be YYYY-MM-DD.") from exc
    if start > end:
        start, end = end, start
    if (end - start).days > 366 * 3:
        raise ValidationFailed("Ask about at most three years at a time.")
    return start, end


def t_financial_summary(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    return finance_service.summary(t.db, start, end)


def t_daily_sales(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    return finance_service.daily(t.db, start, end)


def t_product_performance(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    rows = finance_service.by_product(t.db, start, end)
    key = a.get("sort_by") or "revenue"
    rows = sorted(rows, key=lambda r: r.get(key) or 0, reverse=True)
    return rows[: max(1, min(int(a.get("limit") or 10), 50))]


def t_category_performance(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    return finance_service.by_category(t.db, start, end)


def t_payment_methods(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    return finance_service.payment_breakdown(t.db, start, end)


def t_list_expenses(t: Turn, a: dict[str, Any]) -> Any:
    start, end = _period(a)
    rows, total, amount = finance_service.list_expenses(
        t.db,
        PageParams(page=1, page_size=100),
        date_from=start,
        date_to=end,
        category_id=a.get("category_id"),
    )
    return {
        "count": total,
        "total_amount": amount,
        "shown": [
            {
                "id": e.id,
                "date": e.expense_date,
                "category": e.category.name,
                "amount": e.amount,
                "description": e.description,
                "payment_method": e.payment_method,
                "reference": e.reference,
                "recorded_by": e.recorded_by.full_name,
            }
            for e in rows
        ],
    }


def t_expense_categories(t: Turn, _: dict[str, Any]) -> Any:
    return [{"id": c.id, "name": c.name} for c in finance_service.categories(t.db) if c.is_active]


def t_search_products(t: Turn, a: dict[str, Any]) -> Any:
    rows, total = product_service.list_products(
        t.db, PageParams(page=1, page_size=15), search=a["query"], stock=a.get("stock") or None
    )
    costs = P.PRODUCTS_VIEW_COST.value in t.user.permission_codes
    out = []
    for p in rows:
        item = {
            "name": p.name,
            "sku": p.sku,
            "barcode": p.barcode,
            "selling_price": p.selling_price,
            "on_hand": p.quantity_on_hand,
            "unit": p.unit_of_measure,
            "min_stock": p.min_stock_level,
            "stock_status": product_service.stock_status(p),
        }
        if costs:
            item["average_cost"] = p.avg_cost
        out.append(item)
    return {"matches": total, "products": out}


def t_stock_alerts(t: Turn, _: dict[str, Any]) -> Any:
    from app.services import dashboard_service

    costs = P.PRODUCTS_VIEW_COST.value in t.user.permission_codes
    return dashboard_service.inventory(t.db, None, with_value=costs)


def t_supplier_invoices(t: Turn, a: dict[str, Any]) -> Any:
    rows, total = invoice_service.list_invoices(
        t.db, PageParams(page=1, page_size=20), status=a.get("status") or None
    )
    return {
        "count": total,
        "invoices": [
            {
                "id": i.id,
                "status": i.status,
                "supplier": i.supplier.name if i.supplier else i.extracted_supplier_name,
                "invoice_number": i.invoice_number,
                "invoice_date": i.invoice_date,
                "grand_total": i.grand_total,
                "uploaded": i.created_at,
            }
            for i in rows
        ],
    }


def t_audit_trail(t: Turn, a: dict[str, Any]) -> Any:
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if a.get("action_contains"):
        stmt = stmt.where(AuditLog.action.ilike(f"%{a['action_contains']}%"))
    rows = t.db.scalars(stmt.limit(max(1, min(int(a.get("limit") or 20), 50)))).all()
    names = dict(t.db.execute(select(User.id, User.full_name)).all())
    return [
        {
            "when": r.created_at,
            "who": names.get(r.user_id, "system"),
            "action": r.action,
            "entity": f"{r.entity_type} {r.entity_id}" if r.entity_type else None,
            "details": r.details,
        }
        for r in rows
    ]


def _propose(t: Turn, kind: str, payload: dict[str, Any], summary: str) -> dict[str, Any]:
    p = AssistantProposal(
        conversation_id=t.conversation.id, kind=kind, payload=_j(payload), status="PENDING"
    )
    t.db.add(p)
    t.db.flush()
    t.proposals.append(p)
    audit_service.record(
        t.db,
        action="assistant.proposed",
        actor=t.user,
        ctx=t.ctx,
        entity_type="assistant_proposal",
        entity_id=p.id,
        after={"kind": kind, **_j(payload)},
        details=summary,
    )
    return {
        "proposal_id": p.id,
        "status": "waiting for the user to press Confirm under your answer; nothing saved yet",
    }


def t_propose_expense(t: Turn, a: dict[str, Any]) -> Any:
    try:
        data = ExpenseIn.model_validate(
            {
                "category_id": a["category_id"],
                "expense_date": a["expense_date"],
                "amount": a["amount"],
                "description": a["description"],
                "payment_method": a["payment_method"],
                "reference": a.get("reference") or None,
            }
        )
    except ValidationError as exc:
        raise ValidationFailed(
            "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors())
        ) from exc
    cat = t.db.get(ExpenseCategory, data.category_id)
    if cat is None or not cat.is_active:
        raise ValidationFailed("Unknown expense category id; call expense_categories first.")
    payload = {**data.model_dump(mode="json"), "category_name": cat.name}
    att = _latest_attachment(t)
    if a.get("from_attached_receipt") and att is not None:
        payload["receipt_message_id"] = att.id
    return _propose(
        t, "EXPENSE", payload, f"Expense {data.amount} {cat.name}: {data.description}"[:250]
    )


def t_propose_supplier_invoice(t: Turn, a: dict[str, Any]) -> Any:
    att = _latest_attachment(t)
    if att is None:
        raise ValidationFailed("No file is attached in this conversation.")
    payload = {
        "message_id": att.id,
        "file": att.attachment_name,
        "supplier": a.get("supplier_name"),
        "invoice_number": a.get("invoice_number"),
        "grand_total": a.get("grand_total"),
    }
    return _propose(t, "INVOICE", payload, f"Send {att.attachment_name} to invoice review")


_TOOLS = [
    Tool(
        "financial_summary",
        "Income statement for a period: revenue (net of VAT and refunds), VAT collected, cost "
        "of goods sold, gross profit and margin, stock losses, operating expenses, estimated "
        "net profit, purchases, number of sales, average basket and discounts. Amounts in KES.",
        PERIOD,
        ["date_from", "date_to"],
        (P.FINANCE_READ,),
        t_financial_summary,
    ),
    Tool(
        "daily_sales",
        "Revenue, profit and number of sales for each day of a period.",
        PERIOD,
        ["date_from", "date_to"],
        (P.FINANCE_READ,),
        t_daily_sales,
    ),
    Tool(
        "product_performance",
        "Best-selling products in a period with quantity, revenue, cost and profit.",
        {
            **PERIOD,
            "sort_by": {"type": "string", "enum": ["revenue", "gross_profit", "quantity"]},
            "limit": {"type": "integer"},
        },
        ["date_from", "date_to", "sort_by", "limit"],
        (P.FINANCE_READ,),
        t_product_performance,
    ),
    Tool(
        "category_performance",
        "Revenue and profit per product category in a period.",
        PERIOD,
        ["date_from", "date_to"],
        (P.FINANCE_READ,),
        t_category_performance,
    ),
    Tool(
        "payment_methods",
        "Takings per payment method (cash, M-Pesa, card) in a period.",
        PERIOD,
        ["date_from", "date_to"],
        (P.FINANCE_READ,),
        t_payment_methods,
    ),
    Tool(
        "list_expenses",
        "Operating expenses recorded in a period (rent, salaries, electricity...), with total.",
        {**PERIOD, "category_id": {"type": ["integer", "null"]}},
        ["date_from", "date_to", "category_id"],
        (P.FINANCE_READ,),
        t_list_expenses,
    ),
    Tool(
        "expense_categories",
        "The expense categories and their ids (needed before proposing an expense).",
        {},
        [],
        (P.EXPENSES_WRITE, P.FINANCE_READ),
        t_expense_categories,
    ),
    Tool(
        "propose_expense",
        "Prepare an operating expense for the user to confirm (nothing is saved until they "
        "press Confirm). Use for receipts and bills such as electricity, rent, transport or "
        "repairs. Set from_attached_receipt when the figures come from the attached file.",
        {
            "category_id": {"type": "integer"},
            "expense_date": DATE,
            "amount": {"type": "string", "description": "KES, digits only, e.g. 4500.00"},
            "description": {"type": "string"},
            "payment_method": {"type": "string", "enum": ["CASH", "MPESA", "CARD", "BANK"]},
            "reference": {"type": ["string", "null"], "description": "Receipt/M-Pesa code"},
            "from_attached_receipt": {"type": "boolean"},
        },
        [
            "category_id",
            "expense_date",
            "amount",
            "description",
            "payment_method",
            "reference",
            "from_attached_receipt",
        ],
        (P.EXPENSES_WRITE,),
        t_propose_expense,
    ),
    Tool(
        "propose_supplier_invoice",
        "Prepare sending the file attached in this conversation (a supplier invoice or delivery "
        "note for stock) to Purchasing → Scan invoices, where it is read, matched to products "
        "and approved by a person before stock changes. The user confirms first.",
        {
            "supplier_name": {"type": ["string", "null"]},
            "invoice_number": {"type": ["string", "null"]},
            "grand_total": {"type": ["string", "null"]},
        },
        ["supplier_name", "invoice_number", "grand_total"],
        (P.INVOICES_UPLOAD,),
        t_propose_supplier_invoice,
    ),
    Tool(
        "search_products",
        "Find products by name, SKU or barcode: price, stock on hand and stock status.",
        {
            "query": {"type": "string"},
            "stock": {"type": ["string", "null"], "enum": ["low", "out", "expiring", "ok", None]},
        },
        ["query", "stock"],
        (P.PRODUCTS_READ,),
        t_search_products,
    ),
    Tool(
        "stock_alerts",
        "Stock overview: products low or out of stock, batches expiring soon, inventory value.",
        {},
        [],
        (P.STOCK_READ,),
        t_stock_alerts,
    ),
    Tool(
        "supplier_invoices",
        "Scanned supplier invoices and their status (to review, approved, rejected, failed).",
        {
            "status": {
                "type": ["string", "null"],
                "enum": ["OPEN", "NEEDS_REVIEW", "APPROVED", "REJECTED", "FAILED", None],
            }
        },
        ["status"],
        (P.INVOICES_UPLOAD, P.INVOICES_APPROVE),
        t_supplier_invoices,
    ),
    Tool(
        "audit_trail",
        "Recent entries of the audit log (who did what and when), optionally filtered by "
        "action, e.g. 'expense', 'sale', 'invoice', 'stock'.",
        {"action_contains": {"type": ["string", "null"]}, "limit": {"type": "integer"}},
        ["action_contains", "limit"],
        (P.AUDIT_READ,),
        t_audit_trail,
    ),
]
TOOLS = {t.name: t for t in _TOOLS}


def tools_for(user: User) -> list[Tool]:
    granted = user.permission_codes
    return [t for t in _TOOLS if any(p.value in granted for p in t.needs)]


# --- Attachments -------------------------------------------------------------------------


def _latest_attachment(t: Turn) -> AssistantMessage | None:
    return t.db.scalar(
        select(AssistantMessage)
        .where(
            AssistantMessage.conversation_id == t.conversation.id,
            AssistantMessage.attachment_path.is_not(None),
        )
        .order_by(AssistantMessage.id.desc())
        .limit(1)
    )


def _store_attachment(data: bytes, filename: str) -> tuple[str, str, str]:
    """Same checks as invoice uploads: real content type, size, image decodes."""
    if not data:
        raise ValidationFailed("The file is empty.", code="UNSUPPORTED_FILE")
    if len(data) > invoice_service.MAX_BYTES:
        raise ValidationFailed("The file is larger than 10 MB.", code="FILE_TOO_LARGE")
    mime, ext = invoice_service.sniff(data)
    if mime != "application/pdf":
        try:
            preprocessing.decode(data)
        except Exception as exc:
            raise ValidationFailed(
                "That image could not be read.", code="UNSUPPORTED_FILE"
            ) from exc
    rel = f"assistant/{uuid.uuid4().hex}.{ext}"
    path = get_settings().storage_dir / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return rel, mime, Path(filename or f"file.{ext}").name[:255]


def attachment_file(m: AssistantMessage) -> Path:
    if not m.attachment_path:
        raise NotFoundError("This message has no attachment.")
    return get_settings().storage_dir / m.attachment_path


def _file_block(m: AssistantMessage) -> dict[str, Any]:
    data = attachment_file(m).read_bytes()
    if m.attachment_mime == "application/pdf":
        return {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(data).decode(),
            },
        }
    jpeg = claude_reader._jpeg(preprocessing.decode(data))
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/jpeg",
            "data": base64.b64encode(jpeg).decode(),
        },
    }


# --- Conversation ------------------------------------------------------------------------


def _system(user: User, tools: list[Tool]) -> str:
    s = get_settings()
    names = ", ".join(t.name for t in tools) or "none"
    return f"""You are the AI accounting assistant of {s.store_name}, a supermarket in \
{s.store_address}, inside its Smart Inventory and accounting system. Currency: \
{s.currency} (write amounts like KES 12,345.00). Today is {_today():%A %d %B %Y} \
(time zone {s.store_timezone}).

You are talking to {user.full_name} ({user.role.display_name if user.role else "staff"}). \
The tools you may use for this person are: {names}. They match this person's permissions. \
If a question needs records you have no tool for, say that their account does not have \
access to that information; do not guess.

Rules:
- Every figure about this shop must come from a tool result in this conversation. Never \
invent, estimate or round away numbers; say which period the numbers cover.
- Work out periods yourself from today's date ("last week" = the previous Monday to \
Sunday, "this month" = the 1st to today).
- You cannot change records yourself. To record an expense call propose_expense; to send a \
supplier invoice for stock to the invoice review call propose_supplier_invoice. Then tell \
the user to check the details and press Confirm under your answer.
- When the user attaches a photo or PDF of a receipt or invoice, read it carefully and \
summarise: who issued it, date, number, items, VAT and total, and anything unclear or \
inconsistent (totals that do not add up, missing KRA PIN, unreadable parts). Then offer \
the right next step: goods for resale bought from a supplier → propose_supplier_invoice; \
a bill or receipt for running costs → propose_expense (use expense_categories for the id).
- Answer in the user's language (English or Kiswahili). Be brief and clear; use short \
lists or small tables for figures. These are accounting records: be exact."""


def _history(db: Session, conv: AssistantConversation) -> list[dict[str, Any]]:
    rows = db.scalars(
        select(AssistantMessage)
        .where(AssistantMessage.conversation_id == conv.id, AssistantMessage.error.is_(None))
        .order_by(AssistantMessage.id.desc())
        .limit(HISTORY_MESSAGES)
    ).all()[::-1]
    with_files = [m.id for m in rows if m.attachment_path][-ATTACHMENTS_IN_CONTEXT:]
    out: list[dict[str, Any]] = []
    for m in rows:
        if m.role == "user":
            blocks: list[dict[str, Any]] = []
            if m.attachment_path:
                if m.id in with_files and attachment_file(m).exists():
                    blocks.append(_file_block(m))
                else:
                    blocks.append(
                        {"type": "text", "text": f"[earlier attached file: {m.attachment_name}]"}
                    )
            blocks.append({"type": "text", "text": m.content or "(see the attached file)"})
            content: Any = blocks
        else:
            content = m.content or "(no answer)"
        if out and out[-1]["role"] == m.role:  # keep roles alternating
            prev = out[-1]["content"]
            if isinstance(prev, str):
                prev = [{"type": "text", "text": prev}]
            out[-1]["content"] = prev + (
                content if isinstance(content, list) else [{"type": "text", "text": content}]
            )
        else:
            out.append({"role": m.role, "content": content})
    while out and out[0]["role"] != "user":
        out.pop(0)
    return out


def _summarise(result: Any) -> str:
    text = json.dumps(_j(result), ensure_ascii=False)
    return text if len(text) <= 300 else text[:297] + "..."


def _run_tool(
    turn: Turn, allowed: dict[str, Tool], name: str, args: dict[str, Any]
) -> tuple[str, bool]:
    tool = allowed.get(name)
    if tool is None:
        return "This user's account does not have access to that tool.", False
    try:
        with turn.db.begin_nested():  # a failing tool undoes only its own changes
            result = tool.run(turn, args or {})
        return json.dumps(_j(result), ensure_ascii=False), True
    except (ValidationFailed, NotFoundError, ConflictError, PermissionDenied) as exc:
        return f"Error: {exc}", False
    except Exception:
        logger.exception("Assistant tool %s failed", name)
        return "Error: the records could not be read just now.", False


def ask(
    db: Session,
    user: User,
    text: str,
    *,
    conversation_id: int | None = None,
    file: tuple[bytes, str] | None = None,
    ctx: RequestContext | None = None,
) -> tuple[AssistantConversation, list[AssistantMessage], list[AssistantProposal]]:
    """One question (optionally with a file) → one answer. Both are stored either way."""
    if not get_settings().assistant_enabled:
        raise ConflictError(
            "The AI assistant is not set up: add ANTHROPIC_API_KEY to the server's .env file "
            "and restart the app.",
            code="ASSISTANT_NOT_CONFIGURED",
        )
    text = (text or "").strip()
    if not text and file is None:
        raise ValidationFailed("Type a question or attach a file.")
    if len(text) > 4000:
        raise ValidationFailed("Please keep a question under 4,000 characters.")

    if conversation_id is not None:
        conv = get_conversation(db, conversation_id, user, write=True)
    else:
        title = text or (f"File: {file[1]}" if file else "Conversation")
        conv = AssistantConversation(user_id=user.id, title=title[:120])
        db.add(conv)
        db.flush()

    question = AssistantMessage(conversation_id=conv.id, role="user", content=text)
    if file is not None:
        question.attachment_path, question.attachment_mime, question.attachment_name = (
            _store_attachment(*file)
        )
    db.add(question)
    conv.updated_at = datetime.now(UTC)
    db.commit()  # the question is logged even if the AI call fails

    tools = tools_for(user)
    allowed = {t.name: t for t in tools}
    turn = Turn(db=db, user=user, conversation=conv, ctx=ctx, proposals=[])
    messages = _history(db, conv)
    log: list[dict[str, Any]] = []
    used = {"input_tokens": 0, "output_tokens": 0}
    answer = AssistantMessage(conversation_id=conv.id, role="assistant", content="")
    try:
        for _ in range(MAX_ROUNDS):
            kw: dict[str, Any] = {}
            if tools:
                kw["tools"] = [t.schema() for t in tools]
            response = claude.create(
                max_tokens=MAX_TOKENS, system=_system(user, tools), messages=messages, **kw
            )
            for k, v in claude.usage_of(response).items():
                used[k] += v
            answer.model = str(getattr(response, "model", "") or "")[:60] or None
            calls = [b for b in response.content if b.type == "tool_use"]
            if response.stop_reason != "tool_use" or not calls:
                answer.content = claude.text_of(response) or (
                    "I could not finish that answer. Please ask again in a shorter way."
                    if response.stop_reason == "max_tokens"
                    else ""
                )
                break
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for call in calls:
                out, ok = _run_tool(turn, allowed, call.name, dict(call.input or {}))
                log.append(
                    {"tool": call.name, "input": _j(call.input), "ok": ok, "summary": out[:300]}
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": out,
                        "is_error": not ok,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            answer.content = "That needed too many steps. Please ask a narrower question."
    except claude.AIUnavailable as exc:
        answer.error = str(exc)
        answer.content = str(exc)
    answer.tool_log = log or None
    answer.input_tokens, answer.output_tokens = used["input_tokens"], used["output_tokens"]
    db.add(answer)
    db.flush()
    for p in turn.proposals:
        p.message_id = answer.id
    conv.updated_at = datetime.now(UTC)
    db.commit()
    db.refresh(conv)
    return conv, [question, answer], turn.proposals


# --- Reading the log ---------------------------------------------------------------------


def can_see_all(user: User) -> bool:
    return P.AUDIT_READ.value in user.permission_codes


def get_conversation(
    db: Session, conversation_id: int, user: User, *, write: bool = False
) -> AssistantConversation:
    conv = db.get(AssistantConversation, conversation_id)
    if conv is None:
        raise NotFoundError("Conversation not found.")
    if conv.user_id != user.id and (write or not can_see_all(user)):
        raise NotFoundError("Conversation not found.")
    return conv


def list_conversations(
    db: Session, user: User, params: PageParams, *, everyone: bool = False
) -> tuple[list[tuple[AssistantConversation, int]], int]:
    stmt = select(AssistantConversation)
    if not (everyone and can_see_all(user)):
        stmt = stmt.where(AssistantConversation.user_id == user.id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(AssistantConversation.updated_at.desc(), AssistantConversation.id.desc())
        .offset(params.offset)
        .limit(params.page_size)
    ).all()
    counts = dict(
        db.execute(
            select(AssistantMessage.conversation_id, func.count())
            .where(AssistantMessage.conversation_id.in_([c.id for c in rows] or [0]))
            .group_by(AssistantMessage.conversation_id)
        ).all()
    )
    return [(c, int(counts.get(c.id, 0))) for c in rows], total


def proposals_of(db: Session, conv: AssistantConversation) -> list[AssistantProposal]:
    return list(
        db.scalars(
            select(AssistantProposal)
            .where(AssistantProposal.conversation_id == conv.id)
            .order_by(AssistantProposal.id)
        )
    )


def get_message(db: Session, message_id: int, user: User) -> AssistantMessage:
    m = db.get(AssistantMessage, message_id)
    if m is None:
        raise NotFoundError("Message not found.")
    get_conversation(db, m.conversation_id, user)
    return m


# --- Confirming proposals ----------------------------------------------------------------


def _pending(db: Session, proposal_id: int, user: User) -> AssistantProposal:
    p = db.scalar(
        select(AssistantProposal).where(AssistantProposal.id == proposal_id).with_for_update()
    )
    if p is None:
        raise NotFoundError("Not found.")
    conv = get_conversation(db, p.conversation_id, user, write=True)
    if p.status != "PENDING":
        raise ConflictError(f"This was already {p.status.lower()}.", code="ALREADY_DECIDED")
    del conv
    return p


def confirm(db: Session, proposal_id: int, user: User, ctx: RequestContext) -> AssistantProposal:
    """Save what the AI proposed, through the same service (and checks) as the normal page."""
    p = _pending(db, proposal_id, user)
    granted = user.permission_codes
    if p.kind == "EXPENSE":
        if P.EXPENSES_WRITE.value not in granted:
            raise PermissionDenied("You do not have permission to record expenses.")
        data = ExpenseIn.model_validate(
            {k: p.payload.get(k) for k in ExpenseIn.model_fields if k in p.payload}
        )
        exp = finance_service.create_expense(db, data, user, ctx)
        p.result_id = exp.id
    elif p.kind == "INVOICE":
        if P.INVOICES_UPLOAD.value not in granted:
            raise PermissionDenied("You do not have permission to upload supplier invoices.")
        m = db.get(AssistantMessage, int(p.payload["message_id"]))
        if m is None or m.conversation_id != p.conversation_id:
            raise NotFoundError("The attached file is no longer available.")
        inv = invoice_service.upload(
            db, attachment_file(m).read_bytes(), m.attachment_name or "invoice", user, ctx
        )
        p.result_id = inv.id
    p.status, p.decided_by_id, p.decided_at = "CONFIRMED", user.id, datetime.now(UTC)
    audit_service.record(
        db,
        action="assistant.confirmed",
        actor=user,
        ctx=ctx,
        entity_type="assistant_proposal",
        entity_id=p.id,
        after={"kind": p.kind, "result_id": p.result_id},
    )
    db.commit()
    db.refresh(p)
    return p


def cancel(db: Session, proposal_id: int, user: User, ctx: RequestContext) -> AssistantProposal:
    p = _pending(db, proposal_id, user)
    p.status, p.decided_by_id, p.decided_at = "CANCELLED", user.id, datetime.now(UTC)
    audit_service.record(
        db,
        action="assistant.cancelled",
        actor=user,
        ctx=ctx,
        entity_type="assistant_proposal",
        entity_id=p.id,
        after={"kind": p.kind},
    )
    db.commit()
    db.refresh(p)
    return p
