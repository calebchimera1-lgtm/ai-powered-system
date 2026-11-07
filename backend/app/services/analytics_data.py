"""Daily figures for the forecasting and anomaly engines, read straight from the records.

Days are store-local calendar days (Africa/Nairobi by default), so a sale at 23:30 counts
on the day it happened in the shop, not the UTC day.
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_settings


def _tz() -> str:
    return get_settings().store_timezone


def daily_units_sold(db: Session, start: date, end: date) -> dict[int, np.ndarray]:
    """Units sold per active product per day, start..end inclusive, zero-filled.

    This is demand as *recorded*: a day the product was out of stock shows the sales that
    could be made, not the demand that walked away (a known limit of sales-based forecasts).
    Products are included from their first sale, so a new product has a short history.
    """
    rows = db.execute(
        text(
            """
            SELECT si.product_id, (s.sold_at AT TIME ZONE :tz)::date AS day,
                   SUM(si.quantity) AS qty
            FROM sale_items si JOIN sales s ON s.id = si.sale_id
            JOIN products p ON p.id = si.product_id AND p.is_active
            WHERE (s.sold_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
            GROUP BY 1, 2
            """
        ),
        {"tz": _tz(), "start": start, "end": end},
    ).all()
    n = (end - start).days + 1
    by: dict[int, np.ndarray] = {}
    first: dict[int, int] = {}
    for pid, day, qty in rows:
        arr = by.setdefault(pid, np.zeros(n))
        i = (day - start).days
        arr[i] = float(qty)
        first[pid] = min(first.get(pid, i), i)
    return {pid: arr[first[pid] :] for pid, arr in by.items()}


def product_days(db: Session, start: date, end: date) -> pd.DataFrame:
    """One row per active product per day with the figures the anomaly detector uses."""
    params = {"tz": _tz(), "start": start, "end": end}
    products = pd.DataFrame(
        db.execute(
            text(
                "SELECT id AS product_id, name, avg_cost AS unit_cost FROM products WHERE is_active"
            )
        ).all(),
        columns=["product_id", "name", "unit_cost"],
    )
    if products.empty:
        return pd.DataFrame()
    days = pd.DataFrame({"day": [start + timedelta(days=i) for i in range((end - start).days + 1)]})
    grid = products.merge(days, how="cross")

    moves = pd.DataFrame(
        db.execute(
            text(
                """
                SELECT product_id, (created_at AT TIME ZONE :tz)::date AS day,
                  -SUM(quantity) FILTER (WHERE movement_type = 'SALE_OUT') AS units_sold,
                  -SUM(quantity) FILTER (WHERE movement_type = 'ADJUSTMENT_OUT') AS adj_out,
                  SUM(quantity) FILTER (WHERE movement_type = 'ADJUSTMENT_IN') AS adj_in,
                  COUNT(*) FILTER (WHERE movement_type IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT'))
                    AS adj_count,
                  -SUM(quantity) FILTER (WHERE movement_type = 'DAMAGED') AS damaged
                FROM stock_movements
                WHERE (created_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
                GROUP BY 1, 2
                """
            ),
            params,
        ).all(),
        columns=["product_id", "day", "units_sold", "adj_out", "adj_in", "adj_count", "damaged"],
    )
    # Returns are counted from the return records: damaged returns never re-enter stock.
    rets = pd.DataFrame(
        db.execute(
            text(
                """
                SELECT si.product_id, (r.created_at AT TIME ZONE :tz)::date AS day,
                       SUM(ri.quantity) AS returns
                FROM sale_return_items ri
                JOIN sale_returns r ON r.id = ri.return_id AND r.status = 'APPROVED'
                JOIN sale_items si ON si.id = ri.sale_item_id
                WHERE (r.created_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
                GROUP BY 1, 2
                """
            ),
            params,
        ).all(),
        columns=["product_id", "day", "returns"],
    )
    out = grid.merge(moves, how="left", on=["product_id", "day"]).merge(
        rets, how="left", on=["product_id", "day"]
    )
    cols = ["units_sold", "adj_out", "adj_in", "adj_count", "damaged", "returns"]
    out[cols] = out[cols].astype(float).fillna(0.0)
    out["unit_cost"] = out["unit_cost"].astype(float)
    return out


def user_days(db: Session, start: date, end: date) -> pd.DataFrame:
    """One row per member of staff per day: refunds they took and adjustments they made."""
    params = {"tz": _tz(), "start": start, "end": end}
    users = pd.DataFrame(
        db.execute(
            text("SELECT id AS user_id, full_name AS name FROM users WHERE is_active")
        ).all(),
        columns=["user_id", "name"],
    )
    if users.empty:
        return pd.DataFrame()
    refunds = pd.DataFrame(
        db.execute(
            text(
                """
                SELECT requested_by_id, (created_at AT TIME ZONE :tz)::date,
                       COUNT(*), SUM(refund_total)
                FROM sale_returns WHERE status = 'APPROVED'
                  AND (created_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
                GROUP BY 1, 2
                """
            ),
            params,
        ).all(),
        columns=["user_id", "day", "refunds", "refund_value"],
    )
    adjs = pd.DataFrame(
        db.execute(
            text(
                """
                SELECT user_id, (created_at AT TIME ZONE :tz)::date,
                       COUNT(*), SUM(ABS(quantity) * unit_cost)
                FROM stock_movements
                WHERE movement_type IN ('ADJUSTMENT_IN', 'ADJUSTMENT_OUT')
                  AND (created_at AT TIME ZONE :tz)::date BETWEEN :start AND :end
                GROUP BY 1, 2
                """
            ),
            params,
        ).all(),
        columns=["user_id", "day", "adj_count", "adj_value"],
    )
    active = set(refunds["user_id"]) | set(adjs["user_id"])
    users = users[users["user_id"].isin(active)]
    if users.empty:
        return pd.DataFrame()
    days = pd.DataFrame({"day": [start + timedelta(days=i) for i in range((end - start).days + 1)]})
    out = (
        users.merge(days, how="cross")
        .merge(refunds, how="left", on=["user_id", "day"])
        .merge(adjs, how="left", on=["user_id", "day"])
    )
    cols = ["refunds", "refund_value", "adj_count", "adj_value"]
    out[cols] = out[cols].astype(float).fillna(0.0)
    return out
