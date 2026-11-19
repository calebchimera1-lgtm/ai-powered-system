"""M-Pesa STK push: payment prompt to the customer's phone."""

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, status

from app.api.deps import Ctx, DbSession, limit_per_user, require
from app.core.permissions import P
from app.models import User
from app.schemas.payments import MpesaPaymentOut, StkPushRequest
from app.services import mpesa_service

router = APIRouter(prefix="/payments/mpesa", tags=["Payments"])

Seller = Annotated[User, Depends(require(P.SALES_CREATE))]
prompt_limit = limit_per_user(10, 60, "Too many payment prompts in a minute. Wait a moment.")


def _out(p) -> MpesaPaymentOut:  # type: ignore[no-untyped-def]
    out = MpesaPaymentOut.model_validate(p)
    out.phone = p.phone[:6] + "***" + p.phone[-3:]  # enough to recognise, not to harvest
    return out


@router.post(
    "/stk-push",
    response_model=MpesaPaymentOut,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(prompt_limit)],
)
def send_prompt(body: StkPushRequest, user: Seller, db: DbSession, ctx: Ctx) -> MpesaPaymentOut:
    """Send an M-Pesa payment prompt to the customer's phone. Poll the result with GET."""
    return _out(mpesa_service.start(db, user, body.phone, body.amount, ctx))


@router.get("/{payment_id}", response_model=MpesaPaymentOut)
def payment_status(payment_id: int, user: Seller, db: DbSession) -> MpesaPaymentOut:
    """Current state of a prompt; while pending, asks Safaricom (at most every 5 seconds)."""
    p = mpesa_service.get_for(
        db, payment_id, user, see_all=P.SALES_READ_ALL.value in user.permission_codes
    )
    return _out(mpesa_service.refresh(db, p))


@router.post("/callback/{token}", include_in_schema=False)
def callback(
    token: str, db: DbSession, payload: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    """Result callback from Safaricom (public; the secret token in the URL authenticates it)."""
    mpesa_service.handle_callback(db, token, payload)
    return {"ResultCode": 0, "ResultDesc": "Accepted"}
