# Receipt and invoice digitization: method and honest evaluation

This module reads a supplier invoice (a phone photo, a scan or a PDF) and proposes a
goods-received note (GRN). **Nothing reaches stock until a person approves it.** The OCR
saves typing; it does not make decisions.

## 1. Pipeline

```
upload ──► checks ──► queue ──► worker: read ──► extract ──► match ──► validate ──► NEEDS_REVIEW
 (API)    type/size   (Postgres   (OpenCV +      (rules +    (RapidFuzz   (arithmetic,     │
          sha256       job)        Tesseract /    geometry)   + learnt      duplicates,     ▼
          dedupe                   PDF text)                   aliases)     price jumps)   reviewer edits,
                                                                                           approves ──► receive_goods()
                                                                                                        (stock, WAC, GRN, audit)
```

| Stage | Code | What it does |
|---|---|---|
| Upload checks | `services/invoice_service.upload` | File type from magic bytes (not the extension), at most 10 MB, PDFs at most 5 pages, the image must decode, the same file twice is refused (SHA-256). Stored outside the web root; served only to signed-in staff with invoice rights. |
| Image quality | `ai/ocr/preprocessing.measure` | Sharpness (variance of the Laplacian), brightness, ink darkness (darkest-1 % percentile) and resolution. Problems become plain-English warnings ("The photo looks blurry…"). |
| Clean-up | `preprocessing.prepare` | Finds the paper outline and flattens the perspective, deskews (minimum-area rectangle of the text pixels), denoises, equalises contrast (CLAHE) and binarises (adaptive threshold). |
| Text | `ai/ocr/engines.py` | PDFs with a text layer are read directly (`pdfplumber`, no OCR, exact). Scanned PDFs are rendered at 300 dpi. Images go to Tesseract 5 (LSTM, `--psm 6`), with a greyscale retry if the binarised read is poor. |
| Lines | `ai/ocr/layout.py` | Words are grouped into lines by their vertical centres, so table columns stay on their row. |
| Fields | `ai/ocr/parser.py` | Rules for the invoice number, date (day first, as in Kenya), KRA PIN (with O/0 and I/1 fixes), supplier name and totals. Item lines are split into leading numbers, description and trailing numbers. Quantity, price and total are assigned by checking `qty × price = total` across the possible orders, falling back to the header's column positions. |
| Products | `ai/ocr/matcher.py` | In order: barcode or supplier code, then an alias learnt from earlier approvals, then fuzzy matching (RapidFuzz) with abbreviation expansion (`WHT` → white, `FLR` → flour…). Pack sizes must agree (`2KG` never matches a 1 kg product). ≥ 88 → matched; 65–88 → *suggested* (the reviewer must confirm); below → unmatched. |
| Checks | `ai/ocr/validator.py` | Missing fields, line arithmetic, subtotal / VAT / total consistency, future dates, cost changes over 10 %, duplicate invoice numbers (blocking) and same-date-same-total (warning). |
| Learning | `invoice_service.approve` | On approval, how the supplier wrote each product is stored as an alias, and their item codes as the supplier SKU. Next time those lines match exactly. |

Why rules and not a trained extraction model? There is no labelled set of real Kenyan
supplier invoices to train on, and the brief forbids faking accuracy. Rules plus
arithmetic checks are transparent (every value shows where it came from), run on a laptop
CPU in about a second, and fail visibly. A learned layout model (for example LayoutLM or
Donut) is the natural next step once real approved invoices have been collected; the
corrections stored by the review screen are exactly the labels it would need.

## 2. Evaluation protocol

Real supplier invoices were not available, so the evaluation uses **synthetic** invoices
from `backend/scripts/generate_synthetic_invoices.py`. Each one is labelled as a demo, and
each has a `.truth.json` with the correct answers and the exact printed text. There are
five layouts (classic, coded with item codes, till receipt, VAT-inclusive, PDF) and three
conditions:

* **clean**: rendered page, light JPEG compression
* **scan**: slight rotation, noise, blur and uneven toner
* **phone**: perspective distortion on a dark desk, lighting gradient, blur and heavier compression

To avoid grading the system on data it was tuned on, three separate seeds were used:

