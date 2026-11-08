"""Management dashboard response."""

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class StockItem(BaseModel):
    product_id: int
    name: str
    on_hand: Decimal
    min_stock: Decimal
    unit: str


class ExpiringItem(BaseModel):
    product_id: int
    name: str
    expiry_date: date
    quantity: Decimal
    unit: str
    expired: bool


class InventoryBlock(BaseModel):
    total_products: int
    out_of_stock: int
    low_stock: int
    low_stock_items: list[StockItem]
    expiring_soon: int
    expiring_items: list[ExpiringItem]
    inventory_value: Decimal | None  # None when the user may not see costs


class TrendPoint(BaseModel):
    day: date
    revenue: Decimal
    gross_profit: Decimal


class SalesBlock(BaseModel):
    today_revenue: Decimal
    today_transactions: int
    month_revenue: Decimal
    month_gross_profit: Decimal
    period_revenue: Decimal
    period_gross_profit: Decimal
    period_transactions: int
    gross_margin_percent: Decimal | None
    trend: list[TrendPoint]


class Mover(BaseModel):
    product_id: int
    name: str
    unit: str
    per_day: float
    on_hand: Decimal
    days_of_cover: float | None


class Movers(BaseModel):
    fast: list[Mover]
    slow: list[Mover]


class Shortage(BaseModel):
    product_id: int
    name: str
    stockout_date: date
    lead_time_days: int
    suggested_quantity: Decimal
    unit: str


class Approvals(BaseModel):
    invoices_to_review: int
    purchase_orders_draft: int
    purchase_orders_open: int
    adjustments_pending: int
    returns_pending: int


class CategoryRevenue(BaseModel):
    category: str
    revenue: Decimal
    gross_profit: Decimal


class Dashboard(BaseModel):
    date_from: date
    date_to: date
    category_id: int | None
    inventory: InventoryBlock
    movers: Movers
    shortages: list[Shortage]
    approvals: Approvals
    sales: SalesBlock | None  # finance permission only
    categories: list[CategoryRevenue] | None
    open_irregularities: int | None  # anomaly permission only
