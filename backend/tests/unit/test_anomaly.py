"""Anomaly detector: robust baselines, rules, Isolation Forest and merging."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from app.ai.anomaly import detector as d

START = date(2026, 6, 1)


def product_frame(days: int = 120, seed: int = 0, **spikes: dict[int, float]) -> pd.DataFrame:
    """One product with Poisson sales and occasional one-unit corrections; `spikes` maps a
    column to {day index: value} to inject."""
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(days):
        row = {
            "product_id": 1,
            "name": "Pishori Rice 2kg",
            "unit_cost": 300.0,
            "day": START + timedelta(days=i),
            "units_sold": float(rng.poisson(8)),
            "adj_out": 0.0,
            "adj_in": 0.0,
            "adj_count": 0.0,
            "damaged": 0.0,
            "returns": 0.0,
        }
        if i % 11 == 0:
            row["adj_out"], row["adj_count"] = 1.0, 1.0
        for col, at in spikes.items():
            if i in at:
                row[col] = float(at[i])
        rows.append(row)
    return pd.DataFrame(rows)


def user_frame(days: int = 120, refunds: dict[int, int] | None = None) -> pd.DataFrame:
    rows = []
    for i in range(days):
        n = (refunds or {}).get(i, 1 if i % 9 == 0 else 0)
        rows.append(
            {
                "user_id": 7,
                "name": "Demo Cashier",
                "day": START + timedelta(days=i),
                "refunds": float(n),
                "refund_value": 120.0 * n,
                "adj_count": 0.0,
                "adj_value": 0.0,
            }
        )
    return pd.DataFrame(rows)


def test_baseline_uses_only_the_past() -> None:
    df = product_frame(60, adj_out={50: 30})
    b = d.add_baselines(df, "product_id", d.PRODUCT_COLUMNS)
    row = b[b["day"] == START + timedelta(days=50)].iloc[0]
    assert row["adj_out_norm"] == 0  # the spike itself is not part of its own normal
    assert row["adj_out_z"] >= 20
    assert b.iloc[5]["adj_out_norm"] != b.iloc[5]["adj_out_norm"]  # NaN: too little history
    assert not b.loc[b["adj_out_norm"].notna(), "adj_out_z"].isna().any()


def test_rules_catch_stock_loss_and_ignore_routine_corrections() -> None:
    df = product_frame(adj_out={100: 9}, adj_count={100: 1})
    findings = d.detect(df, pd.DataFrame(), use_forest=False)
    assert [(f.kind, f.day) for f in findings] == [
        ("UNEXPLAINED_STOCK_LOSS", START + timedelta(days=100))
    ]
    f = findings[0]
    assert f.value_kes == 2700.0 and f.quantity == 9
    assert "9 units of Pishori Rice 2kg" in f.explanation
    assert f.evidence["adj_out"]["value"] == 9


def test_rules_catch_bursts_and_damage_and_refunds() -> None:
    df = product_frame(adj_out={90: 6}, adj_count={90: 6}, damaged={100: 12})
    u = user_frame(refunds={110: 7})
    kinds = {(f.entity, f.kind) for f in d.detect(df, u, use_forest=False)}
    assert ("product", "FREQUENT_ADJUSTMENTS") in kinds or (
        "product",
        "UNEXPLAINED_STOCK_LOSS",
    ) in kinds
    assert ("product", "HIGH_WRITE_OFFS") in kinds
    assert ("user", "HIGH_REFUNDS") in kinds


def test_quiet_history_raises_nothing() -> None:
    assert d.detect(product_frame(), user_frame(), use_forest=False) == []


def test_forest_flags_an_unusual_combination_and_explains_it() -> None:
    df = product_frame(adj_out={100: 15}, adj_count={100: 3}, damaged={100: 4})
    forest = d.detect(df, pd.DataFrame(), use_rules=False, contamination=0.01)
    assert any(f.day == START + timedelta(days=100) for f in forest)
    hit = next(f for f in forest if f.day == START + timedelta(days=100))
    assert hit.detector == "ISOLATION_FOREST" and "units adjusted out" in hit.explanation


def test_merge_marks_both_detectors_and_severity() -> None:
    df = product_frame(adj_out={100: 20}, adj_count={100: 1})
    merged = d.detect(df, pd.DataFrame(), contamination=0.01)
    f = next(f for f in merged if f.day == START + timedelta(days=100))
    assert f.detector == "BOTH"
    assert d.severity(f) == "HIGH"  # 20 x 300 = KES 6,000
    low = d.Finding("product", 1, START, "HIGH_RETURNS", "RULE", 0.4, 4, 200.0, "", "")
    assert d.severity(low) == "LOW"
