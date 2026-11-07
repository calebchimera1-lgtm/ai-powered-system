"""Backtest every model, pick the best per product, and forecast.

Rolling-origin backtest: pretend it is day t, forecast the next `horizon` days with only
the data before t, compare with what really sold, then move t forward a week and repeat.
The model with the lowest average RMSSE (scaled squared error, see metrics.py) over those
origins is chosen for each product, so a fancy model is only used where it actually beat
the simple ones on that product's data.

Prediction intervals come from the chosen model's own backtest errors (the 10th and 90th
percentile of actual - forecast), so an "80% interval" is as wide as the model has really
been wrong, not a theoretical assumption. The evaluation checks how often reality fell
inside it.
"""

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from app.ai.forecasting import metrics as m
from app.ai.forecasting.models import Histories, Model, all_models

LOW_HISTORY_DAYS = 56  # fewer days than this: simple models only, labelled low confidence


@dataclass
class ModelScore:
    model: str
    origins: int
    mae: float
    rmse: float
    mape: float | None
    smape: float | None
    mase: float | None
    rmsse: float | None


@dataclass
class ProductForecast:
    product_id: int
    model: str
    history_days: int
    low_confidence: bool
    daily: np.ndarray  # point forecast, one value per day from the origin
    lower: np.ndarray  # 80% interval
    upper: np.ndarray
    residual_std: float  # daily forecast error (standard deviation), for safety stock
    scores: list[ModelScore] = field(default_factory=list)

    @property
    def chosen(self) -> ModelScore | None:
        return next((s for s in self.scores if s.model == self.model), None)

    def score_of(self, name: str) -> ModelScore | None:
        return next((s for s in self.scores if s.model == name), None)


def backtest_origins(n: int, horizon: int, max_origins: int, min_train: int) -> list[int]:
    """Indices t (forecast starts at day t) for a rolling-origin backtest, newest last."""
    last = n - horizon
    out = [last - 7 * k for k in range(max_origins)]
    return sorted(t for t in out if t >= min_train)


def backtest(
    histories: Histories,
    end: date,
    models: list[Model],
    horizon: int = 28,
    max_origins: int = 8,
) -> tuple[dict[int, dict[str, ModelScore]], dict[int, dict[str, np.ndarray]]]:
    """Scores per product and model, and the raw errors (actual - forecast) per product and
    model. `end` is the day after the last day of history."""
    n_by = {pid: len(y) for pid, y in histories.items()}
    n = max(n_by.values(), default=0)
    errs: dict[int, dict[str, list[np.ndarray]]] = {pid: {} for pid in histories}
    per: dict[int, dict[str, list[dict]]] = {pid: {} for pid in histories}
    for t in backtest_origins(n, horizon, max_origins, min_train=28):
        origin = end - timedelta(days=n - t)
        # Align: every product's history is cut at the same calendar date.
        train = {pid: y[: len(y) - (n - t)] for pid, y in histories.items() if len(y) - (n - t) > 0}
        actual = {pid: histories[pid][len(histories[pid]) - (n - t) :][:horizon] for pid in train}
        for model in models:
            preds = model.forecast(train, origin, horizon)
            for pid, pred in preds.items():
                a = actual[pid].astype(float)
                p = pred[: len(a)]
                h = train[pid].astype(float)
                per[pid].setdefault(model.name, []).append(
                    m.all_metrics(a, p, m.mase_scale(h), m.rmsse_scale(h))
                )
                errs[pid].setdefault(model.name, []).append(a - p)
    scores: dict[int, dict[str, ModelScore]] = {}
    for pid, by_model in per.items():
        scores[pid] = {}
        for name, rows in by_model.items():

            def avg(key: str, rows: list[dict] = rows) -> float | None:
                vals = [r[key] for r in rows if r[key] is not None]
                return float(np.mean(vals)) if vals else None

            scores[pid][name] = ModelScore(
                name,
                len(rows),
                avg("mae") or 0.0,
                avg("rmse") or 0.0,
                avg("mape"),
                avg("smape"),
                avg("mase"),
                avg("rmsse"),
            )
    raw = {pid: {k: np.concatenate(v) for k, v in d.items()} for pid, d in errs.items()}
    return scores, raw


def choose(scores: dict[str, ModelScore], allowed: set[str]) -> str:
    candidates = [s for s in scores.values() if s.model in allowed]
    if not candidates:
        return "moving_average"
    # Lowest RMSSE; RMSE breaks ties and covers products with no scale (no variation).
    return min(
        candidates, key=lambda s: (s.rmsse if s.rmsse is not None else float("inf"), s.rmse)
    ).model


