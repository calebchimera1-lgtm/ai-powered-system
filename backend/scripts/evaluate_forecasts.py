"""Evaluate the forecasting models on the store's sales with a held-out test period.

    python -m scripts.evaluate_forecasts [--test-days 28] \
        [--report ../docs/ai/forecast-evaluation.md]

Protocol (nothing is estimated; every number is computed here):

1. The last `--test-days` days of sales are set aside as the TEST period and not touched.
2. On the data before it, every model is backtested (rolling origin, 8 weekly origins,
   28-day horizon) and the best one per product is chosen, exactly as in production.
3. Each model, and the automatically chosen one, then forecasts the test period once.
4. Errors are averaged over products: MAE and RMSE (units), MAPE (non-zero days only),
   sMAPE, MASE and RMSSE (below 1.0 = better than "same weekday last week").
5. Interval coverage: how often the actual daily sales fell inside the 80% interval.

With the demo database the sales are SYNTHETIC (scripts/demo_history.py), generated with
weekly and month-end patterns that the models are designed to pick up, so these results
are likely to be better than on a real shop's noisier data.
"""

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np
from sqlalchemy import func, select

from app.ai.forecasting import engine
from app.ai.forecasting import metrics as m
from app.ai.forecasting.models import all_models
from app.core.database import SessionLocal
from app.models import Product, Sale
from app.services import analytics_data


