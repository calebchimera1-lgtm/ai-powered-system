"""Anomaly detection over daily activity: transparent rules plus an Isolation Forest.

Input is two tables of daily figures (built from the stock ledger, sales and returns):

* product-days: units sold, units adjusted out/in, number of adjustments, units written off
  as damaged, units returned, and the product's average cost;
* user-days: refunds taken, their value, number and value of stock adjustments.

Each figure is compared with that product's (or person's) own recent normal: the median of
the previous 90 days and a robust spread (median absolute deviation), giving a robust
z-score. Only the past is used, so a day is judged the way it would have been that night.

A. Rules fire on clear patterns (for example, "adjusted out 4 or more units and at least
   4 robust z-scores above normal"). Every rule says exactly why it fired.
B. An Isolation Forest (scikit-learn) looks at all the z-scores together and isolates
   days that are unusual in combination, catching patterns no single rule describes. Its
   `contamination` (expected share of unusual days) is set low, about 1%.

Findings from both are merged per entity and day; the detector field says which fired.
Wording: these are *irregularities to investigate*, never accusations.
"""

from dataclasses import dataclass, field
from datetime import date

import numpy as np
import pandas as pd

NORM_DAYS = 90
MIN_NORM_DAYS = 21

PRODUCT_COLUMNS = ["units_sold", "adj_out", "adj_in", "adj_count", "damaged", "returns"]
# The forest looks for loss patterns. Busy sales days (paydays, holidays) are expected and
# are handled by forecasting; with them included, most of its alerts were ordinary peaks.
FOREST_PRODUCT_COLUMNS = ["adj_out", "adj_in", "adj_count", "damaged", "returns"]
USER_COLUMNS = ["refunds", "refund_value", "adj_count", "adj_value"]

KIND_LABELS = {
    "UNEXPLAINED_STOCK_LOSS": "Unexplained stock loss",
    "FREQUENT_ADJUSTMENTS": "Unusually many adjustments",
    "HIGH_WRITE_OFFS": "Damage write-offs above normal",
    "HIGH_RETURNS": "Returns above normal",
    "UNUSUAL_SALES": "Sales far above normal",
    "HIGH_REFUNDS": "Refunds above normal",
    "LARGE_ADJUSTMENTS": "Adjustments above normal",
    "UNUSUAL_ACTIVITY": "Unusual combination of activity",
}

ACTIONS = {
    "UNEXPLAINED_STOCK_LOSS": "Count the product on the shelf and in the store room, and check "
    "who recorded the adjustments and why.",
    "FREQUENT_ADJUSTMENTS": "Review each adjustment's reason with the person who made them; a "
    "single full count is usually better than many small corrections.",
    "HIGH_WRITE_OFFS": "Inspect the damaged stock if it is still there, and check handling and "
    "storage for this product.",
    "HIGH_RETURNS": "Check the returned items and the reasons given; a quality problem with a "
    "batch is a common cause.",
    "UNUSUAL_SALES": "Confirm the sales were genuine (for example a bulk order) and that the "
    "right product was scanned.",
    "HIGH_REFUNDS": "Review the day's refunds with the receipts and the returned goods, and "
    "with the staff member concerned.",
    "LARGE_ADJUSTMENTS": "Review the adjustments and their reasons with the person who made "
    "them.",
    "UNUSUAL_ACTIVITY": "Look at the day's movements for this item together; the details "
    "show which figures were unusual.",
}

FEATURE_WORDS = {
    "units_sold": "units sold",
    "adj_out": "units adjusted out",
    "adj_in": "units adjusted in",
    "adj_count": "adjustments",
    "damaged": "units written off as damaged",
    "returns": "units returned",
    "refunds": "refunds",
    "refund_value": "KES refunded",
    "adj_value": "KES of adjustments",
}


@dataclass
class Finding:
    entity: str  # "product" | "user"
    entity_id: int
    day: date
    kind: str
    detector: str  # "RULE" | "ISOLATION_FOREST" | "BOTH"
    score: float  # 0..1, how unusual
    quantity: float
    value_kes: float
    explanation: str
    action: str
    evidence: dict[str, dict[str, float]] = field(default_factory=dict)


