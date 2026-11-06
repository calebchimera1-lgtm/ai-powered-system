"""Stock movement, adjustment and write-off schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.models.stock import ADJUSTMENT_REASONS, MOVEMENT_TYPES
from app.schemas.common import ORMModel

PositiveQty = Annotated[Decimal, Field(gt=0, le=Decimal("999999999.999"), decimal_places=3)]
SignedQty = Annotated[
    Decimal, Field(ge=Decimal("-999999999.999"), le=Decimal("999999999.999"), decimal_places=3)
]


class UserBrief(ORMModel):
    id: int
    username: str
    full_name: str


class ProductRef(ORMModel):
    id: int
    sku: str
    name: str
    unit_of_measure: str


class MovementOut(ORMModel):
    id: int
    product: ProductRef
    batch_id: int | None
    batch_number: str | None = None
    movement_type: Literal[MOVEMENT_TYPES]  # type: ignore[valid-type]
    quantity: Decimal
    unit_cost: Decimal | None = None
    value: Decimal | None = None
    balance_after: Decimal
    reference_type: str | None
    reference_id: str | None
    reason: str | None
    user: UserBrief
    created_at: datetime


class AdjustmentCreate(BaseModel):
    """Either a physical count (`counted_quantity`) or a direct change (`quantity_change`)."""

    product_id: int
    counted_quantity: Annotated[Decimal, Field(ge=0, decimal_places=3)] | None = None
    quantity_change: SignedQty | None = None
    reason_code: Literal[ADJUSTMENT_REASONS]  # type: ignore[valid-type]
    notes: str | None = Field(None, max_length=1000)
    batch_id: int | None = None
    expiry_date: date | None = None
    allow_negative: bool = False

    @model_validator(mode="after")
    def _one_mode(self) -> "AdjustmentCreate":
        if (self.counted_quantity is None) == (self.quantity_change is None):
            raise ValueError("Give either the counted quantity or the quantity change")
        if self.quantity_change is not None and self.quantity_change == 0:
            raise ValueError("The quantity change must not be zero")
        if self.reason_code in ("OTHER", "THEFT_SUSPECTED") and not (self.notes or "").strip():
            raise ValueError("Please add a note explaining this adjustment")
        return self


class AdjustmentDecision(BaseModel):
    note: str | None = Field(None, max_length=1000)
    allow_negative: bool = False


class AdjustmentOut(ORMModel):
    id: int
    product: ProductRef
    reason_code: str
    notes: str | None
    system_quantity: Decimal
    counted_quantity: Decimal | None
    quantity_change: Decimal
    value_impact: Decimal | None = None
    allow_negative: bool
    status: Literal["PENDING", "APPROVED", "REJECTED"]
    requested_by: UserBrief
    decided_by: UserBrief | None
    decided_at: datetime | None
    decision_note: str | None
    created_at: datetime


class AdjustmentResult(BaseModel):
    adjustment: AdjustmentOut
    applied: bool
    message: str


class WriteOffCreate(BaseModel):
    product_id: int
    quantity: PositiveQty
    kind: Literal["DAMAGED", "EXPIRED"]
    batch_id: int | None = None
    notes: str | None = Field(None, max_length=1000)


class WriteOffResult(BaseModel):
    movements: list[MovementOut]
    quantity_on_hand: Decimal
    value_lost: Decimal | None = None


class StockSummary(BaseModel):
    active_products: int
    out_of_stock: int
    low_stock: int
    expiring_soon: int
    expired_in_stock: int
    pending_adjustments: int
    inventory_value: Decimal | None = None
