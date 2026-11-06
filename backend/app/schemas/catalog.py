"""Category and product schemas.

Money and quantities are Decimals and serialise as JSON strings ("1250.00") so no
precision is lost; the frontend parses them for display.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.catalog import UNITS
from app.schemas.common import ORMModel
from app.utils.barcodes import normalize_barcode

MoneyIn = Annotated[Decimal, Field(ge=0, le=Decimal("99999999.99"), decimal_places=2)]
QtyIn = Annotated[Decimal, Field(ge=0, le=Decimal("999999999.999"), decimal_places=3)]
Unit = Literal[UNITS]  # type: ignore[valid-type]

SKU_CHARS = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.")


def clean_barcode(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    return normalize_barcode(v)


def clean_sku(v: str | None) -> str | None:
    if v is None or not v.strip():
        return None
    v = v.strip().upper()
    if len(v) < 3 or not set(v) <= SKU_CHARS:
        raise ValueError("use 3-40 letters, digits, dashes, dots or underscores")
    return v


# --- Categories -------------------------------------------------------------------


class CategoryIn(BaseModel):
    name: str = Field(..., min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    parent_id: int | None = None

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())


class CategoryUpdate(BaseModel):
    name: str | None = Field(None, min_length=2, max_length=100)
    description: str | None = Field(None, max_length=500)
    parent_id: int | None = None
    is_active: bool | None = None


class CategoryOut(ORMModel):
    id: int
    name: str
    description: str | None
    parent_id: int | None
    is_active: bool
    product_count: int = 0
    path: str = ""


# --- Products ---------------------------------------------------------------------


class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=150)
    description: str | None = Field(None, max_length=2000)
    barcode: str | None = Field(None, max_length=32)
    category_id: int | None = None
    default_supplier_id: int | None = None
    unit_of_measure: Unit = "pcs"
    selling_price: MoneyIn
    vat_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] = Decimal("16")
    min_stock_level: QtyIn = Decimal("0")
    max_stock_level: QtyIn | None = None
    reorder_lead_time_days: int = Field(3, ge=0, le=365)
    tracks_expiry: bool = False

    @field_validator("name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(v.split())

    @field_validator("barcode")
    @classmethod
    def _barcode(cls, v: str | None) -> str | None:
        return clean_barcode(v)

    @model_validator(mode="after")
    def _levels(self) -> "ProductBase":
        if self.max_stock_level is not None and self.max_stock_level < self.min_stock_level:
            raise ValueError("Maximum stock level cannot be below the minimum")
        return self


class OpeningStock(BaseModel):
    quantity: Annotated[Decimal, Field(gt=0, le=Decimal("999999999.999"), decimal_places=3)]
    unit_cost: MoneyIn
    expiry_date: date | None = None
    batch_number: str | None = Field(None, max_length=50)


class ProductCreate(ProductBase):
    sku: str | None = Field(None, max_length=40, description="Generated when left blank")
    purchase_price: MoneyIn = Decimal("0")
    opening_stock: OpeningStock | None = None

    @field_validator("sku")
    @classmethod
    def _sku(cls, v: str | None) -> str | None:
        return clean_sku(v)


class ProductUpdate(BaseModel):
    """Partial update. Stock quantity and average cost are NOT editable here: they change
    only through stock movements, so the ledger stays the single source of truth."""

    name: str | None = Field(None, min_length=2, max_length=150)
    description: str | None = Field(None, max_length=2000)
    sku: str | None = Field(None, max_length=40)
    barcode: str | None = Field(None, max_length=32)
    category_id: int | None = None
    default_supplier_id: int | None = None
    unit_of_measure: Unit | None = None
    selling_price: MoneyIn | None = None
    purchase_price: MoneyIn | None = None
    vat_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)] | None = None
    min_stock_level: QtyIn | None = None
    max_stock_level: QtyIn | None = None
    reorder_lead_time_days: int | None = Field(None, ge=0, le=365)
    tracks_expiry: bool | None = None
    is_active: bool | None = None

    @field_validator("barcode")
    @classmethod
    def _barcode(cls, v: str | None) -> str | None:
        return clean_barcode(v)

    @field_validator("sku")
    @classmethod
    def _sku(cls, v: str | None) -> str | None:
        return clean_sku(v)

    @field_validator("name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return " ".join(v.split()) if v else v


class CategoryBrief(ORMModel):
    id: int
    name: str


class SupplierBrief(ORMModel):
    id: int
    name: str


StockStatus = Literal["out", "low", "ok", "over"]


class ProductOut(ORMModel):
    """Product as seen by everyone with products:read (no cost data)."""

    id: int
    sku: str
    barcode: str | None
    name: str
    description: str | None
    category: CategoryBrief | None
    default_supplier: SupplierBrief | None
    unit_of_measure: str
    image_url: str | None = None
    selling_price: Decimal
    vat_rate: Decimal
    quantity_on_hand: Decimal
    min_stock_level: Decimal
    max_stock_level: Decimal | None
    reorder_lead_time_days: int
    tracks_expiry: bool
    is_active: bool
    stock_status: StockStatus = "ok"
    next_expiry: date | None = None
    created_at: datetime
    updated_at: datetime


class ProductWithCost(ProductOut):
    """Adds cost and margin for roles with products:view_cost."""

    purchase_price: Decimal
    avg_cost: Decimal
    stock_value: Decimal = Decimal("0")
    margin_percent: Decimal | None = None


class BatchOut(ORMModel):
    id: int
    batch_number: str | None
    expiry_date: date | None
    quantity_received: Decimal
    quantity_remaining: Decimal
    unit_cost: Decimal | None = None
    received_at: datetime
    days_to_expiry: int | None = None


class ProductLookup(BaseModel):
    """Result of a barcode/SKU scan."""

    match: Literal["barcode", "sku"]
    product: ProductOut | ProductWithCost
