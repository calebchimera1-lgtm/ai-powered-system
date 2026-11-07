"""Forecasting models.

Every model has the same shape: given each product's daily sales up to (not including)
the forecast origin, return a forecast for the next `horizon` days. Local models fit each
product on its own; the gradient-boosting model is *global*, one model learnt across all
products, which lets slow sellers borrow patterns from busy ones.

All forecasts are clipped at zero (you cannot sell negative units).
"""

import warnings
from collections.abc import Mapping
from datetime import date, timedelta

import numpy as np

Histories = Mapping[
    int, np.ndarray
]  # product id -> daily units, oldest first, ends day before origin


class Model:
    name = "base"
    label = ""
    min_history = 7  # days needed to use the model at all

    def forecast(self, histories: Histories, origin: date, horizon: int) -> dict[int, np.ndarray]:
        return {
            pid: np.clip(self.forecast_one(y, horizon), 0, None)
            for pid, y in histories.items()
            if len(y) >= self.min_history
        }

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        raise NotImplementedError


class Naive(Model):
    name, label, min_history = "naive", "Naive (yesterday repeated)", 1

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        return np.full(horizon, float(y[-1]))


class SeasonalNaive(Model):
    name, label, min_history = "seasonal_naive", "Seasonal naive (same weekday last week)", 7

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        week = y[-7:].astype(float)
        return np.tile(week, horizon // 7 + 1)[:horizon]


class MovingAverage(Model):
    name, label, min_history = "moving_average", "28-day moving average", 7

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        return np.full(horizon, float(np.mean(y[-28:])))


class HoltWinters(Model):
    """Exponential smoothing with additive weekly seasonality (statsmodels)."""

    name, label, min_history = "holt_winters", "Holt-Winters (weekly seasonality)", 28

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing

        data = y[-182:].astype(float)  # the last 26 weeks are plenty and keep fitting fast
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                fit = ExponentialSmoothing(
                    data,
                    trend=None,
                    seasonal="add",
                    seasonal_periods=7,
                    initialization_method="estimated",
                ).fit()
                out = np.asarray(fit.forecast(horizon), dtype=float)
            except (ValueError, np.linalg.LinAlgError):
                out = np.full(horizon, np.nan)
        if not np.all(np.isfinite(out)):  # did not converge: fall back to the level
            out = np.full(horizon, float(np.mean(data[-28:])))
        return out


class CrostonSBA(Model):
    """Croston's method with the Syntetos-Boylan bias correction, for intermittent demand:
    it smooths the size of non-zero sales and the gap between them separately."""

    name, label, min_history = "croston_sba", "Croston / SBA (intermittent demand)", 14
    alpha = 0.1

    def forecast_one(self, y: np.ndarray, horizon: int) -> np.ndarray:
        nz = np.flatnonzero(y > 0)
        if len(nz) == 0:
            return np.zeros(horizon)
        # Start from the first observed gap between sales (starting at 1 day would make a
        # weekly seller look far busier until enough sales had been smoothed in).
        size = float(y[nz[0]])
        interval = float(nz[1] - nz[0]) if len(nz) > 1 else float(len(y))
        last = nz[0]
        for i in nz[1:]:
            size += self.alpha * (float(y[i]) - size)
            interval += self.alpha * (float(i - last) - interval)
            last = i
        return np.full(horizon, (1 - self.alpha / 2) * size / interval)


# --- Global gradient boosting ----------------------------------------------------------


def is_payday(d: date) -> bool:
    """Month-end salary days (28th to the 2nd), a well-known Kenyan retail peak."""
    return d.day >= 28 or d.day <= 2


_HOLIDAYS: dict[int, set[date]] = {}


def is_holiday(d: date) -> bool:
    if d.year not in _HOLIDAYS:
        import holidays

        _HOLIDAYS[d.year] = set(holidays.Kenya(years=d.year).keys())
    return d in _HOLIDAYS[d.year]


def _origin_features(y: np.ndarray) -> tuple[float, float, float, float, np.ndarray]:
    """Summary of the history at the forecast origin."""
    last28 = y[-28:]
    level7, level28 = float(np.mean(y[-7:])), float(np.mean(last28))
    std28 = float(np.std(last28))
    zero_share = float(np.mean(last28 == 0))
    # Mean for each weekday position over the last 4 weeks (position 0 = 7 days before origin).
    k = min(4, len(y) // 7)
    weeks = y[len(y) - 7 * k :].reshape(k, 7) if k else np.zeros((1, 7))
    return level7, level28, std28, zero_share, weeks.mean(axis=0)


def _rows(y: np.ndarray, origin: date, horizon: int) -> np.ndarray:
    level7, level28, std28, zero_share, dow_means = _origin_features(y)
    rows = []
    for h in range(horizon):
        d = origin + timedelta(days=h)
        rows.append(
            [
                h + 1,
                d.weekday(),
                d.day,
                is_payday(d),
                is_holiday(d),
                level7,
                level28,
                std28,
                zero_share,
                dow_means[h % 7],
            ]
        )
    return np.asarray(rows, dtype=float)


FEATURES = [
    "horizon",
    "weekday",
    "day_of_month",
    "payday",
    "public_holiday",
    "mean_last_7",
    "mean_last_28",
    "std_last_28",
    "zero_share_28",
    "same_weekday_mean",
]


class GlobalGradientBoosting(Model):
    """One scikit-learn HistGradientBoosting model (Poisson loss, suited to counts) across
    all products. It forecasts each future day directly from features known at the
    origin (no feeding its own forecasts back in, so errors don't compound)."""

    name, label, min_history = "gradient_boosting", "Gradient boosting (global, scikit-learn)", 56
    train_every = 3  # sample every 3rd origin when building the training set (speed)

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def forecast(self, histories: Histories, origin: date, horizon: int) -> dict[int, np.ndarray]:
        from sklearn.ensemble import HistGradientBoostingRegressor

        usable = {pid: y for pid, y in histories.items() if len(y) >= self.min_history}
        if not usable:
            return {}
        x_parts, y_parts = [], []
        for y in usable.values():
            n = len(y)
            # Training origins t: history y[:t], targets y[t:t+horizon] all known (< n).
            for t in range(28, n - 1, self.train_every):
                h = min(horizon, n - t)
                o = origin - timedelta(days=n - t)
                x_parts.append(_rows(y[:t], o, h))
                y_parts.append(y[t : t + h].astype(float))
        if not x_parts:
            return {}
        model = HistGradientBoostingRegressor(
            loss="poisson",
            max_iter=200,
            learning_rate=0.05,
            max_leaf_nodes=15,
            min_samples_leaf=40,
            l2_regularization=1.0,
            random_state=self.seed,
        )
        model.fit(np.vstack(x_parts), np.concatenate(y_parts))
        return {
            pid: np.clip(model.predict(_rows(y, origin, horizon)), 0, None)
            for pid, y in usable.items()
        }


def all_models() -> list[Model]:
    return [
        Naive(),
        SeasonalNaive(),
        MovingAverage(),
        HoltWinters(),
        CrostonSBA(),
        GlobalGradientBoosting(),
    ]
