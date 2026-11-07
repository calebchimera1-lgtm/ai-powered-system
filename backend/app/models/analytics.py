"""Forecasts, anomaly alerts and notifications."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.auth import User
from app.models.base import Base, IdMixin
from app.models.catalog import Product

RUN_STATUSES = ("RUNNING", "SUCCEEDED", "FAILED")
ALERT_STATUSES = ("OPEN", "INVESTIGATING", "RESOLVED_ISSUE_FOUND", "RESOLVED_NO_ISSUE")
SEVERITIES = ("LOW", "MEDIUM", "HIGH")
DETECTORS = ("RULE", "ISOLATION_FOREST", "BOTH")


class ForecastRun(IdMixin, Base):
    """One training run: which data it used and how the models scored, for reproducibility."""

    __tablename__ = "forecast_runs"
    __table_args__ = (CheckConstraint(f"status IN {RUN_STATUSES!r}", name="status_valid"),)

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="RUNNING")
    history_start: Mapped[date | None] = mapped_column(Date)
    history_end: Mapped[date | None] = mapped_column(Date)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False, default=28)
    params: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    summary: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    error_message: Mapped[str | None] = mapped_column(Text)
    triggered_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))

    triggered_by: Mapped[User | None] = relationship(lazy="joined")


class ProductForecast(IdMixin, Base):
    """Per product: the chosen model, its backtest scores, demand profile and reorder advice."""

    __tablename__ = "forecast_products"
    __table_args__ = (UniqueConstraint("run_id", "product_id", name="uq_forecast_product"),)

    run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    model_name: Mapped[str] = mapped_column(String(30), nullable=False)
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    history_days: Mapped[int] = mapped_column(Integer, nullable=False)
    scores: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    residual_std: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    # Demand profile
    avg_daily_28: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    demand_pattern: Mapped[str | None] = mapped_column(String(14))
    adi: Mapped[float | None] = mapped_column(Float)
    cv2: Mapped[float | None] = mapped_column(Float)
    abc_class: Mapped[str | None] = mapped_column(String(1))
    revenue_90d: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    weekday_profile: Mapped[list[float] | None] = mapped_column(JSONB)
    payday_effect: Mapped[float | None] = mapped_column(Float)
    # Replenishment (as at the run)
    on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False)
    on_order: Mapped[Decimal] = mapped_column(Numeric(14, 3), nullable=False, default=Decimal(0))
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    stockout_date: Mapped[date | None] = mapped_column(Date)
    days_of_cover: Mapped[float | None] = mapped_column(Float)
    safety_stock: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reorder_point: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    should_order: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    suggested_quantity: Mapped[Decimal] = mapped_column(
        Numeric(14, 3), nullable=False, default=Decimal(0)
    )

    product: Mapped[Product] = relationship(lazy="joined")


class Forecast(IdMixin, Base):
    """Daily forecast with its 80% interval (weekly/monthly totals are summed from these)."""

    __tablename__ = "forecasts"
    __table_args__ = (
        UniqueConstraint("run_id", "product_id", "forecast_date", name="uq_forecast_day"),
    )

    run_id: Mapped[int] = mapped_column(
        ForeignKey("forecast_runs.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    forecast_date: Mapped[date] = mapped_column(Date, nullable=False)
    predicted_qty: Mapped[float] = mapped_column(Float, nullable=False)
    lower_bound: Mapped[float] = mapped_column(Float, nullable=False)
    upper_bound: Mapped[float] = mapped_column(Float, nullable=False)
    model_name: Mapped[str] = mapped_column(String(30), nullable=False)


class AnomalyAlert(IdMixin, Base):
    __tablename__ = "anomaly_alerts"
    __table_args__ = (
        CheckConstraint(f"status IN {ALERT_STATUSES!r}", name="status_valid"),
        CheckConstraint(f"severity IN {SEVERITIES!r}", name="severity_valid"),
        CheckConstraint(f"detector IN {DETECTORS!r}", name="detector_valid"),
        CheckConstraint(
            "(entity_type = 'product' AND product_id IS NOT NULL) OR "
            "(entity_type = 'user' AND subject_user_id IS NOT NULL)",
            name="entity_valid",
        ),
        Index("ix_anomaly_alerts_status_detected", "status", "detected_at"),
    )

    entity_type: Mapped[str] = mapped_column(String(10), nullable=False)
    product_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), index=True
    )
    subject_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    value_kes: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=Decimal(0))
    severity: Mapped[str] = mapped_column(String(6), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    detector: Mapped[str] = mapped_column(String(16), nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="OPEN")
    reviewed_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_notes: Mapped[str | None] = mapped_column(Text)
    # entity + kind + first day: the same irregularity is never alerted twice.
    dedupe_key: Mapped[str] = mapped_column(String(120), unique=True, nullable=False)

    product: Mapped[Product | None] = relationship(lazy="joined")
    subject_user: Mapped[User | None] = relationship(foreign_keys=[subject_user_id], lazy="joined")
    reviewed_by: Mapped[User | None] = relationship(foreign_keys=[reviewed_by_id], lazy="joined")


class Notification(IdMixin, Base):
    """One message to one person (role broadcasts are fanned out, so each has its own read
    state). `dedupe_key` stops the same alert repeating (e.g. low stock once a day)."""

    __tablename__ = "notifications"
    __table_args__ = (
        UniqueConstraint("user_id", "dedupe_key", name="uq_notification_dedupe"),
        CheckConstraint("severity IN ('info', 'warning', 'critical')", name="severity_valid"),
        Index("ix_notifications_user_unread", "user_id", "is_read", "created_at"),
    )

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    link: Mapped[str | None] = mapped_column(String(255))
    severity: Mapped[str] = mapped_column(String(10), nullable=False, default="info")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    dedupe_key: Mapped[str] = mapped_column(String(150), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
