"""Forecasting: metrics, models, backtesting/selection and replenishment maths."""

from datetime import date, timedelta
from decimal import Decimal

import numpy as np
import pytest

from app.ai.forecasting import engine, replenishment
from app.ai.forecasting import metrics as m
from app.ai.forecasting.models import (
    CrostonSBA,
    GlobalGradientBoosting,
    HoltWinters,
    MovingAverage,
    Naive,
    SeasonalNaive,
    is_payday,
)

END = date(2026, 11, 7)  # a Saturday


def weekly_series(n: int, base: float = 10, weekend: float = 1.5, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    days = [END - timedelta(days=n - i) for i in range(n)]
    lam = np.array([base * (weekend if d.weekday() >= 5 else 1) for d in days])
    return rng.poisson(lam).astype(float)


# --- Metrics -------------------------------------------------------------------------------


def test_metrics_by_hand() -> None:
    a, p = np.array([2.0, 0.0, 4.0]), np.array([1.0, 1.0, 4.0])
    assert m.mae(a, p) == pytest.approx(2 / 3)
    assert m.rmse(a, p) == pytest.approx(np.sqrt(2 / 3))
    assert m.mape(a, p) == pytest.approx(25.0)  # zero-actual day skipped: (50% + 0%) / 2
    assert m.mape(np.zeros(3), p) is None
    hist = np.array([1, 2, 3, 4, 5, 6, 7, 3, 2, 3, 4, 5, 6, 7], dtype=float)
    assert m.mase_scale(hist) == pytest.approx(2 / 7)  # |3-1| + |2-2| + ... = 2, over 7
    assert m.mase(a, p, 0.5) == pytest.approx((2 / 3) / 0.5)
    assert m.mase_scale(np.ones(14)) is None  # no variation: undefined, not divide-by-zero


# --- Models --------------------------------------------------------------------------------


def test_simple_models() -> None:
    y = np.array([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], dtype=float)
    assert list(Naive().forecast_one(y, 3)) == [10, 10, 10]
    assert list(SeasonalNaive().forecast_one(y, 9)) == [4, 5, 6, 7, 8, 9, 10, 4, 5]
    assert MovingAverage().forecast_one(y, 2)[0] == pytest.approx(5.5)


def test_croston_on_intermittent_demand() -> None:
    y = np.zeros(70)
    y[::7] = 7  # 7 units once a week = 1 a day on average
    f = CrostonSBA().forecast_one(y, 5)
    assert np.allclose(f, f[0])  # flat
    assert f[0] == pytest.approx(0.95, abs=0.06)  # 1/day with the SBA correction (1 - a/2)


def test_holt_winters_learns_the_weekly_shape() -> None:
    y = weekly_series(140, base=20, weekend=2.0)
    f = HoltWinters().forecast(dict.fromkeys([1], y), END, 7)[1]
    sat, sun = f[0], f[1]  # END is a Saturday
    weekdays = f[2:7]
    assert sat > weekdays.mean() * 1.5 and sun > weekdays.mean() * 1.5
    assert np.all(f >= 0)


def test_global_gradient_boosting_runs_across_products() -> None:
    hist = {
        1: weekly_series(120, 20, seed=1),
        2: weekly_series(120, 4, seed=2),
        3: weekly_series(30, 4, seed=3),
    }  # too short for this model
    out = GlobalGradientBoosting().forecast(hist, END, 14)
    assert set(out) == {1, 2}
    assert out[1].mean() > out[2].mean() * 2  # learnt the different levels
    assert np.all(out[1] >= 0)


def test_payday_flag() -> None:
    assert is_payday(date(2026, 10, 28)) and is_payday(date(2026, 11, 2))
    assert not is_payday(date(2026, 11, 15))


# --- Backtest and selection --------------------------------------------------------------------


def test_backtest_origins_are_weekly_and_leave_room_to_train() -> None:
    assert engine.backtest_origins(120, 28, 8, 28) == [36, 43, 50, 57, 64, 71, 78, 85, 92][-8:]
    assert engine.backtest_origins(50, 28, 8, 28) == []


def test_selection_prefers_the_model_that_fits_the_data() -> None:
    weekly = weekly_series(200, base=20, weekend=2.5)
    flat_rare = np.zeros(200)
    flat_rare[::5] = 5  # intermittent
    out = engine.run({1: weekly, 2: flat_rare}, END, horizon=28)
    # Strong weekly pattern: a seasonal model must win, not a flat average.
    assert out[1].model in {"holt_winters", "seasonal_naive", "gradient_boosting"}
    assert out[1].chosen.rmsse < out[1].score_of("moving_average").rmsse
    # Intermittent: the forecast must be near the true average (1/day), not zero.
    assert 0.6 < out[2].daily.mean() < 1.4
    # Intervals contain the point forecast and are not negative.
    for f in out.values():
        assert np.all(f.lower <= f.daily + 1e-9) and np.all(f.daily <= f.upper + 1e-9)
        assert np.all(f.lower >= 0)


def test_short_history_is_flagged_low_confidence() -> None:
    out = engine.run({1: weekly_series(40)}, END, horizon=14)
    assert out[1].low_confidence
    assert out[1].model in {"naive", "seasonal_naive", "moving_average", "croston_sba"}
    assert len(out[1].daily) == 14


def test_demand_pattern_classification() -> None:
    assert engine.demand_pattern(np.full(60, 10.0) + np.tile([0, 1], 30))[0] == "smooth"
    lumpy = np.zeros(60)
    lumpy[::6] = [1, 30, 2, 25, 1, 40, 3, 1, 50, 2]
    assert engine.demand_pattern(lumpy)[0] == "lumpy"
    rare = np.zeros(60)
    rare[::6] = 3
    assert engine.demand_pattern(rare)[0] == "intermittent"


# --- Replenishment -----------------------------------------------------------------------------


def test_stockout_date() -> None:
    daily = np.full(28, 5.0)
    assert replenishment.stockout_date(12, daily, END) == END + timedelta(days=2)  # 5, 10, 15>12
    assert replenishment.stockout_date(0, daily, END) == END
    assert replenishment.stockout_date(500, daily, END) is None


def test_reorder_point_and_quantity_by_hand() -> None:
    plan = replenishment.plan(
        on_hand=20,
        on_order=0,
        daily=np.full(28, 5.0),
        residual_std=2.0,
        lead_time_days=4,
        start=END,
        min_stock=10,
        max_stock=60,
    )
    # Lead-time demand 4 x 5 = 20; safety = 1.65 x 2 x sqrt(4) = 6.6; reorder point 26.6.
    assert plan.lead_time_demand == 20
    assert plan.safety_stock == pytest.approx(6.6)
    assert plan.reorder_point == pytest.approx(26.6)
    assert plan.should_order
    assert plan.order_quantity == Decimal("40")  # up to the maximum of 60
    assert plan.days_of_cover == 4.0


def test_no_order_when_stock_and_open_orders_cover_it() -> None:
    plan = replenishment.plan(
        on_hand=10,
        on_order=40,
        daily=np.full(28, 5.0),
        residual_std=2.0,
        lead_time_days=4,
        start=END,
        min_stock=10,
        max_stock=60,
    )
    assert not plan.should_order and plan.order_quantity == 0


def test_order_quantity_without_maximum_and_weighed_goods() -> None:
    plan = replenishment.plan(
        on_hand=2,
        on_order=0,
        daily=np.full(28, 3.3),
        residual_std=1.0,
        lead_time_days=2,
        start=END,
        min_stock=0,
        max_stock=None,
        whole_units=False,
    )
    # Cover lead time + a review week (9 days x 3.3 = 29.7) + safety 1.65 x sqrt(2) = 2.33.
    assert plan.order_quantity == Decimal(str(round(29.7 + 2.333 - 2, 1)))
