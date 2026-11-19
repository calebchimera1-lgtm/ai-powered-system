from datetime import datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel

Money = Annotated[Decimal, Field(gt=0, le=Decimal("250000"), decimal_places=2)]  # M-Pesa max


class StkPushRequest(BaseModel):
    phone: str = Field(..., min_length=9, max_length=20, description="Customer's M-Pesa number")
    amount: Money = Field(..., description="Sale total in KES; rounded up to whole shillings")


class MpesaPaymentOut(ORMModel):
    id: int
    status: str
    amount: int
    phone: str
    result_desc: str | None
    mpesa_receipt_number: str | None
    created_at: datetime
    completed_at: datetime | None
