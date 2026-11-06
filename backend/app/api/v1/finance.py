"""Expenses and profit analytics."""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel

from app.api.deps import Ctx, DbSession, Pagination, require
from app.core.permissions import P
from app.models import User
from app.schemas.common import Message, Page
from app.schemas.finance import (
    CategoryPerformance,
    DailyPoint,
    ExpenseCategoryOut,
    ExpenseIn,
    ExpenseOut,
    FinancialSummary,
    PaymentBreakdown,
    ProductPerformance,
)
from app.services import finance_service

router = APIRouter(tags=["Finance"])

FinanceReader = Annotated[User, Depends(require(P.FINANCE_READ))]
ExpenseWriter = Annotated[User, Depends(require(P.EXPENSES_WRITE))]


class ExpensePage(Page[ExpenseOut]):
    total_amount: str


def _period(date_from: date | None, date_to: date | None) -> tuple[date, date]:
    """Defaults to the last 30 days, ending today."""
    end = date_to or date.today()
    start = date_from or end - timedelta(days=29)
    return start, end


@router.get("/expense-categories", response_model=list[ExpenseCategoryOut])
def expense_categories(
    _: Annotated[User, Depends(require(P.EXPENSES_WRITE, P.FINANCE_READ, any_of=True))],
    db: DbSession,
) -> list[ExpenseCategoryOut]:
    return [ExpenseCategoryOut.model_validate(c) for c in finance_service.categories(db)]


@router.get("/expenses", response_model=ExpensePage)
def list_expenses(
    _: FinanceReader,
    db: DbSession,
    pagination: Pagination,
    date_from: date | None = None,
    date_to: date | None = None,
    category_id: int | None = None,
) -> ExpensePage:
    rows, total, amount = finance_service.list_expenses(
        db, pagination, date_from=date_from, date_to=date_to, category_id=category_id
    )
    base = Page.build([ExpenseOut.model_validate(e) for e in rows], total, pagination)
    return ExpensePage(**base.model_dump(), total_amount=str(amount))


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(body: ExpenseIn, user: ExpenseWriter, db: DbSession, ctx: Ctx) -> ExpenseOut:
    return ExpenseOut.model_validate(finance_service.create_expense(db, body, user, ctx))


@router.put("/expenses/{expense_id}", response_model=ExpenseOut)
def update_expense(
    expense_id: int, body: ExpenseIn, user: ExpenseWriter, db: DbSession, ctx: Ctx
) -> ExpenseOut:
    exp = finance_service.get_expense(db, expense_id)
    return ExpenseOut.model_validate(finance_service.update_expense(db, exp, body, user, ctx))


@router.delete("/expenses/{expense_id}", response_model=Message)
def delete_expense(expense_id: int, user: ExpenseWriter, db: DbSession, ctx: Ctx) -> Message:
    finance_service.delete_expense(db, finance_service.get_expense(db, expense_id), user, ctx)
    return Message(message="Expense deleted")


class AnalyticsBundle(BaseModel):
    summary: FinancialSummary
    daily: list[DailyPoint]
    by_category: list[CategoryPerformance]
    top_products: list[ProductPerformance]
    payment_methods: list[PaymentBreakdown]


@router.get("/analytics/summary", response_model=FinancialSummary)
def analytics_summary(
    _: FinanceReader, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> FinancialSummary:
    start, end = _period(date_from, date_to)
    return FinancialSummary.model_validate(finance_service.summary(db, start, end))


@router.get("/analytics/products", response_model=list[ProductPerformance])
def analytics_products(
    _: FinanceReader, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> list[ProductPerformance]:
    start, end = _period(date_from, date_to)
    return [
        ProductPerformance.model_validate(r) for r in finance_service.by_product(db, start, end)
    ]


@router.get("/analytics/overview", response_model=AnalyticsBundle)
def analytics_overview(
    _: FinanceReader, db: DbSession, date_from: date | None = None, date_to: date | None = None
) -> AnalyticsBundle:
    """Everything the profit page needs in one request."""
    start, end = _period(date_from, date_to)
    return AnalyticsBundle(
        summary=FinancialSummary.model_validate(finance_service.summary(db, start, end)),
        daily=[DailyPoint.model_validate(p) for p in finance_service.daily(db, start, end)],
        by_category=[
            CategoryPerformance.model_validate(c)
            for c in finance_service.by_category(db, start, end)
        ],
        top_products=[
            ProductPerformance.model_validate(p)
            for p in finance_service.by_product(db, start, end)[:10]
        ],
        payment_methods=[
            PaymentBreakdown.model_validate(p)
            for p in finance_service.payment_breakdown(db, start, end)
        ],
    )
