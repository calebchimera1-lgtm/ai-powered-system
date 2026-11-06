"""Expense and financial analytics schemas."""

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.stock import UserBrief

Amount = Annotated[Decimal, Field(gt=0, le=Decimal("99999999.99"), decimal_places=2)]


class ExpenseCategoryOut(ORMModel):
    id: int
    name: str
    is_active: bool


class ExpenseIn(BaseModel):
    category_id: int
    expense_date: date
    amount: Amount
    description: str = Field(..., min_length=2, max_length=500)
    payment_method: Literal["CASH", "MPESA", "CARD", "BANK"] = "CASH"
    reference: str | None = Field(None, max_length=50)


class ExpenseOut(ORMModel):
    id: int
    category: ExpenseCategoryOut
    expense_date: date
    amount: Decimal
    description: str
    payment_method: str
    reference: str | None
    recorded_by: UserBrief
    created_at: datetime


class FinancialSummary(BaseModel):
    date_from: date
    date_to: date
    transactions: int
    items_sold: Decimal
    sales_gross: Decimal  # what customers paid, incl. VAT
    vat_collected: Decimal
    refunds_gross: Decimal
    revenue: Decimal  # net of VAT and refunds
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    gross_margin_percent: Decimal | None
    stock_losses: Decimal  # damaged/expired write-offs and damaged returns, at cost
    net_adjustments: Decimal  # manual adjustments, at cost (negative = shrinkage)
    operating_expenses: Decimal
    net_profit_estimate: Decimal
    purchases_total: Decimal  # goods received incl. VAT
    average_basket: Decimal | None
    discounts_given: Decimal


class DailyPoint(BaseModel):
    day: date
    revenue: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    transactions: int


class ProductPerformance(BaseModel):
    product_id: int
    name: str
    sku: str
    category: str | None
    quantity: Decimal
    revenue: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    margin_percent: Decimal | None


class CategoryPerformance(BaseModel):
    category: str
    quantity: Decimal
    revenue: Decimal
    cost_of_goods_sold: Decimal
    gross_profit: Decimal
    margin_percent: Decimal | None


class PaymentBreakdown(BaseModel):
    payment_method: str
    transactions: int
    total: Decimal
