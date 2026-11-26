"""AI accounting assistant: ask questions, attach receipts/invoices, confirm proposals.

The Claude API key is used only on the server. Each question and answer, every record the
AI looked up and every confirmation is kept as a log (see assistant_service).
"""

from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from app.api.deps import Ctx, DbSession, Pagination, limit_per_user, require
from app.core.config import get_settings
from app.core.permissions import P
from app.models import AssistantConversation, User
from app.schemas.assistant import (
    AssistantStatus,
    ConversationOut,
    ConversationPage,
    ConversationSummary,
    MessageOut,
    ProposalOut,
)
from app.schemas.common import Page
from app.schemas.stock import UserBrief
from app.services import assistant_service, invoice_service, job_service

router = APIRouter(prefix="/assistant", tags=["AI assistant"])

Member = Annotated[User, Depends(require(P.ASSISTANT_USE))]
# Each question costs API credit: cap how many one person can send.
ask_limit = limit_per_user(15, 60, "Too many questions in a minute. Please wait a moment.")


def _out(db: DbSession, conv: AssistantConversation) -> ConversationOut:
    return ConversationOut(
        id=conv.id,
        title=conv.title,
        user=UserBrief.model_validate(conv.user),
        created_at=conv.created_at,
        updated_at=conv.updated_at,
        messages=[MessageOut.model_validate(m) for m in conv.messages],
        proposals=[ProposalOut.model_validate(p) for p in assistant_service.proposals_of(db, conv)],
    )


@router.get("/status", response_model=AssistantStatus)
def status(user: Member) -> AssistantStatus:
    s = get_settings()
    return AssistantStatus(
        enabled=s.assistant_enabled,
        model=s.assistant_model if s.assistant_enabled else None,
        ai_invoice_reading=s.ai_invoice_reader_enabled,
        tools=[t.name for t in assistant_service.tools_for(user)],
        can_see_all=assistant_service.can_see_all(user),
    )


@router.get("/conversations", response_model=ConversationPage)
def conversations(
    user: Member, db: DbSession, pagination: Pagination, everyone: bool = False
) -> ConversationPage:
    rows, total = assistant_service.list_conversations(db, user, pagination, everyone=everyone)
    items = [
        ConversationSummary(
            id=c.id,
            title=c.title,
            user=UserBrief.model_validate(c.user),
            created_at=c.created_at,
            updated_at=c.updated_at,
            messages=n,
        )
        for c, n in rows
    ]
    return ConversationPage(**Page.build(items, total, pagination).model_dump())


@router.get("/conversations/{conversation_id}", response_model=ConversationOut)
def conversation(conversation_id: int, user: Member, db: DbSession) -> ConversationOut:
    return _out(db, assistant_service.get_conversation(db, conversation_id, user))


@router.post("/messages", response_model=ConversationOut, dependencies=[Depends(ask_limit)])
async def ask(
    user: Member,
    db: DbSession,
    ctx: Ctx,
    text: Annotated[str, Form(max_length=4000)] = "",
    conversation_id: Annotated[int | None, Form()] = None,
    file: Annotated[UploadFile | None, File(description="Receipt/invoice photo or PDF")] = None,
) -> ConversationOut:
    """Ask a question (optionally with a receipt or invoice). Returns the whole conversation."""
    upload = None
    if file is not None and file.filename:
        upload = (await file.read(invoice_service.MAX_BYTES + 1), file.filename)
    conv, _, _ = assistant_service.ask(
        db, user, text, conversation_id=conversation_id, file=upload, ctx=ctx
    )
    return _out(db, conv)


@router.get("/messages/{message_id}/attachment", response_class=FileResponse)
def attachment(message_id: int, user: Member, db: DbSession) -> FileResponse:
    m = assistant_service.get_message(db, message_id, user)
    return FileResponse(
        assistant_service.attachment_file(m),
        media_type=m.attachment_mime or "application/octet-stream",
        filename=m.attachment_name,
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/proposals/{proposal_id}/confirm", response_model=ProposalOut)
def confirm(
    proposal_id: int, user: Member, db: DbSession, ctx: Ctx, background: BackgroundTasks
) -> ProposalOut:
    p = assistant_service.confirm(db, proposal_id, user, ctx)
    if p.kind == "INVOICE" and p.result_id:
        job_id = invoice_service.job_to_run_inline(db, p.result_id)
        if job_id is not None:
            background.add_task(job_service.run_now, job_id)
    return ProposalOut.model_validate(p)


@router.post("/proposals/{proposal_id}/cancel", response_model=ProposalOut)
def cancel(proposal_id: int, user: Member, db: DbSession, ctx: Ctx) -> ProposalOut:
    return ProposalOut.model_validate(assistant_service.cancel(db, proposal_id, user, ctx))
