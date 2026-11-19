"""M-Pesa STK push: send a payment prompt to a customer's phone and track the result.

Flow:
1. The cashier enters the customer's number; ``start`` asks Safaricom to send the prompt.
2. The customer enters their M-Pesa PIN on their phone.
3. The result arrives by callback (if the shop has a public HTTPS address configured), or
   the till asks for it: ``refresh`` calls Safaricom's STK query while the payment is pending.
4. A SUCCESS payment can be attached to exactly one sale at checkout.
"""

import hmac
import logging
import math
import re
import time
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConflictError, NotFoundError, ValidationFailed
from app.models import MpesaPayment, User
from app.services import audit_service, daraja
from app.services.audit_service import RequestContext

logger = logging.getLogger(__name__)

QUERY_INTERVAL = timedelta(seconds=5)
GIVE_UP_AFTER = timedelta(minutes=3)  # the prompt on the phone expires well before this
PLACEHOLDER_CALLBACK = "https://example.com/mpesa/callback"  # results then come by STK query

PHONE_RE = re.compile(r"^(?:\+?254|0)?([17]\d{8})$")

# Safaricom result codes -> (status, message for the cashier)
RESULTS: dict[str, tuple[str, str]] = {
    "0": ("SUCCESS", "Paid"),
    "1032": ("CANCELLED", "The customer cancelled the prompt."),
    "1037": (
        "TIMEOUT",
        "The customer's phone could not be reached, or they did not answer in time.",
    ),
    "1019": ("TIMEOUT", "The prompt expired before the customer answered."),
    "1": ("FAILED", "The customer's M-Pesa balance is not enough."),
    "2001": ("FAILED", "The customer entered a wrong M-Pesa PIN."),
    "1001": ("FAILED", "The customer's phone is busy with another M-Pesa request. Try again."),
    "1025": ("FAILED", "M-Pesa could not send the prompt. Try again."),
    "9999": ("FAILED", "M-Pesa could not send the prompt. Try again."),
}
PROCESSING_ERRORS = {"500.001.1001"}  # STK query: "The transaction is being processed"


def utcnow() -> datetime:
    return datetime.now(UTC)


