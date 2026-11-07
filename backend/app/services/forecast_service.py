"""Run the forecasting engine on the store's sales and store the results."""

import time
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.ai.forecasting import engine
from app.ai.forecasting import replenishment as rp
from app.ai.forecasting.models import all_models
from app.core.config import get_settings
from app.core.exceptions import NotFoundError
from app.core.permissions import P
from app.models import (
    Forecast,
    ForecastRun,
    Product,
    ProductForecast,
    PurchaseOrder,
    PurchaseOrderItem,
    Sale,
    SaleItem,
    SupplierProduct,
    User,
)
from app.services import analytics_data, notification_service

HISTORY_DAYS = 365
HORIZON = 28
KEEP_RUNS = 10
WHOLE_UNITS = {"pcs", "pack", "box", "dozen", "bottle", "carton", "bag"}
MODEL_LABELS = {m.name: m.label for m in all_models()}


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().store_timezone)).date()


def _on_order(db: Session) -> dict[int, Decimal]:
    rows = db.execute(
        select(
            PurchaseOrderItem.product_id,
            func.sum(PurchaseOrderItem.quantity_ordered - PurchaseOrderItem.quantity_received),
        )
        .join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderItem.purchase_order_id)
        .where(PurchaseOrder.status.in_(["SENT", "PARTIAL"]))
        .group_by(PurchaseOrderItem.product_id)
    ).all()
    return {pid: max(q, Decimal(0)) for pid, q in rows}


def _lead_time(db: Session, p: Product) -> int:
    if p.default_supplier_id:
        sp = db.get(SupplierProduct, (p.default_supplier_id, p.id))
        if sp is not None and sp.lead_time_days is not None:
            return sp.lead_time_days
    return p.reorder_lead_time_days


def _abc(db: Session, end: date) -> tuple[dict[int, str], dict[int, Decimal]]:
    """A = products making the top 80% of revenue over 90 days, B = next 15%, C = the rest."""
    tz = get_settings().store_timezone
    rows = db.execute(
        select(SaleItem.product_id, func.sum(SaleItem.line_total))
        .join(Sale, Sale.id == SaleItem.sale_id)
        .where(
            func.timezone(tz, Sale.sold_at)
            >= datetime.combine(end - timedelta(days=90), datetime.min.time())
        )
        .group_by(SaleItem.product_id)
    ).all()
    revenue = {pid: Decimal(v or 0) for pid, v in rows}
    total = sum(revenue.values()) or Decimal(1)
    classes, running = {}, Decimal(0)
    for pid, v in sorted(revenue.items(), key=lambda kv: kv[1], reverse=True):
        running += v
        share = running / total
        classes[pid] = (
            "A"
            if share <= Decimal("0.80") or not classes
            else "B"
            if share <= Decimal("0.95")
            else "C"
        )
    return classes, revenue


def run(db: Session, triggered_by: User | None = None) -> ForecastRun:
    started = time.monotonic()
    end = today()  # forecasts start today; history runs to yesterday
    start = end - timedelta(days=HISTORY_DAYS)
    run_row = ForecastRun(
        status="RUNNING",
        history_start=start,
        history_end=end - timedelta(days=1),
        horizon_days=HORIZON,
        triggered_by_id=triggered_by.id if triggered_by else None,
        params={
            "history_days": HISTORY_DAYS,
            "backtest_horizon": HORIZON,
            "max_origins": 8,
            "selection": "lowest mean RMSSE",
            "interval": "80% from backtest errors",
            "service_level_z": rp.Z_95,
        },
    )
    db.add(run_row)
    db.commit()
    try:
        histories = analytics_data.daily_units_sold(db, start, end - timedelta(days=1))
        results = engine.run(histories, end, horizon=HORIZON) if histories else {}
        _store(db, run_row, histories, results, end)
        run_row.status = "SUCCEEDED"
        run_row.summary = _summary(results, time.monotonic() - started)
    except Exception as exc:  # recorded on the run; the job also records the traceback
        db.rollback()
        run_row = db.get(ForecastRun, run_row.id)  # type: ignore[assignment]
        run_row.status = "FAILED"
        run_row.error_message = str(exc)[:2000]
        run_row.finished_at = datetime.now(UTC)
        db.commit()
        raise
    run_row.finished_at = datetime.now(UTC)
    old = db.scalars(select(ForecastRun.id).order_by(ForecastRun.id.desc()).offset(KEEP_RUNS)).all()
    if old:
        db.execute(delete(ForecastRun).where(ForecastRun.id.in_(old)))
    db.commit()
    db.refresh(run_row)
    return run_row


