"""Evaluate anomaly detection against the irregularities injected into the demo history.

    python -m scripts.evaluate_anomalies --labels storage/demo/anomaly-ground-truth.json \\
        [--report ../docs/ai/anomaly-evaluation.md]

The demo simulation (scripts/demo_history.py) records a few irregularities through the
normal services (shrinkage bursts, bursts of small adjustments, damage spikes, refund
spikes) among ordinary noise (routine count corrections, the odd breakage, normal
returns), and writes what it injected to a separate file the detector never reads.

Scoring is per entity-day: a (product or person, day) pair is a true positive if the
detector flagged it and it is in the ground truth. Reported for rules only, the Isolation
Forest only and both combined, with precision@k (of the k highest-scored findings, how
many were real) and a sweep over the forest's `contamination` setting.

The data is SYNTHETIC and the injected irregularities are deliberately clear-cut, so
these numbers show the detectors work as designed, not how they will do on a real shop.
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select

from app.ai.anomaly import detector
from app.core.database import SessionLocal
from app.models import Product, StockMovement, User
from app.services import analytics_data


def _prf(pred: set, truth: set) -> dict[str, float]:
    tp = len(pred & truth)
    p = tp / len(pred) if pred else 0.0
    r = tp / len(truth) if truth else 0.0
    return {
        "tp": tp,
        "fp": len(pred - truth),
        "fn": len(truth - pred),
        "precision": p,
        "recall": r,
        "f1": 2 * p * r / (p + r) if p + r else 0.0,
    }


def evaluate(labels_path: Path) -> dict:
    data = json.loads(labels_path.read_text())
    labels = data["labels"]
    with SessionLocal() as db:
        first = db.scalar(select(func.min(StockMovement.created_at)))
        last = db.scalar(select(func.max(StockMovement.created_at)))
        start, end = first.date(), last.date()
        pdays = analytics_data.product_days(db, start, end)
        udays = analytics_data.user_days(db, start, end)
        pid = {p.name: p.id for p in db.scalars(select(Product))}
        uid = {u.username: u.id for u in db.scalars(select(User))}
    truth = {
        (
            lb["entity"],
            pid[lb["name"]] if lb["entity"] == "product" else uid[lb["name"]],
            date.fromisoformat(lb["date"]),
        ): lb["kind"]
        for lb in labels
    }
    # Days before a normal is established cannot be judged; exclude them from scoring.
    judged_from = start + timedelta(days=detector.MIN_NORM_DAYS + 1)

    def run(**kw: object) -> list[detector.Finding]:
        return [f for f in detector.detect(pdays, udays, **kw) if f.day >= judged_from]  # type: ignore[arg-type]

    def keyset(fs: list[detector.Finding]) -> set:
        return {(f.entity, f.entity_id, f.day) for f in fs}

    truth_keys = set(truth)
    variants = {
        "Rules only": run(use_forest=False),
        "Isolation Forest only": run(use_rules=False),
        "Combined": run(),
    }
    results = {name: _prf(keyset(fs), truth_keys) for name, fs in variants.items()}
    combined = variants["Combined"]
    ranked = sorted(combined, key=lambda f: f.score, reverse=True)
    at_k = {}
    for k in (5, 10, 20):
        top = keyset(ranked[:k])
        at_k[k] = len(top & truth_keys) / min(k, len(ranked)) if ranked else 0.0
    by_kind = {}
    found = keyset(combined)
    for kind in sorted(set(truth.values())):
        keys = {k for k, v in truth.items() if v == kind}
        by_kind[kind] = {"days": len(keys), "detected": len(keys & found)}
    sweep = {}
    for c in (0.005, 0.01, 0.02, 0.05):
        sweep[c] = {
            "forest": _prf(keyset(run(use_rules=False, contamination=c)), truth_keys),
            "combined": _prf(keyset(run(contamination=c)), truth_keys),
        }
    false_pos = [
        {
            "entity": f.entity,
            "day": f.day.isoformat(),
            "kind": f.kind,
            "detector": f.detector,
            "explanation": f.explanation,
        }
        for f in combined
        if (f.entity, f.entity_id, f.day) not in truth_keys
    ]
    days = (end - judged_from).days + 1
    return {
        "period": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "judged_from": judged_from.isoformat(),
            "days": days,
        },
        "entity_days": {
            "product": int(pdays["product_id"].nunique()) * days,
            "user": int(udays["user_id"].nunique()) * days if len(udays) else 0,
        },
        "truth_days": len(truth_keys),
        "results": results,
        "precision_at_k": at_k,
        "by_kind": by_kind,
        "contamination_sweep": sweep,
        "false_positives": false_pos,
    }


def report(r: dict) -> str:
    pc = lambda x: f"{x * 100:.1f}%"  # noqa: E731
    ed = r["entity_days"]
    lines = [
        "# Anomaly detection evaluation (synthetic demo data)",
        "",
        f"Generated by `scripts/evaluate_anomalies.py` on {date.today():%d %b %Y}. "
        f"Scored over {r['period']['days']} days ({r['period']['judged_from']} to "
        f"{r['period']['end']}): {ed['product']:,} product-days and {ed['user']:,} staff-days, "
        f"of which **{r['truth_days']}** carry an injected irregularity. The data and the "
        "irregularities are SYNTHETIC and deliberately clear-cut; real irregularities are "
        "subtler and real noise is messier, so expect lower figures in a live shop.",
        "",
        "| Detector | True positives | False positives | Missed | Precision | Recall | F1 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, v in r["results"].items():
        lines.append(
            f"| {name} | {v['tp']} | {v['fp']} | {v['fn']} | {pc(v['precision'])} | "
            f"{pc(v['recall'])} | {pc(v['f1'])} |"
        )
    lines += [
        "",
        "**Precision@k** (combined, ranked by score): "
        + ", ".join(f"top {k}: {pc(v)}" for k, v in r["precision_at_k"].items())
        + ".",
        "",
        "## Recall by kind of irregularity (combined)",
        "",
        "| Injected irregularity | Entity-days | Detected |",
        "|---|---|---|",
    ]
    for kind, v in r["by_kind"].items():
        lines.append(f"| {kind.replace('_', ' ').capitalize()} | {v['days']} | {v['detected']} |")
    lines += [
        "",
        "## Isolation Forest `contamination` sweep",
        "",
        "| contamination | Forest P | Forest R | Combined P | Combined R | Combined F1 |",
        "|---|---|---|---|---|---|",
    ]
    for c, v in r["contamination_sweep"].items():
        f, cb = v["forest"], v["combined"]
        lines.append(
            f"| {float(c):.3f} | {pc(f['precision'])} | {pc(f['recall'])} | "
            f"{pc(cb['precision'])} | {pc(cb['recall'])} | {pc(cb['f1'])} |"
        )
    lines += [
        "",
        f"## False positives (combined, {len(r['false_positives'])})",
        "",
        "Days flagged that were not injected. Some are genuinely unusual days produced by "
        "the random simulation (for example two routine corrections on one product), which "
        "a reviewer would close as *no issue*.",
        "",
    ]
    for fp in r["false_positives"][:25]:
        lines.append(
            f"- {fp['day']} · {fp['entity']} · {fp['kind']} · {fp['detector']}: "
            f"{fp['explanation']}"
        )
    if len(r["false_positives"]) > 25:
        lines.append(f"- … and {len(r['false_positives']) - 25} more")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    r = evaluate(args.labels)
    text = report(r)
    print(text)
    if args.report:
        args.report.write_text(text)
    if args.json:
        args.json.write_text(json.dumps(r, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