| Set | Seed | Size | Used for |
|---|---|---|---|
| Development | 7 | 15 | Building and debugging the parser |
| Tuning | 2026 | 60 | First held-out check. Two of its failures led to fixes: decimal commas, and thousands-joining. **It is not unseen any more.** |
| **Final test** | **31337** | **60** | Run once, after all changes. These are the numbers reported. |

Metrics (all computed by `scripts/evaluate_ocr.py`, none estimated):

* **CER / WER**: Levenshtein distance between the OCR text and the printed text, divided by the reference length. Lines made only of punctuation (dashes) are ignored.
* **Field accuracy**: exact match per field. The supplier counts as right only if it matched the right supplier record.
* **Line items**: a predicted line counts as correct only if the product, quantity, unit price and line total are *all* right. Precision, recall and F1 are computed over lines.
* **Product match**: the share of true lines whose product was identified, whatever the numbers.

## 3. Results (final test set, 60 synthetic documents)

| | All | Clean | Scan | Phone |
|---|---|---|---|---|
| Character error rate | 0.3 % | 0.2 % | 0.4 % | 0.6 % |
| Word error rate | 2.1 % | 1.1 % | 2.5 % | 3.4 % |
| Invoice number | 90.0 % | 96.4 % | 87.5 % | 81.2 % |
| Date / total / supplier | 100 % | 100 % | 100 % | 100 % |
| Line items (F1) | 98.1 % | 100 % | 97.5 % | 95.5 % |
| Product identified | 99.4 % | 100 % | 97.5 % | 100 % |
| Seconds per document (laptop CPU) | 0.9 | 0.5 | 1.1 | 1.3 |

The full per-document table is in [`ocr-evaluation.md`](ocr-evaluation.md).

### What goes wrong, and why it is safe

* **Invoice numbers (10 % wrong).** These are real character misreads. Tesseract reads a bold "I" next to an "S" or "T" as "1I" (`SI/2203` → `S1I/2203`), or a label is lost and no number is found. No rule was added for the "1I" pattern, because that would only be tuning to the synthetic font. In practice a wrong number is caught by the reviewer, who is shown the image beside each field, and a missing one raises a warning and blocks approval.
* **Single wrong digits in sizes** (`1L` read as `2L`). The pack-size guard then refuses to match the product, so the line is left unmatched instead of silently booked to the wrong item.
* **Blurry phone photos.** The quality check flagged 4 of the 60 documents as blurry, all of them phone photos of receipts. The two phone receipts with reading errors were among those four, so the reviewer was already told to retake the photo. The other two flagged documents were read correctly; for them the warning was cautious but harmless.

### Limits of this evaluation (read before quoting the numbers)

1. **The data is synthetic.** It uses two clean fonts and the layouts the parser was written for. Real invoices bring handwriting, stamps over text, carbon copies, thermal paper fading, dot-matrix fonts, multi-page tables and layouts nobody anticipated. **Expect real-world accuracy to be clearly lower.**
2. Line items are scored strictly, but only against products that exist in the catalogue.
3. Speed was measured on one development container (4 vCPU), not on the target laptop.

### Measuring it on real invoices

The system records the OCR's own values next to the reviewer's corrections
(`invoice_items.original` and `was_corrected`, `invoices.original_fields`). The
`GET /api/v1/invoices/stats` endpoint reports the share of lines corrected on approved
invoices, which is the real-world error rate. After a few weeks of use, that figure, not
the synthetic one above, is the one to report.

## 4. Reproducing

```bash
cd backend
# Final test set (as reported):
python -m scripts.evaluate_ocr --data /tmp/ocr-final --generate 60 --seed 31337 \
    --report ../docs/ai/ocr-evaluation.md
# Committed samples (12 documents in sample-data/invoices):
python -m scripts.evaluate_ocr --data ../sample-data/invoices
```

In Docker: `docker compose exec api python -m scripts.evaluate_ocr --data /tmp/ocr --generate 60 --seed 31337`.
The automated test suite also runs a 10-document accuracy regression check
(`tests/unit/test_ocr.py::test_ocr_accuracy_on_synthetic_invoices`).
