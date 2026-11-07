"""Measure the invoice-digitization pipeline against synthetic invoices with known answers.

    python -m scripts.evaluate_ocr --data /tmp/ocr-eval [--generate 60] \
        [--report ../docs/ai/ocr-evaluation.md]

Metrics (all computed here, nothing estimated):

* CER / WER     character and word error rate of the raw OCR text versus the text that
                was printed (Levenshtein distance / reference length), lower is better.
* Field accuracy  share of documents where supplier, invoice number, date, subtotal,
                VAT and total are exactly right (supplier = matched to the right record).
* Line items    precision / recall / F1. A predicted line counts as correct only if it is
                matched to the right product AND its quantity, unit price and line total
                are all exact.
* Product match top-1 accuracy of product matching on lines that were found.
* Time          seconds per document on this machine.
"""

import argparse
import json
import statistics
import time
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path

from rapidfuzz.distance import Levenshtein

from app.ai.ocr.matcher import ProductRef, SupplierRef, match_product, match_supplier
from app.ai.ocr.pipeline import process
from scripts.generate_synthetic_invoices import PRODUCTS, SUPPLIERS, generate

CATALOG = [ProductRef(i, name, f"SKU-{i:06d}", None) for i, name in enumerate(PRODUCTS, 1)]
PRODUCT_ID = {p.name: p.id for p in CATALOG}
SUPPLIER_REFS = [SupplierRef(i, name, pin) for i, (name, pin, _) in enumerate(SUPPLIERS, 1)]
SUPPLIER_ID = {s.name: s.id for s in SUPPLIER_REFS}

FIELDS = ["supplier", "invoice_number", "invoice_date", "subtotal", "tax_total", "grand_total"]


def _norm_text(lines: list[str]) -> str:
    # Lines made only of punctuation (e.g. "------" separators) carry no information and
    # are ignored on both sides.
    kept = [ln for ln in lines if any(ch.isalnum() for ch in ln)]
    return " ".join(" ".join(kept).split()).upper()


def evaluate_one(path: Path) -> dict:
    truth = json.loads((path.parent / f"{path.stem}.truth.json").read_text())
    mime = "application/pdf" if path.suffix == ".pdf" else "image/jpeg"
    started = time.perf_counter()
    doc, ext = process(path.read_bytes(), mime)
    seconds = time.perf_counter() - started

    ref = _norm_text(truth["text_lines"])
    hyp = _norm_text([ln.text for ln in doc.lines])
    cer = Levenshtein.distance(hyp, ref) / max(len(ref), 1)
    wer = Levenshtein.distance(hyp.split(), ref.split()) / max(len(ref.split()), 1)

    sup_id, _, _ = match_supplier(
        ext.kra_pin.value, ext.supplier_name.value, ext.header_lines, SUPPLIER_REFS
    )
    fields = {
        "supplier": sup_id == SUPPLIER_ID[truth["supplier_name"]],
        "invoice_number": (ext.invoice_number.value or "").upper()
        == truth["invoice_number"].upper(),
        "invoice_date": isinstance(ext.invoice_date.value, date)
        and ext.invoice_date.value.isoformat() == truth["invoice_date"],
        "subtotal": ext.subtotal.value == Decimal(truth["subtotal"]),
        "tax_total": ext.tax_total.value == Decimal(truth["tax_total"]),
        "grand_total": ext.grand_total.value == Decimal(truth["grand_total"]),
    }

    # Line items: pair predictions with truth by matched product.
    expected = {PRODUCT_ID[it["product"]]: it for it in truth["items"]}
    correct = matched_found = matched_right = 0
    used: set[int] = set()
    for it in ext.items:
        m = match_product(it.description, it.item_code, it.raw_text, CATALOG)
        pid = m.product_id if not m.suggestion_only else m.product_id
        # A line is "found" if it overlaps a truth line by description similarity.
        best_truth = max(
            expected.items(),
            key=lambda kv: Levenshtein.normalized_similarity(
                it.description.upper(), kv[1]["description"].upper()
            ),
            default=None,
        )
        if (
            best_truth
            and Levenshtein.normalized_similarity(
                it.description.upper(), best_truth[1]["description"].upper()
            )
            >= 0.6
        ):
            matched_found += 1
            matched_right += int(pid == best_truth[0])
        if pid in expected and pid not in used:
            t = expected[pid]
            ok = (
                it.quantity == Decimal(t["quantity"])
                and it.unit_price == Decimal(t["unit_price"])
                and it.line_total == Decimal(t["line_total"])
            )
            if ok:
                correct += 1
                used.add(pid)
    return {
        "file": path.name,
        "layout": truth["layout"],
        "condition": truth["condition"],
        "engine": doc.engine,
        "seconds": seconds,
        "cer": cer,
        "wer": wer,
        "fields": fields,
        "items_true": len(truth["items"]),
        "items_pred": len(ext.items),
        "items_correct": correct,
        "lines_found": matched_found,
        "product_right": matched_right,
        "quality_problems": doc.quality.problems,
    }


