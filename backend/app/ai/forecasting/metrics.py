"""Forecast accuracy metrics.

MAPE is undefined when the actual value is zero, and slow-moving products have many
zero days, so it is computed over non-zero days only (and reported with that caveat).
Model selection uses RMSSE (root mean squared scaled error, as in the M5 forecasting
competition) rather than MASE: on products with many zero days an absolute-error measure
rewards forecasting zero (the median), which would leave the shelf empty; a squared-error
measure rewards forecasting the average, which is what stock planning needs.

MASE (mean absolute scaled error) divides the error by the in-sample error of the
seasonal-naive forecast ("same weekday last week"): below 1.0 means the model beats that
simple baseline. It is the fairest way to compare products that sell 2 or 200 a day.
"""

import numpy as np


def mae(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.mean(np.abs(actual - pred)))


def rmse(actual: np.ndarray, pred: np.ndarray) -> float:
    return float(np.sqrt(np.mean((actual - pred) ** 2)))


def mape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    """Mean absolute percentage error over non-zero actual days; None if all are zero."""
    mask = actual != 0
    if not mask.any():
        return None
    return float(np.mean(np.abs((actual[mask] - pred[mask]) / actual[mask])) * 100)


def smape(actual: np.ndarray, pred: np.ndarray) -> float | None:
    denom = np.abs(actual) + np.abs(pred)
    mask = denom != 0
    if not mask.any():
        return None
    return float(np.mean(2 * np.abs(actual[mask] - pred[mask]) / denom[mask]) * 100)


def mase_scale(history: np.ndarray, season: int = 7) -> float | None:
    """In-sample mean absolute error of the seasonal-naive forecast."""
    if len(history) <= season:
        return None
    scale = float(np.mean(np.abs(history[season:] - history[:-season])))
    return scale if scale > 0 else None


def mase(actual: np.ndarray, pred: np.ndarray, scale: float | None) -> float | None:
    if scale is None:
        return None
    return mae(actual, pred) / scale


def rmsse_scale(history: np.ndarray, season: int = 7) -> float | None:
    if len(history) <= season:
        return None
    scale = float(np.mean((history[season:] - history[:-season]) ** 2))
    return scale if scale > 0 else None


def rmsse(actual: np.ndarray, pred: np.ndarray, scale: float | None) -> float | None:
    if scale is None:
        return None
    return float(np.sqrt(np.mean((actual - pred) ** 2) / scale))


def all_metrics(
    actual: np.ndarray, pred: np.ndarray, scale: float | None, sq_scale: float | None = None
) -> dict[str, float | None]:
    return {
        "rmsse": rmsse(actual, pred, sq_scale),
        "mae": mae(actual, pred),
        "rmse": rmse(actual, pred),
        "mape": mape(actual, pred),
        "smape": smape(actual, pred),
        "mase": mase(actual, pred, scale),
    }