def _avg(values: list[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return float(np.mean(vals)) if vals else None


def evaluate(test_days: int = 28) -> dict:
    with SessionLocal() as db:
        last_sale = db.scalar(select(func.max(Sale.sold_at)))
        if last_sale is None:
            raise SystemExit("No sales in the database: seed with --history-days first.")
        end = last_sale.date() + timedelta(days=1)  # day after the last day of data
        start = end - timedelta(days=365)
        hist = analytics_data.daily_units_sold(db, start, end - timedelta(days=1))
        names = {p.id: p.name for p in db.scalars(select(Product))}
    cut = end - timedelta(days=test_days)
    train = {pid: y[:-test_days] for pid, y in hist.items() if len(y) > test_days + 28}
    test = {pid: hist[pid][-test_days:].astype(float) for pid in train}

    models = all_models()
    t0 = time.monotonic()
    chosen = engine.run(train, cut, horizon=test_days)  # backtest + selection on train only
    select_secs = time.monotonic() - t0
    per_model = {mdl.name: mdl.forecast(train, cut, test_days) for mdl in models}

    rows: list[dict] = []
    coverage_hits = coverage_n = 0
    for pid, actual in test.items():
        y = train[pid].astype(float)
        scale, sq = m.mase_scale(y), m.rmsse_scale(y)
        pattern = engine.demand_pattern(y[-90:])[0]
        for name, preds in per_model.items():
            if pid in preds:
                rows.append(
                    {
                        "product": names.get(pid, str(pid)),
                        "pattern": pattern,
                        "model": name,
                        **m.all_metrics(actual, preds[pid], scale, sq),
                        "bias": float(np.mean(preds[pid] - actual)),
                    }
                )
        f = chosen[pid]
        rows.append(
            {
                "product": names.get(pid, str(pid)),
                "pattern": pattern,
                "model": "auto",
                "chosen": f.model,
                **m.all_metrics(actual, f.daily, scale, sq),
                "bias": float(np.mean(f.daily - actual)),
            }
        )
        inside = (actual >= f.lower - 1e-9) & (actual <= f.upper + 1e-9)
        coverage_hits += int(inside.sum())
        coverage_n += len(actual)

    def table(filter_pattern: str | None = None) -> dict[str, dict]:
        out = {}
        for name in [*per_model.keys(), "auto"]:
            sel = [
                r
                for r in rows
                if r["model"] == name and (filter_pattern is None or r["pattern"] == filter_pattern)
            ]
            if sel:
                out[name] = {
                    k: _avg([r[k] for r in sel])
                    for k in ("mae", "rmse", "mape", "smape", "mase", "rmsse", "bias")
                }
                out[name]["products"] = len(sel)
        return out

    patterns = sorted({r["pattern"] for r in rows})
    return {
        "history": {
            "start": start.isoformat(),
            "train_end": (cut - timedelta(days=1)).isoformat(),
            "test_start": cut.isoformat(),
            "test_end": (end - timedelta(days=1)).isoformat(),
        },
        "products": len(test),
        "overall": table(),
        "by_pattern": {p: table(p) for p in patterns},
        "chosen": {names.get(pid, str(pid)): f.model for pid, f in chosen.items()},
        "per_product": [r for r in rows if r["model"] == "auto"],
        "interval_coverage": coverage_hits / coverage_n if coverage_n else None,
        "selection_seconds": round(select_secs, 1),
        "labels": {mdl.name: mdl.label for mdl in models}
        | {"auto": "Automatic choice per product"},
    }


def _f(v: float | None, pct: bool = False) -> str:
    if v is None:
        return "n/a"
    return f"{v:.1f}%" if pct else f"{v:.3f}" if abs(v) < 10 else f"{v:.1f}"


def report(r: dict) -> str:
    h = r["history"]
    lines = [
        "# Forecast evaluation (synthetic demo sales)",
        "",
        f"Generated by `scripts/evaluate_forecasts.py` on {date.today():%d %b %Y}. "
        f"{r['products']} products. Training data {h['start']} to {h['train_end']}; "
        f"**held-out test period {h['test_start']} to {h['test_end']}**, never used for "
        "fitting or model selection. The sales are SYNTHETIC (see "
        "`scripts/demo_history.py`), so treat these as a check that the method works, not as "
        "the accuracy to expect in a real shop.",
        "",
        "MASE and RMSSE below 1.0 mean better than the seasonal-naive baseline "
        '("same weekday last week"). MAPE ignores zero-sales days. Bias is the average '
        "forecast minus actual, in units per day.",
        "",
        "## All products",
        "",
    ]

    def tbl(t: dict) -> list[str]:
        out = [
            "| Model | MAE | RMSE | MAPE | sMAPE | MASE | RMSSE | Bias |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for name, v in sorted(t.items(), key=lambda kv: (kv[1]["rmsse"] is None, kv[1]["rmsse"])):
            label = r["labels"].get(name, name)
            label = f"**{label}**" if name == "auto" else label
            out.append(
                f"| {label} | {_f(v['mae'])} | {_f(v['rmse'])} | {_f(v['mape'], True)} | "
                f"{_f(v['smape'], True)} | {_f(v['mase'])} | {_f(v['rmsse'])} | "
                f"{v['bias']:+.2f} |"
            )
        return out

    lines += tbl(r["overall"])
    for pattern, t in r["by_pattern"].items():
        n = next(iter(t.values()))["products"]
        lines += ["", f"## {pattern.capitalize()} demand ({n} product{'s' if n != 1 else ''})", ""]
        lines += tbl(t)
    cov = r["interval_coverage"]
    lines += [
        "",
        "## Prediction intervals",
        "",
        f"Actual daily sales fell inside the 80% interval on **{cov * 100:.1f}%** of "
        "product-days in the test period (the target is 80%).",
        "",
        "## Model chosen for each product (by backtest on training data only)",
        "",
        "| Product | Chosen model | Test MASE | Test RMSSE | Test MAE |",
        "|---|---|---|---|---|",
    ]
    for row in sorted(r["per_product"], key=lambda x: x["product"]):
        lines.append(
            f"| {row['product']} | {r['labels'].get(row['chosen'], row['chosen'])} | "
            f"{_f(row['mase'])} | {_f(row['rmsse'])} | {_f(row['mae'])} |"
        )
    lines += ["", f"Backtesting and selection took {r['selection_seconds']} s on this machine.", ""]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--test-days", type=int, default=28)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    r = evaluate(args.test_days)
    text = report(r)
    print(text)
    if args.report:
        args.report.write_text(text)
    if args.json:
        args.json.write_text(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