# --- Robust baselines --------------------------------------------------------------------


def _trailing(series: pd.Series, fn: str) -> pd.Series:
    roll = series.shift(1).rolling(NORM_DAYS, min_periods=MIN_NORM_DAYS)
    if fn == "median":
        return roll.median()
    return roll.apply(lambda w: float(np.nanmedian(np.abs(w - np.nanmedian(w)))), raw=True)


def add_baselines(frame: pd.DataFrame, key: str, columns: list[str]) -> pd.DataFrame:
    """Adds <col>_norm and <col>_z (robust z-score against the entity's own past)."""
    frame = frame.sort_values([key, "day"]).reset_index(drop=True)
    parts = []
    for _, g in frame.groupby(key, sort=False):
        g = g.copy()
        for col in columns:
            med = _trailing(g[col], "median")
            mad = _trailing(g[col], "mad")
            # Floor the spread: counts of 0-1 a day must not make a single unit look extreme.
            spread = np.maximum(1.4826 * mad, np.maximum(np.sqrt(med.clip(lower=0)), 1.0))
            g[f"{col}_norm"] = med
            g[f"{col}_z"] = ((g[col] - med) / spread).where(med.notna(), 0.0)
        parts.append(g)
    return pd.concat(parts, ignore_index=True) if parts else frame


# --- Rules ------------------------------------------------------------------------------


def _ev(row: pd.Series, cols: list[str]) -> dict[str, dict[str, float]]:
    return {
        c: {
            "value": round(float(row[c]), 2),
            "normal": round(float(row.get(f"{c}_norm") or 0), 2),
            "z": round(float(row.get(f"{c}_z") or 0), 2),
        }
        for c in cols
    }


def _fmt(x: float) -> str:
    return f"{x:,.0f}" if float(x).is_integer() else f"{x:,.1f}"


def product_rules(df: pd.DataFrame) -> list[Finding]:
    out = []
    for _, r in df.iterrows():
        if pd.isna(r.get("adj_out_norm")):
            continue  # not enough history to know what is normal
        cost = float(r["unit_cost"] or 0)
        name = r.get("name", f"product {r['product_id']}")

        def add(
            kind: str,
            z: float,
            qty: float,
            value: float,
            text: str,
            cols: list[str],
            r: pd.Series = r,
        ) -> None:
            out.append(
                Finding(
                    "product",
                    int(r["product_id"]),
                    r["day"],
                    kind,
                    "RULE",
                    min(1.0, abs(z) / 10),
                    qty,
                    round(value, 2),
                    text,
                    ACTIONS[kind],
                    _ev(r, cols),
                )
            )

        if r["adj_out"] >= 4 and r["adj_out_z"] >= 4 and r["adj_out"] * cost >= 500:
            add(
                "UNEXPLAINED_STOCK_LOSS",
                r["adj_out_z"],
                r["adj_out"],
                r["adj_out"] * cost,
                f"{_fmt(r['adj_out'])} units of {name} were adjusted out of stock on "
                f"{r['day']:%d %b}, against a typical {_fmt(r['adj_out_norm'])} a day.",
                ["adj_out", "adj_count"],
            )
        if r["adj_count"] >= 4:
            add(
                "FREQUENT_ADJUSTMENTS",
                max(r["adj_count_z"], 4),
                r["adj_out"] + r["adj_in"],
                (r["adj_out"] + r["adj_in"]) * cost,
                f"{int(r['adj_count'])} separate stock adjustments to {name} on "
                f"{r['day']:%d %b}; usually there are {_fmt(r['adj_count_norm'])}.",
                ["adj_count", "adj_out", "adj_in"],
            )
        if r["damaged"] >= 5 and r["damaged_z"] >= 4:
            add(
                "HIGH_WRITE_OFFS",
                r["damaged_z"],
                r["damaged"],
                r["damaged"] * cost,
                f"{_fmt(r['damaged'])} units of {name} were written off as damaged on "
                f"{r['day']:%d %b}, against a typical {_fmt(r['damaged_norm'])} a day.",
                ["damaged"],
            )
        if r["returns"] >= 4 and r["returns_z"] >= 4:
            add(
                "HIGH_RETURNS",
                r["returns_z"],
                r["returns"],
                r["returns"] * cost,
                f"{_fmt(r['returns'])} units of {name} were returned on {r['day']:%d %b}, "
                f"against a typical {_fmt(r['returns_norm'])}.",
                ["returns"],
            )
        norm = r["units_sold_norm"] or 0
        if r["units_sold_z"] >= 6 and r["units_sold"] >= max(3 * norm, 10):
            add(
                "UNUSUAL_SALES",
                r["units_sold_z"],
                r["units_sold"],
                0.0,
                f"{_fmt(r['units_sold'])} units of {name} were sold on {r['day']:%d %b}, "
                f"about {r['units_sold'] / max(norm, 1):.1f} times a normal day.",
                ["units_sold"],
            )
    return out


