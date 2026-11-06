"""Purchase order and goods-received schemas. Costs are KES, VAT-exclusive."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.common import ORMModel
from app.schemas.stock import UserBrief

Qty = Annotated[Decimal, Field(gt=0, le=Decimal("999999.999"), decimal_places=3)]
Cost = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=4)]
Rate = Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]


class POLine(BaseModel):
    product_id: int
    quantity: Qty
    unit_cost: Cost


class POCreate(BaseModel):
    supplier_id: int
    expected_date: date | None = None
    notes: str | None = Field(None, max_length=1000)
    items: list[POLine] = Field(..., min_length=1, max_length=300)

    @model_validator(mode="after")
    def _unique(self) -> "POCreate":
        ids = [i.product_id for i in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each product can appear only once on an order")
        return self


class ProductBriefPO(ORMModel):
    id: int
    sku: str
    name: str
    unit_of_measure: str
    tracks_expiry: bool
    vat_rate: Decimal


class POItemOut(ORMModel):
    id: int
    product: ProductBriefPO
    quantity_ordered: Decimal
    quantity_received: Decimal
    unit_cost: Decimal


class SupplierRef(ORMModel):
    id: int
    name: str


class POOut(ORMModel):
    id: int
    po_number: str
    supplier: SupplierRef
    status: str
    order_date: date
    expected_date: date | None
    notes: str | None
    created_by: UserBrief
    sent_at: datetime | None
    created_at: datetime
    items: list[POItemOut]
    total: Decimal = Decimal("0")


class GRNLine(BaseModel):
    product_id: int
    quantity: Qty
    unit_cost: Cost
    vat_rate: Rate | None = None  # defaults to the product's VAT rate
    batch_number: str | None = Field(None, max_length=50)
    expiry_date: date | None = None


class GoodsReceivedCreate(BaseModel):
    supplier_id: int
    purchase_order_id: int | None = None
    supplier_invoice_number: str | None = Field(None, max_length=50)
    invoice_date: date | None = None
    notes: str | None = Field(None, max_length=1000)
    items: list[GRNLine] = Field(..., min_length=1, max_length=300)

    @field_validator("supplier_invoice_number")
    @classmethod
    def _inv(cls, v: str | None) -> str | None:
        v = (v or "").strip().upper()
        return v or None


class PurchaseItemOut(ORMModel):
    id: int
    product: ProductBriefPO
    quantity: Decimal
    unit_cost: Decimal
    vat_rate: Decimal
    tax_amount: Decimal
    line_total: Decimal
    previous_unit_cost: Decimal | None
    batch_number: str | None
    expiry_date: date | None


class PriceChange(BaseModel):
    product_id: int
    product_name: str
    previous_unit_cost: Decimal
    new_unit_cost: Decimal
    change_percent: Decimal


class PurchaseOut(ORMModel):
    id: int
    grn_number: str
    supplier: SupplierRef
    purchase_order_id: int | None
    po_number: str | None = None
    supplier_invoice_number: str | None
    invoice_date: date | None
    received_at: datetime
    subtotal: Decimal
    tax_total: Decimal
    grand_total: Decimal
    source: str
    notes: str | None
    received_by: UserBrief
    items: list[PurchaseItemOut]
    price_changes: list[PriceChange] = []
