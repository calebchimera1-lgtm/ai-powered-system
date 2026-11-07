"""Turn a demand forecast into stock decisions.

* Stock-out date: the first day the cumulative forecast is more than the stock on hand.
* Reorder point = expected demand over the supplier lead time + safety stock, where
  safety stock = z x (daily forecast error) x sqrt(lead time). z = 1.65 aims for a 95%
  chance of not running out before the delivery arrives (assuming roughly normal errors).
* Order now if on hand + already on order is at or below the reorder point. Order enough
  to reach the maximum stock level, or, if none is set, to cover the lead time plus one
  review week plus safety stock.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import numpy as np

REVIEW_DAYS = 7  # how often orders are placed
Z_95 = 1.65


@dataclass
class Replenishment:
    stockout_date: date | None
    days_of_cover: float | None
    lead_time_demand: float
    safety_stock: float
    reorder_point: float
    should_order: bool
    order_quantity: Decimal


def stockout_date(on_hand: float, daily: np.ndarray, start: date) -> date | None:
    if on_hand <= 0:
        return start
    cum = np.cumsum(daily)
    idx = np.flatnonzero(cum > on_hand)
    return start + timedelta(days=int(idx[0])) if len(idx) else None


def plan(
    *,
    on_hand: float,
    on_order: float,
    daily: np.ndarray,
    residual_std: float,
    lead_time_days: int,
    start: date,
    min_stock: float,
    max_stock: float | None,
    whole_units: bool = True,
    z: float = Z_95,
) -> Replenishment:
    lead = max(int(lead_time_days), 1)
    horizon = len(daily)
    avg = float(np.mean(daily)) if horizon else 0.0

    def demand_over(days: int) -> float:
        if days <= horizon:
            return float(np.sum(daily[:days]))
        return float(np.sum(daily)) + avg * (days - horizon)

    ltd = demand_over(lead)
    safety = z * residual_std * math.sqrt(lead)
    rop = max(ltd + safety, min_stock)
    position = on_hand + on_order
    should = position <= rop and (avg > 0 or position < min_stock)
    if max_stock is not None and max_stock > 0:
        target = max(max_stock, rop)
    else:
        target = demand_over(lead + REVIEW_DAYS) + safety
    qty = max(target - position, 0.0) if should else 0.0
    if whole_units:
        qty = float(math.ceil(qty - 1e-9))
    else:
        qty = round(qty, 1)
    return Replenishment(
        stockout_date=stockout_date(on_hand, daily, start),
        days_of_cover=round(on_hand / avg, 1) if avg > 0 else None,
        lead_time_demand=round(ltd, 2),
        safety_stock=round(safety, 2),
        reorder_point=round(rop, 2),
        should_order=should and qty > 0,
        order_quantity=Decimal(str(qty)),
    )