def user_rules(df: pd.DataFrame) -> list[Finding]:
    out = []
    for _, r in df.iterrows():
        if pd.isna(r.get("refunds_norm")):
            continue
        name = r.get("name", f"user {r['user_id']}")

        def add(
            kind: str,
            z: float,
            qty: float,
            value: float,
            text: str,
            cols: list[str],
            r: pd.Series = r,
        ) -> None:
            out.append(
                Finding(
                    "user",
                    int(r["user_id"]),
                    r["day"],
                    kind,
                    "RULE",
                    min(1.0, abs(z) / 10),
                    qty,
                    round(value, 2),
                    text,
                    ACTIONS[kind],
                    _ev(r, cols),
                )
            )

        if r["refunds"] >= 4 and r["refunds_z"] >= 4:
            add(
                "HIGH_REFUNDS",
                r["refunds_z"],
                r["refunds"],
                r["refund_value"],
                f"{name} processed {int(r['refunds'])} refunds (KES {r['refund_value']:,.0f}) on "
                f"{r['day']:%d %b}; a typical day has {_fmt(r['refunds_norm'])}.",
                ["refunds", "refund_value"],
            )
        if r["adj_count"] >= 5:
            add(
                "FREQUENT_ADJUSTMENTS",
                max(r["adj_count_z"], 4),
                r["adj_count"],
                r["adj_value"],
                f"{name} recorded {int(r['adj_count'])} stock adjustments on {r['day']:%d %b}; "
                f"a typical day has {_fmt(r['adj_count_norm'])}.",
                ["adj_count", "adj_value"],
            )
        elif r["adj_value"] >= 1000 and r["adj_value_z"] >= 4:
            add(
                "LARGE_ADJUSTMENTS",
                r["adj_value_z"],
                r["adj_count"],
                r["adj_value"],
                f"{name}'s stock adjustments on {r['day']:%d %b} were worth KES "
                f"{r['adj_value']:,.0f}, well above their usual "
                f"KES {r['adj_value_norm']:,.0f}.",
                ["adj_value", "adj_count"],
            )
    return out


# --- Isolation Forest --------------------------------------------------------------------

IF_KIND = {
    "adj_out": "UNEXPLAINED_STOCK_LOSS",
    "adj_in": "LARGE_ADJUSTMENTS",
    "adj_count": "FREQUENT_ADJUSTMENTS",
    "damaged": "HIGH_WRITE_OFFS",
    "returns": "HIGH_RETURNS",
    "units_sold": "UNUSUAL_SALES",
    "refunds": "HIGH_REFUNDS",
    "refund_value": "HIGH_REFUNDS",
    "adj_value": "LARGE_ADJUSTMENTS",
}


