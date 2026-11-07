"""Schemas for forecasts, reorder suggestions, anomaly alerts and notifications."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common import ORMModel
from app.schemas.stock import UserBrief


class ProductRef(ORMModel):
    id: int
    name: str
    sku: str
    unit_of_measure: str
    default_supplier_id: int | None = None


class ForecastRunOut(ORMModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    history_start: date | None
    history_end: date | None
    horizon_days: int
    params: dict[str, Any] | None
    summary: dict[str, Any] | None
    error_message: str | None


class ModelScoreOut(BaseModel):
    model: str
    label: str
    origins: int
    mae: float
    rmse: float
    mape: float | None
    smape: float | None
    mase: float | None
    rmsse: float | None


class ProductForecastOut(ORMModel):
    product: ProductRef
    model_name: str
    model_label: str = ""
    low_confidence: bool
    history_days: int
    avg_daily_28: float
    demand_pattern: str | None
    adi: float | None
    cv2: float | None
    abc_class: str | None
    revenue_90d: Decimal | None
    weekday_profile: list[float] | None
    payday_effect: float | None
    on_hand: Decimal
    on_order: Decimal
    lead_time_days: int
    stockout_date: date | None
    days_of_cover: float | None
    safety_stock: float
    reorder_point: float
    should_order: bool
    suggested_quantity: Decimal
    residual_std: float
    next_7_days: float = 0
    next_28_days: float = 0
    chosen_mase: float | None = None
    seasonal_naive_mase: float | None = None


class ForecastOverview(BaseModel):
    run: ForecastRunOut | None
    running: bool
    products: list[ProductForecastOut]


class SeriesPoint(BaseModel):
    date: date
    actual: float | None = None
    forecast: float | None = None
    lower: float | None = None
    upper: float | None = None


class ProductForecastDetail(BaseModel):
    run: ForecastRunOut
    forecast: ProductForecastOut
    scores: list[ModelScoreOut]
    series: list[SeriesPoint]


class ReorderLine(BaseModel):
    product: ProductRef
    on_hand: Decimal
    on_order: Decimal
    reorder_point: float
    stockout_date: date | None
    suggested_quantity: Decimal
    unit_cost: Decimal | None
    line_value: Decimal | None


class ReorderGroup(BaseModel):
    supplier_id: int | None
    supplier_name: str
    lines: list[ReorderLine]
    total_value: Decimal


class AnomalyAlertOut(ORMModel):
    id: int
    entity_type: str
    product: ProductRef | None
    subject_user: UserBrief | None
    kind: str
    kind_label: str = ""
    detected_at: datetime
    period_start: date
    period_end: date
    quantity: float
    value_kes: Decimal
    severity: str
    score: float
    detector: str
    explanation: str
    recommended_action: str
    evidence: list[dict[str, Any]] | None
    status: str
    reviewed_by: UserBrief | None
    reviewed_at: datetime | None
    review_notes: str | None


class AnomalyReview(BaseModel):
    status: Literal["INVESTIGATING", "RESOLVED_ISSUE_FOUND", "RESOLVED_NO_ISSUE"]
    notes: str | None = Field(None, max_length=2000)


class AnomalyStats(BaseModel):
    by_status: dict[str, int]
    open_by_severity: dict[str, int]
    open_value_kes: Decimal
    reviewed: int
    precision: float | None


class NotificationOut(ORMModel):
    id: int
    type: str
    title: str
    message: str
    link: str | None
    severity: str
    is_read: bool
    created_at: datetime


class NotificationPage(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class MarkRead(BaseModel):
    ids: list[int] | None = Field(None, max_length=500)  # None = all


class JobQueued(BaseModel):
    job_id: int
    message: str