def normalise_phone(raw: str) -> str:
    """0712 345 678, +254 712 345 678, 712345678 -> 254712345678 (Safaricom format)."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    m = PHONE_RE.match(digits)
    if not m:
        raise ValidationFailed(
            "Enter a Kenyan mobile number such as 0712 345 678.",
            details=[{"field": "phone", "message": "not a Kenyan mobile number"}],
        )
    return "254" + m.group(1)


def whole_shillings(total: Decimal) -> int:
    """M-Pesa only takes whole shillings; cents are rounded up so the shop is never short."""
    return max(1, math.ceil(total))


def _ensure_enabled() -> None:
    if not get_settings().mpesa_enabled:
        raise ConflictError(
            "M-Pesa payment prompts are not set up. Enter the transaction code from the "
            "customer's SMS instead, or ask an administrator to add the Daraja settings.",
            code="MPESA_NOT_CONFIGURED",
        )


def _callback_url() -> str:
    s = get_settings()
    if s.mpesa_callback_base_url and s.mpesa_callback_token:
        base = s.mpesa_callback_base_url.rstrip("/")
        return f"{base}/api/v1/payments/mpesa/callback/{s.mpesa_callback_token}"
    return PLACEHOLDER_CALLBACK


def start(
    db: Session, user: User, phone: str, sale_total: Decimal, ctx: RequestContext
) -> MpesaPayment:
    _ensure_enabled()
    msisdn = normalise_phone(phone)
    amount = whole_shillings(sale_total)
    reference = f"POS{int(time.time()) % 10**9}"
    payment = MpesaPayment(
        phone=msisdn,
        amount=amount,
        sale_total=sale_total,
        account_reference=reference,
        status="PENDING",
        initiated_by_id=user.id,
    )
    db.add(payment)
    db.flush()
    try:
        r = daraja.get_client().stk_push(
            phone=msisdn,
            amount=amount,
            reference=reference,
            description="Shop payment",
            callback_url=_callback_url(),
        )
    except daraja.DarajaError as exc:
        db.rollback()
        raise ValidationFailed(str(exc), code="MPESA_UNAVAILABLE") from exc

    if str(r.get("ResponseCode")) == "0" and r.get("CheckoutRequestID"):
        payment.checkout_request_id = r["CheckoutRequestID"]
        payment.merchant_request_id = r.get("MerchantRequestID")
        payment.result_desc = "Waiting for the customer to enter their M-Pesa PIN"
    else:
        payment.status = "FAILED"
        payment.result_code = str(r.get("errorCode") or r.get("ResponseCode") or "")[:20]
        payment.result_desc = _safe_text(
            r.get("errorMessage")
            or r.get("ResponseDescription")
            or "M-Pesa did not accept the request."
        )
        payment.completed_at = utcnow()
    audit_service.record(
        db,
        action="payment.mpesa_prompt_sent",
        actor=user,
        ctx=ctx,
        entity_type="mpesa_payment",
        entity_id=payment.id,
        after={"phone": _mask(msisdn), "amount": amount, "status": payment.status},
    )
    db.commit()
    db.refresh(payment)
    return payment


def get_for(db: Session, payment_id: int, user: User, *, see_all: bool) -> MpesaPayment:
    p = db.get(MpesaPayment, payment_id)
    if p is None or (p.initiated_by_id != user.id and not see_all):
        raise NotFoundError("Payment not found")
    return p


def refresh(db: Session, p: MpesaPayment) -> MpesaPayment:
    """While a payment is pending, ask Safaricom for its result (at most every 5 seconds)."""
    if p.status != "PENDING" or not p.checkout_request_id:
        return p
    now = utcnow()
    if now - p.created_at < QUERY_INTERVAL:
        return p
    if p.last_checked_at and now - p.last_checked_at < QUERY_INTERVAL:
        return p
    p.last_checked_at = now
    try:
        r = daraja.get_client().stk_query(p.checkout_request_id)
    except daraja.DarajaError:
        db.commit()  # keep last_checked_at; try again on the next poll
        return p
    code = r.get("ResultCode")
    if code is not None and str(r.get("ResponseCode", "0")) == "0":
        _apply_result(p, str(code), r.get("ResultDesc"))
    elif r.get("errorCode") in PROCESSING_ERRORS:
        pass  # the customer has not answered yet
    if p.status == "PENDING" and now - p.created_at > GIVE_UP_AFTER:
        p.status, p.result_desc, p.completed_at = "TIMEOUT", "No answer from M-Pesa.", now
    db.commit()
    db.refresh(p)
    return p


def _apply_result(
    p: MpesaPayment, code: str, desc: Any, metadata: dict[str, Any] | None = None
) -> None:
    status, message = RESULTS.get(code, ("FAILED", "M-Pesa did not complete the payment."))
    p.status = status
    p.result_code = code[:20]
    p.result_desc = (
        message if status != "FAILED" or code in RESULTS else _safe_text(desc) or message
    )
    p.completed_at = utcnow()
    if metadata:
        receipt = metadata.get("MpesaReceiptNumber")
        if receipt and re.fullmatch(r"[A-Z0-9]{8,20}", str(receipt)):
            p.mpesa_receipt_number = str(receipt)
        if metadata.get("PhoneNumber"):
            p.paid_phone = str(metadata["PhoneNumber"])[:15]
        paid = metadata.get("Amount")
        if status == "SUCCESS" and paid is not None and Decimal(str(paid)) < p.amount:
            p.status, p.result_desc = "FAILED", "M-Pesa reported a smaller amount than requested."


def handle_callback(db: Session, token: str, payload: dict[str, Any]) -> bool:
    """Safaricom's result callback. The secret token in the URL proves it came from the
    address given to Safaricom; unknown or already-final payments are ignored."""
    expected = get_settings().mpesa_callback_token
    if not expected or not hmac.compare_digest(token, expected):
        raise NotFoundError("Not found")
    cb = (payload.get("Body") or {}).get("stkCallback") or {}
    checkout_id = cb.get("CheckoutRequestID")
    if not isinstance(checkout_id, str):
        return False
    p = db.scalar(
        select(MpesaPayment)
        .where(MpesaPayment.checkout_request_id == checkout_id)
        .with_for_update(of=MpesaPayment)
    )
    if p is None or p.status != "PENDING":
        return False
    items = (cb.get("CallbackMetadata") or {}).get("Item") or []
    metadata = {i.get("Name"): i.get("Value") for i in items if isinstance(i, dict)}
    _apply_result(p, str(cb.get("ResultCode")), cb.get("ResultDesc"), metadata)
    p.callback_payload = {
        "ResultCode": cb.get("ResultCode"),
        "ResultDesc": _safe_text(cb.get("ResultDesc")),
        "Receipt": p.mpesa_receipt_number,
    }
    db.commit()
    return True


def claim_for_sale(
    db: Session, payment_id: int, cashier: User, grand_total: Decimal
) -> MpesaPayment:
    """Lock a successful payment so it can be attached to one sale (called inside checkout)."""
    p = db.scalar(
        select(MpesaPayment).where(MpesaPayment.id == payment_id).with_for_update(of=MpesaPayment)
    )
    if p is None or p.initiated_by_id != cashier.id:
        raise ValidationFailed("That M-Pesa payment was not found.", code="MPESA_PAYMENT_INVALID")
    if p.status != "SUCCESS":
        raise ValidationFailed(
            "That M-Pesa payment has not been completed.", code="MPESA_PAYMENT_INVALID"
        )
    if p.sale_id is not None:
        raise ConflictError(
            "That M-Pesa payment is already used for another sale.", code="MPESA_PAYMENT_USED"
        )
    if p.amount < whole_shillings(grand_total):
        raise ValidationFailed(
            f"The customer paid KES {p.amount:,} but the sale total is KES {grand_total:,.2f}. "
            "Send a new prompt for the full amount.",
            code="MPESA_AMOUNT_SHORT",
        )
    return p


def sale_reference(p: MpesaPayment) -> str:
    """What the receipt shows: the M-Pesa receipt number, or Safaricom's request id."""
    return p.mpesa_receipt_number or f"STK {p.checkout_request_id}"[:40]


def _mask(msisdn: str) -> str:
    return msisdn[:6] + "***" + msisdn[-3:]


def _safe_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or ""))[:250]
