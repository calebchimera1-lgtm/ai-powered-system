"""Demand forecasts and reorder suggestions."""

from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from app.api.deps import DbSession, limit_per_user, require
from app.core.permissions import P
from app.models import BackgroundJob, ProductForecast, Supplier, SupplierProduct, User
from app.schemas.analytics import (
    ForecastOverview,
    ForecastRunOut,
    JobQueued,
    ModelScoreOut,
    ProductForecastDetail,
    ProductForecastOut,
    ReorderGroup,
    ReorderLine,
    SeriesPoint,
)
from app.services import forecast_service, job_service

router = APIRouter(prefix="/forecasts", tags=["Forecasting"])

Reader = Annotated[User, Depends(require(P.FORECASTS_READ))]
Planner = Annotated[User, Depends(require(P.FORECASTS_READ, P.PURCHASES_WRITE))]


def _out(pf: ProductForecast, extra: dict[str, float] | None = None) -> ProductForecastOut:
    out = ProductForecastOut.model_validate(pf)
    out.model_label = forecast_service.MODEL_LABELS.get(pf.model_name, pf.model_name)
    scores = {s["model"]: s for s in pf.scores or []}
    out.chosen_mase = (scores.get(pf.model_name) or {}).get("mase")
    out.seasonal_naive_mase = (scores.get("seasonal_naive") or {}).get("mase")
    if extra:
        out.next_7_days, out.next_28_days = extra["next_7_days"], extra["next_28_days"]
    return out


def _running(db: DbSession) -> bool:
    return (
        db.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.job_type == "forecast.run",
                BackgroundJob.status.in_(["PENDING", "RUNNING"]),
            )
        )
        is not None
    )


@router.get("", response_model=ForecastOverview)
def overview(_: Reader, db: DbSession) -> ForecastOverview:
    """The latest forecast for every product, most urgent (earliest stock-out) first."""
    run = forecast_service.latest_run(db)
    rows = forecast_service.product_rows(db, run) if run else []
    return ForecastOverview(
        run=ForecastRunOut.model_validate(run) if run else None,
        running=_running(db),
        products=[_out(pf, extra) for pf, extra in rows],
    )


@router.post(
    "/run",
    response_model=JobQueued,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(limit_per_user(5, 60, "Too many forecast runs. Wait a minute."))],
)
def run_now(user: Planner, db: DbSession) -> JobQueued:
    """Re-train and re-forecast in the background (takes a few seconds to a minute)."""
    if _running(db):
        job_id = db.scalar(
            select(BackgroundJob.id).where(
                BackgroundJob.job_type == "forecast.run",
                BackgroundJob.status.in_(["PENDING", "RUNNING"]),
            )
        )
        return JobQueued(job_id=job_id or 0, message="A forecast is already being prepared.")
    job = job_service.enqueue(db, "forecast.run", {"user_id": user.id})
    db.commit()
    return JobQueued(job_id=job.id, message="Forecast queued.")


@router.get("/products/{product_id}", response_model=ProductForecastDetail)
def product_forecast(product_id: int, _: Reader, db: DbSession) -> ProductForecastDetail:
    """Actual sales for the last 13 weeks and the forecast with its 80% interval."""
    d = forecast_service.product_detail(db, product_id)
    pf = d["product"]
    future = [p["forecast"] for p in d["series"] if p.get("forecast") is not None]
    totals = {"next_7_days": round(sum(future[:7]), 1), "next_28_days": round(sum(future), 1)}
    return ProductForecastDetail(
        run=ForecastRunOut.model_validate(d["run"]),
        forecast=_out(pf, totals),
        scores=[
            ModelScoreOut(**s, label=forecast_service.MODEL_LABELS.get(s["model"], s["model"]))
            for s in pf.scores or []
        ],
        series=[SeriesPoint(**p) for p in d["series"]],
    )


@router.get("/reorder", response_model=list[ReorderGroup])
def reorder(_: Planner, db: DbSession) -> list[ReorderGroup]:
    """What to order now, grouped by each product's usual supplier."""
    run = forecast_service.latest_run(db)
    if run is None:
        return []
    rows = (
        db.scalars(
            select(ProductForecast).where(
                ProductForecast.run_id == run.id, ProductForecast.should_order.is_(True)
            )
        )
        .unique()
        .all()
    )
    groups: dict[int | None, ReorderGroup] = {}
    for pf in rows:
        p = pf.product
        if not p.is_active:
            continue
        sid = p.default_supplier_id
        if sid not in groups:
            sup = db.get(Supplier, sid) if sid else None
            groups[sid] = ReorderGroup(
                supplier_id=sid,
                supplier_name=sup.name if sup else "No usual supplier",
                lines=[],
                total_value=Decimal(0),
            )
        sp = db.get(SupplierProduct, (sid, p.id)) if sid else None
        cost = (sp.last_unit_price if sp and sp.last_unit_price else None) or p.purchase_price
        value = (cost * pf.suggested_quantity).quantize(Decimal("0.01")) if cost else None
        groups[sid].lines.append(
            ReorderLine(
                product=p,
                on_hand=pf.on_hand,
                on_order=pf.on_order,
                reorder_point=pf.reorder_point,
                stockout_date=pf.stockout_date,
                lead_time_days=pf.lead_time_days,
                suggested_quantity=pf.suggested_quantity,
                unit_cost=cost,
                line_value=value,
            )
        )
        groups[sid].total_value += value or 0
    for g in groups.values():
        g.lines.sort(
            key=lambda line: (line.stockout_date is None, line.stockout_date, line.product.name)
        )
    return sorted(groups.values(), key=lambda g: (g.supplier_id is None, g.supplier_name))