def summarise(rows: list[dict]) -> dict:
    t = sum(r["items_true"] for r in rows)
    p = sum(r["items_pred"] for r in rows)
    c = sum(r["items_correct"] for r in rows)
    precision = c / p if p else 0.0
    recall = c / t if t else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    found = sum(r["lines_found"] for r in rows)
    return {
        "documents": len(rows),
        "cer": statistics.mean(r["cer"] for r in rows),
        "wer": statistics.mean(r["wer"] for r in rows),
        "fields": {f: sum(r["fields"][f] for r in rows) / len(rows) for f in FIELDS},
        "all_fields": sum(all(r["fields"].values()) for r in rows) / len(rows),
        "item_precision": precision,
        "item_recall": recall,
        "item_f1": f1,
        "product_match_accuracy": (sum(r["product_right"] for r in rows) / found) if found else 0.0,
        "seconds_mean": statistics.mean(r["seconds"] for r in rows),
        "seconds_p95": sorted(r["seconds"] for r in rows)[max(0, int(len(rows) * 0.95) - 1)],
    }


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def report(rows: list[dict], path: Path | None) -> str:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        groups[f"condition: {r['condition']}"].append(r)
        groups[f"layout: {r['layout']}"].append(r)
    overall = summarise(rows)
    lines = [
        "# OCR evaluation (synthetic invoices)",
        "",
        f"Generated by `scripts/evaluate_ocr.py` on {date.today():%d %b %Y}. "
        f"{overall['documents']} SYNTHETIC invoices with known answers "
        "(see `scripts/generate_synthetic_invoices.py`). These numbers describe this "
        "dataset only; real supplier documents vary more and should be measured too.",
        "",
        "| Group | Docs | CER | WER | All header fields right | Invoice no. | Date | Total "
        "| Supplier | Item P | Item R | Item F1 | Product match | Sec/doc |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def row(name: str, s: dict) -> str:
        f = s["fields"]
        return (
            f"| {name} | {s['documents']} | {pct(s['cer'])} | {pct(s['wer'])} | "
            f"{pct(s['all_fields'])} | {pct(f['invoice_number'])} | {pct(f['invoice_date'])} | "
            f"{pct(f['grand_total'])} | {pct(f['supplier'])} | {pct(s['item_precision'])} | "
            f"{pct(s['item_recall'])} | {pct(s['item_f1'])} | "
            f"{pct(s['product_match_accuracy'])} | {s['seconds_mean']:.1f} |"
        )

    lines.append(row("**All**", overall))
    for name in sorted(groups):
        lines.append(row(name, summarise(groups[name])))
    lines += [
        "",
        "## Per document",
        "",
        "| File | Engine | CER | Fields right | Items correct / expected | Quality warnings |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['file']} | {r['engine']} | {pct(r['cer'])} | "
            f"{sum(r['fields'].values())}/{len(FIELDS)} | {r['items_correct']}/{r['items_true']} | "
            f"{len(r['quality_problems'])} |"
        )
    text = "\n".join(lines) + "\n"
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--generate", type=int, default=0, help="Generate this many invoices first")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--report", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args()
    if args.generate:
        generate(args.data, args.generate, args.seed)
    files = sorted(p for p in args.data.iterdir() if p.suffix in (".jpg", ".png", ".pdf"))
    rows = []
    for f in files:
        rows.append(evaluate_one(f))
        r = rows[-1]
        print(
            f"{r['file']:42} cer={pct(r['cer']):>6} fields={sum(r['fields'].values())}/6 "
            f"items={r['items_correct']}/{r['items_true']} ({r['seconds']:.1f}s)"
        )
    print(report(rows, args.report))
    if args.json:
        args.json.write_text(json.dumps(rows, indent=2, default=str))


if __name__ == "__main__":
    main()