def _store(
    db: Session,
    run_row: ForecastRun,
    histories: dict[int, np.ndarray],
    results: dict[int, engine.ProductForecast],
    end: date,
) -> None:
    on_order = _on_order(db)
    classes, revenue = _abc(db, end)
    for pid, f in results.items():
        p = db.get(Product, pid)
        if p is None:
            continue
        y = histories[pid]
        pattern, adi, cv2 = engine.demand_pattern(y[-90:])
        lead = _lead_time(db, p)
        plan = rp.plan(
            on_hand=float(p.quantity_on_hand),
            on_order=float(on_order.get(pid, 0)),
            daily=f.daily,
            residual_std=f.residual_std,
            lead_time_days=lead,
            start=end,
            min_stock=float(p.min_stock_level),
            max_stock=float(p.max_stock_level) if p.max_stock_level is not None else None,
            whole_units=p.unit_of_measure in WHOLE_UNITS,
        )
        db.add(
            ProductForecast(
                run_id=run_row.id,
                product_id=pid,
                model_name=f.model,
                low_confidence=f.low_confidence,
                history_days=f.history_days,
                scores=[
                    {k: (round(v, 4) if isinstance(v, float) else v) for k, v in s.__dict__.items()}
                    for s in f.scores
                ],
                residual_std=round(f.residual_std, 4),
                avg_daily_28=round(float(np.mean(y[-28:])), 3),
                demand_pattern=pattern,
                adi=adi,
                cv2=cv2,
                abc_class=classes.get(pid, "C"),
                revenue_90d=revenue.get(pid, Decimal(0)),
                weekday_profile=engine.weekday_profile(y[-91:], end),
                payday_effect=engine.payday_effect(y[-182:], end),
                on_hand=p.quantity_on_hand,
                on_order=on_order.get(pid, Decimal(0)),
                lead_time_days=lead,
                stockout_date=plan.stockout_date,
                days_of_cover=plan.days_of_cover,
                safety_stock=plan.safety_stock,
                reorder_point=plan.reorder_point,
                should_order=plan.should_order,
                suggested_quantity=plan.order_quantity,
            )
        )
        for h in range(len(f.daily)):
            db.add(
                Forecast(
                    run_id=run_row.id,
                    product_id=pid,
                    forecast_date=end + timedelta(days=h),
                    predicted_qty=round(float(f.daily[h]), 3),
                    lower_bound=round(float(f.lower[h]), 3),
                    upper_bound=round(float(f.upper[h]), 3),
                    model_name=f.model,
                )
            )
        if (
            plan.should_order
            and plan.stockout_date
            and plan.stockout_date <= end + timedelta(days=lead)
        ):
            notification_service.notify(
                db,
                perms=[P.PURCHASES_WRITE],
                type="PREDICTED_SHORTAGE",
                severity="warning",
                title=f"{p.name} is likely to run out by {plan.stockout_date:%d %b}",
                message=f"At the forecast rate, stock of {p.name} lasts until about "
                f"{plan.stockout_date:%a %d %b}, and a delivery takes {lead} day"
                f"{'s' if lead != 1 else ''}. Suggested order: "
                f"{plan.order_quantity.normalize():f} {p.unit_of_measure}.",
                link="/reorder",
                dedupe_key=f"shortage:{pid}:{end:%G-W%V}",
            )