def isolation_forest(
    df: pd.DataFrame,
    key: str,
    columns: list[str],
    entity: str,
    contamination: float,
    seed: int = 0,
) -> list[Finding]:
    from sklearn.ensemble import IsolationForest

    data = df[df[f"{columns[0]}_norm"].notna()].copy()
    if len(data) < 50:
        return []
    zcols = [f"{c}_z" for c in columns]
    x = data[zcols].clip(-10, 30).to_numpy(dtype=float)
    model = IsolationForest(n_estimators=200, contamination=contamination, random_state=seed)
    flagged = model.fit_predict(x) == -1
    raw = -model.score_samples(x)  # higher = more unusual
    lo, hi = np.quantile(raw, 0.5), raw.max()
    data["_score"] = np.clip((raw - lo) / max(hi - lo, 1e-9), 0, 1)
    out = []
    for (_, r), is_out in zip(data.iterrows(), flagged, strict=True):
        if not is_out:
            continue
        # Explain with the figures furthest above their normal (high side only: a quiet day
        # is not suspicious).
        ups = sorted(((float(r[f"{c}_z"]), c) for c in columns if r[f"{c}_z"] > 2), reverse=True)
        if not ups:
            continue
        top = ups[0][1]
        kind = IF_KIND.get(top, "UNUSUAL_ACTIVITY")
        name = r.get("name", f"{entity} {r[key]}")
        parts = [
            f"{_fmt(r[c])} {FEATURE_WORDS[c]} (normal {_fmt(r[f'{c}_norm'] or 0)})"
            for _, c in ups[:3]
        ]
        if entity == "product":
            cost = float(r["unit_cost"] or 0)
            qty = float(r["adj_out"] + r["adj_in"] + r["damaged"] + r["returns"])
            value = qty * cost
        else:
            qty = float(r["refunds"] + r["adj_count"])
            value = float(r["refund_value"] + r["adj_value"])
        out.append(
            Finding(
                entity,
                int(r[key]),
                r["day"],
                kind,
                "ISOLATION_FOREST",
                float(r["_score"]),
                qty,
                round(value, 2),
                f"Unusual day for {name} on {r['day']:%d %b}: " + "; ".join(parts) + ".",
                ACTIONS[kind],
                _ev(r, [c for _, c in ups[:3]]),
            )
        )
    return out


# --- Combine -----------------------------------------------------------------------------


def severity(f: Finding) -> str:
    if f.value_kes >= 5000 or (f.detector == "BOTH" and f.value_kes >= 2000):
        return "HIGH"
    if f.value_kes >= 1000 or f.detector == "BOTH" or f.score >= 0.8:
        return "MEDIUM"
    return "LOW"


def merge(rule: list[Finding], forest: list[Finding]) -> list[Finding]:
    """One finding per (entity, id, day): rules keep their wording, the forest adds weight."""
    by_key: dict[tuple, Finding] = {}
    for f in rule:
        key = (f.entity, f.entity_id, f.day)
        if key in by_key:  # several rules on the same day: keep the strongest
            if f.score > by_key[key].score:
                by_key[key] = f
        else:
            by_key[key] = f
    for f in forest:
        key = (f.entity, f.entity_id, f.day)
        if key in by_key:
            hit = by_key[key]
            hit.detector = "BOTH"
            hit.score = max(hit.score, f.score)
        else:
            by_key[key] = f
    return sorted(by_key.values(), key=lambda f: (f.day, f.entity, f.entity_id))


def detect(
    product_days: pd.DataFrame,
    user_days: pd.DataFrame,
    *,
    contamination: float = 0.01,
    use_rules: bool = True,
    use_forest: bool = True,
    seed: int = 0,
) -> list[Finding]:
    pdays = (
        add_baselines(product_days, "product_id", PRODUCT_COLUMNS)
        if len(product_days)
        else product_days
    )
    udays = add_baselines(user_days, "user_id", USER_COLUMNS) if len(user_days) else user_days
    rule: list[Finding] = []
    forest: list[Finding] = []
    if use_rules:
        rule += product_rules(pdays) if len(pdays) else []
        rule += user_rules(udays) if len(udays) else []
    if use_forest:
        if len(pdays):
            forest += isolation_forest(
                pdays, "product_id", FOREST_PRODUCT_COLUMNS, "product", contamination, seed
            )
        if len(udays):
            forest += isolation_forest(udays, "user_id", USER_COLUMNS, "user", contamination, seed)
    return merge(rule, forest)