def run(
    histories: Histories,
    end: date,
    horizon: int = 28,
    backtest_horizon: int = 28,
    max_origins: int = 8,
    models: list[Model] | None = None,
) -> dict[int, ProductForecast]:
    """Backtest, choose and forecast `horizon` days from `end` for every product."""
    models = models or all_models()
    by_name = {mdl.name: mdl for mdl in models}
    scores, errors = backtest(histories, end, models, backtest_horizon, max_origins)

    chosen: dict[int, str] = {}
    for pid, y in histories.items():
        allowed = {mdl.name for mdl in models if len(y) >= mdl.min_history}
        if len(y) < LOW_HISTORY_DAYS:
            allowed &= {"naive", "seasonal_naive", "moving_average", "croston_sba"}
        chosen[pid] = (
            choose(scores.get(pid, {}), allowed)
            if scores.get(pid)
            else ("moving_average" if len(y) >= 7 else "naive")
        )

    # Fit each model needed on the full history (the global model once for everyone).
    final: dict[str, dict[int, np.ndarray]] = {}
    for name in set(chosen.values()):
        subset = {pid: y for pid, y in histories.items() if chosen[pid] == name}
        if name == "gradient_boosting":
            subset = dict(histories)  # learns across all products
        final[name] = by_name[name].forecast(subset, end, horizon)

    out: dict[int, ProductForecast] = {}
    for pid, y in histories.items():
        name = chosen[pid]
        point = final.get(name, {}).get(pid)
        if point is None:  # model could not run for this product: fall back
            name = "moving_average" if len(y) >= 7 else "naive"
            point = by_name.get(name, models[0]).forecast({pid: y}, end, horizon).get(pid)
            if point is None:
                point = np.zeros(horizon)
        e = errors.get(pid, {}).get(name)
        if e is not None and len(e) >= 10:
            lo_q, hi_q = np.quantile(e, [0.1, 0.9])
            sd = float(np.std(e))
        else:
            # Too little backtest data: assume Poisson-like noise around the forecast.
            sd = float(np.sqrt(max(np.mean(point), 0.25)))
            lo_q, hi_q = -1.2816 * sd, 1.2816 * sd
        out[pid] = ProductForecast(
            product_id=pid,
            model=name,
            history_days=len(y),
            low_confidence=len(y) < LOW_HISTORY_DAYS or e is None,
            daily=point,
            lower=np.clip(point + lo_q, 0, None),
            upper=np.clip(point + hi_q, 0, None),
            residual_std=sd,
            scores=sorted(scores.get(pid, {}).values(), key=lambda s: s.model),
        )
    return out


# --- Demand profile --------------------------------------------------------------------


def demand_pattern(y: np.ndarray) -> tuple[str, float | None, float | None]:
    """Syntetos-Boylan classification by the average gap between sales (ADI) and the
    variability of sale sizes (CV squared): smooth, erratic, intermittent or lumpy."""
    nz = y[y > 0]
    if len(nz) < 2:
        return "insufficient", None, None
    adi = len(y) / len(nz)
    cv2 = float((np.std(nz) / np.mean(nz)) ** 2)
    if adi < 1.32:
        kind = "smooth" if cv2 < 0.49 else "erratic"
    else:
        kind = "intermittent" if cv2 < 0.49 else "lumpy"
    return kind, round(adi, 2), round(cv2, 3)


def weekday_profile(y: np.ndarray, end: date) -> list[float]:
    """Average sales on each weekday (Mon..Sun) relative to the overall average."""
    n = len(y)
    days = [end - timedelta(days=n - i) for i in range(n)]
    overall = float(np.mean(y)) or 1.0
    out = []
    for wd in range(7):
        vals = [y[i] for i, d in enumerate(days) if d.weekday() == wd]
        out.append(round(float(np.mean(vals)) / overall, 3) if vals else 1.0)
    return out


def payday_effect(y: np.ndarray, end: date) -> float | None:
    """How much busier month-end payday days are than other days (1.30 = 30% busier)."""
    from app.ai.forecasting.models import is_payday

    n = len(y)
    pay, other = [], []
    for i in range(n):
        (pay if is_payday(end - timedelta(days=n - i)) else other).append(y[i])
    if not pay or not other or np.mean(other) == 0:
        return None
    return round(float(np.mean(pay) / np.mean(other)), 3)