def _summary(results: dict[int, engine.ProductForecast], seconds: float) -> dict[str, Any]:
    chosen: dict[str, int] = {}
    by_model: dict[str, list[float]] = {}
    beats = compared = 0
    for f in results.values():
        chosen[f.model] = chosen.get(f.model, 0) + 1
        for s in f.scores:
            if s.mase is not None:
                by_model.setdefault(s.model, []).append(s.mase)
        mine, base = f.chosen, f.score_of("seasonal_naive")
        if mine and base and mine.rmsse is not None and base.rmsse is not None:
            compared += 1
            beats += mine.rmsse < base.rmsse
    return {
        "products": len(results),
        "low_confidence": sum(f.low_confidence for f in results.values()),
        "chosen_models": chosen,
        "mean_mase_by_model": {k: round(float(np.mean(v)), 3) for k, v in by_model.items()},
        "beats_seasonal_naive": beats,
        "compared_with_seasonal_naive": compared,
        "seconds": round(seconds, 1),
    }


# --- Reading ----------------------------------------------------------------------------


def latest_run(db: Session) -> ForecastRun | None:
    return db.scalar(
        select(ForecastRun).where(ForecastRun.status == "SUCCEEDED").order_by(ForecastRun.id.desc())
    )


def product_rows(
    db: Session, run_row: ForecastRun
) -> list[tuple[ProductForecast, dict[str, float]]]:
    totals = {
        (pid, k): float(v or 0)
        for pid, k, v in db.execute(
            select(
                Forecast.product_id,
                (Forecast.forecast_date < run_row.history_end + timedelta(days=8)).label("week"),
                func.sum(Forecast.predicted_qty),
            )
            .where(Forecast.run_id == run_row.id)
            .group_by(Forecast.product_id, "week")
        ).all()
    }
    rows = (
        db.scalars(select(ProductForecast).where(ProductForecast.run_id == run_row.id))
        .unique()
        .all()
    )
    out = []
    for r in rows:
        week = totals.get((r.product_id, True), 0.0)
        out.append(
            (
                r,
                {
                    "next_7_days": round(week, 1),
                    "next_28_days": round(week + totals.get((r.product_id, False), 0.0), 1),
                },
            )
        )
    return sorted(out, key=lambda t: (t[0].stockout_date or date.max, t[0].product.name))


def product_detail(db: Session, product_id: int, history_days: int = 91) -> dict[str, Any]:
    run_row = latest_run(db)
    if run_row is None:
        raise NotFoundError("No forecast has been run yet")
    pf = db.scalar(
        select(ProductForecast).where(
            ProductForecast.run_id == run_row.id, ProductForecast.product_id == product_id
        )
    )
    if pf is None:
        raise NotFoundError("This product has no forecast (it may not have sold yet)")
    end = run_row.history_end
    start = end - timedelta(days=history_days - 1)
    actual = analytics_data.daily_units_sold(db, start, end).get(product_id, np.zeros(0))
    pad = history_days - len(actual)
    series = [
        {"date": (start + timedelta(days=i)).isoformat(), "actual": float(v)}
        for i, v in enumerate(np.concatenate([np.zeros(pad), actual]))
    ]
    # What sold since the run (if it is not from today), to compare with the forecast.
    since = analytics_data.daily_units_sold(db, end + timedelta(days=1), today()).get(product_id)
    fc = db.scalars(
        select(Forecast)
        .where(Forecast.run_id == run_row.id, Forecast.product_id == product_id)
        .order_by(Forecast.forecast_date)
    ).all()
    first_sold = (today() - timedelta(days=len(since) - 1)) if since is not None else None
    for f in fc:
        row: dict[str, Any] = {
            "date": f.forecast_date.isoformat(),
            "forecast": f.predicted_qty,
            "lower": f.lower_bound,
            "upper": f.upper_bound,
        }
        if since is not None and first_sold and first_sold <= f.forecast_date < today():
            row["actual"] = float(since[(f.forecast_date - first_sold).days])
        elif f.forecast_date < today():
            row["actual"] = 0.0
        series.append(row)
    return {"run": run_row, "product": pf, "series": series}
